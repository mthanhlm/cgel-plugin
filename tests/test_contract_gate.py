"""contract_gate.py — subprocess tests against Phase 0 exit criteria."""

import json
import os
import shutil
import tempfile
import unittest

from hookrunner import run_hook, run_cli, decision_line

CONTRACT = {
    "task": {"id": "TASK-T1", "type": "bug-fix", "goal": "Fix the widget"},
    "acceptance_criteria": [
        {"id": "AC-1", "description": "widget works", "required_checks": ["unit-tests"]}
    ],
    "scope": {"allowed": ["src/**", "tests/**"], "forbidden": ["src/legacy/**"]},
}


class GateTestCase(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="cgel-repo-")
        self.state = tempfile.mkdtemp(prefix="cgel-state-")
        os.makedirs(os.path.join(self.repo, ".cgel"))
        os.makedirs(os.path.join(self.repo, ".task"))
        self.env = {"CGEL_STATE_DIR": self.state}

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.state, ignore_errors=True)

    # ---------------------------------------------------------- helpers

    def write_contract(self, contract=None):
        path = os.path.join(self.repo, ".task", "contract.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(contract or CONTRACT, fh)

    def seal(self, contract=None, extra_args=()):
        self.write_contract(contract)
        code, out, err = run_cli(["summary"], cwd=self.repo, env=self.env)
        self.assertEqual(code, 0, err)
        digest = decision_line(out).split("digest=")[1].split()[0]
        task_id = (contract or CONTRACT)["task"]["id"]
        code, out, err = run_cli(
            ["seal", task_id, "--digest", digest] + list(extra_args),
            cwd=self.repo,
            env=self.env,
        )
        self.assertEqual(code, 0, out + err)
        return digest

    def edit(self, rel_path, env=None):
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": os.path.join(self.repo, rel_path)},
            "cwd": self.repo,
        }
        merged = dict(self.env)
        merged.update(env or {})
        return run_hook("contract_gate.py", payload, env=merged)

    # ------------------------------------------------------------ tests

    def test_not_a_cgel_project_allows(self):
        plain = tempfile.mkdtemp(prefix="cgel-plain-")
        try:
            payload = {
                "tool_name": "Write",
                "tool_input": {"file_path": os.path.join(plain, "src/app.py")},
                "cwd": plain,
            }
            code, _, _ = run_hook("contract_gate.py", payload, env=self.env)
            self.assertEqual(code, 0)
        finally:
            shutil.rmtree(plain, ignore_errors=True)

    def test_no_sealed_contract_blocks_app_code(self):
        code, _, err = self.edit("src/app.py")
        self.assertEqual(code, 2)
        self.assertIn("no sealed contract", err)

    def test_contract_draft_path_always_writable(self):
        code, _, _ = self.edit(".task/contract.json")
        self.assertEqual(code, 0)

    def test_sealed_allows_in_scope(self):
        self.seal()
        code, _, err = self.edit("src/app.py")
        self.assertEqual(code, 0, err)

    def test_sealed_blocks_out_of_scope(self):
        self.seal()
        code, _, err = self.edit("docs/readme.md")
        self.assertEqual(code, 2)
        self.assertIn("outside scope.allowed", err)

    def test_sealed_blocks_forbidden_path(self):
        self.seal()
        code, _, err = self.edit("src/legacy/old.py")
        self.assertEqual(code, 2)
        self.assertIn("scope.forbidden", err)

    def test_governance_path_blocked_without_capability(self):
        self.seal()
        code, _, err = self.edit(".claude/rules/constitution.md")
        self.assertEqual(code, 2)
        self.assertIn("modify-governance", err)

    def test_registry_named_capability(self):
        self.seal()
        code, _, err = self.edit(".cgel/registry.json")
        self.assertEqual(code, 2)
        self.assertIn("modify-verification-registry", err)

    def test_governance_allowed_with_sealed_capability(self):
        contract = json.loads(json.dumps(CONTRACT))
        contract["task"]["id"] = "TASK-GOV"
        contract["scope"]["allowed"] = [".claude/**"]
        contract["protected_capabilities"] = ["modify-governance"]
        self.seal(contract)
        code, _, err = self.edit(".claude/rules/constitution.md")
        self.assertEqual(code, 0, err)
        # capability granted, but scope still applies elsewhere
        code, _, _ = self.edit("src/app.py")
        self.assertEqual(code, 2)

    def test_governance_blocked_even_when_scope_matches(self):
        contract = json.loads(json.dumps(CONTRACT))
        contract["task"]["id"] = "TASK-WIDE"
        contract["scope"]["allowed"] = ["**"]
        self.seal(contract)
        code, _, err = self.edit("docs/standards/security.md")
        self.assertEqual(code, 2)
        self.assertIn("governance", err)

    def test_close_shuts_the_gate_again(self):
        self.seal()
        code, out, err = run_cli(
            ["close", "--as", "ESCALATE"], cwd=self.repo, env=self.env
        )
        self.assertEqual(code, 0, out + err)
        code, _, _ = self.edit("src/app.py")
        self.assertEqual(code, 2)

    def test_malformed_stdin_fails_open(self):
        code, _, _ = run_hook(
            "contract_gate.py", None, env=self.env, raw_stdin="{not json"
        )
        self.assertEqual(code, 0)

    def test_kill_switch_env(self):
        code, _, _ = self.edit("src/app.py", env={"CGEL_GATE": "off"})
        self.assertEqual(code, 0)

    def test_kill_switch_config(self):
        with open(
            os.path.join(self.repo, ".cgel", "config.json"), "w", encoding="utf-8"
        ) as fh:
            json.dump({"gate": "off"}, fh)
        code, _, _ = self.edit("src/app.py")
        self.assertEqual(code, 0)

    def test_file_outside_repo_not_gated(self):
        outside = tempfile.mkdtemp(prefix="cgel-outside-")
        try:
            payload = {
                "tool_name": "Write",
                "tool_input": {"file_path": os.path.join(outside, "x.txt")},
                "cwd": self.repo,
            }
            code, _, _ = run_hook("contract_gate.py", payload, env=self.env)
            self.assertEqual(code, 0)
        finally:
            shutil.rmtree(outside, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
