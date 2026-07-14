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

    def test_force_push_blocked(self):
        code, _, err = self.bash("git push --force origin main")
        self.assertEqual(code, 2)
        self.assertIn("force-push", err)

    def test_short_force_flag_blocked(self):
        code, _, _ = self.bash("git push -f origin main")
        self.assertEqual(code, 2)

    def test_force_with_lease_allowed(self):
        code, _, err = self.bash("git push --force-with-lease origin main")
        self.assertEqual(code, 0, err)

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
