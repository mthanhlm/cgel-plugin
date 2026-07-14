"""CGEL PostToolUse / PostToolUseFailure recorder.

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
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cgel_common as C

EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")


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
    event_name = payload.get("hook_event_name") or "PostToolUse"
    cwd = payload.get("cwd") or os.getcwd()
    repo_root = C.find_repo_root(cwd)
    if not repo_root:
        return 0
    task = C.load_state(repo_root)
    if task["lifecycle"] not in C.TASK_LIFECYCLES:
        return 0

    tool_input = payload.get("tool_input") or {}
    record = None

    if tool in EDIT_TOOLS and event_name == "PostToolUse":
        file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
        if not file_path:
            return 0
        abs_path = os.path.abspath(
            file_path if os.path.isabs(file_path) else os.path.join(cwd, file_path)
        )
        if not abs_path.startswith(repo_root + os.sep):
            return 0
        rel = os.path.relpath(abs_path, repo_root).replace(os.sep, "/")
        if C.path_matches(rel, C.DRAFT_EXEMPT_PATTERNS):
            return 0
        record = {"type": "edit", "tool": tool, "path": rel, "at": C.utc_now()}
    elif tool == "Bash":
        command = tool_input.get("command") or ""
        audit_all = C.read_config(repo_root).get("audit_bash") == "all"
        if "cgel" not in command and not audit_all:
            return 0
        record = {
            "type": "bash",
            "event": event_name,
            "command_head": command[:160],
            "command_digest": C.sha256_bytes(command.encode("utf-8", "replace")),
            "exit_code": _exit_code_of(payload),
            "at": C.utc_now(),
        }

    if record is None:
        return 0
    task_dir = C.task_dir(repo_root, task["task_id"])
    C.chain_append(
        os.path.join(task_dir, C.EVENTS_FILE),
        record,
        C.chain_seed(task["task_id"]),
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # recorder must never break a tool call
        C._debug("recorder:main", exc)
        sys.exit(0)
