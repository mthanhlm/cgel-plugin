"""CGEL PreToolUse gate for Edit|Write|NotebookEdit.

Rooted at the FILE, not at the session: a session opened above a project
(a monorepo root) still gates the edits it makes inside one.

Blocks (exit 2) file edits unless a sealed contract covers them. Several
tasks may be open at once (D-39), so the two halves of a scope have
different reach:
  - scope.forbidden is REPO-WIDE. Any open task's forbidden list vetoes the
    path for every task, including while that task is BLOCKED (blocked is
    not withdrawn). "Must never change" is the one line a user writes
    expecting it to hold regardless of what else is going on.
  - scope.allowed is per task. An edit is allowed when ANY open task in an
    edit lifecycle names the path, and no task forbids it.
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

    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not file_path:
        return allow()

    cwd = payload.get("cwd") or os.getcwd()
    repo_root = C.resolve_repo_root(cwd, file_path)
    if not repo_root:
        return allow()  # not a CGEL-enabled project

    # The kill-switch checks moved BELOW rooting so that a gate turned off is
    # still a gate that RAN: `cgel status` can then say gate=off rather than
    # gate=unobserved, which is the difference between "you turned it off" and
    # "it was never wired up".
    gate = "on"
    if os.environ.get("CGEL_GATE", "").lower() == "off":
        gate = "off"
    elif C.read_config(repo_root).get("gate") == "off":
        gate = "off"
    C.note_gate_seen(repo_root, "PreToolUse:Edit", cwd, gate=gate, rate_limit=True)
    if gate == "off":
        return allow()

    rel, in_repo = C.resolve_target(cwd, repo_root, file_path)
    if not in_repo:
        return allow()  # writes outside the project are not gated here

    if C.path_matches(rel, C.DRAFT_EXEMPT_PATTERNS):
        return allow()  # contract drafts and debug mirror stay writable

    capability = C.governance_capability_for(rel)
    open_tasks = C.open_tasks(repo_root)

    # Root memory files (CLAUDE.md, CLAUDE.local.md) are writable during the
    # onboarding window — when NO task governs the repo yet — so a fresh
    # project can be given a tailored CLAUDE.md before the first seal. The
    # moment any task is SEALED/ACTIVE/BLOCKED this falls through to normal
    # scope, so the model cannot rewrite its own memory mid-task, unscoped and
    # unrecorded. Nested CLAUDE.md and .claude/CLAUDE.md are not root memory
    # files and stay gated (the latter as a governance path).
    if not open_tasks and rel in C.ROOT_MEMORY_FILES:
        return allow()

    # scope.forbidden is repo-wide, and it is checked BEFORE anything can
    # allow. It was per-task: task B's scope.allowed silently overrode task
    # A's "must never change", which is the one line in a contract a user
    # writes expecting it to hold no matter what else is going on. A BLOCKED
    # task's veto counts too — it is blocked, not withdrawn.
    vetoes = [
        t["task_id"]
        for t in open_tasks
        if C.path_matches(
            rel, ((t.get("sealed") or {}).get("contract", {}).get("scope", {}))
            .get("forbidden", [])
        )
    ]
    if vetoes:
        return block(
            "CGEL gate: '%s' matches scope.forbidden on %s. A forbidden path "
            "is refused repo-wide for as long as that task is open — another "
            "task's scope.allowed does not override it. Close that task, or "
            "reseal it with the user if its forbidden list is wrong."
            % (rel, ", ".join(vetoes))
        )

    editable = [t for t in open_tasks if t["lifecycle"] in C.EDIT_LIFECYCLES]

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
        # No per-task forbidden check here: the repo-wide veto above already
        # returned for every forbidden path, on every open task.
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
