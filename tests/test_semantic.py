"""Phase 3 — semantic layer: rule parsing, frozen verifier trigger,
findings recording, blocking-finding PASS gate, sanitized attestation,
read-only verifier agent."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from hookrunner import run_cli, decision_line, PLUGIN_ROOT

RULES_MD = """# Security standards

## SEC-1 — No credentials in logs
Blocking: yes
Owner: security-team
Applies-To: src/**
Requirement: never write tokens or passwords to any log stream.

## STYLE-1 — Prefer explicit names
Blocking: no
Applies-To: src/**
Requirement: no single-letter identifiers in public APIs.
"""

CONTRACT_HIGH = {
    "task": {"id": "TASK-S1", "type": "feature", "goal": "Semantic layer demo"},
    "acceptance_criteria": [
        {"id": "AC-1", "description": "check passes", "required_checks": ["ok-check"]}
    ],
    "scope": {"allowed": ["src/**"]},
    "risk": {"level": "high", "reasons": ["touches auth"]},
}

REGISTRY = {"checks": {"ok-check": {"command": "echo all good"}}}


class SemanticTestCase(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="cgel-repo-")
        self.state = tempfile.mkdtemp(prefix="cgel-state-")
        for rel in (".cgel", ".task", "src", "docs/standards"):
            os.makedirs(os.path.join(self.repo, rel))
        self.env = {"CGEL_STATE_DIR": self.state}
        self.write(".cgel/registry.json", json.dumps(REGISTRY))
        self.write("docs/standards/security.md", RULES_MD)
        self.write("src/app.py", "print('hello')\n")
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "i"],
            cwd=self.repo,
            check=True,
        )

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.state, ignore_errors=True)

    def cli(self, *args):
        return run_cli(list(args), cwd=self.repo, env=self.env)

    def write(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def seal(self, contract=CONTRACT_HIGH):
        self.write(".task/contract.json", json.dumps(contract))
        code, out, err = self.cli("summary")
        self.assertEqual(code, 0, err)
        digest = decision_line(out).split("digest=")[1].split()[0]
        code, out, err = self.cli("seal", contract["task"]["id"], "--digest", digest)
        self.assertEqual(code, 0, out + err)

    def findings(self, items, verifier="cgel-verifier"):
        self.write(
            ".task/findings.json",
            json.dumps({"verifier": verifier, "findings": items}),
        )

    def sealed_task(self):
        repos = os.listdir(self.state)
        task_id = CONTRACT_HIGH["task"]["id"]
        with open(os.path.join(self.state, repos[0], task_id, "sealed_task.json")) as fh:
            return json.load(fh)

    # -------------------------------------------------------------- rules

    def test_rules_parsed(self):
        code, out, err = self.cli("rules")
        self.assertEqual(code, 0)
        self.assertIn("RULES OK — 2 rule(s), 1 blocking", decision_line(out))
        self.assertIn("SEC-1 [BLOCKING]", err)
        self.assertIn("STYLE-1", err)

    # ----------------------------------------------------- frozen trigger

    def test_high_risk_freezes_semantic_requirement(self):
        self.seal()
        requirement = self.sealed_task()["semantic_verification"]
        self.assertTrue(requirement["required"])
        self.assertIn("risk.level=high", requirement["reasons"])
        self.assertEqual(requirement["blocking_rule_ids"], ["SEC-1"])

    def test_low_risk_not_required(self):
        contract = json.loads(json.dumps(CONTRACT_HIGH))
        contract["risk"] = {"level": "low"}
        self.seal(contract)
        self.assertFalse(self.sealed_task()["semantic_verification"]["required"])

    # ----------------------------------------------------------- recording

    def test_record_unknown_rule_denied(self):
        self.seal()
        self.findings([{"rule_id": "NOPE-9", "status": "fail"}])
        code, out, err = self.cli("semantic", "record")
        self.assertEqual(code, 1)
        self.assertIn("SEMANTIC DENIED", decision_line(out))
        self.assertIn("unknown rule_id", err)

    def test_record_blocking_finding_fails_loud(self):
        self.seal()
        self.findings(
            [
                {
                    "rule_id": "SEC-1",
                    "status": "fail",
                    "confidence": 0.9,
                    "evidence": [{"path": "src/app.py", "line": 1}],
                    "reason": "token printed to stdout",
                }
            ]
        )
        code, out, err = self.cli("semantic", "record")
        self.assertEqual(code, 1)
        self.assertIn("SEMANTIC FAIL", decision_line(out))
        self.assertIn("1 blocking", decision_line(out))
        self.assertIn("SEC-1", err)

    # ------------------------------------------------------------ PASS gate

    def test_pass_requires_semantic_when_frozen(self):
        self.seal()
        self.cli("verify", "ok-check")
        code, _, err = self.cli("close", "--as", "PASS")
        self.assertEqual(code, 1)
        self.assertIn("semantic verification required", err)
        self.assertIn("risk.level=high", err)

    def test_blocking_finding_blocks_pass(self):
        self.seal()
        self.findings([{"rule_id": "SEC-1", "status": "fail", "reason": "leak"}])
        self.cli("semantic", "record")
        self.cli("verify", "ok-check")
        code, _, err = self.cli("close", "--as", "PASS")
        self.assertEqual(code, 1)
        self.assertIn("blocking semantic finding", err)

    def test_semantic_pass_then_close_pass_exports_attestation(self):
        self.seal()
        self.findings(
            [
                {"rule_id": "SEC-1", "status": "pass", "confidence": 1.0},
                {"rule_id": "STYLE-1", "status": "fail", "reason": "non-blocking nit"},
            ]
        )
        code, out, _ = self.cli("semantic", "record")
        self.assertEqual(code, 0, out)  # non-blocking fail does not block
        self.cli("verify", "ok-check")
        code, out, err = self.cli("close", "--as", "PASS")
        self.assertEqual(code, 0, out + err)
        self.assertIn("attestation exported", err)
        repos = os.listdir(self.state)
        att_path = os.path.join(
            self.state, repos[0], "TASK-S1", "attestation", "attestation.json"
        )
        with open(att_path) as fh:
            attestation = json.load(fh)
        self.assertEqual(attestation["terminal_status"], "PASS")
        self.assertEqual(attestation["criteria"][0]["checks"][0]["status"], "pass")
        self.assertEqual(len(attestation["rule_findings"]), 2)
        raw = json.dumps(attestation)
        self.assertNotIn("all good", raw)  # sanitized: no raw command output
        self.assertTrue(attestation["evidence_chain_head"].startswith("sha256:"))

    def test_semantic_stale_after_workspace_change(self):
        self.seal()
        self.findings([{"rule_id": "SEC-1", "status": "pass"}])
        self.cli("semantic", "record")
        self.write("src/app.py", "print('changed after verifier ran')\n")
        self.cli("verify", "ok-check")  # evidence fresh, semantic stale
        code, _, err = self.cli("close", "--as", "PASS")
        self.assertEqual(code, 1)
        self.assertIn("semantic findings stale", err)

    def test_attest_on_demand(self):
        self.seal()
        code, out, _ = self.cli("attest")
        self.assertEqual(code, 0)
        self.assertIn("ATTEST OK", decision_line(out))

    # ------------------------------------------------------------- agents

    def test_verifier_agent_is_read_only(self):
        path = os.path.join(PLUGIN_ROOT, "agents", "verifier.md")
        with open(path) as fh:
            text = fh.read()
        match = re.search(r"^tools:\s*(.+)$", text, re.M)
        self.assertIsNotNone(match, "verifier.md must declare a tools: line")
        tools = {t.strip() for t in match.group(1).split(",")}
        self.assertEqual(tools, {"Read", "Grep", "Glob"})
        for forbidden in ("Write", "Edit", "NotebookEdit", "Bash"):
            self.assertNotIn(forbidden, tools)

    def test_explorer_agent_is_read_only(self):
        path = os.path.join(PLUGIN_ROOT, "agents", "explorer.md")
        with open(path) as fh:
            text = fh.read()
        match = re.search(r"^tools:\s*(.+)$", text, re.M)
        tools = {t.strip() for t in match.group(1).split(",")}
        self.assertEqual(tools, {"Read", "Grep", "Glob"})


if __name__ == "__main__":
    unittest.main()
