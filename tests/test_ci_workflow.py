"""CI runs the release preflight, and runs every check the registry declares.

The cgel-release skill tells a human to run the suite before shipping; the
workflow is what makes that true when nobody reads the skill. These tests
pin the properties that make the workflow worth having — if it stops
running on main, or starts listing test modules by hand, or drifts away
from the registered checks, the green tick would start meaning less than
it appears to.
"""

import json
import os
import re
import unittest

from hookrunner import PLUGIN_ROOT

WORKFLOW_PATH = os.path.join(PLUGIN_ROOT, ".github", "workflows", "ci.yml")
REGISTRY_PATH = os.path.join(PLUGIN_ROOT, ".cgel", "registry.json")

# `unittest tests.foo.test_bar` — a hand-maintained module list, which stops
# running whatever nobody remembered to append to it.
ENUMERATED_MODULES_RE = re.compile(r"unittest\s+(?:-\w+\s+)*[\w.]*test_\w+")

ON_PULL_REQUEST_RE = re.compile(r"^\s*pull_request:\s*$", re.M)
ON_PUSH_RE = re.compile(r"^\s*push:\s*$", re.M)
BRANCHES_MAIN_RE = re.compile(r"^\s*branches:\s*\[\s*main\s*\]\s*$", re.M)


def workflow_text():
    with open(WORKFLOW_PATH, encoding="utf-8") as fh:
        return fh.read()


def registered_commands():
    with open(REGISTRY_PATH, encoding="utf-8") as fh:
        checks = json.load(fh)["checks"]
    return {check_id: entry["command"] for check_id, entry in checks.items()}


class VacuousPassGuard(unittest.TestCase):
    def test_workflow_is_found_and_substantial(self):
        self.assertGreater(len(workflow_text()), 200)

    def test_registry_has_checks(self):
        self.assertGreaterEqual(len(registered_commands()), 3)


class WorkflowTriggers(unittest.TestCase):
    def test_runs_on_pull_requests(self):
        self.assertRegex(workflow_text(), ON_PULL_REQUEST_RE)

    def test_runs_on_push_to_main(self):
        text = workflow_text()
        self.assertRegex(text, ON_PUSH_RE)
        self.assertRegex(text, BRANCHES_MAIN_RE)


class WorkflowRunsTheRealSuite(unittest.TestCase):
    def test_uses_test_discovery(self):
        self.assertIn("python3 -m unittest discover", workflow_text())

    def test_does_not_enumerate_test_modules_by_hand(self):
        match = ENUMERATED_MODULES_RE.search(workflow_text())
        self.assertIsNone(
            match,
            "ci.yml enumerates test modules (%r); use discovery instead"
            % (match.group(0) if match else ""),
        )

    def test_every_registered_check_runs_in_ci(self):
        # Otherwise the sealed yardstick and the green tick measure
        # different things.
        text = workflow_text()
        for check_id, command in registered_commands().items():
            self.assertIn(command, text, "check %r never runs in CI" % check_id)


if __name__ == "__main__":
    unittest.main()
