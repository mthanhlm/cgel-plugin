"""Approval-by-question: verify a user's AskUserQuestion answer from the
session transcript, so gated commands need one tap on "Approve" instead of
a typed command or a raw permission prompt.

Trust honesty (Profile A): the transcript is written by the Claude Code
harness from a real UI interaction — a model cannot answer a question by
itself — but the file lives under the same OS principal as everything else
here, so this anchor is tamper-EVIDENT, never tamper-proof, exactly like
the state store. The hard anchor (a permission prompt, or the user typing
the command) remains available: turn this gate off and keep `ask` rules.

An approval is:
  - a `toolUseResult.answers` pair from an AskUserQuestion entry in the
    MAIN thread (sidechains are subagents, not the user),
  - whose question (or its options) contains every required binding token —
    a seal's digest prefix, otherwise the exact command string, both
    whitespace-collapsed,
  - whose selected answer starts with "Approve",
  - recent (default 24h), and not already consumed by an earlier gated
    command (ledger in the repo's runtime state store). A consumed SEAL
    approval stays valid for the same digest, so resealing the identical
    contract after a governance-bundle change needs no second question.
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone

import cgel_common as C

TAIL_BYTES = 1 << 20  # transcripts grow to many MB; approvals are recent
MAX_AGE = timedelta(hours=24)
LEDGER_NAME = "approvals.jsonl"


def ledger_path(repo_root):
    return os.path.join(C.repo_state_dir(repo_root), LEDGER_NAME)


def collapse_ws(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def _tail_lines(path):
    try:
        size = os.path.getsize(path)
        seeked = size > TAIL_BYTES
        with open(path, "rb") as fh:
            if seeked:
                fh.seek(size - TAIL_BYTES)
            data = fh.read()
    except OSError as exc:
        C._debug("approvals:tail", exc)
        return []
    lines = data.decode("utf-8", "replace").splitlines()
    # The first line of a MID-FILE seek is almost surely a fragment. When we
    # read from byte 0 it is a whole line, and dropping it unconditionally
    # made the first approval of a short transcript invisible — the one a
    # user hits on their first task in a session.
    if seeked and len(lines) > 1:
        return lines[1:]
    return lines


def _parse_when(value):
    try:
        return datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except Exception:
        return None


def iter_answers(transcript_path):
    """Newest-first (key, question_blob, answer, at) for every answered
    AskUserQuestion in the transcript tail. question_blob folds in the
    question text plus its options' labels and descriptions, whitespace-
    collapsed, so binding tokens can live in either."""
    found = []
    for line in _tail_lines(transcript_path):
        line = line.strip()
        if not line or '"toolUseResult"' not in line or '"answers"' not in line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        if entry.get("isSidechain"):
            continue
        result = entry.get("toolUseResult")
        if not isinstance(result, dict):
            continue
        answers = result.get("answers")
        if not isinstance(answers, dict) or not answers:
            continue
        tool_use_id = None
        content = (entry.get("message") or {}).get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tool_use_id = block.get("tool_use_id")
                    break
        if not tool_use_id:
            continue
        questions = {}
        for question in result.get("questions") or []:
            if isinstance(question, dict):
                questions[question.get("question") or ""] = question
        at = _parse_when(entry.get("timestamp"))
        for index, (question_text, answer) in enumerate(sorted(answers.items())):
            key = "%s#%d" % (tool_use_id, index)
            question = questions.get(question_text)
            parts = [question_text]
            if question:
                # Only the option the user ACTUALLY CHOSE may carry a binding
                # token. Folding in every option meant a token that appeared
                # solely in a rejected option — "Don't seal", "Deny" — still
                # bound: the user's refusal authorised the command.
                for option in question.get("options") or []:
                    if not isinstance(option, dict):
                        continue
                    label = option.get("label") or ""
                    if label and collapse_ws(label) == collapse_ws(str(answer)):
                        parts.append(label)
                        parts.append(option.get("description") or "")
            found.append((key, collapse_ws(" ".join(parts)), answer, at))
    found.reverse()
    return found


class LedgerError(Exception):
    """The consumption ledger could not be read or written.

    'One approval, one command' is only true if we can both see what was
    already spent and record what we are spending. When we cannot, the only
    honest answer is to deny — a caller that treats this as 'nothing
    consumed' has turned the ledger into unlimited replay."""


# The two Bash hooks are two gates, and one question can legitimately
# authorise one command at each: `cgel seal … --allow-dirty && git push` is
# approval_gate's business AND command_guard's. Keying the ledger on the bare
# answer meant whichever gate ran first spent the key and the other found it
# spent — denied forever, with no second question that could help. The gate
# class is an explicit constant per hook, never derived from the free-form
# purpose string ("seal+allow-dirty" is one purpose, not two classes).
GATE_CGEL = "cgel"
GATE_GIT = "git"


def _load_ledger(path):
    """key -> {gate class: the row that spent it at that gate}.

    The row is kept, not just the gate name: reuse_ok compares its recorded
    tokens (the same-digest reseal path). A legacy row written before gate
    classes existed is filed under "*" and counts against EVERY gate, because
    "we don't know which gate spent this" must read as spent, not available."""
    consumed = {}
    try:
        rows = C.read_jsonl(path)
    except Exception as exc:
        raise LedgerError("approvals ledger unreadable: %s" % exc)
    for row in rows:
        key = row.get("key")
        if not key:
            continue
        consumed.setdefault(key, {})[row.get("gate") or "*"] = row
    return consumed


def _spent(consumed, key, gate):
    """The row that already spent this key at this gate, or None."""
    rows = consumed.get(key)
    if not rows:
        return None
    return rows.get(gate) or rows.get("*")


def find_approval(transcript_path, tokens, repo_root, reuse_ok=False, gate=None):
    """The newest un-consumed approval whose text carries every token.

    Returns (key, answer) or None. With reuse_ok, a consumed approval still
    counts when its recorded tokens equal these tokens (the reseal case).
    Raises LedgerError when the ledger cannot be read — the caller must deny.
    """
    if not transcript_path or not tokens:
        return None
    wanted = [collapse_ws(t) for t in tokens if collapse_ws(t)]
    if not wanted:
        return None
    consumed = _load_ledger(ledger_path(repo_root))
    now = datetime.now(timezone.utc)
    for key, blob, answer, at in iter_answers(transcript_path):
        if not (answer or "").strip().lower().startswith("approve"):
            continue
        if any(token not in blob for token in wanted):
            continue
        # An approval whose age cannot be established is not fresh. This read
        # `at is not None and ...`, so a missing or unparseable timestamp
        # skipped the expiry check entirely and the approval was valid
        # forever — an expiry that fails open is not an expiry.
        if at is None or now - at > MAX_AGE:
            continue
        row = _spent(consumed, key, gate)
        if row is not None and not (reuse_ok and row.get("tokens") == wanted):
            continue
        return key, answer
    return None


def consume(repo_root, key, purpose, tokens, command, gate=None):
    """Record that this approval was spent at this gate.

    Raises LedgerError on failure. This used to swallow OSError, so on an
    unwritable state dir every call found the approval un-consumed and
    allowed the command again: 'one approval, one command' became unlimited
    silent replay."""
    try:
        path = ledger_path(repo_root)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(
                C.canonical_json(
                    {
                        "key": key,
                        "gate": gate or "*",
                        "purpose": purpose,
                        "tokens": [collapse_ws(t) for t in tokens],
                        "command_digest": C.sha256_bytes(
                            command.encode("utf-8", "replace")
                        ),
                        "at": C.utc_now(),
                    }
                )
                + "\n"
            )
    except OSError as exc:
        C._debug("approvals:consume", exc)
        raise LedgerError("approvals ledger unwritable: %s" % exc)


def allow_json(reason):
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": reason,
            }
        }
    )
