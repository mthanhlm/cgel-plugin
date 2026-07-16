"""CGEL PreToolUse gate for Edit|Write|NotebookEdit.

Blocks (exit 2) file edits unless a sealed contract covers them. Several
tasks may be open at once (D-39): an edit is allowed when ANY open task in
an edit lifecycle covers the path —
  - the path matches that task's scope.allowed and not its scope.forbidden,
  - governance paths (.claude/**, .cgel/**, docs/standards/**, docs/adr/**,
    hook config) additionally require the matching protected capability in
    that same task's sealed contract.
With no covering task the block message says why per task, so two open
scopes never silently absorb each other's work.

Assurance honesty: HARD_ENFORCED for Edit/Write/NotebookEdit only. It does
not stop Bash-level writes on an unsandboxed host (Profile A).

Convenience gate -> fails OPEN on malformed input (never brick a session).
Kill switches: env CGEL_GATE=off, or .cgel/config.json {"gate": "off"}.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cgel_common as C


def allow():
    return 0


def block(message):
    print(message, file=sys.stderr)
    return 2


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:
        C._debug("contract_gate:stdin", exc)
        return allow()

    if os.environ.get("CGEL_GATE", "").lower() == "off":
        return allow()

    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not file_path:
        return allow()

    cwd = payload.get("cwd") or os.getcwd()
    repo_root = C.find_repo_root(cwd)
    if not repo_root:
        return allow()  # not a CGEL-enabled project

    if C.read_config(repo_root).get("gate") == "off":
        return allow()

    abs_path = os.path.abspath(
        file_path if os.path.isabs(file_path) else os.path.join(cwd, file_path)
    )
    if not abs_path.startswith(repo_root + os.sep):
        return allow()  # writes outside the project are not gated here
    rel = os.path.relpath(abs_path, repo_root).replace(os.sep, "/")

    if C.path_matches(rel, C.DRAFT_EXEMPT_PATTERNS):
        return allow()  # contract drafts and debug mirror stay writable

    capability = C.governance_capability_for(rel)
    editable = [
        t for t in C.open_tasks(repo_root) if t["lifecycle"] in C.EDIT_LIFECYCLES
    ]

    if not editable:
        return block(
            "CGEL gate: no sealed contract for this repository — application "
            "files are read-only. Draft %s, run `cgel summary`, get the "
            "user's approval (AskUserQuestion, digest included), and seal "
            "with `cgel seal <TASK-ID> --digest <sha256 from summary>`. "
            "Bypass (user only): CGEL_GATE=off." % C.CONTRACT_REL_PATH
        )

    reasons = []
    for task in editable:
        contract = (task.get("sealed") or {}).get("contract", {})
        scope = contract.get("scope", {})
        task_id = task.get("task_id")
        if capability and capability not in contract.get(
            "protected_capabilities", []
        ):
            reasons.append(
                "%s: governance path needs capability '%s'" % (task_id, capability)
            )
            continue
        if C.path_matches(rel, scope.get("forbidden", [])):
            reasons.append("%s: matches scope.forbidden" % task_id)
            continue
        if not C.path_matches(rel, scope.get("allowed", [])):
            reasons.append(
                "%s: outside scope.allowed (%s)"
                % (task_id, ", ".join(scope.get("allowed", [])))
            )
            continue
        return allow()  # this open task covers the edit

    if capability and all("capability" in reason for reason in reasons):
        return block(
            "CGEL gate: '%s' is a governance path (guidebook/registry/hook "
            "config). It is read-only during a task unless a sealed contract "
            "grants the protected capability '%s'. Draft a dedicated "
            "governance task if this change is intended." % (rel, capability)
        )
    return block(
        "CGEL gate: '%s' is not covered by any open task — %s. Do not widen "
        "a change silently: amend the right contract and reseal with the "
        "user, or open a task whose scope includes this path."
        % (rel, "; ".join(reasons))
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # convenience gate: never brick the session
        C._debug("contract_gate:main", exc)
        sys.exit(0)
