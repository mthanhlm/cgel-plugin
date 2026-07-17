"""`cgel check remove` — the sanctioned exit a rotted check never had.

Before this, the registry was add-only. A check whose target had moved could be
neither detected (the one-sided canary reported it ok) nor removed: the registry
is a governance file the task skill forbids hand-editing and the gate holds
read-only, so the only exit was a Bash write around the gate — the one move CGEL
tells the model never to make. remove closes that loop, under the same
between-tasks-only gate as add, because the registry is part of the sealed
governance bundle.
"""

import json
import os
import shutil
import tempfile
import unittest

from hookrunner import run_cli, decision_line

CONTRACT = {
    "task": {"id": "TASK-R1", "type": "feature", "goal": "unrelated open task"},
    "acceptance_criteria": [
        {"id": "AC-1", "description": "x", "required_checks": ["unit-tests"]}
    ],
    "scope": {"allowed": ["src/**"]},
    "risk": {"level": "low", "reasons": ["fixture: exercises registry freeze"]},
}

REGISTRY = {
    "checks": {
        "unit-tests": {"command": "test -d src && python3 -m compileall -q src"},
        "rotted": {"command": "test -d gone && python3 -m compileall -q gone"},
    }
}


class CheckRemoveTestCase(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="cgel-rm-repo-")
        self.state = tempfile.mkdtemp(prefix="cgel-rm-state-")
        os.makedirs(os.path.join(self.repo, ".cgel"))
        os.makedirs(os.path.join(self.repo, ".task"))
        self.env = {"CGEL_STATE_DIR": self.state}
        self.write_registry(REGISTRY)

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.state, ignore_errors=True)

    def cli(self, *args):
        return run_cli(list(args), cwd=self.repo, env=self.env)

    def write_registry(self, obj):
        with open(
            os.path.join(self.repo, ".cgel", "registry.json"), "w", encoding="utf-8"
        ) as fh:
            json.dump(obj, fh, indent=1)

    def registry(self):
        with open(
            os.path.join(self.repo, ".cgel", "registry.json"), encoding="utf-8"
        ) as fh:
            return json.load(fh)

    def write_contract(self, contract):
        with open(
            os.path.join(self.repo, ".task", "contract.json"), "w", encoding="utf-8"
        ) as fh:
            json.dump(contract, fh)

    def seal_a_task(self):
        self.write_contract(CONTRACT)
        code, out, err = self.cli("summary")
        self.assertEqual(code, 0, err)
        digest = decision_line(out).split("digest=")[1].split()[0]
        code, _, err = self.cli("seal", "TASK-R1", "--digest", digest)
        self.assertEqual(code, 0, err)


class RemoveTakesACheckOutOfTheRegistry(CheckRemoveTestCase):
    def test_removing_an_existing_check_reports_and_persists(self):
        code, out, err = self.cli("check", "remove", "rotted")
        self.assertEqual(code, 0, err)
        self.assertIn("CHECK REMOVED", decision_line(out))
        self.assertNotIn("rotted", self.registry()["checks"])

    def test_other_checks_are_left_untouched(self):
        self.cli("check", "remove", "rotted")
        self.assertIn("unit-tests", self.registry()["checks"])


class RemoveRefusesRatherThanSilentlySucceeding(CheckRemoveTestCase):
    def test_removing_an_unknown_id_is_denied(self):
        code, out, err = self.cli("check", "remove", "never-existed")
        self.assertEqual(code, 1)
        self.assertIn("CHECK DENIED", decision_line(out))
        # names the ids that do exist, so the user can correct a typo
        self.assertIn("unit-tests", err)

    def test_a_denied_removal_changes_nothing(self):
        before = self.registry()
        self.cli("check", "remove", "never-existed")
        self.assertEqual(self.registry(), before)


class RemoveHonoursTheSealedRegistry(CheckRemoveTestCase):
    def test_removal_is_denied_while_a_task_is_open(self):
        self.seal_a_task()
        code, out, err = self.cli("check", "remove", "rotted")
        self.assertEqual(code, 1, "removed a check from a sealed registry")
        self.assertIn("CHECK DENIED", decision_line(out))
        self.assertIn("governance bundle", decision_line(out) + err)

    def test_the_check_survives_a_denied_removal_under_seal(self):
        self.seal_a_task()
        self.cli("check", "remove", "rotted")
        self.assertIn("rotted", self.registry()["checks"])


if __name__ == "__main__":
    unittest.main()
