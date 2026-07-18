"""Shared helpers for CGEL hooks and CLI. Stdlib only.

Trust model note (Profile A): everything here runs as the same OS principal
as the agent's Bash tool. The state store is therefore tamper-evident at
best, never tamper-proof. Do not present it as a hard trust boundary.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

CONTRACT_REL_PATH = ".task/contract.json"
DRAFT_EXEMPT_PATTERNS = [".task/**"]
# Root memory files the model may write during onboarding — before any task is
# sealed — so a fresh repo can be given a tailored CLAUDE.md. Exact
# repo-relative names only: a nested `sub/CLAUDE.md` is not one of these, and
# `.claude/CLAUDE.md` stays a governance path. contract_gate honours this ONLY
# while no task governs the repo.
ROOT_MEMORY_FILES = {"CLAUDE.md", "CLAUDE.local.md"}
REGISTRY_REL_PATH = ".cgel/registry.json"
EVIDENCE_FILE = "evidence.jsonl"
EVENTS_FILE = "events.jsonl"
ITERATIONS_FILE = "iterations.jsonl"
SEMANTIC_FILE = "semantic.jsonl"

# Directories whose contents form the sealed governance bundle (the measure).
# Mirrors GOVERNANCE_PATH_CAPS: everything the gate protects gets digested.
GOVERNANCE_BUNDLE_ROOTS = [".cgel", ".claude", "docs/standards", "docs/adr", "hooks"]

# Ordered: first match wins. Paths that shape how a task is judged or gated.
GOVERNANCE_PATH_CAPS = [
    (".cgel/registry.json", "modify-verification-registry"),
    (".cgel/registry.yaml", "modify-verification-registry"),
    (".claude/settings.json", "modify-hook-policy"),
    (".claude/settings.local.json", "modify-hook-policy"),
    ("hooks/**", "modify-hook-policy"),
    (".claude/**", "modify-governance"),
    (".cgel/**", "modify-governance"),
    ("docs/standards/**", "modify-governance"),
    ("docs/adr/**", "modify-governance"),
]

TERMINAL_STATUSES = ("ROLLED_BACK", "ESCALATE", "ABORT")
EDIT_LIFECYCLES = ("SEALED", "ACTIVE")  # BLOCKED does NOT allow edits
TASK_LIFECYCLES = ("SEALED", "ACTIVE", "BLOCKED")  # a current task exists


def _debug(context, exc):
    if os.environ.get("CGEL_DEBUG"):
        print("cgel-debug %s: %r" % (context, exc), file=sys.stderr)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def state_root():
    override = os.environ.get("CGEL_STATE_DIR")
    if override:
        return override
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(
            "~\\AppData\\Local"
        )
    else:
        base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser(
            "~/.local/state"
        )
    return os.path.join(base, "cgel")


def repo_id(repo_root):
    # Callers MUST pass a resolve_repo_root() result: this does not resolve
    # symlinks itself, so two aliases of one repo would key two stores.
    abspath = os.path.abspath(repo_root)
    digest = hashlib.sha256(abspath.encode("utf-8")).hexdigest()[:12]
    name = os.path.basename(abspath) or "repo"
    return "%s-%s" % (name, digest)


def repo_state_dir(repo_root):
    return os.path.join(state_root(), repo_id(repo_root))


def _find_cgel_dir(start):
    """Nearest ancestor containing .cgel/ — CGEL is opt-in per project."""
    cur = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.isdir(os.path.join(cur, ".cgel")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def _realpath(path):
    """realpath that never raises.

    The obvious bad cases do not raise on their own: non-strict realpath
    resolves a broken or looping link to the path UNRESOLVED, which is the
    answer we want — the target keeps its in-repo name and stays judged by
    scope instead of escaping the prefix test. This wrapper is for the
    residue (a non-str path, an embedded null). An exception escaping to a
    hook's bare `except -> exit 0` would turn an unreadable link into an
    ungated edit, so failure falls back to abspath and stays in-repo.
    """
    try:
        return os.path.realpath(path)
    except (OSError, ValueError, TypeError) as exc:
        _debug("realpath", exc)
        return os.path.abspath(path)


def _split_unresolved(target, cwd):
    """(real_dir, leaf) for `target` interpreted against `cwd`.

    No abspath before the split: abspath collapses `..` textually, which is
    wrong across a symlinked parent (`link/../x` is not `x` when `link`
    points elsewhere). Join, split, then resolve the DIRECTORY only.
    """
    raw = target if os.path.isabs(target) else os.path.join(cwd, target)
    parent, leaf = os.path.split(raw)
    return _realpath(parent or cwd), leaf


def resolve_repo_root(cwd, target=None):
    """The project a decision belongs to: rooted at the FILE, not the session.

    Realpath the DIRECTORY, never the final component. `src/escape.py` may be
    a symlink to /etc/passwd: resolving the leaf would move the decision to
    /etc, land outside repo_root, and ungate an edit scope.allowed never
    authorised. The directory alias defeats the prefix test (must-fix #5);
    the leaf alias is the one whose gating we must keep.

    With no target, root at the real cwd — a session's own project.
    """
    if target:
        real_dir, _leaf = _split_unresolved(target, cwd or os.getcwd())
        root = _find_cgel_dir(real_dir)
        if root:
            return root
        # Fall through: the target is outside any project, but the session may
        # still be inside one. resolve_target then reports in_repo=False.
    return _find_cgel_dir(_realpath(cwd or os.getcwd()))


def resolve_target(cwd, repo_root, target):
    """(rel, in_repo) for `target` against `repo_root`, both realpath'd at the
    directory. `rel` is the repo-relative slash path the scope is written in;
    in_repo is False when the target lives outside the project entirely."""
    if not repo_root:
        return None, False
    real_dir, leaf = _split_unresolved(target, cwd or os.getcwd())
    root = _realpath(repo_root)
    if real_dir != root and not real_dir.startswith(root + os.sep):
        return None, False
    abs_path = os.path.join(real_dir, leaf)
    return os.path.relpath(abs_path, root).replace(os.sep, "/"), True


def read_config(repo_root):
    path = os.path.join(repo_root, ".cgel", "config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        _debug("read_config", exc)
        return {}


def atomic_write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2, ensure_ascii=False, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError as exc:
            _debug("atomic_write_json cleanup", exc)
        raise


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------- globbing

def _glob_to_regex(pattern):
    pat = pattern.strip().replace(os.sep, "/")
    while pat.startswith("./"):
        pat = pat[2:]
    if pat.endswith("/"):
        pat += "**"
    out = []
    i = 0
    while i < len(pat):
        ch = pat[i]
        if ch == "*":
            if pat[i : i + 2] == "**":
                if pat[i + 2 : i + 3] == "/":
                    # `**/` means zero or more WHOLE segments. It used to
                    # compile to `.*`, which swallowed the slash and matched
                    # across segment boundaries: `src/**/impl/**` became
                    # `^src/.*impl/.*$` and authorised `src/notimpl/y.py` —
                    # a scope matching a path its author never named.
                    out.append("(?:[^/]*/)*")
                    i += 3
                else:
                    # Trailing (or bare) `**`: everything below here.
                    out.append(".*")
                    i += 2
            else:
                out.append("[^/]*")
                i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    return re.compile("^" + "".join(out) + "$")


_GLOB_CHARS = ("*", "?", "[")


def _is_bare_directory(repo_root, pattern):
    """Is `pattern` a wildcard-free path naming a directory that exists now?

    Residual, accepted: a wildcard-free pattern naming a directory that does
    not YET exist is not caught. Catching that needs an existence oracle over
    a scope whose whole job may be to create files, and a check that guesses
    is one the reader learns to ignore.
    """
    pat = pattern.strip().replace(os.sep, "/")
    if any(ch in pat for ch in _GLOB_CHARS) or pat.endswith("/"):
        return False  # has wildcards, or already says "everything below"
    try:
        return os.path.isdir(os.path.join(repo_root, pat))
    except OSError as exc:
        _debug("bare_directory:%s" % pattern, exc)
        return False


def path_matches(rel_path, patterns):
    rel = rel_path.replace(os.sep, "/")
    for pattern in patterns or []:
        try:
            if _glob_to_regex(pattern).match(rel):
                return True
        except re.error as exc:
            _debug("path_matches:%s" % pattern, exc)
    return False


def governance_capability_for(rel_path):
    for pattern, capability in GOVERNANCE_PATH_CAPS:
        if path_matches(rel_path, [pattern]):
            return capability
    return None


def _glob_prefix(pattern):
    pat = pattern.strip().replace(os.sep, "/")
    while pat.startswith("./"):
        pat = pat[2:]
    cut = len(pat)
    for wildcard in ("*", "?", "["):
        idx = pat.find(wildcard)
        if idx != -1:
            cut = min(cut, idx)
    return pat[:cut].rstrip("/")


def scopes_overlap(a_patterns, b_patterns):
    """Cheap containment heuristic: two allowed-scopes overlap when the
    literal prefix of one pattern contains the other's. Advisory only — the
    edit gate and the repo-wide diff digest stay authoritative; this exists
    so sealing a second task over shared paths is a warned choice, not an
    accident."""
    for a in a_patterns or []:
        prefix_a = _glob_prefix(a)
        for b in b_patterns or []:
            prefix_b = _glob_prefix(b)
            shorter, longer = sorted((prefix_a, prefix_b), key=len)
            if not shorter:
                return True  # a bare '**' touches everything
            if longer == shorter or longer.startswith(shorter + "/"):
                return True
    return False


# ---------------------------------------------------------------- contract

RISK_LEVELS = ("low", "medium", "high")

# Reaching any of these means the task can change how it is judged, or how
# the gate behaves. That is a structural fact about the scope, not an opinion
# about the work, so the graded party does not get to rate it lower.
_GOVERNANCE_ROOTS = tuple(pattern for pattern, _cap in GOVERNANCE_PATH_CAPS)


def _floor_risk(c):
    """Raise risk.level to `high` for the two cases the author cannot argue.

    Deliberately narrow and deliberately dumb. Both triggers are literally
    true — the task really can rewrite its own measure — and the escape is to
    tighten the scope, not to argue. A floor that fires on a guess ("more
    than N files") is one the reader learns to ignore, and a warning nobody
    reads is worse than no warning (D-36)."""
    risk = c["risk"]
    reasons = []
    if c.get("protected_capabilities"):
        reasons.append(
            "floored to high: the contract requests protected capabilities (%s)"
            % ", ".join(c["protected_capabilities"])
        )
    reaching = [
        pattern
        for pattern in c["scope"].get("allowed") or []
        if scopes_overlap([pattern], list(_GOVERNANCE_ROOTS))
    ]
    if reaching:
        reasons.append(
            "floored to high: scope.allowed reaches governance paths (%s)"
            % ", ".join(sorted(reaching))
        )
    if not reasons:
        return
    risk["level"] = "high"
    # Idempotent: normalize runs at validate, summary AND seal, and each must
    # digest the same artifact — appending the reason twice would move the
    # digest between the screen the user read and the seal they approved.
    for reason in reasons:
        if reason not in risk["reasons"]:
            risk["reasons"].append(reason)


def normalize_contract(contract):
    """Apply defaults so summary/seal digest the exact same artifact."""
    c = json.loads(json.dumps(contract))  # deep copy
    c.setdefault("protected_capabilities", [])
    budgets = c.setdefault("budgets", {})
    budgets.setdefault("max_iterations", 5)
    budgets.setdefault("max_replans", 2)
    # risk.level has NO default. It used to default to "low", which is the
    # level at which _semantic_requirement returns required=False — so the
    # challenger, the built-in rules and the opus verifier never ran on a
    # normal task, and cmd_summary never told the user that. The whole
    # semantic layer was gated behind a setdefault nobody typed. A risk level
    # is a claim the author makes and argues; validate_contract rejects a
    # contract that does not make one.
    risk = c.setdefault("risk", {})
    risk.setdefault("reasons", [])
    scope = c.setdefault("scope", {})
    scope.setdefault("allowed", [])
    scope.setdefault("forbidden", [])
    _floor_risk(c)
    scope.setdefault("notes", [])
    return c


def contract_digest(contract):
    canonical = json.dumps(
        normalize_contract(contract),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def validate_contract(contract, repo_root=None):
    """Hand-rolled validation (stdlib only). Returns a list of error strings."""
    errors = []

    def err(msg):
        errors.append(msg)

    if not isinstance(contract, dict):
        return ["contract root must be a JSON object"]

    task = contract.get("task")
    if not isinstance(task, dict):
        err("task: required object with id, type, goal")
    else:
        task_id = task.get("id")
        if not isinstance(task_id, str) or not _TASK_ID_RE.match(task_id):
            err("task.id: required, pattern ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
        if not isinstance(task.get("goal"), str) or not task.get("goal").strip():
            err("task.goal: required non-empty string")
        if not isinstance(task.get("type"), str) or not task.get("type").strip():
            err("task.type: required non-empty string (bug-fix, feature, ...)")

    criteria = contract.get("acceptance_criteria")
    if not isinstance(criteria, list) or not criteria:
        err("acceptance_criteria: required non-empty list")
    else:
        for idx, item in enumerate(criteria):
            if not isinstance(item, dict):
                err("acceptance_criteria[%d]: must be an object" % idx)
                continue
            if not isinstance(item.get("id"), str) or not item.get("id").strip():
                err("acceptance_criteria[%d].id: required" % idx)
            if (
                not isinstance(item.get("description"), str)
                or not item.get("description").strip()
            ):
                err("acceptance_criteria[%d].description: required" % idx)
            checks = item.get("required_checks", [])
            if not isinstance(checks, list) or not all(
                isinstance(x, str) for x in checks
            ):
                err("acceptance_criteria[%d].required_checks: list of strings" % idx)

    scope = contract.get("scope")
    if not isinstance(scope, dict):
        err("scope: required object with allowed[]")
    else:
        allowed = scope.get("allowed")
        if (
            not isinstance(allowed, list)
            or not allowed
            or not all(isinstance(x, str) and x.strip() for x in allowed)
        ):
            err("scope.allowed: required non-empty list of path globs")
        else:
            for pattern in allowed:
                if os.path.isabs(pattern) or ".." in pattern.split("/"):
                    err("scope.allowed: '%s' must be repo-relative" % pattern)
                elif repo_root and _is_bare_directory(repo_root, pattern):
                    # A wildcard-free pattern naming a directory matches NO
                    # file: path_matches compares it to a file's rel path.
                    # scopes_overlap reads the same string the opposite way
                    # (as a prefix), so a contract scoped to `src` seals green,
                    # warns about nothing, and then authorises nothing — the
                    # gate refuses every edit the user believes they approved.
                    # This is a TYPE check (a directory is here now), never an
                    # existence oracle: a scope may legitimately create files.
                    err(
                        "scope.allowed: '%s' is a directory, and a directory "
                        "matches no file — write '%s/**' (or '%s/'). "
                        "(scopes_overlap reads it the opposite way, so this "
                        "seals green and authorises nothing.)"
                        % (pattern, pattern.rstrip("/"), pattern.rstrip("/"))
                    )
        forbidden = scope.get("forbidden", [])
        if not isinstance(forbidden, list) or not all(
            isinstance(x, str) for x in forbidden
        ):
            err("scope.forbidden: list of path globs")

    caps = contract.get("protected_capabilities", [])
    if not isinstance(caps, list) or not all(isinstance(x, str) for x in caps):
        err("protected_capabilities: list of strings")

    # The risk level decides whether anything grades this work: at `low`,
    # semantic verification is not required, so the challenger, the built-in
    # rules and the verifier all stand down. It used to default to `low`
    # silently. Make it a claim the author states and argues — at EVERY level,
    # so it cannot be dodged by claiming `medium` to skip the argument.
    risk = contract.get("risk")
    if not isinstance(risk, dict):
        err(
            'risk: required object, e.g. {"level": "medium", "reasons": '
            '["why this level is honest"]} — there is no default; the level '
            "decides whether the work is graded at all"
        )
    else:
        level = risk.get("level")
        if level not in RISK_LEVELS:
            err(
                "risk.level: required, one of %s — say which and argue it in "
                "risk.reasons" % ", ".join(RISK_LEVELS)
            )
        reasons = risk.get("reasons")
        if (
            not isinstance(reasons, list)
            or not reasons
            or not all(isinstance(x, str) and x.strip() for x in reasons)
        ):
            err(
                "risk.reasons: required non-empty list of strings — a level "
                "with no argument is a default wearing a claim's clothes"
            )

    budgets = contract.get("budgets", {})
    if not isinstance(budgets, dict):
        err("budgets: must be an object")
    else:
        max_iter = budgets.get("max_iterations", 5)
        max_replans = budgets.get("max_replans", 2)
        if not isinstance(max_iter, int) or max_iter < 1:
            err("budgets.max_iterations: integer >= 1")
        if not isinstance(max_replans, int) or max_replans < 0:
            err("budgets.max_replans: integer >= 0")

    review = contract.get("intent_review")
    if review is not None:
        if not isinstance(review, dict):
            err("intent_review: must be an object")
        else:
            concerns = review.get("concerns", [])
            if not isinstance(concerns, list) or not all(
                isinstance(x, str) for x in concerns
            ):
                err("intent_review.concerns: list of strings")

    return errors


# ------------------------------------------------------------------- state

def repo_fingerprint(repo_root):
    """Which repository this is, by git lineage: the sorted root commits.

    Deliberately NOT unique per working copy — a clone, a worktree and a
    `mv`d repo all share it. That is the point. It GUARDS the path-keyed
    store; it never keys it. A repo-local UUID would key uniquely and be
    wrong: .cgel/ is gitignored (D-35), so a fresh clone would mint a new id
    and orphan live tasks, while `cp -r` would duplicate one.

    Returns None when there is no answer (no git, no commits, git missing).
    None means "unknown", and unknown never drops a task.

    Note: because the lineage is shared, stale_stores() may surface a sibling
    worktree's store. Its output is advice for the user, never an automatic
    move.
    """
    head = None
    try:
        proc = _git(repo_root, "rev-parse", "HEAD")
        if proc.returncode == 0:
            head = proc.stdout.strip()
    except Exception as exc:  # noqa: BLE001 — identity is best-effort
        _debug("fingerprint:head", exc)
        return None
    if not head:
        return None  # no git, or a repo with no commits yet

    store = repo_state_dir(repo_root)
    cache_path = os.path.join(store, "fingerprint.json")
    cached = None
    try:
        cached = load_json(cache_path)
    except Exception as exc:
        _debug("fingerprint:cache-read", exc)
    if isinstance(cached, dict) and cached.get("head") == head:
        value = cached.get("fingerprint")
        return value if isinstance(value, str) else None

    try:
        proc = _git(repo_root, "rev-list", "--max-parents=0", "HEAD")
        if proc.returncode != 0:
            return None
        roots = sorted(x.strip() for x in proc.stdout.split() if x.strip())
    except Exception as exc:  # noqa: BLE001
        _debug("fingerprint:rev-list", exc)
        return None
    if not roots:
        return None
    value = "git-root:" + ",".join(roots)

    # Only cache into a store that already exists: a READ must never be the
    # thing that creates the store directory, or `cgel status` in a fresh
    # checkout would mint a store and then report on it.
    if os.path.isdir(store):
        try:
            atomic_write_json(cache_path, {"head": head, "fingerprint": value})
        except Exception as exc:
            _debug("fingerprint:cache-write", exc)
    return value


def _fingerprint_ok(current, state):
    """Does this task belong to the repo now at this path?

    Unknown on EITHER side keeps the task. A task sealed before fingerprints
    existed has none; a non-git project can never produce one. Neither is
    evidence of a mismatch, and this guard drops tasks — so it fires only on
    a positive disagreement between two known values.
    """
    if not current:
        return True
    recorded = (state or {}).get("repo_fingerprint")
    if not recorded:
        return True
    return recorded == current


def _store_tasks(repo_root):
    """Every open task in the store at this path, fingerprint unexamined."""
    store = repo_state_dir(repo_root)
    tasks = []
    try:
        names = sorted(os.listdir(store))
    except OSError:
        return tasks
    for name in names:
        tdir = os.path.join(store, name)
        if not os.path.isdir(tdir):
            continue
        try:
            state = load_json(os.path.join(tdir, "state.json"))
            sealed = load_json(os.path.join(tdir, "sealed_task.json"))
        except Exception as exc:
            _debug("_store_tasks:%s" % name, exc)
            continue
        if not isinstance(state, dict) or not isinstance(sealed, dict):
            # Valid JSON of the wrong shape. This is an enumerator on the read
            # side: it cannot refuse, so it skips — and every writer that MUST
            # refuse (seal's stale-directory check) does its own guarding.
            # Without this the .get() below raised out of every verb that lists
            # tasks, including the seal that was trying to report the problem.
            _debug("_store_tasks:%s" % name, TypeError("state.json is not an object"))
            continue
        if state.get("lifecycle") not in TASK_LIFECYCLES:
            continue
        if state.get("task_id") and state["task_id"] != name:
            continue  # rotated archive dir — not addressable
        tasks.append(
            {
                "lifecycle": state["lifecycle"],
                "task_id": state.get("task_id") or name,
                "sealed": sealed,
                "state": state,
            }
        )
    tasks.sort(key=lambda t: t["state"].get("sealed_at") or "")
    return tasks


def open_tasks(repo_root):
    """Every task in the store whose lifecycle is SEALED/ACTIVE/BLOCKED,
    oldest seal first — and which belongs to the repo now at this path.

    There is no CURRENT pointer any more — several tasks may be open at once
    (D-39) and state.json is the single authority. Tasks left open by older
    versions become visible here instead of being masked by a stale pointer;
    `cgel status` lists them and `cgel close --task <id>` retires them.

    The store is keyed by absolute path, so a NEW repo at a reused path would
    otherwise inherit the old one's open task — a sealed contract whose scope
    describes code that no longer exists. Those tasks are withheld here and
    reported by `cgel status` (see foreign_tasks).
    """
    tasks = _store_tasks(repo_root)
    # Lazy: the fingerprint costs a git call, so do not pay it for the two
    # cases that cannot need it — no tasks at all, and tasks that predate
    # fingerprints entirely. Semantics are identical either way.
    if not any(t["state"].get("repo_fingerprint") for t in tasks):
        return tasks
    current = repo_fingerprint(repo_root)
    return [t for t in tasks if _fingerprint_ok(current, t["state"])]


def foreign_tasks(repo_root):
    """Open tasks in this path's store that belong to a DIFFERENT repo.

    Non-empty means a repo was replaced at this path (a delete + re-clone, a
    fresh `git init` over an old checkout). The tasks are real and their
    evidence is intact — they just are not about this code.
    """
    tasks = _store_tasks(repo_root)
    if not any(t["state"].get("repo_fingerprint") for t in tasks):
        return []
    current = repo_fingerprint(repo_root)
    if not current:
        return []
    return [t for t in tasks if not _fingerprint_ok(current, t["state"])]


def stale_stores(repo_root):
    """Stores at OTHER paths that look like they belong to this repo.

    A moved or renamed repo re-keys its store and loses sight of its own open
    tasks — `cgel status` says DRAFT and the user concludes the task is gone.
    Returns [(store_path, old_root, task_ids, confidence)] where confidence is
    'certain' or 'possible'. Never moves anything: the caller shows the user
    what it found and lets them decide, because git lineage is shared by
    worktrees and clones, so a hit may be a sibling that is doing fine.
    """
    root = _realpath(repo_root)
    mine = repo_state_dir(repo_root)
    current = repo_fingerprint(repo_root)
    prefix = os.path.basename(root) + "-"
    hits = []
    try:
        names = sorted(os.listdir(state_root()))
    except OSError:
        return hits
    for name in names:
        store = os.path.join(state_root(), name)
        if store == mine or not os.path.isdir(store):
            continue
        ids, fps, roots = [], set(), set()
        try:
            entries = sorted(os.listdir(store))
        except OSError:
            continue
        for entry in entries:
            state = None
            try:
                state = load_json(os.path.join(store, entry, "state.json"))
            except Exception:
                continue
            if not isinstance(state, dict):
                continue
            if state.get("lifecycle") not in TASK_LIFECYCLES:
                continue
            ids.append(state.get("task_id") or entry)
            if state.get("repo_fingerprint"):
                fps.add(state["repo_fingerprint"])
            if state.get("repo_root"):
                roots.add(state["repo_root"])
        if not ids:
            continue
        old_root = sorted(roots)[0] if roots else None
        # The copy discriminator, before any lineage match. A MOVE leaves its
        # old path empty; a `cp -r`, a clone and a `git worktree add` leave the
        # original in place and share its lineage. Without this, copying a repo
        # with an open task tells the user to `mv` the ORIGINAL's store onto
        # the copy — adopting a live task away from the repo still using it.
        if old_root and os.path.isdir(old_root) and _realpath(old_root) != root:
            continue
        # Strongest discriminator first.
        if current and current in fps:
            hits.append((store, old_root, ids, "certain"))
        elif any(_realpath(r) == root for r in roots):
            hits.append((store, old_root, ids, "certain"))
        elif not fps and not roots and name.startswith(prefix):
            # The only branch that can see a pre-0.13 store — and pre-0.13 is
            # every store that exists today. A name match is weak evidence, so
            # it is never presented as a paste-ready move.
            hits.append((store, old_root, ids, "possible"))
    return hits


def load_task(repo_root, task_id):
    for task in open_tasks(repo_root):
        if task["task_id"] == task_id:
            return task
    return None


def resolve_task(repo_root, task_id=None):
    """(task, error). An explicit --task wins; else the sole open task.

    With two or more tasks open every addressed verb must say which one —
    the alternative is what the transcripts showed: one session deciding
    another session's open iteration.
    """
    tasks = open_tasks(repo_root)
    if task_id:
        for task in tasks:
            if task["task_id"] == task_id:
                return task, None
        open_ids = ", ".join(t["task_id"] for t in tasks) or "none"
        return None, "no open task '%s' (open: %s)" % (task_id, open_ids)
    if not tasks:
        return None, "no sealed task"
    if len(tasks) == 1:
        return tasks[0], None
    return None, "%d tasks are open (%s) — pass --task <id>" % (
        len(tasks),
        ", ".join(t["task_id"] for t in tasks),
    )


def task_dir(repo_root, task_id):
    return os.path.join(repo_state_dir(repo_root), task_id)


def update_state(repo_root, task_id, **fields):
    path = os.path.join(task_dir(repo_root, task_id), "state.json")
    try:
        state = load_json(path)
    except Exception as exc:
        _debug("update_state:load", exc)
        state = {"task_id": task_id}
    state.update(fields)
    atomic_write_json(path, state)
    return state


def set_blocked(repo_root, task_id, reason):
    fields = {
        "lifecycle": "BLOCKED",
        "blocked_reason": reason,
        "blocked_at": utc_now(),
    }
    try:
        state = load_json(os.path.join(task_dir(repo_root, task_id), "state.json"))
        if state.get("lifecycle") in EDIT_LIFECYCLES:
            fields["lifecycle_before_block"] = state["lifecycle"]
    except Exception as exc:
        _debug("set_blocked:prior", exc)
    return update_state(repo_root, task_id, **fields)


# ---------------------------------------------------------------- digests

def sha256_bytes(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file(path):
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()
    except OSError as exc:
        _debug("sha256_file:%s" % path, exc)
        return None


def canonical_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ------------------------------------------------------- governance bundle

def _iter_bundle_files(repo_root):
    for root in GOVERNANCE_BUNDLE_ROOTS:
        abs_root = os.path.join(repo_root, root)
        if os.path.isfile(abs_root):
            yield root
            continue
        for dirpath, dirnames, filenames in os.walk(abs_root):
            dirnames[:] = sorted(
                d for d in dirnames if d not in ("__pycache__", ".git")
            )
            for name in sorted(filenames):
                if name.endswith((".pyc", ".tmp")) or name == ".DS_Store":
                    continue
                full = os.path.join(dirpath, name)
                yield os.path.relpath(full, repo_root).replace(os.sep, "/")


BUNDLE_SCHEMA = 2

# A stat-keyed cache may not be trusted for a file whose mtime is inside the
# filesystem's timestamp granularity: within one tick, two same-size writes
# are indistinguishable by stat. Rehash instead of guessing.
STAT_CACHE_SETTLE_SECONDS = 2.0

# Keys the bundle deliberately does NOT measure, per member. `permissions` in
# settings.local.json is rewritten by the harness every time the user approves
# a tool — measuring it meant the user's own approval BLOCKED every open task,
# which taught them the block was noise. The rest of the file is still
# measured, and the file is still edit-gated as a governance path.
BUNDLE_PROJECTIONS = {".claude/settings.local.json": ("permissions",)}


def projected_digest(full_path, drop_keys):
    """Digest a JSON member with `drop_keys` removed. Any parse trouble falls
    back to the whole file: measuring too much is a false block, measuring the
    wrong thing silently is a hole, and only one of those is safe."""
    try:
        with open(full_path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return sha256_file(full_path)
        kept = {k: v for k, v in data.items() if k not in drop_keys}
        return sha256_bytes(canonical_json(kept).encode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — unreadable/invalid: measure it all
        _debug("bundle:projection:%s" % full_path, exc)
        return sha256_file(full_path)


def governance_bundle(repo_root, schema=BUNDLE_SCHEMA):
    """Digest every gate-protected file: the sealed measure (contract §15.5).

    VERSIONED: `schema` selects the measure. Callers comparing against a
    SEALED bundle must recompute under THAT bundle's schema, defaulting to 1
    when it records none (i.e. every seal made before this release). The
    projection and the richer cache key therefore apply only to new seals —
    no open seal moves, and nobody is forced to reseal to upgrade.

    File digests are cached by a stat key in the runtime state store — same
    principal as everything else there, so the cache concedes nothing Profile
    A had not already conceded, and it turns the per-verify bundle walk from
    hash-everything into stat-everything. The key is (mtime_ns, size) at
    schema 1 and (schema, mtime_ns, size, ctime_ns, inode) at schema 2, and
    at either schema a member touched within STAT_CACHE_SETTLE_SECONDS is
    rehashed rather than trusted.

    Config `bundle_exclude` globs drop churn-prone paths from the measure
    (the recurring case: a gitignored repo-local skill whose every edit
    voided open seals). Excluded files stay edit-gated as governance paths;
    changing them just no longer moves the bundle digest. The config file
    itself is always digested, so an exclusion cannot be added invisibly
    mid-task."""
    exclude = read_config(repo_root).get("bundle_exclude") or []
    cache_path = os.path.join(repo_state_dir(repo_root), "bundle_cache.json")
    try:
        cache = load_json(cache_path)
        if not isinstance(cache, dict):
            cache = {}
    except Exception:
        cache = {}
    members = {}
    fresh = {}
    excluded = []
    rehashed = False
    for rel in sorted(set(_iter_bundle_files(repo_root))):
        if exclude and rel != ".cgel/config.json" and path_matches(rel, exclude):
            excluded.append(rel)
            continue
        full = os.path.join(repo_root, rel)
        try:
            info = os.stat(full)
            if schema >= 2:
                # ctime and inode too: a file swapped for another of the same
                # size keeps mtime+size, and the pair alone was a cache hit on
                # the old content.
                key = "v2:%d:%d:%d:%d:%d" % (
                    schema, info.st_mtime_ns, info.st_size,
                    info.st_ctime_ns, info.st_ino,
                )
            else:
                key = "%d:%d" % (info.st_mtime_ns, info.st_size)
            # Applies to BOTH schemas, because it is not a change to the
            # measure — it is a fix to the cache lying about it, and v1's
            # cache lies the same way. Filesystem timestamp granularity is
            # coarser than a write: two same-size rewrites inside one tick
            # produce identical mtime AND ctime (measured, not assumed: on
            # WSL2 /tmp three consecutive writes share one ns). A stat-keyed
            # cache then serves the OLD digest for a governance file that
            # changed, so the bundle does not move and the sealed measure is
            # silently stale — verified against the shipped tree by editing a
            # registry check command and watching the digest hold still.
            # A file touched inside the window is never served from cache;
            # the cost is bounded to files written seconds ago.
            if key and time.time() - info.st_mtime < STAT_CACHE_SETTLE_SECONDS:
                key = None
        except OSError:
            key = None
        cached = cache.get(rel)
        if key and isinstance(cached, dict) and cached.get("key") == key:
            digest = cached.get("digest")
        else:
            drop = BUNDLE_PROJECTIONS.get(rel) if schema >= 2 else None
            digest = projected_digest(full, drop) if drop else sha256_file(full)
            rehashed = True
        if digest:
            members[rel] = digest
            if key:
                fresh[rel] = {"key": key, "digest": digest}
        elif schema >= 2:
            # sha256_file returns None for a member it cannot read (mode 000,
            # a dangling link). Dropping it silently REMOVED it from the
            # measure, so making a governance file unreadable took it out of
            # the bundle without moving the digest. Record the fact instead.
            members[rel] = "unreadable"
    if rehashed or set(fresh) != set(cache):
        try:
            atomic_write_json(cache_path, fresh)
        except Exception as exc:
            _debug("bundle:cache", exc)
    member_list = [{"path": rel, "digest": members[rel]} for rel in sorted(members)]
    bundle_digest = sha256_bytes(canonical_json(member_list).encode("utf-8"))
    return {
        "digest": bundle_digest,
        "members": member_list,
        "schema": schema,
        "excluded": excluded,
    }


def bundle_diff(sealed_members, current_members):
    sealed_map = {m["path"]: m["digest"] for m in sealed_members or []}
    current_map = {m["path"]: m["digest"] for m in current_members or []}
    changes = []
    for path in sorted(set(sealed_map) | set(current_map)):
        if path not in current_map:
            changes.append("removed: %s" % path)
        elif path not in sealed_map:
            changes.append("added: %s" % path)
        elif sealed_map[path] != current_map[path]:
            changes.append("changed: %s" % path)
    return changes


# ------------------------------------------------------ workspace snapshot

def _git(repo_root, *args):
    # text=True decodes strictly: a filename or commit message this locale
    # cannot decode raised UnicodeDecodeError inside workspace_snapshot, whose
    # `except Exception` then returned the "no-git" constant — a digest that
    # compares equal to itself forever, so evidence never went stale. A decode
    # must never be able to disable a control. quotePath is pinned so a user's
    # git config cannot change what the callers' parsers see.
    return subprocess.run(
        ["git", "-c", "core.quotePath=true"] + list(args),
        cwd=repo_root,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


MAX_SNAPSHOT_ENTRIES = 400


WORKSPACE_INERT = {
    "git-missing": "git is not on PATH",
    "no-git": "this project is not a git work tree",
    "git-error": "git could not be run here",
}


def git_state(repo_root):
    """(code, detail) — is the workspace binding live? code None means yes.

    Deliberately `rev-parse --is-inside-work-tree`, NOT `rev-parse HEAD`: a
    freshly initialized repo with no commits is a live work tree whose diff
    digest still varies, so HEAD would call it dead when it is not.
    """
    try:
        proc = _git(repo_root, "rev-parse", "--is-inside-work-tree")
    except FileNotFoundError:
        return "git-missing", WORKSPACE_INERT["git-missing"]
    except OSError as exc:
        _debug("git_state:os", exc)
        return "git-error", WORKSPACE_INERT["git-error"]
    except Exception as exc:  # subprocess.TimeoutExpired and friends
        _debug("git_state", exc)
        return "git-error", WORKSPACE_INERT["git-error"]
    if proc.returncode != 0 or proc.stdout.strip() != "true":
        return "no-git", WORKSPACE_INERT["no-git"]
    return None, None


def inert_reason(code):
    return WORKSPACE_INERT.get(code, "the workspace binding is not live")


BEACON_FILE = "gate_beacon.json"


def note_gate_seen(repo_root, hook, cwd, gate="on", rate_limit=False):
    """Record that a hook ran here. The gate's only liveness signal.

    `cgel status` claims SEALED. Whether the gate is actually running is a
    different fact, and one CGEL cannot ask the harness: a plugin that was
    never installed, a session rooted above the project, a stale settings
    file all look identical from inside. A hook that fires leaves this; a
    gate that never fires leaves nothing, and absence is the report.

    Diagnostics must never break a gate, so the whole body is best-effort.
    """
    try:
        store = repo_state_dir(repo_root)
        if not os.path.isdir(store):
            return  # a beacon must not be the thing that mints the store
        path = os.path.join(store, BEACON_FILE)
        if rate_limit:
            # Skip only when the beacon is fresh AND recorded the same gate
            # state: a transition always writes, so flipping the kill switch
            # surfaces on the next tool call rather than up to a minute later.
            try:
                age = time.time() - os.path.getmtime(path)
                if age < 60:
                    prior = load_json(path)
                    if isinstance(prior, dict) and prior.get("gate") == gate:
                        return
            except (OSError, ValueError, TypeError):
                pass
        atomic_write_json(
            path, {"hook": hook, "cwd": cwd, "gate": gate, "at": utc_now()}
        )
    except Exception as exc:  # noqa: BLE001 — never break a gate to log one
        _debug("beacon:write", exc)


def gate_seen(repo_root):
    """(beacon, age_seconds) or (None, None). Age from mtime — no ISO parse."""
    try:
        path = os.path.join(repo_state_dir(repo_root), BEACON_FILE)
        beacon = load_json(path)
        if not isinstance(beacon, dict):
            return None, None
        return beacon, time.time() - os.path.getmtime(path)
    except Exception as exc:  # noqa: BLE001
        _debug("beacon:read", exc)
        return None, None


def workspace_snapshot(repo_root):
    """base_revision + content digest of every path dirty vs HEAD.

    Evidence bound to this digest goes stale on ANY workspace change,
    including a commit (HEAD moves) — re-verify after committing.

    Per-path digests ride along as `entries` (capped) so a check that
    declares `watch` globs can tell an irrelevant change from one that
    touches what it measures. The diff_digest algorithm is unchanged.
    """
    # The "no-git" constants stay byte-identical: _evidence_problem compares
    # diff_digest for EQUALITY, so changing them would silently invalidate
    # every in-flight seal. What was missing is that this digest equals itself
    # forever — the workspace binding is inert and nothing said so, so every
    # surface printed green over a control that was not running. `degraded`
    # is additive and carries the reason out to the surfaces.
    try:
        head_proc = _git(repo_root, "rev-parse", "HEAD")
        status_proc = _git(repo_root, "status", "--porcelain", "--untracked-files=all")
    except Exception as exc:
        _debug("workspace_snapshot:git", exc)
        code, _ = git_state(repo_root)
        return {
            "base_revision": "no-git",
            "diff_digest": "no-git",
            "degraded": code or "git-error",
        }
    if status_proc.returncode != 0:
        code, _ = git_state(repo_root)
        return {
            "base_revision": "no-git",
            "diff_digest": "no-git",
            "degraded": code or "no-git",
        }
    head = head_proc.stdout.strip() if head_proc.returncode == 0 else "no-head"
    entries = []
    detail = {}
    for line in status_proc.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip().strip('"')
        if path == ".task" or path.startswith(".task/"):
            continue
        full = os.path.join(repo_root, path)
        if os.path.isfile(full):
            digest = sha256_file(full) or "unreadable"
        else:
            digest = "deleted"
        entries.append("%s:%s" % (path, digest))
        detail[path] = digest
    canonical = head + "\n" + "\n".join(sorted(entries))
    snapshot = {
        "base_revision": head,
        "diff_digest": sha256_bytes(canonical.encode("utf-8")),
    }
    if len(detail) <= MAX_SNAPSHOT_ENTRIES:
        snapshot["entries"] = detail
    return snapshot


def snapshot_changed_paths(old, new):
    """Paths whose content differs between two snapshots, or None when that
    is unknowable — a side lacks per-path entries, or HEAD moved (a commit
    re-bases every path, so everything may have changed)."""
    if not isinstance(old, dict) or not isinstance(new, dict):
        return None
    if old.get("base_revision") != new.get("base_revision"):
        return None
    a, b = old.get("entries"), new.get("entries")
    if a is None or b is None:
        return None
    return sorted(p for p in set(a) | set(b) if a.get(p) != b.get(p))


# ---------------------------------------------------------------- registry

def load_registry(repo_root):
    """Returns (registry dict, file digest). Missing file -> ({}, None)."""
    path = os.path.join(repo_root, REGISTRY_REL_PATH)
    try:
        data = load_json(path)
    except FileNotFoundError:
        return {}, None
    except Exception as exc:
        _debug("load_registry", exc)
        return {}, sha256_file(path)
    return (data if isinstance(data, dict) else {}), sha256_file(path)


# -------------------------------------------------------------- hash chain

def chain_seed(task_id):
    return "genesis:%s" % task_id


def _record_hash(record):
    body = dict(record)
    chain = dict(body.get("chain") or {})
    chain.pop("hash", None)
    body["chain"] = chain
    return sha256_bytes(canonical_json(body).encode("utf-8"))


def _lock(fh):
    try:
        import fcntl

        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    except Exception as exc:  # non-POSIX: best-effort append
        _debug("chain:lock", exc)


def chain_append(path, record, seed):
    """Append a hash-chained record. Tamper-EVIDENT only (Profile A)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a+", encoding="utf-8") as fh:
        _lock(fh)
        fh.seek(0)
        prev = seed
        last = None
        for line in fh:
            if line.strip():
                last = line
        if last is not None:
            try:
                prev = (json.loads(last).get("chain") or {}).get("hash") or seed
            except Exception as exc:
                _debug("chain_append:last", exc)
        rec = dict(record)
        rec["chain"] = {"prev": prev}
        rec["chain"]["hash"] = _record_hash(rec)
        fh.seek(0, os.SEEK_END)
        fh.write(canonical_json(rec) + "\n")
        return rec


def chain_verify(path, seed):
    """Returns (ok, record_count, error). Missing file -> (True, 0, None)."""
    if not os.path.isfile(path):
        return True, 0, None
    prev = seed
    count = 0
    try:
        with open(path, encoding="utf-8") as fh:
            for number, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    return False, count, "record %d: not valid JSON" % number
                chain = rec.get("chain") or {}
                if chain.get("prev") != prev:
                    return False, count, "record %d: chain broken (prev mismatch)" % number
                if chain.get("hash") != _record_hash(rec):
                    return False, count, "record %d: content does not match hash" % number
                prev = chain["hash"]
                count += 1
    except OSError as exc:
        return False, count, "unreadable: %s" % exc
    return True, count, None


def read_jsonl(path):
    records = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    records.append(json.loads(line))
                except Exception as exc:
                    _debug("read_jsonl:%s" % path, exc)
    except FileNotFoundError:
        pass
    except OSError as exc:
        _debug("read_jsonl:%s" % path, exc)
    return records


def chain_head(path):
    records = read_jsonl(path)
    if not records:
        return None
    return (records[-1].get("chain") or {}).get("hash")


def count_edit_events(task_dir_path):
    events = read_jsonl(os.path.join(task_dir_path, EVENTS_FILE))
    return sum(1 for e in events if e.get("type") == "edit")


def edit_event_paths(task_dir_path):
    """Paths of every recorded edit event, in order — so freshness checks can
    ask WHICH files changed after a record, not just how many."""
    return [
        e.get("path")
        for e in read_jsonl(os.path.join(task_dir_path, EVENTS_FILE))
        if e.get("type") == "edit"
    ]


# -------------------------------------------------------------- iterations

def iteration_records(task_dir_path):
    return read_jsonl(os.path.join(task_dir_path, ITERATIONS_FILE))


def open_iteration(records):
    """The latest iteration_open with no matching decision, or None."""
    decided = {
        r.get("iteration") for r in records if r.get("type") == "iteration_decision"
    }
    for record in reversed(records):
        if (
            record.get("type") == "iteration_open"
            and record.get("iteration") not in decided
        ):
            return record
    return None


def latest_failure_signature(task_dir_path):
    """Machine-observed signature of the newest failing evidence that no
    later pass of the same check has superseded.

    A check that failed and then passed is green: keeping its old failure
    alive tripped the default-same guard on finished work twice in real use,
    once forcing an unwanted ROLLBACK label and once an ESCALATE close of
    fully verified work plus a whole second contract."""
    seen = set()
    for rec in reversed(read_jsonl(os.path.join(task_dir_path, EVIDENCE_FILE))):
        if rec.get("type") != "evidence":
            continue
        check_id = (rec.get("check") or {}).get("id")
        if check_id in seen:
            continue
        seen.add(check_id)
        result = rec.get("result") or {}
        if result.get("status") == "fail":
            return {
                "check_id": check_id,
                "failure_kind": result.get("failure_kind"),
                "failure_subject": result.get("failure_subject"),
                "diagnostic_fingerprint": result.get("diagnostic_fingerprint"),
            }
    return None


def signature_key(signature):
    """default-same guard compares kind + fingerprint, not free text."""
    if not signature:
        return None
    return (
        signature.get("check_id"),
        signature.get("failure_kind"),
        signature.get("diagnostic_fingerprint") or signature.get("failure_subject"),
    )


# ---------------------------------------------------------- semantic rules

_RULE_HEAD_RE = re.compile(
    r"^##\s+([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d+)\s*(?:—|–|-)\s*(.+?)\s*$"
)
_RULE_FIELD_RE = re.compile(r"^([A-Za-z-]+):\s*(.+?)\s*$")

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILTIN_RULES_PATH = os.path.join(PLUGIN_DIR, "rules", "builtin.md")


def _parse_rules_file(path, source):
    rules = {}
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as exc:
        _debug("parse_rules:%s" % source, exc)
        return rules
    current = None
    for line in lines:
        head = _RULE_HEAD_RE.match(line)
        if head:
            current = {
                "id": head.group(1),
                "title": head.group(2),
                "blocking": False,
                "applies_to": [],
                "owner": None,
                "source": source,
            }
            rules[current["id"]] = current
            continue
        if line.startswith("#"):
            current = None
            continue
        if current is None:
            continue
        field = _RULE_FIELD_RE.match(line)
        if not field:
            continue
        key, value = field.group(1).lower(), field.group(2)
        if key == "blocking":
            current["blocking"] = value.strip().lower() in ("yes", "true")
        elif key == "applies-to":
            current["applies_to"] = [s.strip() for s in value.split(",") if s.strip()]
        elif key == "owner":
            current["owner"] = value.strip()
    return rules


def load_semantic_rules(repo_root):
    """Project rules from docs/standards/*.md, layered over the plugin's
    built-in review rules (impact, debt, comments, secrets).

    Built-ins are the production bar every repo gets for free; a project
    rule with the same id replaces its built-in, and `.cgel/config.json`
    {"builtin_rules": "off"} removes them entirely. Returns
    {rule_id: {id, title, blocking, applies_to, owner, source}}."""
    rules = {}
    if read_config(repo_root).get("builtin_rules") != "off":
        rules.update(_parse_rules_file(BUILTIN_RULES_PATH, "cgel-builtin"))
    base = os.path.join(repo_root, "docs", "standards")
    if not os.path.isdir(base):
        return rules
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames.sort()
        for name in sorted(filenames):
            if not name.endswith(".md"):
                continue
            source = os.path.relpath(os.path.join(dirpath, name), repo_root).replace(
                os.sep, "/"
            )
            rules.update(_parse_rules_file(os.path.join(dirpath, name), source))
    return rules
