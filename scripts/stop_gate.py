"""CGEL Stop gate — bounded continuation.

Blocks the agent from silently stopping mid-iteration: if the current task
is ACTIVE and the latest iteration has no recorded decision, exit 2 sends
the agent back to decide (RETRY/REPLAN/ROLLBACK_ITERATION) or close
honestly. Every iteration ends with a decision — that is the loop contract.

Bounded: at most `stop_continuation_limit` (config, default 2) forced
continuations per task, tracked in the state store — a Stop hook must
never create an infinite loop. Convenience gate -> fails OPEN.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cgel_common as C

DEFAULT_LIMIT = 2


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:
        C._debug("stop_gate:stdin", exc)
        return 0

    cwd = payload.get("cwd") or os.getcwd()
    repo_root = C.find_repo_root(cwd)
    if not repo_root:
        return 0
    task = C.load_state(repo_root)
    if task["lifecycle"] != "ACTIVE":
        return 0

    tdir = C.task_dir(repo_root, task["task_id"])
    pending = C.open_iteration(C.iteration_records(tdir))
    if not pending:
        return 0

    limit = C.read_config(repo_root).get("stop_continuation_limit", DEFAULT_LIMIT)
    if not isinstance(limit, int) or limit < 0:
        limit = DEFAULT_LIMIT
    used = task["state"].get("stop_continuations", 0)
    if used >= limit:
        return 0  # bound reached: let the turn end, the state store remembers

    C.update_state(repo_root, task["task_id"], stop_continuations=used + 1)
    print(
        "CGEL stop gate: task %s is ACTIVE and iteration %d has no decision. "
        "Do not leave the loop dangling: record the outcome with "
        "`cgel iterate decide RETRY|REPLAN|ROLLBACK_ITERATION`, then either "
        "continue, close (`cgel close --as ...`), or tell the user why you "
        "are stopping. (forced continuation %d/%d)"
        % (task["task_id"], pending["iteration"], used + 1, limit),
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # convenience gate: never trap the session
        C._debug("stop_gate:main", exc)
        sys.exit(0)
