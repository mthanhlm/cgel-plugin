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
from datetime import datetime, timezone

CONTRACT_REL_PATH = ".task/contract.json"
DRAFT_EXEMPT_PATTERNS = [".task/**"]
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
    abspath = os.path.abspath(repo_root)
    digest = hashlib.sha256(abspath.encode("utf-8")).hexdigest()[:12]
    name = os.path.basename(abspath) or "repo"
    return "%s-%s" % (name, digest)


def repo_state_dir(repo_root):
    return os.path.join(state_root(), repo_id(repo_root))


def find_repo_root(start):
    """Nearest ancestor containing .cgel/ — CGEL is opt-in per project."""
    cur = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.isdir(os.path.join(cur, ".cgel")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


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
                out.append(".*")
                i += 2
                if i < len(pat) and pat[i] == "/":
                    i += 1
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

def normalize_contract(contract):
    """Apply defaults so summary/seal digest the exact same artifact."""
    c = json.loads(json.dumps(contract))  # deep copy
    c.setdefault("protected_capabilities", [])
    c.setdefault("exceptions", [])
    budgets = c.setdefault("budgets", {})
    budgets.setdefault("max_iterations", 5)
    budgets.setdefault("max_replans", 2)
    risk = c.setdefault("risk", {})
    risk.setdefault("level", "low")
    risk.setdefault("reasons", [])
    scope = c.setdefault("scope", {})
    scope.setdefault("allowed", [])
    scope.setdefault("forbidden", [])
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
_RISK_LEVELS = ("low", "medium", "high")


def validate_contract(contract):
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
        forbidden = scope.get("forbidden", [])
        if not isinstance(forbidden, list) or not all(
            isinstance(x, str) for x in forbidden
        ):
            err("scope.forbidden: list of path globs")

    caps = contract.get("protected_capabilities", [])
    if not isinstance(caps, list) or not all(isinstance(x, str) for x in caps):
        err("protected_capabilities: list of strings")

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

    risk = contract.get("risk", {})
    if not isinstance(risk, dict):
        err("risk: must be an object")
    elif risk.get("level", "low") not in _RISK_LEVELS:
        err("risk.level: one of %s" % (_RISK_LEVELS,))

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

def open_tasks(repo_root):
    """Every task in the store whose lifecycle is SEALED/ACTIVE/BLOCKED,
    oldest seal first.

    There is no CURRENT pointer any more — several tasks may be open at once
    (D-39) and state.json is the single authority. Tasks left open by older
    versions become visible here instead of being masked by a stale pointer;
    `cgel status` lists them and `cgel close --task <id>` retires them.
    """
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
            _debug("open_tasks:%s" % name, exc)
            continue
        if not isinstance(state, dict) or not isinstance(sealed, dict):
            # Valid JSON of the wrong shape. This is an enumerator on the read
            # side: it cannot refuse, so it skips — and every writer that MUST
            # refuse (seal's stale-directory check) does its own guarding.
            # Without this the .get() below raised out of every verb that lists
            # tasks, including the seal that was trying to report the problem.
            _debug("open_tasks:%s" % name, TypeError("state.json is not an object"))
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


def governance_bundle(repo_root):
    """Digest every gate-protected file: the sealed measure (contract §15.5).

    File digests are cached by (mtime_ns, size) in the runtime state store —
    same principal as everything else there, so the cache concedes nothing
    Profile A had not already conceded, and it turns the per-verify bundle
    walk from hash-everything into stat-everything.

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
    rehashed = False
    for rel in sorted(set(_iter_bundle_files(repo_root))):
        if exclude and rel != ".cgel/config.json" and path_matches(rel, exclude):
            continue
        full = os.path.join(repo_root, rel)
        try:
            info = os.stat(full)
            key = "%d:%d" % (info.st_mtime_ns, info.st_size)
        except OSError:
            key = None
        cached = cache.get(rel)
        if key and isinstance(cached, dict) and cached.get("key") == key:
            digest = cached.get("digest")
        else:
            digest = sha256_file(full)
            rehashed = True
        if digest:
            members[rel] = digest
            if key:
                fresh[rel] = {"key": key, "digest": digest}
    if rehashed or set(fresh) != set(cache):
        try:
            atomic_write_json(cache_path, fresh)
        except Exception as exc:
            _debug("bundle:cache", exc)
    member_list = [{"path": rel, "digest": members[rel]} for rel in sorted(members)]
    bundle_digest = sha256_bytes(canonical_json(member_list).encode("utf-8"))
    return {"digest": bundle_digest, "members": member_list}


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


def workspace_snapshot(repo_root):
    """base_revision + content digest of every path dirty vs HEAD.

    Evidence bound to this digest goes stale on ANY workspace change,
    including a commit (HEAD moves) — re-verify after committing.

    Per-path digests ride along as `entries` (capped) so a check that
    declares `watch` globs can tell an irrelevant change from one that
    touches what it measures. The diff_digest algorithm is unchanged.
    """
    try:
        head_proc = _git(repo_root, "rev-parse", "HEAD")
        status_proc = _git(repo_root, "status", "--porcelain", "--untracked-files=all")
    except Exception as exc:
        _debug("workspace_snapshot:git", exc)
        return {"base_revision": "no-git", "diff_digest": "no-git"}
    if status_proc.returncode != 0:
        return {"base_revision": "no-git", "diff_digest": "no-git"}
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
