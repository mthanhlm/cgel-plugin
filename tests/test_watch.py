"""Watch-scoped evidence staleness — a check that declares `watch` globs
survives unrelated edits; everything else keeps the old any-change-stales
rule. Needs a real git repo: freshness is judged from workspace snapshots.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

from hookrunner import run_hook, run_cli, decision_line

CONTRACT = {
    "task": {"id": "TASK-W1", "type": "feature", "goal": "Watch scoping"},
    "acceptance_criteria": [
        {
            "id": "AC-1",
            "description": "code ok",
            "required_checks": ["code-check", "any-check"],
        }
    ],
    "scope": {"allowed": ["src/**", "docs/**"]},
    "risk": {"level": "low", "reasons": ["fixture: exercises watch globs"]},
}


class WatchTestCase(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="cgel-repo-")
        self.state = tempfile.mkdtemp(prefix="cgel-state-")
        os.makedirs(os.path.join(self.repo, ".cgel"))
        os.makedirs(os.path.join(self.repo, ".task"))
        os.makedirs(os.path.join(self.repo, "src"))
        os.makedirs(os.path.join(self.repo, "docs"))
        self.write("src/app.py", "print('v1')\n")
        self.write("docs/readme.md", "# v1\n")
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.env = {"CGEL_STATE_DIR": self.state}
        self.cli(
            "check", "add", "code-check",
            "--command", "test -d src", "--watch", "src/**",
        )
        self.cli("check", "add", "any-check", "--command", "test -d src")

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.state, ignore_errors=True)

    def git(self, *args):
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t"] + list(args),
            cwd=self.repo,
            check=True,
            capture_output=True,
        )

    def write(self, rel, content):
        with open(os.path.join(self.repo, rel), "w", encoding="utf-8") as fh:
            fh.write(content)

    def cli(self, *args):
        return run_cli(list(args), cwd=self.repo, env=self.env)

    def seal_and_open(self, expected="code-check,any-check"):
        with open(
            os.path.join(self.repo, ".task", "contract.json"), "w", encoding="utf-8"
        ) as fh:
            json.dump(CONTRACT, fh)
        code, out, err = self.cli("summary")
        self.assertEqual(code, 0, err)
        digest = decision_line(out).split("digest=")[1].split()[0]
        code, out, err = self.cli("seal", "TASK-W1", "--digest", digest)
        self.assertEqual(code, 0, out + err)
        code, out, err = self.cli(
            "iterate", "open", "--change", "x", "--expect", expected
        )
        self.assertEqual(code, 0, out + err)

    # ------------------------------------------------------------ tests

    def test_unwatched_path_edit_keeps_watched_evidence_fresh(self):
        self.seal_and_open()
        code, _, err = self.cli("verify", "code-check", "any-check")
        self.assertEqual(code, 0, err)
        self.write("docs/readme.md", "# v2 — docs only\n")
        code, out, err = self.cli("iterate", "decide", "ADVANCE")
        self.assertEqual(code, 1)
        self.assertIn("any-check", err)      # no watch -> any change stales it
        self.assertNotIn("code-check:", err)  # watched, docs change ignored
        code, _, _ = self.cli("verify", "any-check")
        self.assertEqual(code, 0)
        code, out, err = self.cli("iterate", "decide", "ADVANCE")
        self.assertEqual(code, 0, out + err)

    def test_watched_path_edit_stales_watched_evidence(self):
        self.seal_and_open(expected="code-check")
        code, _, _ = self.cli("verify", "code-check")
        self.assertEqual(code, 0)
        self.write("src/app.py", "print('v2')\n")
        code, _, err = self.cli("iterate", "decide", "ADVANCE")
        self.assertEqual(code, 1)
        self.assertIn("code-check", err)

    def test_a_commit_stales_everything_even_watched(self):
        self.seal_and_open(expected="code-check")
        code, _, _ = self.cli("verify", "code-check")
        self.assertEqual(code, 0)
        self.write("docs/readme.md", "# v2\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "docs")
        code, _, err = self.cli("iterate", "decide", "ADVANCE")
        self.assertEqual(code, 1)
        self.assertIn("code-check", err)

    def test_recorded_edit_events_respect_watch_globs(self):
        self.seal_and_open(expected="code-check")
        code, _, _ = self.cli("verify", "code-check")
        self.assertEqual(code, 0)
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": os.path.join(self.repo, "docs/readme.md")},
            "cwd": self.repo,
            "hook_event_name": "PostToolUse",
        }
        code, _, _ = run_hook("evidence_recorder.py", payload, env=self.env)
        self.assertEqual(code, 0)
        # an edit EVENT on an unwatched path does not stale watched evidence
        code, out, err = self.cli("iterate", "decide", "ADVANCE")
        self.assertEqual(code, 0, out + err)


if __name__ == "__main__":
    unittest.main()
