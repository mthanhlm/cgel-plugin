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

    BUILTIN_IDS = ["CGEL-COMMENT-1", "CGEL-DEBT-1", "CGEL-IMPACT-1", "CGEL-SECRET-1"]
    # The split is about ground truth, not importance: IMPACT-1 and SECRET-1
    # are checkable by searching, so a block is arguable. DEBT-1 and COMMENT-1
    # are judgements of taste, and blocking on taste at close — with an
    # ungated ESCALATE as the only exit — is how a lint gate earns itself an
    # off switch. They still run and still reach the human.
    BLOCKING_BUILTIN_IDS = ["CGEL-IMPACT-1", "CGEL-SECRET-1"]
    ADVISORY_BUILTIN_IDS = ["CGEL-COMMENT-1", "CGEL-DEBT-1"]

    def test_rules_parsed_with_builtins(self):
        code, out, err = self.cli("rules")
        self.assertEqual(code, 0)
        self.assertIn("RULES OK — 6 rule(s), 3 blocking", decision_line(out))
        self.assertIn("SEC-1 [BLOCKING]", err)
        self.assertIn("STYLE-1", err)
        self.assertIn("cgel-builtin", err)
        for rule_id in self.BLOCKING_BUILTIN_IDS:
            self.assertIn("%s [BLOCKING]" % rule_id, err)
        for rule_id in self.ADVISORY_BUILTIN_IDS:
            self.assertIn(rule_id, err)
            self.assertNotIn("%s [BLOCKING]" % rule_id, err)

    def test_builtin_rules_config_off(self):
        self.write(".cgel/config.json", '{"builtin_rules": "off"}')
        code, out, err = self.cli("rules")
        self.assertEqual(code, 0)
        self.assertIn("RULES OK — 2 rule(s), 1 blocking", decision_line(out))
        self.assertNotIn("CGEL-IMPACT-1", err)

    def test_project_rule_with_same_id_replaces_builtin(self):
        # Override a BLOCKING builtin, not an advisory one: overriding
        # CGEL-DEBT-1 with `Blocking: no` is now a no-op, so the test would
        # pass whether or not replacement worked. The host owns its yardstick
        # — that only means something if it can downgrade a rule that blocks.
        self.write(
            "docs/standards/overrides.md",
            "## CGEL-IMPACT-1 — our own impact policy\nBlocking: no\n",
        )
        code, out, err = self.cli("rules")
        self.assertEqual(code, 0)
        self.assertIn("RULES OK — 6 rule(s), 2 blocking", decision_line(out))
        self.assertIn("our own impact policy", err)
        self.assertNotIn("CGEL-IMPACT-1 [BLOCKING]", err)

    # ----------------------------------------------------- frozen trigger

    def test_high_risk_freezes_semantic_requirement(self):
        self.seal()
        requirement = self.sealed_task()["semantic_verification"]
        self.assertTrue(requirement["required"])
        self.assertIn("risk.level=high", requirement["reasons"])
        self.assertEqual(
            requirement["blocking_rule_ids"],
            self.BLOCKING_BUILTIN_IDS + ["SEC-1"],
        )
        for rule_id in self.ADVISORY_BUILTIN_IDS:
            self.assertNotIn(rule_id, requirement["blocking_rule_ids"])

    def test_medium_risk_requires_semantic_via_builtins(self):
        contract = json.loads(json.dumps(CONTRACT_HIGH))
        contract["risk"] = {"level": "medium", "reasons": ["fixture: medium claim"]}
        self.seal(contract)
        requirement = self.sealed_task()["semantic_verification"]
        self.assertTrue(requirement["required"])
        self.assertIn("blocking rules present at risk.level=medium",
                      requirement["reasons"])

    def test_low_risk_not_required(self):
        contract = json.loads(json.dumps(CONTRACT_HIGH))
        contract["risk"] = {"level": "low", "reasons": ["fixture: low claim, argued"]}
        self.seal(contract)
        self.assertFalse(self.sealed_task()["semantic_verification"]["required"])

    def test_record_accepts_builtin_rule_finding(self):
        self.seal()
        self.findings(
            [
                {
                    "rule_id": "CGEL-IMPACT-1",
                    "status": "fail",
                    "confidence": 0.9,
                    "evidence": [{"path": "src/app.py", "line": 1}],
                    "reason": "old call shape survives in src/app.py",
                }
            ]
        )
        code, out, _ = self.cli("semantic", "record")
        self.assertEqual(code, 1)
        self.assertIn("1 blocking", decision_line(out))

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
        code, _, err = self.cli("close", "--as", "PASS", "--reason", "fixture close")
        self.assertEqual(code, 1)
        self.assertIn("semantic verification required", err)
        self.assertIn("risk.level=high", err)

    def test_blocking_finding_blocks_pass(self):
        self.seal()
        self.findings([{"rule_id": "SEC-1", "status": "fail", "reason": "leak"}])
        self.cli("semantic", "record")
        self.cli("verify", "ok-check")
        code, _, err = self.cli("close", "--as", "PASS", "--reason", "fixture close")
        self.assertEqual(code, 1)
        self.assertIn("blocking semantic finding", err)

    def test_a_blocking_finding_cannot_be_erased_by_re_running_the_verifier(self):
        """The re-roll. The verifier is a model, so re-running it unchanged is
        a dice roll, and "run it until it agrees" is the cheapest way past the
        only judgement in the pipeline.

        This test exists because the README claimed this control before any
        code implemented it — the verifier caught the false row on this very
        task, which is exactly the defect the release exists to remove.
        """
        self.seal()
        self.findings([{"rule_id": "SEC-1", "status": "fail", "reason": "leak"}])
        self.cli("semantic", "record")
        self.cli("verify", "ok-check")
        code, _, err = self.cli("close", "--as", "PASS", "--reason", "done")
        self.assertEqual(code, 1)
        self.assertIn("blocking semantic finding", err)

        # Re-run the verifier, change nothing, get a clean answer.
        self.findings([{"rule_id": "SEC-1", "status": "pass", "reason": "looks fine now"}])
        self.cli("semantic", "record")
        self.cli("verify", "ok-check")
        code, _, err = self.cli("close", "--as", "PASS", "--reason", "done")
        self.assertEqual(code, 1, "a re-roll with no workspace change closed PASS")
        self.assertIn("no workspace change between the two verifier runs", err)

    def test_the_re_roll_guard_does_not_launder_itself_in_two_steps(self):
        # Anchored on the LAST BLOCKING run, not the previous record:
        # blocking -> clean -> clean would otherwise walk past it, because by
        # the third run the immediately prior record is already clean.
        self.seal()
        self.findings([{"rule_id": "SEC-1", "status": "fail", "reason": "leak"}])
        self.cli("semantic", "record")
        for _ in range(2):
            self.findings([{"rule_id": "SEC-1", "status": "pass", "reason": "fine"}])
            self.cli("semantic", "record")
        self.cli("verify", "ok-check")
        code, _, err = self.cli("close", "--as", "PASS", "--reason", "done")
        self.assertEqual(code, 1)
        self.assertIn("no workspace change between the two verifier runs", err)

    def test_a_real_fix_clears_a_blocking_finding(self):
        # The guard must not wedge the normal path: fix the code, re-run, pass.
        self.seal()
        self.findings([{"rule_id": "SEC-1", "status": "fail", "reason": "leak"}])
        self.cli("semantic", "record")
        with open(os.path.join(self.repo, "src", "app.py"), "a") as fh:
            fh.write("# the actual fix\n")  # the workspace really moved
        self.findings([{"rule_id": "SEC-1", "status": "pass", "reason": "fixed"}])
        self.cli("semantic", "record")
        self.cli("verify", "ok-check")
        code, out, err = self.cli("close", "--as", "PASS", "--reason", "fixed the leak")
        self.assertEqual(code, 0, err)
        self.assertIn("CLOSE OK", decision_line(out))

    def test_a_non_pass_close_reports_the_re_roll_without_refusing(self):
        """The guard gates PASS; ESCALATE stays reachable — the loop always
        comes to rest. But a non-PASS close REPORTS what PASS would have
        objected to, and a re-rolled finding is the single most useful thing
        such a record can carry.

        The guard was first written behind `elif not probe`, which suppressed
        only the report (a probe's blockers never gate the close), so an
        ESCALATE's attestation silently omitted the objection while
        pass_blockers is documented as "what CGEL could not have certified".
        """
        self.seal()
        self.findings([{"rule_id": "SEC-1", "status": "fail", "reason": "leak"}])
        self.cli("semantic", "record")
        self.findings([{"rule_id": "SEC-1", "status": "pass", "reason": "fine"}])
        self.cli("semantic", "record")
        code, out, err = self.cli(
            "close", "--as", "ESCALATE", "--reason", "the verifier and I disagree"
        )
        self.assertEqual(code, 0, err)
        self.assertIn("could not have certified", err)
        self.assertIn("no workspace change between the two verifier runs", err)

        store = os.path.join(self.state, os.listdir(self.state)[0], "TASK-S1")
        with open(os.path.join(store, "attestation", "attestation.json")) as fh:
            att = json.load(fh)
        self.assertTrue(
            any("verifier runs" in b for b in att["pass_blockers"]),
            "the attestation omitted the objection PASS would have raised",
        )

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
        code, out, err = self.cli("close", "--as", "PASS", "--reason", "fixture close")
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
        code, _, err = self.cli("close", "--as", "PASS", "--reason", "fixture close")
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

    def test_challenger_agent_is_read_only(self):
        path = os.path.join(PLUGIN_ROOT, "agents", "challenger.md")
        with open(path) as fh:
            text = fh.read()
        match = re.search(r"^tools:\s*(.+)$", text, re.M)
        self.assertIsNotNone(match, "challenger.md must declare a tools: line")
        tools = {t.strip() for t in match.group(1).split(",")}
        self.assertEqual(tools, {"Read", "Grep", "Glob"})

    def test_verifier_carries_builtin_duties(self):
        path = os.path.join(PLUGIN_ROOT, "agents", "verifier.md")
        with open(path) as fh:
            text = fh.read()
        for rule_id in ("CGEL-IMPACT-1", "CGEL-DEBT-1", "CGEL-COMMENT-1",
                        "CGEL-SECRET-1"):
            self.assertIn(rule_id, text)


if __name__ == "__main__":
    unittest.main()
