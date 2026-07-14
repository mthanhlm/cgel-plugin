"""CGEL PreToolUse gate for Edit|Write|NotebookEdit.

Blocks (exit 2) file edits unless a sealed contract covers them:
  - no sealed contract  -> block everything except .task/** drafts
  - sealed              -> path must match scope.allowed, not scope.forbidden
  - governance paths (.claude/**, .cgel/**, docs/standards/**, docs/adr/**,
    hook config) additionally require the matching protected capability
    in the sealed contract.

Assurance honesty: this is HARD_ENFORCED for Edit/Write/NotebookEdit only.
It does not stop Bash-level writes on an unsandboxed host (Profile A).

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

    task = C.load_state(repo_root)
    sealed_contract = (task.get("sealed") or {}).get("contract", {})
    capabilities = sealed_contract.get("protected_capabilities", [])

    capability = C.governance_capability_for(rel)
    if capability:
        if task["lifecycle"] not in C.EDIT_LIFECYCLES or capability not in capabilities:
            return block(
                "CGEL gate: '%s' is a governance path (guidebook/registry/hook "
                "config). It is read-only during a task unless the sealed "
                "contract grants the protected capability '%s'. Draft a "
                "dedicated governance task if this change is intended."
                % (rel, capability)
            )
        # capability granted: fall through to the normal scope check

    if task["lifecycle"] not in C.EDIT_LIFECYCLES:
        return block(
            "CGEL gate: no sealed contract for this repository — application "
            "files are read-only. Draft %s, then run `cgel validate` and "
            "`cgel summary`, show the summary to the user, and seal with "
            "`cgel seal <TASK-ID> --digest <sha256 from summary>`. "
            "Bypass (user only): CGEL_GATE=off." % C.CONTRACT_REL_PATH
        )

    scope = sealed_contract.get("scope", {})
    if C.path_matches(rel, scope.get("forbidden", [])):
        return block(
            "CGEL gate: '%s' matches scope.forbidden of sealed task %s. "
            "If this file must change, ESCALATE: amend the contract and "
            "reseal with the user." % (rel, task.get("task_id"))
        )
    if not C.path_matches(rel, scope.get("allowed", [])):
        return block(
            "CGEL gate: '%s' is outside scope.allowed of sealed task %s "
            "(allowed: %s). Do not widen the change silently — ESCALATE: "
            "amend the contract and reseal with the user."
            % (rel, task.get("task_id"), ", ".join(scope.get("allowed", [])))
        )

    return allow()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # convenience gate: never brick the session
        C._debug("contract_gate:main", exc)
        sys.exit(0)
