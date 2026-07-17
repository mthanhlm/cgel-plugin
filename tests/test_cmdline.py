"""The tokenizer resolves invocations, never raises, and never launders.

These test the three properties the gates depend on, not the parser's
internals:
  1. analyze() is total — no input raises.
  2. Unresolvable input yields argv=None, which means "keep the caller's
     blunt verdict", never "allow".
  3. A shell that could receive a payload makes the whole line unresolved,
     so segment-splitting cannot be used to smuggle one past a gate.
"""

import os
import sys
import unittest

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugin", "scripts"
    ),
)

import cmdline


class Totality(unittest.TestCase):
    """Property 1. shlex.split() raises ValueError on an unbalanced quote,
    and command_guard's handler is fail-closed — so an apostrophe in a commit
    message would become a false block. Nothing here may raise."""

    HOSTILE = [
        "",
        "   ",
        "'",
        '"',
        "git log --grep=won't",
        "git commit -m 'it's broken'",
        "\\",
        "git push \\",
        "$(",
        "`",
        "|||",
        "&&&&",
        ">>>",
        "a" * 10000,
        "git\x00push",
        "échec --force",
        "git -C",
        "env",
        "xargs",
    ]

    def test_analyze_never_raises(self):
        for cmd in self.HOSTILE:
            try:
                cmdline.analyze(cmd)
            except Exception as exc:  # pragma: no cover — the assertion is the point
                self.fail("analyze(%r) raised %r" % (cmd, exc))

    def test_the_apostrophe_that_disqualified_shlex_resolves(self):
        # Not merely "does not raise": it must still resolve, or the guard
        # falls back to the blunt regex for every quoted commit message.
        segs = cmdline.analyze("git log --grep=won't")
        self.assertEqual(len(segs), 1)
        self.assertFalse(segs[0].resolved)  # unbalanced quote -> fall back
        # ...and the balanced form resolves normally.
        segs = cmdline.analyze("git log --grep=wont")
        self.assertEqual(cmdline.git_parts(segs[0].argv)[0], "log")


class GitGlobalsDoNotHideTheSubcommand(unittest.TestCase):
    """Property: `git -C . push` is a push. This is must-fix #2 — every rule
    anchored `git\\s+push` and git accepts globals in between."""

    def sub(self, cmd):
        segs = cmdline.analyze(cmd)
        self.assertEqual(len(segs), 1, cmd)
        self.assertTrue(segs[0].resolved, cmd)
        return cmdline.git_parts(segs[0].argv)[0]

    def test_globals_before_the_subcommand(self):
        for cmd in (
            "git push --force origin main",
            "git -C . push --force origin main",
            "git -C /tmp/x push --force",
            "git -c user.name=x push --force",
            "git --git-dir=.git push --force",
            "git --no-pager push --force",
            "git -c a=b -C . --no-pager push --force",
            "git --exec-path=/usr/lib/git push",
        ):
            self.assertEqual(self.sub(cmd), "push", cmd)

    def test_an_unknown_global_does_not_become_the_verb(self):
        # Skipping unknown flags is what keeps a future git global from
        # silently turning every rule off.
        self.assertEqual(self.sub("git --future-flag push --force"), "push")

    def test_a_pathspec_is_not_a_flag(self):
        sub, args = cmdline.git_parts(cmdline.analyze("git checkout -- -f.txt")[0].argv)
        self.assertEqual(sub, "checkout")
        self.assertIn("-f.txt", args)

    def test_a_branch_name_is_not_the_subcommand(self):
        self.assertEqual(self.sub("git checkout feature/reset--hard-fix"), "checkout")


class LineWrappingIsUndone(unittest.TestCase):
    """must-fix #3: the gates bound a command with [^\\n], so a wrapped
    command escaped every rule."""

    def test_backslash_newline_is_joined(self):
        segs = cmdline.analyze("git reset \\\n  --hard")
        self.assertEqual(len(segs), 1)
        sub, args = cmdline.git_parts(segs[0].argv)
        self.assertEqual(sub, "reset")
        self.assertIn("--hard", args)

    def test_a_real_newline_still_separates_commands(self):
        # collapse_ws would merge these into one command and false-block the
        # second half. Two lines are two commands.
        segs = cmdline.analyze("cgel status\nnpm run build -- --allow-dirty")
        self.assertEqual(len(segs), 2)
        self.assertEqual(segs[0].argv[:2], ["cgel", "status"])
        self.assertEqual(segs[1].argv[0], "npm")


class NoLaundering(unittest.TestCase):
    """Property 3, and the reason segment-splitting is safe at all.

    If a line can hand a string to a shell, no segment on it may resolve —
    otherwise the split becomes the bypass it was meant to close."""

    def assertFallsBack(self, cmd):
        segs = cmdline.analyze(cmd)
        self.assertEqual(len(segs), 1, "%r should collapse to one raw segment" % cmd)
        self.assertFalse(segs[0].resolved, "%r must not resolve" % cmd)
        self.assertEqual(segs[0].raw, cmd)

    def test_a_pipe_into_a_shell_poisons_the_line(self):
        self.assertFallsBack("echo 'push --force' | xargs git")
        self.assertFallsBack("echo x | sh")
        self.assertFallsBack("cat script | bash")

    def test_sh_c_is_never_resolved_to_sh(self):
        self.assertFallsBack("sh -c 'git push --force'")
        self.assertFallsBack("bash -c 'git reset --hard'")

    def test_command_substitution_poisons_the_line(self):
        self.assertFallsBack("git $(echo push) --force")
        self.assertFallsBack("echo `git push --force`")
        self.assertFallsBack("git ${VERB} --force")

    def test_redirection_is_not_resolved(self):
        segs = cmdline.analyze("> out.txt git push --force")
        self.assertFalse(segs[0].resolved)

    def test_env_prefix_still_resolves(self):
        # `env FOO=1 git push` IS a push — unwrapping this is the point.
        segs = cmdline.analyze("env FOO=1 git push --force")
        self.assertTrue(segs[0].resolved)
        self.assertEqual(cmdline.git_parts(segs[0].argv)[0], "push")

    def test_a_transparent_wrapper_around_a_shell_is_still_a_shell(self):
        # env/sudo must stay transparent (so `env FOO=1 git push` resolves)
        # WITHOUT becoming a hole: wrapping the shell in one cannot buy back
        # the resolution the shell just lost.
        self.assertFallsBack("env FOO=1 sh -c 'git push --force'")
        self.assertFallsBack("sudo bash -c 'git reset --hard'")
        self.assertFallsBack("echo x | env sh")

    def test_assignment_prefix_still_resolves(self):
        segs = cmdline.analyze("CGEL_GIT=allow git push --force")
        self.assertTrue(segs[0].resolved)
        self.assertEqual(segs[0].env.get("CGEL_GIT"), "allow")
        self.assertEqual(cmdline.git_parts(segs[0].argv)[0], "push")


class QuotedTextIsNotAnInvocation(unittest.TestCase):
    """The false-block half. A read of a command is not a run of it."""

    def test_a_grep_for_a_command_is_a_grep(self):
        segs = cmdline.analyze("grep -rn 'git push' docs/")
        self.assertTrue(segs[0].resolved)
        self.assertEqual(segs[0].argv[0], "grep")
        self.assertIsNone(cmdline.git_parts(segs[0].argv)[0])

    def test_a_commit_message_mentioning_a_command_is_a_commit(self):
        segs = cmdline.analyze("git commit -m 'docs: explain git push --force'")
        sub, args = cmdline.git_parts(segs[0].argv)
        self.assertEqual(sub, "commit")
        self.assertIn("docs: explain git push --force", args)

    def test_log_grep_is_a_log(self):
        segs = cmdline.analyze("git log --grep='git push'")
        self.assertEqual(cmdline.git_parts(segs[0].argv)[0], "log")


class Separators(unittest.TestCase):
    def test_chained_commands_are_separate_segments(self):
        segs = cmdline.analyze("cgel seal T1 --digest sha256:ab && git push --force")
        self.assertEqual(len(segs), 2)
        self.assertEqual(segs[0].argv[0], "cgel")
        self.assertEqual(cmdline.git_parts(segs[1].argv)[0], "push")

    def test_semicolons_and_background(self):
        segs = cmdline.analyze("cgel status; git push --force & echo done")
        subs = [s.argv[0] for s in segs if s.resolved]
        self.assertIn("cgel", subs)
        self.assertIn("git", subs)


class Parts(unittest.TestCase):
    def test_gh_globals_do_not_hide_pr_create(self):
        segs = cmdline.analyze("gh -R owner/repo pr create --title x")
        verb, sub, _ = cmdline.gh_parts(segs[0].argv)
        self.assertEqual(verb, "pr")
        self.assertEqual(sub, "create")

    # Tombstone: test_cgel_dash_C_does_not_hide_the_verb is DELETED with
    # cgel_parts. Its premise — "the CLI's -C flag does not exist yet" — was
    # true when written and false the day the flag shipped, and the helper it
    # guarded was never wired to anything. The property it cared about (a -C
    # between `cgel` and the verb must not hide the verb from the approval
    # gate) is real and now lives where it is enforced:
    # test_approvals.py::test_dash_c_does_not_walk_past_the_gate exercises the
    # gate itself against every gated verb and both flag spellings.

    def test_parts_of_a_non_match_are_empty(self):
        self.assertEqual(cmdline.git_parts(["npm", "test"]), (None, []))
        self.assertEqual(cmdline.git_parts(None), (None, []))


if __name__ == "__main__":
    unittest.main()
