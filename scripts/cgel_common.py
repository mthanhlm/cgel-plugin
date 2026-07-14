"""Shared helpers for CGEL hooks and CLI. Stdlib only.

Trust model note (Profile A): everything here runs as the same OS principal
as the agent's Bash tool. The state store is therefore tamper-evident at
best, never tamper-proof. Do not present it as a hard trust boundary.
"""

import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone

CONTRACT_REL_PATH = ".task/contract.json"
DRAFT_EXEMPT_PATTERNS = [".task/**"]

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
EDIT_LIFECYCLES = ("SEALED", "ACTIVE")  # ACTIVE arrives in Phase 2


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

    return errors


# ------------------------------------------------------------------- state

def load_state(repo_root):
    """Current task state from the runtime state store.

    Returns {"lifecycle": "NO_TASK"} or
    {"lifecycle": "SEALED"|"ACTIVE", "task_id", "sealed", "state"}.
    """
    store = repo_state_dir(repo_root)
    current_path = os.path.join(store, "CURRENT")
    try:
        with open(current_path, encoding="utf-8") as fh:
            task_id = fh.read().strip()
    except FileNotFoundError:
        return {"lifecycle": "NO_TASK"}
    except Exception as exc:
        _debug("load_state:CURRENT", exc)
        return {"lifecycle": "NO_TASK"}
    if not task_id:
        return {"lifecycle": "NO_TASK"}
    task_dir = os.path.join(store, task_id)
    try:
        state = load_json(os.path.join(task_dir, "state.json"))
        sealed = load_json(os.path.join(task_dir, "sealed_task.json"))
    except Exception as exc:
        _debug("load_state:task", exc)
        return {"lifecycle": "NO_TASK"}
    lifecycle = state.get("lifecycle")
    if lifecycle not in EDIT_LIFECYCLES:
        return {"lifecycle": "NO_TASK"}
    return {
        "lifecycle": lifecycle,
        "task_id": task_id,
        "sealed": sealed,
        "state": state,
    }
