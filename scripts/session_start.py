"""CGEL SessionStart — resume protocol + CLI PATH setup.

On session start/resume:
  1. ensures `cgel` is reachable on PATH (symlink ~/.local/bin/cgel ->
     this plugin's bin/cgel; POSIX only; opt-out CGEL_NO_SYMLINK=1;
     never overwrites a file it does not own),
  2. injects a compact state summary from the runtime state store as
     additionalContext, so a fresh context window re-enters the loop
     where it left off instead of re-deriving (or ignoring) task state.

Silent when no CGEL task exists. Never blocks (exit 0 always).
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cgel_common as C


def ensure_cli_symlink():
    """Idempotent. Creates or repairs ~/.local/bin/cgel only when the link
    is missing or clearly points at a (stale) cgel plugin install."""
    if os.name == "nt" or os.environ.get("CGEL_NO_SYMLINK"):
        return
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(
        os.path.dirname(os.path.realpath(__file__))
    )
    target = os.path.join(plugin_root, "bin", "cgel")
    if not os.path.isfile(target):
        return
    link = os.path.join(os.path.expanduser("~"), ".local", "bin", "cgel")
    try:
        if os.path.islink(link):
            current = os.readlink(link)
            if current == target:
                return
            if not current.endswith(os.path.join("bin", "cgel")):
                return  # someone else's link — leave it alone
            os.unlink(link)  # stale link from a previous install location
        elif os.path.exists(link):
            return  # a real file we do not own — never overwrite
        os.makedirs(os.path.dirname(link), exist_ok=True)
        os.symlink(target, link)
    except OSError as exc:
        C._debug("session_start:symlink", exc)


def summary_text(repo_root, task):
    sealed = task["sealed"]
    state = task["state"]
    contract = sealed["contract"]
    tdir = C.task_dir(repo_root, task["task_id"])
    records = C.iteration_records(tdir)
    opens = [r for r in records if r.get("type") == "iteration_open"]
    decisions = [r for r in records if r.get("type") == "iteration_decision"]
    budgets = contract["budgets"]
    max_iter = budgets["max_iterations"] + state.get("budget_extra_iterations", 0)
    max_replans = budgets["max_replans"] + state.get("budget_extra_replans", 0)
    replans = sum(1 for d in decisions if d.get("decision") == "REPLAN")

    lines = [
        "CGEL resume — a sealed task is in progress; continue it, do not restart.",
        "Task: %s (%s) — %s" % (
            task["task_id"], contract["task"]["type"], contract["task"]["goal"]
        ),
        "Lifecycle: %s%s" % (
            task["lifecycle"],
            " (reason: %s)" % state.get("blocked_reason")
            if task["lifecycle"] == "BLOCKED"
            else "",
        ),
        "Scope allowed: %s" % ", ".join(contract["scope"]["allowed"]),
        "Budgets: iterations %d/%d, replans %d/%d"
        % (len(opens), max_iter, replans, max_replans),
    ]

    pending = C.open_iteration(records)
    if pending:
        lines.append(
            "Open iteration %d: %s (decide with `cgel iterate decide ...`)"
            % (pending["iteration"], pending.get("intended_change") or "?")
        )
    signature = C.latest_failure_signature(tdir)
    if signature:
        lines.append(
            "Last failure: check=%s kind=%s subject=%s"
            % (
                signature.get("check_id"),
                signature.get("failure_kind"),
                (signature.get("failure_subject") or "")[:120],
            )
        )
    evidence = [
        r
        for r in C.read_jsonl(os.path.join(tdir, C.EVIDENCE_FILE))
        if r.get("type") == "evidence"
    ]
    lines.append("Evidence records: %d" % len(evidence))
    lines.append(
        "Next: `cgel status` for the current line; work only inside scope; "
        "PASS needs fresh `cgel verify` evidence for every criterion."
    )
    return "\n".join(lines)


def main():
    ensure_cli_symlink()
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:
        C._debug("session_start:stdin", exc)
        return 0
    cwd = payload.get("cwd") or os.getcwd()
    repo_root = C.find_repo_root(cwd)
    if not repo_root:
        return 0
    task = C.load_state(repo_root)
    if task["lifecycle"] == "NO_TASK":
        return 0
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": summary_text(repo_root, task),
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # never break session startup
        C._debug("session_start:main", exc)
        sys.exit(0)
