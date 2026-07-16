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
        with open(path, "rb") as fh:
            if size > TAIL_BYTES:
                fh.seek(size - TAIL_BYTES)
            data = fh.read()
    except OSError as exc:
        C._debug("approvals:tail", exc)
        return []
    lines = data.decode("utf-8", "replace").splitlines()
    # the first line of a mid-file seek is almost surely a fragment
    return lines[1:] if len(lines) > 1 else lines


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
        blobs = {}
        for question in result.get("questions") or []:
            if not isinstance(question, dict):
                continue
            parts = [question.get("question") or ""]
            for option in question.get("options") or []:
                if isinstance(option, dict):
                    parts.append(option.get("label") or "")
                    parts.append(option.get("description") or "")
            blobs[question.get("question") or ""] = collapse_ws(" ".join(parts))
        at = _parse_when(entry.get("timestamp"))
        for index, (question_text, answer) in enumerate(sorted(answers.items())):
            key = "%s#%d" % (tool_use_id, index)
            blob = blobs.get(question_text) or collapse_ws(question_text)
            found.append((key, blob, answer, at))
    found.reverse()
    return found


def _load_ledger(path):
    consumed = {}
    for row in C.read_jsonl(path):
        key = row.get("key")
        if key:
            consumed[key] = row
    return consumed


def find_approval(transcript_path, tokens, repo_root, reuse_ok=False):
    """The newest un-consumed approval whose text carries every token.

    Returns (key, answer) or None. With reuse_ok, a consumed approval still
    counts when its recorded tokens equal these tokens (the reseal case).
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
        if at is not None and now - at > MAX_AGE:
            continue
        row = consumed.get(key)
        if row is not None and not (reuse_ok and row.get("tokens") == wanted):
            continue
        return key, answer
    return None


def consume(repo_root, key, purpose, tokens, command):
    try:
        path = ledger_path(repo_root)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(
                C.canonical_json(
                    {
                        "key": key,
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
