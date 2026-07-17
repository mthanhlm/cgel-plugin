"""Resolve a Bash command line into the invocations it actually performs.

Both PreToolUse Bash gates used to match the TEXT of a command against a
regex table. Text is not an invocation, and the gap ran both ways:

  - `git -C . push --force origin main` bypassed all eight destructive
    rules and the push gate, because every pattern anchored `git\\s+push`
    and git accepts globals in between.
  - `grep -rn 'git push' docs/` was blocked, because the text contains the
    pattern. A read of a command is not a run of it.

This module answers one question — "what does this line actually invoke?" —
and both gates decide on the answer instead of on the text.

THREE PROPERTIES, all load-bearing, all tested:

1. It never raises. shlex was the obvious tool and is disqualified:
   shlex.split("git log --grep=won't") raises ValueError, and in
   command_guard that lands in a fail-closed handler — an apostrophe in a
   commit message becomes a false block. Here, anything unparseable
   resolves to None.

2. None means FALL BACK, never "allow". A segment we cannot resolve is
   handed back to the caller's existing blunt-regex verdict, which is
   exactly today's behaviour. The tokenizer can only make the gates
   sharper, never blinder.

3. A shell that reads from a pipe, a subshell, or a command substitution
   makes the WHOLE line unresolved. Otherwise the segment split is a
   laundering channel: `echo 'push --force' | xargs git` must not resolve
   to a benign `echo`.

Stdlib only, no imports at all. Python 3.8+.
"""

# Unquoted characters that end one invocation and begin another. `&` is a
# separator too (background), and a newline separates commands unless it was
# escaped — see _join_continuations.
_SEPARATORS = (";", "\n", "|", "&")

# Anything here means a nested command we cannot see into. The line stops
# being resolvable; the caller keeps its blunt verdict.
_OPAQUE = ("$(", "`", "<(", ">(", "${")

# A command that takes a program to run from its arguments or its stdin.
# Resolving a segment to one of these would name the wrapper, not the work.
_SHELL_LIKE = frozenset(
    ("sh", "bash", "zsh", "dash", "ksh", "eval", "exec", "source", ".")
)
# Transparent wrappers: the real command is right there in their arguments,
# so `env FOO=1 git push` and `sudo git push` are pushes and must resolve.
_ARG_RUNNERS = frozenset(("env", "nohup", "time", "timeout", "nice", "sudo"))
# These take the command from STDIN, so what runs cannot be read off the
# line. Their presence anywhere poisons every segment — this is the set that
# makes segment-splitting safe rather than a laundering channel.
_STDIN_RUNNERS = _SHELL_LIKE | frozenset(("xargs",))

# git's own globals, which may appear between `git` and the subcommand.
# Splitting these is the whole point: `git -C . push` is a push.
_GIT_GLOBAL_WITH_VALUE = frozenset(("-C", "-c", "--git-dir", "--work-tree", "--namespace",
                                    "--exec-path", "--super-prefix"))
_GIT_GLOBAL_FLAG = frozenset(("--no-pager", "--paginate", "--bare", "--no-replace-objects",
                              "--literal-pathspecs", "--no-optional-locks", "--html-path",
                              "--man-path", "--info-path", "-p", "-P"))

# gh's globals behave the same way ahead of `pr create`.
_GH_GLOBAL_WITH_VALUE = frozenset(("-R", "--repo", "--hostname"))


class Segment(object):
    """One invocation on the line.

    argv is None when the segment could not be resolved — the caller must
    then keep whatever verdict its own regexes produce for the raw text."""

    __slots__ = ("raw", "argv", "env")

    def __init__(self, raw, argv=None, env=None):
        self.raw = raw
        self.argv = argv
        self.env = env or {}

    @property
    def resolved(self):
        return self.argv is not None

    def __repr__(self):
        return "Segment(%r, argv=%r)" % (self.raw[:40], self.argv)


def join_continuations(command):
    """Undo backslash-newline line wrapping.

    The gates' patterns use [^\\n] to bound a command, so a wrapped
    `git reset \\<newline>  --hard` evaded every rule. Collapsing the
    continuation is the fix; collapsing ALL whitespace is not — that would
    merge two genuinely separate lines into one command and produce false
    blocks (`cgel status` newline `npm run build -- --allow-dirty`).
    """
    out = []
    i = 0
    n = len(command)
    while i < n:
        if command[i] == "\\" and i + 1 < n and command[i + 1] == "\n":
            i += 2
            while i < n and command[i] in " \t":
                i += 1
            out.append(" ")
            continue
        out.append(command[i])
        i += 1
    return "".join(out)


def _split_segments(command):
    """Split on unquoted separators. Returns (segments, ok).

    ok is False when quoting is unbalanced — the split is then untrustworthy
    and the whole line must fall back."""
    segments = []
    buf = []
    quote = None
    i = 0
    n = len(command)
    while i < n:
        ch = command[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < n:
                buf.append(command[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            buf.append(ch)
            buf.append(command[i + 1])
            i += 2
            continue
        if ch in _SEPARATORS:
            segments.append("".join(buf))
            buf = []
            # swallow a doubled separator (&& ||)
            if i + 1 < n and command[i + 1] == ch:
                i += 1
            i += 1
            continue
        buf.append(ch)
        i += 1
    segments.append("".join(buf))
    if quote:
        return [command], False
    return [s for s in segments if s.strip()], True


def _tokenize(segment):
    """Split one segment into argv. Returns None if it cannot be trusted."""
    if any(marker in segment for marker in _OPAQUE):
        return None
    tokens = []
    buf = []
    quote = None
    had = False
    i = 0
    n = len(segment)
    while i < n:
        ch = segment[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < n:
                buf.append(segment[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
                i += 1
                continue
            buf.append(ch)
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            had = True
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            buf.append(segment[i + 1])
            i += 2
            continue
        if ch in " \t":
            if buf or had:
                tokens.append("".join(buf))
                buf = []
                had = False
            i += 1
            continue
        if ch in ("<", ">"):
            # A redirection. Everything after it is a file, not an argument,
            # and a leading one hides the real argv0. Stop trusting this
            # segment rather than guess.
            return None
        buf.append(ch)
        i += 1
    if quote:
        return None
    if buf or had:
        tokens.append("".join(buf))
    return tokens or None


def _strip_assignments(argv):
    """Drop leading VAR=value prefixes. Returns (env, rest)."""
    env = {}
    i = 0
    for tok in argv:
        if "=" in tok and not tok.startswith("=") and not tok.startswith("-"):
            name = tok.split("=", 1)[0]
            if name and (name[0].isalpha() or name[0] == "_") and all(
                c.isalnum() or c == "_" for c in name
            ):
                env[name] = tok.split("=", 1)[1]
                i += 1
                continue
        break
    return env, argv[i:]


def _unwrap(argv):
    """Peel wrappers that take the real command in their arguments.

    `env FOO=1 git push` and `sudo git push` are pushes. `xargs git push` is
    not resolvable — the arguments come from stdin, so what runs is unknown.
    """
    seen = 0
    while argv and seen < 4:
        head = argv[0]
        if head in _ARG_RUNNERS:
            rest = argv[1:]
            # skip the wrapper's own flags and assignments
            while rest and (rest[0].startswith("-") or "=" in rest[0].split(" ")[0]):
                if rest[0].startswith("-"):
                    rest = rest[1:]
                else:
                    _, rest = _strip_assignments(rest)
                    break
            argv = rest
            seen += 1
            continue
        if head in _STDIN_RUNNERS:
            return None  # `sh -c '<anything>'` / `xargs git` — work unknowable
        return argv
    return argv or None


def analyze(command):
    """Resolve a command line. Returns a list of Segment.

    Never raises. A segment whose argv is None must keep the caller's
    existing text-based verdict."""
    try:
        return _analyze(command)
    except Exception:
        # Totality is the contract: an unparsed line falls back, and the
        # gates are exactly as strong as they were before this module.
        return [Segment(command)]


def _analyze(command):
    if not command or not command.strip():
        return []
    joined = join_continuations(command)
    if any(marker in joined for marker in _OPAQUE):
        # A substitution anywhere can inject an invocation into any segment.
        return [Segment(command)]
    raw_segments, ok = _split_segments(joined)
    if not ok:
        return [Segment(command)]
    # A pipeline feeding a shell launders the payload: `echo 'push --force'
    # | xargs git` must not resolve to `echo`. If any segment is a shell or
    # an arg-runner, no segment on this line is trustworthy.
    for raw in raw_segments:
        probe = _tokenize(raw)
        if probe is None:
            continue
        _, rest = _strip_assignments(probe)
        if rest and rest[0] in _STDIN_RUNNERS:
            return [Segment(command)]
        # `env sh`, `sudo bash` — a transparent wrapper around a shell is
        # still a shell.
        if rest and rest[0] in _ARG_RUNNERS:
            inner = _unwrap(rest)
            if inner is None or (inner and inner[0] in _STDIN_RUNNERS):
                return [Segment(command)]
    segments = []
    for raw in raw_segments:
        argv = _tokenize(raw)
        if argv is None:
            segments.append(Segment(raw))
            continue
        env, rest = _strip_assignments(argv)
        rest = _unwrap(rest)
        if not rest:
            segments.append(Segment(raw))
            continue
        segments.append(Segment(raw, argv=rest, env=env))
    return segments


def git_parts(argv):
    """(subcommand, args) for a git invocation, globals stripped.

    Returns (None, []) when argv is not git. This is the function that makes
    `git -C . push --force` a push."""
    if not argv or argv[0] != "git":
        return None, []
    i = 1
    while i < len(argv):
        tok = argv[i]
        if tok in _GIT_GLOBAL_WITH_VALUE:
            i += 2
            continue
        if tok in _GIT_GLOBAL_FLAG:
            i += 1
            continue
        if tok.startswith("--") and "=" in tok:
            i += 1  # --git-dir=x form
            continue
        if tok.startswith("-"):
            i += 1  # an unknown global; skip rather than mistake it for a verb
            continue
        return tok, argv[i + 1 :]
    return None, []


def gh_parts(argv):
    """(subcommand, sub-subcommand, args) for a gh invocation."""
    if not argv or argv[0] != "gh":
        return None, None, []
    i = 1
    while i < len(argv):
        tok = argv[i]
        if tok in _GH_GLOBAL_WITH_VALUE:
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        rest = argv[i + 1 :]
        sub = None
        for candidate in rest:
            if not candidate.startswith("-"):
                sub = candidate
                break
        return tok, sub, rest
    return None, None, []


# Tombstone: cgel_parts(argv) is DELETED. It returned (verb, args) for a cgel
# invocation with globals stripped, and existed for one stated purpose — "a
# `-C <root>` flag is planned for the CLI; strip it here so the approval
# gate's verb detection does not silently stop matching the day it lands".
#
# When the flag first shipped, the gate did not use this: it detected verbs
# with a raw-text anchor instead, and this sat as a second, unused
# implementation of a solved problem — and a WRONG one: it stripped
# `-C <val>` but not `--directory <val>`, so `cgel --directory /repo seal T1`
# returned verb="/repo". A helper nothing calls, whose docstring promises a
# future that has already happened, and which is wrong for the flag it
# names, is the exact shape D-46 deleted five of. The instruction left here
# was: if a caller ever needs argv-level cgel parsing, write it then, in the
# caller, against the flags that exist then.
#
# D-48 did exactly that. approval_gate now carries its own `_cgel_parts`,
# written against the flags as shipped (all four `-C` spellings), and the
# raw-text anchors are gone — text there can only refuse a line this module
# cannot resolve, never decide one. This helper stays deleted.
