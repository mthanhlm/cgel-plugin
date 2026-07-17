"""CGEL PreToolUse gate for Bash — approval-by-question on privileged verbs.

Commands that move the yardstick or spend the user's budget run only when
the transcript carries a fresh matching AskUserQuestion approval. With one,
the call is auto-ALLOWED (no second permission prompt — one gate, not two).
Without one, it is denied with instructions to ask first. This replaces
the old ceremony of the user typing `cgel seal ...`/`cgel unblock ...` by
hand or sitting at a Bash permission prompt.

Gated verbs and their binding token:
  - cgel seal            -> the --digest value's prefix (or the exact command)
  - cgel unblock, cgel iterate decide --override-reason,
    cgel check add --force/--allow-unproven, cgel check remove,
    any cgel command with --allow-dirty
                         -> the exact command string, whitespace-collapsed

ONE DECIDER. Verdicts come only from invocations this gate can read exactly:
cmdline.analyze resolves the line into argv per segment, and verb, flags,
digest and `-C` are read off each cgel invocation. Text never decides — the
gate once kept a raw-text regex table as a co-equal fallback, and every
review round found the two deciders disagreeing (a flag spelling, a subshell
opener, invocation by path, a discarded pin). Two implementations of one
predicate is a defect factory; there is now one.

A TRIPWIRE, not a second decider. A line cmdline cannot fully resolve (a
redirection, a substitution, a shell reading stdin, a `(`/`{` group) yields
no purposes, no roots, no pins. If it LOOKS like it carries a gated verb, it
is refused outright with the remedy stated — run the verb as a plain single
command; otherwise it is ignored. Text can refuse; it can never authorise.

PER INVOCATION, not per line. Every gated invocation on a line must
independently find its root (its own `-C`, else the session's directory —
never a sibling's, never a guess) and its own approval. Enforcement is
two-phase: every invocation is checked before anything is consumed, so a
deny spends nothing. The line-level shape vouched `seal --digest APPROVED
&& seal --digest NEVERAPPROVED` on the strength of the first digest alone —
order-dependent enforcement, live in 0.13.0.

WHERE a command is rooted is never guessed. The gate roots at the session's
directory (payload["cwd"]) plus an invocation's own `-C`; it does not model
the shell, so a gated verb that follows a `cd`/`pushd` on its line is DENIED
unless pinned by its own ABSOLUTE `-C`. Rooting through the session anyway
used to file the approval against the wrong repository's ledger, and where
the session's config said {"approval_gate": "off"}, waved a foreign
project's seal through. An approval-gated verb we cannot root is a verb we
cannot gate (the tombstoned rule in tests/test_approvals.py).

Trust class: same-principal, tamper-evident (see approvals.py). The floor is
literal spellings: a deliberately quote-mangled invocation (`cgel se"al"`)
is outside this trust class — the attempt is at least visible in the
transcript. Convenience gate -> fails OPEN on malformed input; stands aside
on UNGATED commands outside CGEL projects, and fails CLOSED on gated ones.
Kill switches: .cgel/config.json {"approval_gate": "off"}, or the env vars
CGEL_APPROVAL_GATE=off / CGEL_GATE=off — which must be set in the SESSION's
environment. `CGEL_APPROVAL_GATE=off cgel seal ...` does NOT work: this hook
is a separate process, and an inline assignment applies to the command the
hook is deciding about, not to the hook.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import approvals
import cgel_common as C
import cmdline

# ------------------------------------------------------------- the tripwire
#
# Consulted ONLY for a line cmdline cannot fully resolve, and its only power
# is to refuse. Over-matching costs a deny with a stated, working remedy;
# under-matching is a bypass — so each verb is matched at any distance after
# `cgel` on the same physical line, in any `-C` spelling (there is no flag
# anchoring to get wrong: the old anchors demanded `=` or whitespace after
# `-C`, so the attached spelling `-C.` matched nothing and an unapproved
# seal ran — live in 0.13.0). Flags that gate a verb only in combination
# (`check add --force`) require the combination, so everyday unreadable
# lines (`cgel iterate decide ... 2>&1 | tail`) stay ungated.
_GATED_HINT = re.compile(
    r"\bcgel\b[^\n]*(?:"
    r"\bseal\b|"
    r"\bunblock\b|"
    r"\bcheck\s+remove\b|"
    r"\bcheck\s+add\b[^\n]*(?:--force\b|--allow-unproven\b)|"
    r"\biterate\s+decide\b[^\n]*--override-reason|"
    r"--allow-dirty\b"
    r")"
)

# A subshell or brace group. cmdline.py does not treat these as opaque, so
# `(cd /other && cgel seal ...)` splits into a segment whose argv[0] carries
# "(" — a nested shell this module cannot see into. Such a line is not
# readable; the tripwire decides it.
_GROUPING_CHARS = ("(", ")", "{", "}")

# Builtins that move the shell, and therefore move which project a later
# cgel invocation on the same line addresses.
_DIR_CHANGERS = frozenset(("cd", "pushd", "popd"))
# cgel's own top-level globals that take a value, in argparse's spellings.
_CGEL_GLOBAL_WITH_VALUE = frozenset(("-C", "--directory"))

_DIGEST_SHAPE = re.compile(r"^sha256:[0-9a-fA-F]{8,64}$")
DIGEST_PREFIX_LEN = len("sha256:") + 12


def _has_flag(args, name):
    """True when `--flag` is present in either spelling argparse accepts.

    An exact-membership test missed `--override-reason=x`, which argparse
    accepts — a failure override walking past the gate on an equals sign.
    Every value-taking gated flag must be read both ways."""
    prefix = name + "="
    return any(arg == name or arg.startswith(prefix) for arg in args)


def _cgel_parts(argv):
    """(verb, args, dash_c) for a cgel invocation, top-level globals stripped.

    cmdline.py's tombstone deleted a shared `cgel_parts` and said to write one
    in the caller, against the flags that exist then, if a caller ever needed
    argv-level cgel parsing. This is that caller and these are those flags:
    `-C`/`--directory` take a value, spelled four ways.

    argv[0] is compared by BASENAME: `./plugin/bin/cgel seal ...` and the
    absolute path into the plugin cache are the same invocation as
    `cgel seal ...`.

    Returns (None, [], None) for anything that is not cgel."""
    if not argv or os.path.basename(argv[0]) != "cgel":
        return None, [], None
    dash_c = None
    i = 1
    while i < len(argv):
        tok = argv[i]
        if tok in _CGEL_GLOBAL_WITH_VALUE:  # -C dir / --directory dir
            if dash_c is None and i + 1 < len(argv):
                dash_c = argv[i + 1]
            i += 2
            continue
        if tok.startswith("--directory="):  # --directory=dir
            if dash_c is None:
                dash_c = tok.split("=", 1)[1]
            i += 1
            continue
        if tok.startswith("-C") and len(tok) > 2:  # -Cdir
            if dash_c is None:
                dash_c = tok[2:]
            i += 1
            continue
        if tok.startswith("-"):
            i += 1  # an unknown global; skip rather than mistake it for a verb
            continue
        return tok, argv[i + 1 :], dash_c
    return None, [], dash_c


def _gated_purposes(argv):
    """(purposes, seal) for one resolved invocation.

    Anchored on cgel FIRST: testing flags against a bare argv once gated
    `npm run build -- --allow-dirty` — a foreign program's flag, and the
    named false-block fixture in cmdline.py's docstring."""
    if not argv or os.path.basename(argv[0]) != "cgel":
        return [], False
    verb, args, _ = _cgel_parts(argv)
    purposes = []
    if verb == "unblock":
        purposes.append("unblock")
    elif verb == "iterate" and args[:1] == ["decide"] and _has_flag(args, "--override-reason"):
        purposes.append("failure-override")
    elif verb == "check" and args[:1] == ["add"] and (
        _has_flag(args, "--force") or _has_flag(args, "--allow-unproven")
    ):
        purposes.append("check-force")
    elif verb == "check" and args[:1] == ["remove"]:
        purposes.append("check-remove")
    if _has_flag(argv, "--allow-dirty"):
        purposes.append("allow-dirty")
    return purposes, verb == "seal"


def _seal_digest(args):
    """The --digest value of a seal's argv, both spellings, or None."""
    for i, tok in enumerate(args):
        if tok == "--digest":
            return args[i + 1] if i + 1 < len(args) else None
        if tok.startswith("--digest="):
            return tok.split("=", 1)[1]
    return None


def _pinned(dash_c):
    """True when `-C` names the project outright, so no `cd` can move it.

    The remedy the rooting deny prescribes; it must clear every deny that
    names it, or the gate is a wedge whose only exit is the off switch."""
    return bool(dash_c) and os.path.isabs(dash_c)


def _readable(segments):
    """True when every segment resolved and none hides inside a group."""
    if not segments:
        return False
    for seg in segments:
        if not seg.resolved or not seg.argv:
            return False
        if any(ch in seg.argv[0] for ch in _GROUPING_CHARS):
            return False
    return True


def _whole_line_is_bare_cgel(segments):
    """True when every segment is a plain `cgel` invocation.

    The auto-run vouch may cover the line only when everything on it is
    cgel — each cgel verb carries its own gate, so the vouch adds no
    authority the user did not grant. Anything else on the line (another
    program, a `cd`) was never named in the question, so the gated verbs
    still run, the user just sees the normal prompt for the rest."""
    if not segments:
        return False
    for seg in segments:
        if not seg.resolved or not seg.argv:
            return False
        if os.path.basename(seg.argv[0]) != "cgel":
            return False
    return True


def deny(purpose, ask_for):
    print(
        "CGEL approval gate: %s needs the user's recorded approval. Ask with "
        "the AskUserQuestion tool first — a short plain-language brief (goal, "
        "files, checks, risk), options starting with 'Approve' — and include "
        "%s in the question or an option so the approval binds to exactly "
        "this action. Then rerun the command. The user may instead run it "
        "themselves. Off switch: .cgel/config.json {\"approval_gate\": "
        '"off"}.' % (purpose, ask_for),
        file=sys.stderr,
    )
    return 2


def deny_unrootable(problem, remedy):
    """Deny a gated verb whose project this gate cannot name.

    Deliberately NOT deny(): no approval can fix a rooting problem, so
    sending the model to collect a tap on a question would bind an approval
    to the wrong project's ledger — the defect. State the problem, name the
    remedy, stop."""
    print(
        "CGEL approval gate: %s, so this gate cannot tell which project the "
        "command addresses and will not guess. %s Approving it changes "
        "nothing — the project has to be named, not authorised. Off switch: "
        '.cgel/config.json {"approval_gate": "off"}.' % (problem, remedy),
        file=sys.stderr,
    )
    return 2


def deny_unreadable():
    """Refuse a line we cannot parse that looks like it carries a gated verb.

    No verdict is taken from the text — not a purpose, not a root, not a
    digest — so the only safe answer is no, with the remedy stated."""
    print(
        "CGEL approval gate: this line could not be read exactly — a "
        "redirection, a `(`/`{` group, a shell reading stdin, or a backtick "
        "or `$(`/`${` ANYWHERE on it, including inside quoted prose like a "
        "--hypothesis string — and it looks like it may carry a gated `cgel` "
        "verb. The gate takes no verdict from text it cannot parse — it "
        "refuses. Run gated verbs as plain single commands — `cgel [-C "
        "/abs/dir] <verb> …` on a line of their own — spell identifiers in "
        "prose without backticks, and keep unrelated commands off that line. "
        "Approving this exact line would change nothing. Off switch: "
        '.cgel/config.json {"approval_gate": "off"}.',
        file=sys.stderr,
    )
    return 2


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:
        C._debug("approval_gate:stdin", exc)
        return 0

    if payload.get("tool_name") != "Bash":
        return 0
    for switch in ("CGEL_APPROVAL_GATE", "CGEL_GATE"):
        if os.environ.get(switch, "").lower() == "off":
            return 0

    command = (payload.get("tool_input") or {}).get("command") or ""
    if "cgel" not in command:
        return 0

    segments = cmdline.analyze(command)
    if not _readable(segments):
        if _GATED_HINT.search(command):
            return deny_unreadable()
        return 0

    cwd = payload.get("cwd") or os.getcwd()

    # Collect the gated invocations, each with its own flags and whether a
    # directory change came before it on the line.
    moved = False
    invocations = []
    for seg in segments:
        argv = seg.argv
        if os.path.basename(argv[0]) in _DIR_CHANGERS:
            moved = True
            continue
        purposes, seal = _gated_purposes(argv)
        if not purposes and not seal:
            continue
        _, args, dash_c = _cgel_parts(argv)
        invocations.append({
            "purposes": purposes,
            "seal": seal,
            "dash_c": dash_c,
            "digest": _seal_digest(args) if seal else None,
            "after_move": moved,
        })
    if not invocations:
        # Standing aside is for ungated commands — a grep naming a verb,
        # `cgel status`, `cgel -C /anywhere audit`. Nothing to root, nothing
        # to approve; where the line points cannot matter.
        return 0

    transcript = payload.get("transcript_path")
    flat_command = approvals.collapse_ws(command)

    # Phase 1 — every invocation must be rootable and approved before
    # anything is spent, so a deny consumes nothing.
    plans = []  # (root, key, purpose, tokens)
    vouchable = True
    whole_line_read = False
    for inv in invocations:
        if inv["after_move"] and not _pinned(inv["dash_c"]):
            return deny_unrootable(
                "a gated `cgel` verb follows a directory change (`cd`/"
                "`pushd`) on this line",
                "Address the project outright instead: `cgel -C /abs/path "
                "<verb> …` — an ABSOLUTE `-C` pins the project no matter "
                "where the shell stands.",
            )
        dash_c = inv["dash_c"]
        # `-C` is relative to the SESSION's directory (payload["cwd"]), not
        # to this hook process's cwd — the harness spawns hooks wherever it
        # likes, and resolving against the process once rooted the gate at a
        # different project whose approval_gate:off waved the seal through.
        if dash_c:
            base = dash_c if os.path.isabs(dash_c) else os.path.join(cwd, dash_c)
        else:
            base = cwd
        root = C.resolve_repo_root(base)
        if not root:
            # An approval-gated verb we cannot root is a verb we cannot
            # gate; standing aside would make `-C /not-a-project` the
            # bypass. Say the true thing for each mistake: naming a
            # non-project and sitting in one are different errors.
            if dash_c:
                problem = "`cgel -C %s` does not name a CGEL project" % dash_c
                remedy = "Point it at a project, or run `cgel init` there first."
            else:
                problem = (
                    "this session's directory is not a CGEL project, and "
                    "the command names none"
                )
                remedy = (
                    "Address the project explicitly: `cgel -C <dir> <verb> "
                    "…`. A session opened above your projects is the usual "
                    "cause."
                )
            return deny_unrootable(problem, remedy)
        if C.read_config(root).get("approval_gate") == "off":
            continue  # this project asked for no ceremony; nothing to bind
        if inv["purposes"]:
            # Anything beyond a plain seal binds to the exact command
            # string — the user must have read the whole line.
            purpose = "+".join(inv["purposes"]) + ("+seal" if inv["seal"] else "")
            found = approvals.find_approval(
                transcript, [flat_command], root, gate=approvals.GATE_CGEL
            )
            if not found:
                return deny(
                    "`%s`" % (command if len(command) <= 120 else purpose),
                    "the exact command in backticks",
                )
            plans.append((root, found[0], purpose, [flat_command]))
            whole_line_read = True
            continue
        digest = inv["digest"] or ""
        if not _DIGEST_SHAPE.match(digest):
            # The CLI itself refuses a seal without a digest. Nothing to
            # bind — and nothing to vouch for.
            vouchable = False
            continue
        token = digest[:DIGEST_PREFIX_LEN]
        by_digest = approvals.find_approval(
            transcript, [token], root, reuse_ok=True, gate=approvals.GATE_CGEL
        )
        by_command = approvals.find_approval(
            transcript, [flat_command], root, reuse_ok=True, gate=approvals.GATE_CGEL
        )
        found = by_digest or by_command
        if not found:
            return deny("`cgel seal`", "the digest prefix `%s…`" % token)
        plans.append((root, found[0], "seal", [token]))
        if by_command:
            whole_line_read = True

    # Phase 2 — every invocation held; spend the approvals.
    for root, key, purpose, tokens in plans:
        approvals.consume(root, key, purpose, tokens, command, gate=approvals.GATE_CGEL)

    if not plans:
        return 0  # everything exempt or digestless — nothing was bound

    # The vouch tells the harness to run the WHOLE line unprompted, so it is
    # emitted only when every gated invocation was individually satisfied
    # AND the user read everything the line does: either it is all cgel, or
    # an approval quoted the exact command.
    if vouchable and (whole_line_read or _whole_line_is_bare_cgel(segments)):
        print(approvals.allow_json("CGEL: user approved this command via question"))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # convenience gate: never brick the session
        C._debug("approval_gate:main", exc)
        sys.exit(0)
