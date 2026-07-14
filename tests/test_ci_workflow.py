"""CI runs the release preflight on every push.

The cgel-release skill tells a human to run the suite before shipping; the
workflow is what makes that true when nobody reads the skill. These tests
pin the properties that make it worth having — if it stops running on main,
or starts listing test modules by hand, the green tick would start meaning
less than it appears to.

There is deliberately no test that CI runs every check in .cgel/registry.json.
Per EXC-1 the registry is gitignored, so CI has no registry to compare
against, and a check that silently no-ops in CI is worse than no check.
"""

import os
import re
import unittest

from hookrunner import REPO_ROOT

WORKFLOW_PATH = os.path.join(REPO_ROOT, ".github", "workflows", "ci.yml")

# `unittest tests.foo.test_bar` — a hand-maintained module list, which stops
# running whatever nobody remembered to append to it.
ENUMERATED_MODULES_RE = re.compile(r"unittest\s+(?:-\w+\s+)*[\w.]*test_\w+")

ON_PULL_REQUEST_RE = re.compile(r"^\s*pull_request:\s*$", re.M)
ON_PUSH_RE = re.compile(r"^\s*push:\s*$", re.M)
BRANCHES_MAIN_RE = re.compile(r"^\s*branches:\s*\[\s*main\s*\]\s*$", re.M)


def workflow_text():
    with open(WORKFLOW_PATH, encoding="utf-8") as fh:
        return fh.read()


class VacuousPassGuard(unittest.TestCase):
    def test_workflow_is_found_and_substantial(self):
        self.assertGreater(len(workflow_text()), 200)


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

    def test_preflight_covers_the_shipped_payload(self):
        text = workflow_text()
        self.assertIn("compileall -q plugin/scripts plugin/bin/cgel", text)
        self.assertIn("plugin/hooks/hooks.json", text)


if __name__ == "__main__":
    unittest.main()
