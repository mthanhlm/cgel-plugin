"""cgel CLI — subprocess tests: validate, summary, seal ceremony, close."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

from hookrunner import run_cli, decision_line

CONTRACT = {
    "task": {"id": "TASK-C1", "type": "feature", "goal": "Add refund endpoint"},
    "acceptance_criteria": [
        {"id": "AC-1", "description": "endpoint returns 201", "required_checks": ["unit-tests"]}
    ],
    "scope": {"allowed": ["src/**"]},
}


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="cgel-repo-")
        self.state = tempfile.mkdtemp(prefix="cgel-state-")
        os.makedirs(os.path.join(self.repo, ".cgel"))
        os.makedirs(os.path.join(self.repo, ".task"))
        self.env = {"CGEL_STATE_DIR": self.state}

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.state, ignore_errors=True)

    def cli(self, *args):
        return run_cli(list(args), cwd=self.repo, env=self.env)

    def write_contract(self, contract):
        with open(
            os.path.join(self.repo, ".task", "contract.json"), "w", encoding="utf-8"
        ) as fh:
            json.dump(contract, fh)

    def summary_digest(self):
        code, out, err = self.cli("summary")
        self.assertEqual(code, 0, err)
        return decision_line(out).split("digest=")[1].split()[0]

    # ------------------------------------------------------------ tests

    def test_validate_fail_missing_goal(self):
        broken = json.loads(json.dumps(CONTRACT))
        del broken["task"]["goal"]
        self.write_contract(broken)
        code, out, err = self.cli("validate")
        self.assertEqual(code, 1)
        self.assertIn("VALIDATE FAIL", decision_line(out))
        self.assertIn("task.goal", err)

    def test_validate_pass(self):
        self.write_contract(CONTRACT)
        code, out, _ = self.cli("validate")
        self.assertEqual(code, 0)
        self.assertIn("VALIDATE PASS", decision_line(out))
        self.assertIn("sha256:", decision_line(out))

    def test_summary_shows_seal_mode(self):
        self.write_contract(CONTRACT)
        code, out, err = self.cli("summary")
        self.assertEqual(code, 0)
        self.assertIn("seal_mode=auto", decision_line(out))
        self.assertIn("Allowed scope:", err)
        with_caps = json.loads(json.dumps(CONTRACT))
        with_caps["protected_capabilities"] = ["external-write"]
        self.write_contract(with_caps)
        _, out, _ = self.cli("summary")
        self.assertIn("seal_mode=human", decision_line(out))

    def test_seal_digest_mismatch_denied(self):
        self.write_contract(CONTRACT)
        code, out, err = self.cli(
            "seal", "TASK-C1", "--digest", "sha256:" + "0" * 64
        )
        self.assertEqual(code, 1)
        self.assertIn("SEAL DENIED", decision_line(out))
        self.assertIn("digest mismatch", decision_line(out) + err)

    def test_contract_edit_after_summary_invalidates_digest(self):
        self.write_contract(CONTRACT)
        digest = self.summary_digest()
        changed = json.loads(json.dumps(CONTRACT))
        changed["scope"]["allowed"].append("infra/**")  # silent widening
        self.write_contract(changed)
        code, out, _ = self.cli("seal", "TASK-C1", "--digest", digest)
        self.assertEqual(code, 1)
        self.assertIn("SEAL DENIED", decision_line(out))

    def test_seal_ok_then_double_seal_denied(self):
        self.write_contract(CONTRACT)
        digest = self.summary_digest()
        code, out, _ = self.cli("seal", "TASK-C1", "--digest", digest)
        self.assertEqual(code, 0)
        self.assertIn("SEAL OK", decision_line(out))
        code, out, _ = self.cli("seal", "TASK-C1", "--digest", digest)
        self.assertEqual(code, 1)
        self.assertIn("already active", decision_line(out))

    def test_status_transitions(self):
        code, out, _ = self.cli("status")
        self.assertEqual(code, 0)
        self.assertEqual(decision_line(out), "STATUS NO_TASK")
        self.write_contract(CONTRACT)
        _, out, _ = self.cli("status")
        self.assertIn("STATUS DRAFT task=TASK-C1", decision_line(out))
        digest = self.summary_digest()
        self.cli("seal", "TASK-C1", "--digest", digest)
        _, out, _ = self.cli("status")
        self.assertIn("STATUS SEALED task=TASK-C1", decision_line(out))
        self.cli("close", "--as", "ABORT")
        _, out, _ = self.cli("status")
        self.assertIn("STATUS DRAFT", decision_line(out))  # draft file remains

    def test_close_pass_denied_in_phase0(self):
        self.write_contract(CONTRACT)
        digest = self.summary_digest()
        self.cli("seal", "TASK-C1", "--digest", digest)
        code, out, err = self.cli("close", "--as", "PASS")
        self.assertEqual(code, 1)
        self.assertIn("CLOSE DENIED", decision_line(out))
        self.assertIn("evidence", (decision_line(out) + err).lower())

    def test_close_escalate_ok(self):
        self.write_contract(CONTRACT)
        digest = self.summary_digest()
        self.cli("seal", "TASK-C1", "--digest", digest)
        code, out, _ = self.cli("close", "--as", "ESCALATE", "--reason", "user verify")
        self.assertEqual(code, 0)
        self.assertIn("CLOSE OK", decision_line(out))

    def test_task_id_mismatch_denied(self):
        self.write_contract(CONTRACT)
        digest = self.summary_digest()
        code, out, _ = self.cli("seal", "TASK-OTHER", "--digest", digest)
        self.assertEqual(code, 1)
        self.assertIn("task id mismatch", decision_line(out))

    def test_dirty_scope_intersection_denied_then_allowed(self):
        subprocess.run(
            ["git", "init", "-q"], cwd=self.repo, check=True, capture_output=True
        )
        src = os.path.join(self.repo, "src")
        os.makedirs(src)
        with open(os.path.join(src, "wip.py"), "w", encoding="utf-8") as fh:
            fh.write("# user work in progress\n")
        self.write_contract(CONTRACT)
        digest = self.summary_digest()
        code, out, err = self.cli("seal", "TASK-C1", "--digest", digest)
        self.assertEqual(code, 1, out + err)
        self.assertIn("uncommitted changes intersect", decision_line(out))
        self.assertIn("src/wip.py", err)
        code, out, _ = self.cli(
            "seal", "TASK-C1", "--digest", digest, "--allow-dirty"
        )
        self.assertEqual(code, 0, out)
        self.assertIn("SEAL OK", decision_line(out))

    def test_check_add_list_and_force(self):
        code, out, _ = self.cli(
            "check", "add", "unit-tests", "--command", "npm test", "--kind", "test"
        )
        self.assertEqual(code, 0)
        self.assertIn("CHECK ADDED", decision_line(out))
        code, out, _ = self.cli(
            "check", "add", "unit-tests", "--command", "pytest"
        )
        self.assertEqual(code, 1)
        self.assertIn("already exists", decision_line(out))
        code, _, _ = self.cli(
            "check", "add", "unit-tests", "--command", "pytest", "--force"
        )
        self.assertEqual(code, 0)
        code, out, err = self.cli("check", "list")
        self.assertEqual(code, 0)
        self.assertIn("CHECK LIST — 1 check(s)", decision_line(out))
        self.assertIn("unit-tests: pytest", err)
        with open(os.path.join(self.repo, ".cgel", "registry.json")) as fh:
            registry = json.load(fh)
        self.assertEqual(registry["checks"]["unit-tests"]["command"], "pytest")

    def test_check_add_denied_while_task_open(self):
        self.write_contract(CONTRACT)
        digest = self.summary_digest()
        self.cli("seal", "TASK-C1", "--digest", digest)
        code, out, _ = self.cli(
            "check", "add", "late-check", "--command", "echo x"
        )
        self.assertEqual(code, 1)
        self.assertIn("CHECK DENIED", decision_line(out))
        self.assertIn("governance bundle", decision_line(out))

    def test_init_creates_structure(self):
        fresh = tempfile.mkdtemp(prefix="cgel-fresh-")
        try:
            code, out, _ = run_cli(["init"], cwd=fresh, env=self.env)
            self.assertEqual(code, 0)
            self.assertIn("INIT OK", decision_line(out))
            self.assertTrue(os.path.isfile(os.path.join(fresh, ".cgel", "config.json")))
            self.assertTrue(os.path.isdir(os.path.join(fresh, ".task")))
            with open(os.path.join(fresh, ".gitignore"), encoding="utf-8") as fh:
                self.assertIn(".task/", fh.read())
        finally:
            shutil.rmtree(fresh, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
