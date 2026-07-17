"""Phase B — repo identity: the store is keyed by PATH, and paths lie.

The runtime state store lives outside the repo (.cgel/ is gitignored, D-35)
and is keyed by absolute path. Two things follow, both silent:

  - delete a repo and clone another at the same path, and the new repo
    inherits the old one's open task — a sealed contract whose scope
    describes code that no longer exists,
  - move a repo, and it loses sight of its own open task; `cgel status`
    says DRAFT and the user concludes the work is gone.

A git-lineage fingerprint (the sorted root commits) GUARDS the store. It
does not KEY it: lineage is shared by clones and worktrees, so it can say
"this is not yours" but never "this is uniquely mine".
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from hookrunner import run_cli, run_hook, decision_line

CONTRACT = {
    "task": {"id": "TASK-ID1", "type": "bug-fix", "goal": "identity fixture"},
    "acceptance_criteria": [
        {"id": "AC-1", "description": "x", "required_checks": ["unit-tests"]}
    ],
    "scope": {"allowed": ["src/**"], "forbidden": []},
    "risk": {"level": "low", "reasons": ["fixture: exercises repo identity"]},
}


class IdentityTestCase(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="cgel-ident-")
        self.state = tempfile.mkdtemp(prefix="cgel-state-")
        self.env = {"CGEL_STATE_DIR": self.state}

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)
        shutil.rmtree(self.state, ignore_errors=True)

    # ---------------------------------------------------------- helpers

    def git(self, path, *args):
        return subprocess.run(
            ["git"] + list(args), cwd=path, capture_output=True, text=True
        )

    def make_repo(self, name, seed="0", git=True):
        """A project at <base>/<name>.

        `seed` must differ between repos meant to be DIFFERENT: git commits
        are content-addressed, so two repos with identical content, author,
        message and second-granularity timestamp share a root commit and are
        genuinely one lineage. A fixture that forgets this silently tests
        nothing.
        """
        path = os.path.join(self.base, name)
        os.makedirs(os.path.join(path, ".cgel"))
        os.makedirs(os.path.join(path, ".task"))
        os.makedirs(os.path.join(path, "src"))
        with open(os.path.join(path, ".cgel", "registry.json"), "w") as fh:
            json.dump({"checks": {"unit-tests": {"command": "true"}}}, fh)
        with open(os.path.join(path, "src", "a.py"), "w") as fh:
            fh.write("x = %s\n" % seed)
        if git:
            self.git(path, "init", "-q")
            self.git(path, "config", "user.email", "t@example.com")
            self.git(path, "config", "user.name", "t")
            self.git(path, "add", "-A")
            self.git(path, "commit", "-qm", "init")
        return path

    def seal(self, path):
        with open(os.path.join(path, ".task", "contract.json"), "w") as fh:
            json.dump(CONTRACT, fh)
        code, out, err = run_cli(["summary"], cwd=path, env=self.env)
        self.assertEqual(code, 0, err)
        digest = decision_line(out).split("digest=")[1].split()[0]
        code, out, err = run_cli(
            ["seal", "TASK-ID1", "--digest", digest], cwd=path, env=self.env
        )
        self.assertEqual(code, 0, out + err)

    def status(self, path):
        code, out, err = run_cli(["status"], cwd=path, env=self.env)
        return code, decision_line(out) or "", err

    def edit_is_gated(self, path):
        code, _, _ = run_hook(
            "contract_gate.py",
            {
                "tool_name": "Write",
                "tool_input": {"file_path": os.path.join(path, "src", "a.py")},
                "cwd": path,
            },
            env=self.env,
        )
        return code == 2

    # ------------------------------------------------------------ tests

    def test_a_new_repo_at_a_reused_path_does_not_inherit_the_task(self):
        path = self.make_repo("proj", seed="1")
        self.seal(path)
        self.assertIn("STATUS SEALED", self.status(path)[1])
        self.assertFalse(self.edit_is_gated(path))  # in scope, task is ours

        shutil.rmtree(path)
        self.make_repo("proj", seed="2")  # different lineage, same path

        code, line, err = self.status(path)
        self.assertEqual(code, 1)
        self.assertIn("STATUS ORPHANED", line)
        self.assertIn("TASK-ID1", err)
        self.assertIn("DIFFERENT repository", err)
        self.assertIn(self.state, err)  # names the store to remove

    def test_an_orphaned_store_leaves_the_gate_closed(self):
        # The foreign task is withheld, so there is NO open task here — and
        # no open task means application files are read-only. Inheriting the
        # task would have been worse than useless: it would have OPENED the
        # gate for a scope written against code that no longer exists.
        path = self.make_repo("proj", seed="1")
        self.seal(path)
        shutil.rmtree(path)
        self.make_repo("proj", seed="2")
        self.assertTrue(self.edit_is_gated(path))

    def test_a_moved_repo_reports_stale_with_an_adopt_instruction(self):
        src = self.make_repo("before", seed="3")
        self.seal(src)
        dst = os.path.join(self.base, "after")
        shutil.move(src, dst)

        code, line, err = self.status(dst)
        self.assertEqual(code, 1)
        self.assertIn("STATUS STALE", line)
        self.assertIn("TASK-ID1", err)
        self.assertIn("mv ", err)  # a paste-ready adopt, lineage is certain

    def test_a_copied_repo_reports_neither(self):
        # The dangerous case. A copy shares the original's lineage, so a
        # lineage match alone would tell the user to `mv` the ORIGINAL's store
        # onto the copy — adopting a live task away from the repo still using
        # it. A move leaves its old path empty; a copy does not.
        orig = self.make_repo("orig", seed="4")
        self.seal(orig)
        copy = os.path.join(self.base, "copy")
        shutil.copytree(orig, copy, symlinks=True)

        code, line, err = self.status(copy)
        self.assertNotIn("STATUS STALE", line)
        self.assertNotIn("STATUS ORPHANED", line)
        self.assertNotIn("mv ", err)
        self.assertIn("STATUS SEALED", self.status(orig)[1])

    def test_a_sibling_worktree_does_not_adopt_the_main_stores_task(self):
        main = self.make_repo("main", seed="5")
        self.seal(main)
        tree = os.path.join(self.base, "wt")
        self.git(main, "worktree", "add", "-q", tree, "-b", "side")
        os.makedirs(os.path.join(tree, ".cgel"), exist_ok=True)

        code, line, err = self.status(tree)
        self.assertNotIn("STATUS STALE", line)
        self.assertNotIn("mv ", err)
        self.assertIn("STATUS SEALED", self.status(main)[1])

    def test_a_task_sealed_without_a_fingerprint_is_untouched(self):
        # Every store that exists today predates fingerprints. Unknown on
        # either side keeps the task: this guard drops work, so it fires only
        # on a positive disagreement between two known values.
        path = self.make_repo("legacy", seed="6")
        self.seal(path)
        for name in os.listdir(self.state):
            state_path = os.path.join(self.state, name, "TASK-ID1", "state.json")
            if os.path.isfile(state_path):
                with open(state_path) as fh:
                    state = json.load(fh)
                del state["repo_fingerprint"]
                del state["repo_root"]
                with open(state_path, "w") as fh:
                    json.dump(state, fh)
        self.assertIn("STATUS SEALED", self.status(path)[1])

    def test_a_non_git_project_is_unaffected(self):
        path = self.make_repo("plain", git=False)
        self.seal(path)
        self.assertIn("STATUS SEALED", self.status(path)[1])

    def test_a_repo_with_no_commits_yet_is_unaffected(self):
        path = os.path.join(self.base, "empty")
        os.makedirs(os.path.join(path, ".cgel"))
        os.makedirs(os.path.join(path, ".task"))
        os.makedirs(os.path.join(path, "src"))
        with open(os.path.join(path, ".cgel", "registry.json"), "w") as fh:
            json.dump({"checks": {"unit-tests": {"command": "true"}}}, fh)
        self.git(path, "init", "-q")
        self.seal(path)
        self.assertIn("STATUS SEALED", self.status(path)[1])

    def test_a_pre_fingerprint_store_at_a_matching_name_is_offered_cautiously(self):
        # The ONLY branch that can see a store written before this release —
        # and that is every store that exists today. It has no fingerprint and
        # no recorded root, so a name match is the only evidence there is, and
        # name matches are weak: two checkouts of `api` under different
        # parents produce the same basename. Hence advice, never a paste-ready
        # move.
        src = self.make_repo("proj", seed="9")
        self.seal(src)
        for name in os.listdir(self.state):
            state_path = os.path.join(self.state, name, "TASK-ID1", "state.json")
            if os.path.isfile(state_path):
                with open(state_path) as fh:
                    state = json.load(fh)
                del state["repo_fingerprint"]
                del state["repo_root"]
                with open(state_path, "w") as fh:
                    json.dump(state, fh)
        # Same basename, different path: the store key no longer matches.
        dst = os.path.join(self.base, "moved", "proj")
        os.makedirs(os.path.dirname(dst))
        shutil.move(src, dst)

        code, line, err = self.status(dst)
        self.assertEqual(code, 1)
        self.assertIn("STATUS STALE", line)
        self.assertIn("cannot prove it is yours", err)
        self.assertIn("ls ", err)  # look first
        self.assertNotIn("Adopt it: `mv", err)  # never paste-ready here

    def test_reading_status_does_not_create_a_store(self):
        # repo_fingerprint caches under the store. A read must never be the
        # thing that mints the store directory.
        path = self.make_repo("fresh", seed="7")
        before = sorted(os.listdir(self.state))
        self.status(path)
        self.assertEqual(sorted(os.listdir(self.state)), before)

    def test_the_fingerprint_is_not_exported_in_sealed_task(self):
        # sealed_task.json is an export surface the user may hand to someone
        # else; where their checkout lives is not part of the contract.
        path = self.make_repo("proj", seed="8")
        self.seal(path)
        for name in os.listdir(self.state):
            sealed_path = os.path.join(self.state, name, "TASK-ID1", "sealed_task.json")
            if os.path.isfile(sealed_path):
                with open(sealed_path) as fh:
                    sealed = json.load(fh)
                self.assertNotIn("repo_fingerprint", sealed)
                self.assertNotIn("repo_root", sealed)


if __name__ == "__main__":
    unittest.main()
