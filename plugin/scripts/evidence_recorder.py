"""CGEL PostToolUse recorder.

Appends hash-chained events to the task's events.jsonl in the runtime
state store:
  - edit events (Edit/Write/NotebookEdit inside the repo) — they mark all
    prior evidence stale (edit_seq binding checked at PASS),
  - bash events for `cgel` invocations — an independent, hook-observed
    anchor that `cgel audit` cross-checks (dual-sink candidate, D-32).

Recorder rule: NEVER block the tool call. Exit 0 on every path; failures
are visible only with CGEL_DEBUG=1. Payload shape differences across
Claude Code versions are isolated in the adapter below (backlog V-4).
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cgel_common as C

EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")
CGEL_WORD = re.compile(r"\bcgel\b")


def _exit_code_of(payload):
    """Best-effort exit code across payload variants (adapter, V-4)."""
    response = payload.get("tool_response")
    candidates = []
    if isinstance(response, dict):
        for key in ("exit_code", "exitCode", "code", "returnCode", "return_code"):
            candidates.append(response.get(key))
    for value in candidates:
        if isinstance(value, int):
            return value
    return None


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:
        C._debug("recorder:stdin", exc)
        return 0

    tool = payload.get("tool_name") or ""
    cwd = payload.get("cwd") or os.getcwd()
    tool_input = payload.get("tool_input") or {}

    # The target must be known BEFORE rooting: the recorder roots at the file
    # it is recording, so an edit below a monorepo-root session is still an
    # event in the project that owns the file. A Bash command has no target
    # and roots at the session.
    file_path = None
    if tool in EDIT_TOOLS:
        file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
        if not file_path:
            return 0
    elif tool != "Bash":
        return 0

    repo_root = C.resolve_repo_root(cwd, file_path)
    if not repo_root:
        return 0
    tasks = C.open_tasks(repo_root)
    if not tasks:
        return 0

    record = None
    if tool in EDIT_TOOLS:
        rel, in_repo = C.resolve_target(cwd, repo_root, file_path)
        if not in_repo:
            return 0
        if C.path_matches(rel, C.DRAFT_EXEMPT_PATTERNS):
            return 0
        record = {"type": "edit", "tool": tool, "path": rel, "at": C.utc_now()}
    else:
        command = tool_input.get("command") or ""
        audit_all = C.read_config(repo_root).get("audit_bash") == "all"
        if not CGEL_WORD.search(command) and not audit_all:
            return 0
        record = {
            "type": "bash",
            "command_head": command[:160],
            "command_digest": C.sha256_bytes(command.encode("utf-8", "replace")),
            "exit_code": _exit_code_of(payload),
            "at": C.utc_now(),
        }

    if record is None:
        return 0
    # Every open task gets the event: the workspace is shared, so an edit
    # anywhere is a freshness fact for all of them (watch globs decide
    # per-check whether it matters).
    for task in tasks:
        task_dir = C.task_dir(repo_root, task["task_id"])
        C.chain_append(
            os.path.join(task_dir, C.EVENTS_FILE),
            dict(record),
            C.chain_seed(task["task_id"]),
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # recorder must never break a tool call
        C._debug("recorder:main", exc)
        sys.exit(0)
