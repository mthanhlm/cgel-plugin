"""Phase E — no surface prints green over a control that is not running.

Two controls can be silently absent, and both leave every screen looking
healthy:

  - the WORKSPACE BINDING. With no git, workspace_snapshot returns the
    "no-git" constant for diff_digest. A digest that compares equal to
    itself forever means evidence can never go stale — `cgel verify` passes,
    the code changes, and PASS still certifies it.
  - the GATE ITSELF. `cgel status` says SEALED, which reads as "edits are
    gated". Whether any hook is running is a different fact, and one CGEL
    cannot ask the harness: a plugin that was never installed, a session
    rooted above the project, and a healthy install all look identical from
    inside. Only a hook that fired can prove one fired.

The rule these pin: qualify the claim, never fake the verdict. AUDIT OK
stays OK — the chain IS intact — while saying what it could not observe.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

from hookrunner import run_cli, run_hook, decision_line

CONTRACT = {
    "task": {"id": "TASK-V1", "type": "bug-fix", "goal": "fail-visible fixture"},
    "acceptance_criteria": [
        {"id": "AC-1", "description": "x", "required_checks": ["ok-check"]}
    ],
    "scope": {"allowed": ["src/**"], "forbidden": []},
    "risk": {"level": "low", "reasons": ["fixture: exercises the surfaces"]},
}
REGISTRY = {"checks": {"ok-check": {"command": "test -f src/app.py", "kind": "test"}}}


class FailVisibleFixture(unittest.TestCase):
    """Fixture only — no tests, so subclasses do not re-run each other's."""

    git = True

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="cgel-repo-")
        self.state = tempfile.mkdtemp(prefix="cgel-state-")
        os.makedirs(os.path.join(self.repo, ".cgel"))
        os.makedirs(os.path.join(self.repo, ".task"))
        os.makedirs(os.path.join(self.repo, "src"))
        self.env = {"CGEL_STATE_DIR": self.state}
        with open(os.path.join(self.repo, ".cgel", "registry.json"), "w") as fh:
            json.dump(REGISTRY, fh)
        with open(os.path.join(self.repo, "src", "app.py"), "w") as fh:
            fh.write("x = 1\n")
        if self.git:
            for args in (
                ["init", "-q"],
                ["add", "-A"],
                ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"],
            ):
                subprocess.run(["git"] + args, cwd=self.repo, check=True,
                               capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.state, ignore_errors=True)

    def cli(self, *args):
        return run_cli(list(args), cwd=self.repo, env=self.env)

    def seal(self):
        with open(os.path.join(self.repo, ".task", "contract.json"), "w") as fh:
            json.dump(CONTRACT, fh)
        code, out, err = self.cli("summary")
        self.assertEqual(code, 0, err)
        digest = decision_line(out).split("digest=")[1].split()[0]
        return self.cli("seal", "TASK-V1", "--digest", digest)

    def edit_hook(self, env=None):
        merged = dict(self.env)
        merged.update(env or {})
        return run_hook(
            "contract_gate.py",
            {
                "tool_name": "Write",
                "tool_input": {"file_path": os.path.join(self.repo, "src", "app.py")},
                "cwd": self.repo,
            },
            env=merged,
        )

    def gate_token(self):
        code, out, err = self.cli("status")
        line = decision_line(out) or ""
        return line.split("gate=")[1].split()[0] if "gate=" in line else None


class InertWorkspaceTestCase(FailVisibleFixture):
    git = False  # the whole point: no work tree, so nothing can go stale

    def test_seal_warns_that_the_binding_is_inert(self):
        # seal MINTS the workspace claim. If it is inert, every record this
        # task makes is permanently fresh, and this is the moment to say so.
        code, out, err = self.seal()
        self.assertEqual(code, 0, err)
        self.assertIn("workspace binding inert", decision_line(out))
        self.assertIn("cannot go stale", err)

    def test_audit_stays_ok_but_says_the_workspace_is_inert(self):
        # AUDIT OK is not softened: the chain IS intact. A DIFFERENT claim —
        # that evidence is bound to the code as it stands — is the one being
        # qualified.
        self.seal()
        self.cli("verify", "ok-check")
        code, out, err = self.cli("audit")
        self.assertEqual(code, 0, err)
        self.assertIn("AUDIT OK", decision_line(out))
        self.assertIn("chain=intact", decision_line(out))
        self.assertIn("workspace=inert(no-git)", decision_line(out))
        self.assertIn("cannot go stale", err)
        self.assertIn("1 of 1 evidence record(s)", err)

    def test_doctor_reports_the_git_state_too(self):
        # Written first asserting only `code == 0`, which named a behaviour
        # nothing implemented — cmd_check_doctor never called git_state. A
        # test for a feature that does not exist cannot fail, and in the very
        # phase whose thesis is "no green over a control that is not running"
        # that is the defect itself. The warning exists now, and this asserts
        # it.
        code, out, err = self.cli("check", "doctor")
        self.assertEqual(code, 0, err)
        self.assertIn("workspace binding is inert", err)
        self.assertIn("cannot go stale", err)

    def test_the_no_git_constants_are_unchanged(self):
        # Load-bearing: _evidence_problem compares diff_digest for EQUALITY,
        # so renaming these would invalidate every in-flight seal.
        self.seal()
        self.cli("verify", "ok-check")
        store = os.path.join(self.state, os.listdir(self.state)[0], "TASK-V1")
        with open(os.path.join(store, "evidence.jsonl")) as fh:
            rec = json.loads(fh.readline())
        self.assertEqual(rec["workspace"]["diff_digest"], "no-git")
        self.assertEqual(rec["workspace"]["base_revision"], "no-git")
        self.assertEqual(rec["workspace"]["degraded"], "no-git")


class BoundWorkspaceTestCase(FailVisibleFixture):
    def test_a_live_work_tree_reports_bound(self):
        self.seal()
        self.cli("verify", "ok-check")
        code, out, err = self.cli("audit")
        self.assertEqual(code, 0, err)
        self.assertIn("workspace=bound", decision_line(out))
        self.assertNotIn("inert", err)

    def test_seal_does_not_warn_on_a_live_work_tree(self):
        code, out, err = self.seal()
        self.assertEqual(code, 0, err)
        self.assertNotIn("inert", decision_line(out))
        self.assertNotIn("WARNING", err)

    def test_a_repo_with_no_commits_is_still_a_live_work_tree(self):
        # Deliberately `rev-parse --is-inside-work-tree`, not `rev-parse
        # HEAD`: an initialized repo with no commits is live, and its diff
        # digest still varies. HEAD would call it dead.
        empty = tempfile.mkdtemp(prefix="cgel-empty-")
        try:
            subprocess.run(["git", "init", "-q"], cwd=empty, check=True,
                           capture_output=True)
            import sys

            from hookrunner import SCRIPTS_DIR

            sys.path.insert(0, SCRIPTS_DIR)
            import cgel_common

            code, _ = cgel_common.git_state(empty)
            self.assertIsNone(code)
        finally:
            shutil.rmtree(empty, ignore_errors=True)


class GateBeaconTestCase(FailVisibleFixture):
    def test_a_gate_no_hook_has_ever_run_is_unobserved(self):
        # The headline case: `cgel status` said SEALED into a project where
        # nothing was gated, and read as a guarantee.
        self.seal()
        self.assertEqual(self.gate_token(), "unobserved")
        code, out, err = self.cli("status")
        self.assertIn("may not be running at all", err)

    def test_a_hook_that_fires_makes_the_gate_observed(self):
        self.seal()
        self.edit_hook()
        self.assertEqual(self.gate_token(), "on")

    def test_a_gate_turned_off_reports_off_not_unobserved(self):
        # The kill-switch checks sit BELOW rooting so that a gate turned off
        # is still a gate that RAN. Otherwise "you turned it off" and "it was
        # never wired up" are the same screen.
        self.seal()
        self.edit_hook(env={"CGEL_GATE": "off"})
        self.assertEqual(self.gate_token(), "off")
        code, out, err = self.cli("status")
        self.assertIn("NOT gated", err)
        self.assertNotIn("may not be running at all", err)

    def test_a_transition_beats_the_rate_limit(self):
        # The beacon is rate-limited to one write a minute, but a CHANGE
        # always writes: a kill switch must surface on the next tool call,
        # not up to a minute later.
        self.seal()
        self.edit_hook()
        self.assertEqual(self.gate_token(), "on")
        self.edit_hook(env={"CGEL_GATE": "off"})
        self.assertEqual(self.gate_token(), "off")
        self.edit_hook()
        self.assertEqual(self.gate_token(), "on")

    def test_a_live_config_off_wins_without_needing_a_beacon(self):
        # Read from disk right now — a fact needing no freshness.
        self.seal()
        with open(os.path.join(self.repo, ".cgel", "config.json"), "w") as fh:
            json.dump({"gate": "off"}, fh)
        self.assertEqual(self.gate_token(), "off")

    def test_a_beacon_older_than_the_seal_is_unobserved(self):
        # A beacon from before this seal proves nothing about this task.
        self.edit_hook()  # beacon written before there is any task
        self.seal()
        self.assertEqual(self.gate_token(), "unobserved")

    def test_a_stale_beacon_saying_off_is_unobserved_not_off(self):
        # A stale beacon is unobserved REGARDLESS of what it recorded. One
        # old CGEL_GATE=off experiment must not report `off` forever: a false
        # RED is how a reader learns to ignore the token.
        self.seal()
        self.edit_hook(env={"CGEL_GATE": "off"})
        self.assertEqual(self.gate_token(), "off")
        beacon = os.path.join(
            self.state, os.listdir(self.state)[0], "gate_beacon.json"
        )
        old = os.path.getmtime(beacon) - (7 * 3600)
        os.utime(beacon, (old, old))
        self.assertEqual(self.gate_token(), "unobserved")

    def test_status_with_no_task_carries_no_gate_prose(self):
        # The token qualifies a SEALED claim. A repo with no sealed task has
        # no claim to qualify, and two paragraphs on the most-run command in
        # the product is how a diagnostic gets ignored.
        code, out, err = self.cli("status")
        self.assertIn("STATUS NO_TASK", decision_line(out))
        self.assertNotIn("gate=", decision_line(out))
        self.assertEqual(err.strip(), "")

    def test_the_beacon_never_creates_the_store(self):
        # A diagnostic must not mint the thing it reports on.
        before = sorted(os.listdir(self.state))
        self.edit_hook()
        self.assertEqual(sorted(os.listdir(self.state)), before)


class DoctorDegradedTestCase(FailVisibleFixture):
    def test_a_check_doctor_cannot_test_is_degraded_not_ok(self):
        # A malformed entry was `continue`d past silently while len(checks)
        # still counted it as healthy: DOCTOR OK over a check with no
        # command at all.
        with open(os.path.join(self.repo, ".cgel", "registry.json"), "w") as fh:
            json.dump(
                {
                    "checks": {
                        "ok-check": {"command": "test -f src/app.py", "kind": "test"},
                        "broken-entry": {"kind": "test"},
                    }
                },
                fh,
            )
        code, out, err = self.cli("check", "doctor")
        self.assertEqual(code, 1)
        self.assertIn("DOCTOR DEGRADED", decision_line(out))
        self.assertIn("broken-entry", decision_line(out))
        self.assertIn("did not prove", err)

    def test_a_healthy_registry_is_still_ok_with_no_parenthetical(self):
        code, out, err = self.cli("check", "doctor")
        self.assertEqual(code, 0, err)
        self.assertIn("DOCTOR OK", decision_line(out))
        self.assertNotIn("unknown", decision_line(out))

    def test_doctor_does_not_warn_about_git_on_a_live_work_tree(self):
        # The other half: a warning that fires everywhere is noise, and noise
        # is how a diagnostic gets ignored.
        code, out, err = self.cli("check", "doctor")
        self.assertEqual(code, 0, err)
        self.assertNotIn("workspace binding is inert", err)


if __name__ == "__main__":
    unittest.main()
