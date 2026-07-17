"""command_guard.py — subprocess tests (fail-closed safety gate)."""

import os
import shutil
import tempfile
import unittest

from hookrunner import run_hook


class GuardTestCase(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="cgel-repo-")
        os.makedirs(os.path.join(self.repo, ".cgel"))
        self.env = {}

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def bash(self, command, env=None):
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": self.repo,
        }
        return run_hook("command_guard.py", payload, env=env or self.env)

    # ------------------------------------------- decide on the invocation
    #
    # Every rule anchored `git\s+<subcommand>`, but git accepts globals in
    # between — so `git -C . push --force` bypassed all eight rules AND the
    # push gate. The same text-matching blocked `grep -rn 'git push'`,
    # because a read of a command looked exactly like a run of it. Both
    # directions are the same defect: text is not an invocation.

    def assertBlocked(self, command, rule=None):
        code, _, err = self.bash(command)
        self.assertEqual(code, 2, "%r should be blocked; got %d" % (command, code))
        if rule:
            self.assertIn(rule, err)

    def assertAllowed(self, command):
        code, out, err = self.bash(command)
        self.assertEqual(code, 0, "%r should be allowed: %s" % (command, err))

    def test_git_globals_do_not_hide_a_destructive_subcommand(self):
        for command in (
            "git -C . push --force origin main",
            "git -c user.name=x push --force origin main",
            "git -C /tmp/x reset --hard",
            "git --no-pager reset --hard",
            "git -C . branch -D feature",
            "git -c a=b -C . clean -fd",
            "git -C . stash drop",
        ):
            self.assertBlocked(command)

    def test_git_globals_do_not_hide_a_push(self):
        code, _, err = self.bash("git -C /srv/repo push origin main")
        self.assertEqual(code, 2)
        self.assertIn("[push]", err)

    def test_a_line_wrapped_destructive_command_is_blocked(self):
        # The patterns bound a command with [^\n], so a backslash-newline
        # split every rule's match in half.
        self.assertBlocked("git reset \\\n  --hard")
        self.assertBlocked("git push \\\n  --force origin main")

    def test_reading_about_a_command_is_not_running_it(self):
        for command in (
            "grep -rn 'git push' docs/",
            'grep -rn "git push --force" .',
            "git log --grep='git push'",
            "rg 'git reset --hard' plugin/",
            "echo 'do not git push --force here'",
        ):
            self.assertAllowed(command)

    def test_a_commit_message_mentioning_a_push_is_not_a_push(self):
        # Found by dogfooding: the old guard blocked the commit that FIXED
        # this, because the message quoted `grep -rn 'git push'` as an example
        # of a false block. Both shapes must pass — the heredoc one is not
        # theoretical, it is the exact command that was refused.
        self.assertAllowed(
            "git add -A && git commit -q -F - <<'EOF'\n"
            "fix: a grep for 'git push' was wrongly blocked\n"
            "EOF"
        )
        self.assertAllowed("git commit -m 'docs: a grep for git push was blocked'")

    def test_force_if_includes_is_push_gated_not_force_blocked(self):
        # --force-if-includes is the safe sibling of --force-with-lease; the
        # lookahead only exempted -with-lease, so it was blocked as a force
        # push. It is still a push, so it still needs push approval.
        code, _, err = self.bash("git push --force-if-includes origin main")
        self.assertEqual(code, 2)
        self.assertIn("[push]", err)
        self.assertNotIn("[force-push]", err)

    def test_a_filename_is_not_a_flag(self):
        # Everything after `--` is a pathspec. `-f.txt` is a file.
        self.assertAllowed("git checkout -- -f.txt")
        self.assertAllowed("git checkout feature/reset--hard-fix")

    def test_an_unresolvable_line_keeps_the_blunt_verdict(self):
        # The fallback contract: cmdline can sharpen a gate, never blind one.
        # A shell that could receive a payload is unresolvable, so the raw
        # text is judged exactly as it was before the tokenizer existed.
        self.assertBlocked("sh -c 'git push --force origin main'")
        self.assertBlocked("echo x | xargs git push --force")

    def test_the_guard_stands_aside_outside_a_cgel_project(self):
        # Fail-closed must not mean bricking Bash in every repo on the
        # machine: CGEL is opt-in per project.
        plain = tempfile.mkdtemp(prefix="not-cgel-")
        self.addCleanup(shutil.rmtree, plain, True)
        code, _, _ = run_hook(
            "command_guard.py",
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git push --force origin main"},
                "cwd": plain,
            },
            env=self.env,
        )
        self.assertEqual(code, 0)

    # -------------------------------------- the escape hatch is per-command
    #
    # APPROVAL_PREFIX matched the start of the LINE, so a prefix on a
    # harmless command disabled the guard for everything chained after it.
    # An escape hatch that exempts commands it does not name is not an
    # escape hatch, it is a hole.

    def test_the_prefix_exempts_only_the_command_it_prefixes(self):
        self.assertAllowed("CGEL_GIT=allow git reset --hard")
        self.assertBlocked("CGEL_GIT=allow echo hi && git reset --hard")
        self.assertBlocked("CGEL_GIT=allow echo hi ; git push --force origin main")

    def test_no_block_message_tells_the_model_how_to_bypass(self):
        # APPROVAL_PREFIX is a plain string test — a model that reads the
        # hint can type the prefix as easily as a human. Naming the bypass in
        # the refusal handed the blocked party the key.
        for command in ("git reset --hard", "git push origin main"):
            _, _, err = self.bash(command)
            self.assertNotIn("CGEL_GIT", err, "the refusal must not advertise it")

    def test_force_push_blocked(self):
        code, _, err = self.bash("git push --force origin main")
        self.assertEqual(code, 2)
        self.assertIn("force-push", err)

    def test_short_force_flag_blocked(self):
        code, _, _ = self.bash("git push -f origin main")
        self.assertEqual(code, 2)

    def test_force_with_lease_needs_push_approval(self):
        # not destructive, but still a push — the push gate wants a
        # recorded user answer before anything reaches a remote
        code, _, err = self.bash("git push --force-with-lease origin main")
        self.assertEqual(code, 2)
        self.assertIn("push", err)

    def test_plain_push_needs_approval(self):
        code, _, err = self.bash("git push origin main")
        self.assertEqual(code, 2)
        self.assertIn("CGEL guard [push]", err)
        self.assertIn("AskUserQuestion", err)

    def test_push_gate_config_off(self):
        with open(
            os.path.join(self.repo, ".cgel", "config.json"), "w", encoding="utf-8"
        ) as fh:
            fh.write('{"push_gate": "off"}')
        code, _, err = self.bash("git push origin main")
        self.assertEqual(code, 0, err)

    def test_push_user_prefix_allows(self):
        code, _, err = self.bash("CGEL_GIT=allow git push origin main")
        self.assertEqual(code, 0, err)

    def test_fetch_and_pull_unaffected_by_push_gate(self):
        for command in ("git fetch origin", "git pull --rebase"):
            code, _, err = self.bash(command)
            self.assertEqual(code, 0, "%s: %s" % (command, err))

    def test_reset_hard_blocked(self):
        code, _, err = self.bash("git reset --hard HEAD~1")
        self.assertEqual(code, 2)
        self.assertIn("reset-hard", err)

    def test_clean_force_blocked(self):
        code, _, _ = self.bash("git clean -fd")
        self.assertEqual(code, 2)

    def test_checkout_dot_blocked(self):
        code, _, _ = self.bash("git checkout .")
        self.assertEqual(code, 2)

    def test_restore_staged_allowed(self):
        code, _, err = self.bash("git restore --staged src/app.py")
        self.assertEqual(code, 0, err)

    def test_branch_force_delete_blocked(self):
        code, _, _ = self.bash("git branch -D feature/x")
        self.assertEqual(code, 2)

    def test_stash_drop_blocked(self):
        code, _, _ = self.bash("git stash drop")
        self.assertEqual(code, 2)

    def test_remote_branch_delete_blocked(self):
        code, _, _ = self.bash("git push origin --delete feature/x")
        self.assertEqual(code, 2)

    def test_normal_git_allowed(self):
        for command in ("git status", "git diff", "git log --oneline", "git add -p"):
            code, _, err = self.bash(command)
            self.assertEqual(code, 0, "%s: %s" % (command, err))

    def test_user_approval_prefix_allows(self):
        code, _, err = self.bash("CGEL_GIT=allow git reset --hard HEAD~1")
        self.assertEqual(code, 0, err)

    # ------------------------------------------------- ai attribution

    def test_co_author_trailer_blocked(self):
        code, _, err = self.bash(
            'git commit -m "fix: thing\n\n'
            'Co-Authored-By: Claude <noreply@anthropic.com>"'
        )
        self.assertEqual(code, 2)
        self.assertIn("ai-attribution/co-author-trailer", err)

    def test_co_author_trailer_heredoc_blocked(self):
        code, _, err = self.bash(
            "git commit -m \"$(cat <<'EOF'\nfix: thing\n\n"
            "Co-authored-by: Claude Opus <noreply@anthropic.com>\nEOF\n)\""
        )
        self.assertEqual(code, 2)
        self.assertIn("ai-attribution", err)

    def test_generated_with_footer_blocked(self):
        code, _, err = self.bash(
            'gh pr create --title "x" --body "does a thing\n\n'
            '🤖 Generated with [Claude Code](https://claude.com/claude-code)"'
        )
        self.assertEqual(code, 2)
        self.assertIn("ai-attribution", err)

    def test_robot_footer_without_claude_name_blocked(self):
        code, _, err = self.bash('git commit -m "x\n\n🤖 Generated with some tool"')
        self.assertEqual(code, 2)
        self.assertIn("robot-footer", err)

    def test_clean_commit_allowed(self):
        code, _, err = self.bash('git commit -m "fix: correct the off-by-one"')
        self.assertEqual(code, 0, err)

    def test_legitimate_claude_mention_in_commit_allowed(self):
        """The block is narrow by design: it targets the mechanical trailer /
        footer, not the word. A repo may legitimately commit *about* Claude."""
        for command in (
            'git commit -m "docs: document Claude Code compatibility"',
            'git commit -m "feat: add anthropic sdk client"',
        ):
            code, _, err = self.bash(command)
            self.assertEqual(code, 0, "%s: %s" % (command, err))

    def test_reading_attribution_allowed(self):
        """Only authoring commands are gated — searching for a trailer is not
        adding one."""
        for command in (
            'git log --grep="Co-Authored-By: Claude"',
            'grep -rn "Generated with Claude Code" .',
        ):
            code, _, err = self.bash(command)
            self.assertEqual(code, 0, "%s: %s" % (command, err))

    def test_attribution_user_approval_prefix_allows(self):
        code, _, err = self.bash(
            'CGEL_GIT=allow git commit -m "x\n\nCo-Authored-By: Claude <n@a.com>"'
        )
        self.assertEqual(code, 0, err)

    def test_attribution_kill_switch_config(self):
        with open(
            os.path.join(self.repo, ".cgel", "config.json"), "w", encoding="utf-8"
        ) as fh:
            fh.write('{"ai_attribution_guard": "off"}')
        code, _, err = self.bash(
            'git commit -m "x\n\nCo-Authored-By: Claude <n@a.com>"'
        )
        self.assertEqual(code, 0, err)

    def test_attribution_kill_switch_does_not_disable_safety_rules(self):
        with open(
            os.path.join(self.repo, ".cgel", "config.json"), "w", encoding="utf-8"
        ) as fh:
            fh.write('{"ai_attribution_guard": "off"}')
        code, _, err = self.bash("git reset --hard HEAD~1")
        self.assertEqual(code, 2)
        self.assertIn("reset-hard", err)

    def test_malformed_stdin_fails_closed(self):
        code, _, err = run_hook("command_guard.py", None, raw_stdin="{oops")
        self.assertEqual(code, 2)
        self.assertIn("fail closed", err)

    def test_non_bash_tool_ignored(self):
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "x"},
            "cwd": self.repo,
        }
        code, _, _ = run_hook("command_guard.py", payload)
        self.assertEqual(code, 0)

    def test_not_a_cgel_project_ignored(self):
        plain = tempfile.mkdtemp(prefix="cgel-plain-")
        try:
            payload = {
                "tool_name": "Bash",
                "tool_input": {"command": "git reset --hard"},
                "cwd": plain,
            }
            code, _, _ = run_hook("command_guard.py", payload)
            self.assertEqual(code, 0)
        finally:
            shutil.rmtree(plain, ignore_errors=True)

    def test_kill_switch_env(self):
        code, _, _ = self.bash("git reset --hard", env={"CGEL_GIT_GUARD": "off"})
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
