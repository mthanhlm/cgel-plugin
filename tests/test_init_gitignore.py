"""cgel init adds nothing to the host project's git history (D-35 / EXC-1).

Both directories init creates are local: .task/ is the runtime mirror, and
.cgel/ holds the registry. Per D-35 the registry is deliberately per-machine
rather than a committed, reviewed yardstick — so a fresh clone starts with no
checks, and `cgel verify` has nothing to run until someone registers them.
That is a real weakening of principle #3, accepted by the project owner and
recorded in ARCHITECT.md; these tests pin the behaviour that was chosen, so
it cannot drift back by accident in either direction.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from hookrunner import CLI, PLUGIN_ROOT, REPO_ROOT

EXPECTED_ENTRIES = (".cgel/", ".task/")


def read_gitignore(repo):
    path = os.path.join(repo, ".gitignore")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return fh.read().splitlines()


class InitGitignore(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="cgel-init-")
        self.state = tempfile.mkdtemp(prefix="cgel-state-")
        subprocess.run(
            ["git", "init", "-q"], cwd=self.repo, check=True, capture_output=True
        )
        self.env = {"CGEL_STATE_DIR": self.state}

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.state, ignore_errors=True)

    def init(self):
        merged = os.environ.copy()
        merged.update(self.env)
        return subprocess.run(
            [sys.executable, CLI, "init"],
            cwd=self.repo,
            env=merged,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_guard_init_actually_succeeds(self):
        # Otherwise every assertion below would pass over a missing file.
        proc = self.init()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIsNotNone(read_gitignore(self.repo), "init wrote no .gitignore")

    def test_both_directories_are_ignored(self):
        self.init()
        lines = read_gitignore(self.repo)
        for entry in EXPECTED_ENTRIES:
            self.assertIn(entry, lines)

    def test_init_is_idempotent(self):
        self.init()
        self.init()
        lines = read_gitignore(self.repo)
        for entry in EXPECTED_ENTRIES:
            self.assertEqual(lines.count(entry), 1, "%s duplicated" % entry)

    def test_existing_gitignore_is_appended_not_clobbered(self):
        path = os.path.join(self.repo, ".gitignore")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("node_modules/\n")
        self.init()
        lines = read_gitignore(self.repo)
        self.assertIn("node_modules/", lines)
        for entry in EXPECTED_ENTRIES:
            self.assertIn(entry, lines)

    def test_missing_trailing_newline_does_not_glue_entries(self):
        path = os.path.join(self.repo, ".gitignore")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("*.log")  # no trailing newline
        self.init()
        lines = read_gitignore(self.repo)
        self.assertIn("*.log", lines)
        for entry in EXPECTED_ENTRIES:
            self.assertIn(entry, lines)


class ThisRepoMatchesTheDocumentedBehaviour(unittest.TestCase):
    def test_repo_gitignore_ignores_both(self):
        lines = read_gitignore(REPO_ROOT)
        self.assertIsNotNone(lines)
        for entry in EXPECTED_ENTRIES:
            self.assertIn(entry, lines)

    def test_architect_records_the_override(self):
        # A doc that still describes the superseded layout is worse than no
        # doc: it reads as current.
        with open(os.path.join(REPO_ROOT, "ARCHITECT.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("D-35", text)

    def test_cli_declares_both_entries(self):
        with open(os.path.join(PLUGIN_ROOT, "bin", "cgel"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn('GITIGNORE_ENTRIES = (".cgel/", ".task/")', text)


if __name__ == "__main__":
    unittest.main()
