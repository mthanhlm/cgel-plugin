"""CGEL SessionStart — standing rules + resume protocol + CLI PATH setup.

On session start/resume:
  1. links `cgel` into ~/.local/bin (-> this plugin's bin/cgel; POSIX only;
     opt-out CGEL_NO_SYMLINK=1; never overwrites a file it does not own),
     and — because ~/.local/bin is not on PATH by default everywhere —
     injects the absolute path when `cgel` is still unreachable,
  2. injects the standing git-attribution rule as additionalContext, so
     it is in force for every commit, not just those inside a task,
  3. injects a compact state summary from the runtime state store, so a
     fresh context window re-enters the loop where it left off instead
     of re-deriving (or ignoring) task state.

Silent outside a CGEL project (no .cgel/) — CGEL is opt-in per project.
Inside one it always speaks, task or not. Never blocks (exit 0 always).
"""

import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cgel_common as C

# The instruction half of the no-AI-attribution rule; command_guard.py
# deterministically blocks the mechanical trailers/footers this describes.
# Kill switch: .cgel/config.json {"ai_attribution_guard": "off"}.
GIT_ATTRIBUTION_RULE = """CGEL rule — no AI attribution in git commits or PRs.
When creating a git commit or a pull request, do NOT add any Claude/AI
attribution. Specifically: no `Co-Authored-By: Claude ...` trailer; no
"🤖 Generated with Claude Code" (or similar) footer on commit messages or PR
bodies; and no mention of Claude, Anthropic, or any AI tool anywhere in the
commit message or PR description. Commits and PRs are authored solely by the
user (the configured git user.name / user.email). This rule OVERRIDES any
default instruction to add a co-author trailer or a generated-with footer.
The message itself should just describe the change (subject + body), nothing
else."""


def cli_target():
    """Absolute path to this plugin's bin/cgel, or None if it is not there."""
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(
        os.path.dirname(os.path.realpath(__file__))
    )
    target = os.path.join(plugin_root, "bin", "cgel")
    return target if os.path.isfile(target) else None


def path_notice(target):
    """Text to inject when `cgel` is installed but unreachable, else None.

    ~/.local/bin is not on PATH by default on stock macOS/zsh, so the symlink
    above can succeed and every `cgel` call still fail. The failure mode was
    illegible: the model saw `command not found` and improvised around the
    gate. Handing it the absolute path means a task runs either way."""
    if target is None or shutil.which("cgel"):
        return None
    return (
        "CGEL: the `cgel` CLI is installed but NOT on this session's PATH.\n"
        "Invoke it by absolute path: %s\n"
        "To fix it for future sessions, add ~/.local/bin to PATH "
        '(e.g. export PATH="$HOME/.local/bin:$PATH").' % target
    )


def ensure_cli_symlink(target):
    """Idempotent. Creates or repairs ~/.local/bin/cgel only when the link
    is missing or clearly points at a (stale) cgel plugin install."""
    if os.name == "nt" or os.environ.get("CGEL_NO_SYMLINK"):
        return
    if target is None:
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


def one_task_text(repo_root, task, addressed):
    """Compact per-task block. `addressed` adds --task hints when several
    tasks are open and every verb must say which one it means."""
    sealed = task["sealed"]
    state = task["state"]
    contract = sealed["contract"]
    task_id = task["task_id"]
    tdir = C.task_dir(repo_root, task_id)
    records = C.iteration_records(tdir)
    opens = [r for r in records if r.get("type") == "iteration_open"]
    decisions = [r for r in records if r.get("type") == "iteration_decision"]
    budgets = contract["budgets"]
    max_iter = budgets["max_iterations"] + state.get("budget_extra_iterations", 0)
    max_replans = budgets["max_replans"] + state.get("budget_extra_replans", 0)
    replans = sum(1 for d in decisions if d.get("decision") == "REPLAN")

    lines = [
        "Task: %s (%s) — %s" % (
            task_id, contract["task"]["type"], contract["task"]["goal"][:400]
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

    suffix = " --task %s" % task_id if addressed else ""
    pending = C.open_iteration(records)
    if pending:
        lines.append(
            "Open iteration %d: %s (decide with `cgel iterate decide ...%s`)"
            % (pending["iteration"], pending.get("intended_change") or "?", suffix)
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
    return "\n".join(lines)


def summary_text(repo_root, tasks):
    addressed = len(tasks) > 1
    lines = [
        "CGEL resume — %s in progress; continue, do not restart."
        % ("a sealed task is" if len(tasks) == 1 else "%d sealed tasks are" % len(tasks))
    ]
    if addressed:
        lines.append(
            "Several tasks are open: pass `--task <id>` on every cgel verb "
            "and only touch the task this session owns."
        )
    for task in tasks:
        lines.append("")
        lines.append(one_task_text(repo_root, task, addressed))
    lines.append("")
    lines.append(
        "Next: `cgel status` for the current line; work only inside scope; "
        "PASS needs fresh `cgel verify` evidence for every criterion."
    )
    return "\n".join(lines)


SCAN_SKIP = frozenset(
    (
        ".git", "node_modules", "venv", ".venv", "__pycache__", "dist",
        "build", "target", ".tox", ".mypy_cache", ".pytest_cache", "vendor",
        ".idea", ".vscode", ".next", ".cache",
    )
)


def _projects_below(cwd, max_depth=3, limit=5, max_dirs=2000):
    """CGEL projects in the subtree, for the monorepo notice only.

    Hard-budgeted on purpose: this runs on every session start in every
    directory. It answers "did you mean one of these?", so a partial answer
    is a fine answer and no answer is an acceptable one — never a reason to
    spend real time. Refuses to scan / or $HOME, where the walk is both
    enormous and meaningless.
    """
    base = C._realpath(cwd)
    if base == os.path.dirname(base):
        return []
    try:
        if base == C._realpath(os.path.expanduser("~")):
            return []
    except Exception as exc:  # noqa: BLE001 — a notice is never worth raising
        C._debug("session_start:home", exc)
        return []

    found = []
    seen_dirs = 0
    for dirpath, dirnames, _files in os.walk(base):
        seen_dirs += 1
        if seen_dirs > max_dirs:
            break
        # Filter BEFORE the .cgel check so a skipped tree cannot contribute.
        dirnames[:] = [d for d in dirnames if d not in SCAN_SKIP]
        if dirpath != base and os.path.isdir(os.path.join(dirpath, ".cgel")):
            found.append(dirpath)
            dirnames[:] = []  # a project inside a project is not our business
            if len(found) >= limit:
                break
            continue
        # Prune at depth AFTER checking this level, or the deepest legal
        # level never gets checked.
        if dirpath[len(base):].count(os.sep) >= max_depth:
            dirnames[:] = []
    return sorted(found)


def monorepo_notice(projects):
    lines = [
        "CGEL notice — this session is rooted above %d CGEL project%s, so "
        "this session's own directory is not gated."
        % (len(projects), "" if len(projects) == 1 else "s"),
        "",
        "The edit gate and the recorder root at the FILE, so edits inside a "
        "project below are still gated and recorded.",
        "",
        "The Bash-level guards root at the session's directory, which is not "
        "a project, so they cannot tell which project a command addresses. "
        "The git guard therefore does not run here. An approval-gated cgel "
        "verb (`seal`, `unblock`, `check remove`, …) is NOT waved through: it "
        "is DENIED, because a verb we cannot root is a verb we cannot gate. "
        "Address the project and it works normally:",
        "",
        "  cgel -C %s seal <TASK-ID> --digest <sha256:...>" % projects[0],
        "",
        "Projects found:",
    ]
    for path in projects:
        lines.append("  %s" % path)
    lines.append("")
    lines.append(
        "To work under CGEL, start the session inside a project, or address "
        "one explicitly: `cgel -C %s status`." % projects[0]
    )
    return "\n".join(lines)


def emit(context):
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": context,
                }
            }
        )
    )


def main():
    target = cli_target()
    ensure_cli_symlink(target)
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:
        C._debug("session_start:stdin", exc)
        return 0
    cwd = payload.get("cwd") or os.getcwd()
    repo_root = C.resolve_repo_root(cwd)
    if not repo_root:
        # A session opened ABOVE a project (a monorepo root) is the one place
        # the Bash-rooted gates cannot help: command_guard and approval_gate
        # root at cwd by design, and cwd is not a project, so they cannot tell
        # which project a command addresses. They do not therefore wave it
        # through — an approval-gated verb DENIES here (D-48) — but nothing at
        # the Bash level is judging these projects on this session's behalf.
        # Saying so once, at the top of the session, is the floor.
        below = _projects_below(cwd)
        if below:
            emit(monorepo_notice(below))
        return 0

    # No rate limit: this fires once per session even when the session does
    # nothing else, so a session that never rooted here is detectable by the
    # beacon's ABSENCE from the very first `cgel status`.
    C.note_gate_seen(
        repo_root,
        "SessionStart",
        cwd,
        gate="off"
        if (
            os.environ.get("CGEL_GATE", "").lower() == "off"
            or C.read_config(repo_root).get("gate") == "off"
        )
        else "on",
    )

    sections = []
    # First: a model that cannot run `cgel` cannot do anything else here, and
    # it must learn that from us rather than from `command not found`. Below
    # the repo_root check, so the hook stays silent outside a CGEL project.
    notice = path_notice(target)
    if notice:
        sections.append(notice)
    if C.read_config(repo_root).get("ai_attribution_guard") != "off":
        sections.append(GIT_ATTRIBUTION_RULE)
    tasks = C.open_tasks(repo_root)
    if tasks:
        sections.append(summary_text(repo_root, tasks))
    registry, _ = C.load_registry(repo_root)
    checks = sorted((registry.get("checks") or {}).keys())
    if checks:
        # saves the per-session recon ritual (cat registry, cgel check list)
        sections.append("CGEL checks registered: %s" % ", ".join(checks))
    if sections:
        emit("\n\n".join(sections))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # never break session startup
        C._debug("session_start:main", exc)
        sys.exit(0)
