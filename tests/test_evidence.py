"""Phase 1 — evidence pipeline: verify, audit, hash chain, seal binding,
governance bundle freeze, evidence-gated PASS."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

from hookrunner import run_cli, run_hook, decision_line

CONTRACT = {
    "task": {"id": "TASK-E1", "type": "feature", "goal": "Evidence pipeline demo"},
    "acceptance_criteria": [
        {
            "id": "AC-1",
            "description": "check passes",
            "required_checks": ["ok-check"],
        }
    ],
    "scope": {"allowed": ["src/**"]},
    "risk": {"level": "low", "reasons": ["fixture: exercises the evidence pipeline"]},
}

REGISTRY = {
    "checks": {
        "ok-check": {"command": "echo all good"},
        "fail-check": {
            "command": "sh -c 'echo FAILED: assertion broke; exit 1'",
            "kind": "test",
        },
        # A real linter emitting cp1252 on a UTF-8 locale. Before the bytes
        # capture this raised UnicodeDecodeError out of _run_check, past every
        # handler, before chain_append — no evidence, no decision line, and
        # nothing recording that a record was missing.
        "non-utf8-check": {
            "command": (
                "python3 -c \"import sys; "
                "sys.stdout.buffer.write(b'FAILED: caf\\xe9 \\xff\\xfe broke\\n'); "
                'sys.exit(1)"'
            ),
            "kind": "test",
        },
        "slow-check": {
            "command": "sh -c 'echo starting up; sleep 30'",
            "timeout_seconds": 1,
            "kind": "test",
        },
        "loud-check": {
            "command": (
                "python3 -c \"import sys; "
                "sys.stdout.write('x' * 4000000); sys.exit(1)\""
            ),
            "kind": "test",
        },
    }
}


class EvidenceTestCase(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="cgel-repo-")
        self.state = tempfile.mkdtemp(prefix="cgel-state-")
        os.makedirs(os.path.join(self.repo, ".cgel"))
        os.makedirs(os.path.join(self.repo, ".task"))
        os.makedirs(os.path.join(self.repo, "src"))
        self.env = {"CGEL_STATE_DIR": self.state}
        self.write_json(".cgel/registry.json", REGISTRY)
        with open(os.path.join(self.repo, "src", "app.py"), "w") as fh:
            fh.write("print('hello')\n")
        self.git("init", "-q")
        self.git("add", "-A")
        self.git(
            "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"
        )

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.state, ignore_errors=True)

    def git(self, *args):
        subprocess.run(
            ["git"] + list(args), cwd=self.repo, check=True, capture_output=True
        )

    def cli(self, *args):
        return run_cli(list(args), cwd=self.repo, env=self.env)

    def write_json(self, rel, obj):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=1)

    def seal(self, contract=CONTRACT):
        self.write_json(".task/contract.json", contract)
        code, out, err = self.cli("summary")
        self.assertEqual(code, 0, err)
        digest = decision_line(out).split("digest=")[1].split()[0]
        code, out, err = self.cli("seal", contract["task"]["id"], "--digest", digest)
        self.assertEqual(code, 0, out + err)
        return digest

    def task_store(self):
        repos = os.listdir(self.state)
        self.assertEqual(len(repos), 1)
        return os.path.join(self.state, repos[0], "TASK-E1")

    # ------------------------------------------------------------ verify

    def test_seal_binds_governance_bundle(self):
        self.seal()
        with open(os.path.join(self.task_store(), "sealed_task.json")) as fh:
            sealed = json.load(fh)
        bundle = sealed["governance_bundle"]
        self.assertTrue(bundle["digest"].startswith("sha256:"))
        paths = [m["path"] for m in bundle["members"]]
        self.assertIn(".cgel/registry.json", paths)
        self.assertTrue(sealed["workspace"]["base_revision"] != "no-git")

    def records(self):
        with open(os.path.join(self.task_store(), "evidence.jsonl")) as fh:
            return [json.loads(l) for l in fh if l.strip()]

    # ---------------------------------------- the runner is total (must-fix #4)
    #
    # The property under test is not "these four inputs are handled". It is
    # that _run_check ALWAYS reaches chain_append: a verification that leaves
    # no record is the one failure this pipeline cannot detect afterwards,
    # because there is no record saying a record is missing.

    def test_non_utf8_check_output_still_records_evidence(self):
        self.seal()
        code, out, err = self.cli("verify", "non-utf8-check")
        self.assertEqual(code, 1, out + err)
        self.assertIn("VERIFY FAIL check=non-utf8-check", decision_line(out))
        self.assertIn("evidence=sha256:", decision_line(out))
        self.assertNotIn("Traceback", err)
        self.assertEqual(len(self.records()), 1)
        code, out, err = self.cli("audit")
        self.assertEqual(code, 0, out + err)
        self.assertIn("chain=intact", decision_line(out))

    def test_undecodable_output_is_replacement_decoded_and_json_safe(self):
        # errors="replace", never surrogateescape: a lone surrogate would make
        # canonical_json raise at chain_append and lose the record we just
        # fought to keep.
        self.seal()
        self.cli("verify", "non-utf8-check")
        rec = self.records()[0]
        self.assertIn("�", rec["output"]["summary"])
        json.dumps(rec)  # must not raise

    def test_timeout_records_the_partial_output_not_a_bytes_repr(self):
        self.seal()
        code, out, err = self.cli("verify", "slow-check")
        self.assertEqual(code, 1, out + err)
        rec = self.records()[0]
        self.assertEqual(rec["result"]["failure_kind"], "timeout")
        self.assertIsNone(rec["result"]["exit_code"])
        summary = rec["output"]["summary"]
        self.assertIn("starting up", summary)
        self.assertIn("[timeout after 1s]", summary)
        # TimeoutExpired.stdout is bytes; formatting it into a %s used to
        # stringify a bytes repr into the record.
        self.assertNotIn("b'", summary)

    def test_oversized_output_is_capped_and_says_so(self):
        # bytes is what the check PRODUCED; the summary is what was RETAINED.
        # Recording only the retained size would silently redefine the field.
        self.seal()
        code, out, err = self.cli("verify", "loud-check")
        self.assertEqual(code, 1, out + err)
        rec = self.records()[0]
        self.assertEqual(rec["output"]["bytes"], 4000000)
        self.assertTrue(rec["output"]["truncated"])
        self.assertLess(len(rec["output"]["summary"]), 2000)
        self.assertTrue(rec["chain"]["hash"].startswith("sha256:"))

    def test_harness_error_records_evidence_rather_than_vanishing(self):
        # A registry the runner cannot use at all. Sealed with the bad value in
        # place, so the bundle matches and we reach _run_check.
        registry = json.loads(json.dumps(REGISTRY))
        registry["checks"]["ok-check"]["timeout_seconds"] = "abc"
        self.write_json(".cgel/registry.json", registry)
        self.seal()
        code, out, err = self.cli("verify", "ok-check")
        self.assertEqual(code, 1, out + err)
        self.assertIn("VERIFY FAIL check=ok-check", decision_line(out))
        self.assertNotIn("Traceback", err)
        rec = self.records()[0]
        self.assertEqual(rec["result"]["status"], "fail")
        self.assertEqual(rec["result"]["failure_kind"], "harness_error")
        # A broken runner is not the project's regression: it must not be
        # fingerprinted, or the default-same guard reads it as one.
        self.assertIsNone(rec["result"]["diagnostic_fingerprint"])

    def test_verify_pass_records_bound_evidence(self):
        self.seal()
        code, out, err = self.cli("verify", "ok-check")
        self.assertEqual(code, 0, out + err)
        self.assertIn("VERIFY PASS check=ok-check", decision_line(out))
        with open(os.path.join(self.task_store(), "evidence.jsonl")) as fh:
            records = [json.loads(l) for l in fh if l.strip()]
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["result"]["status"], "pass")
        self.assertTrue(rec["contract_digest"].startswith("sha256:"))
        self.assertTrue(rec["governance_digest"].startswith("sha256:"))
        self.assertTrue(rec["chain"]["prev"].startswith("genesis:"))

    def test_verify_fail_records_failure_signature(self):
        self.seal()
        code, out, err = self.cli("verify", "fail-check")
        self.assertEqual(code, 1)
        self.assertIn("VERIFY FAIL check=fail-check", decision_line(out))
        with open(os.path.join(self.task_store(), "evidence.jsonl")) as fh:
            rec = json.loads(fh.readline())
        self.assertEqual(rec["result"]["status"], "fail")
        self.assertEqual(rec["result"]["failure_kind"], "test_assertion")
        self.assertIn("FAILED", rec["result"]["failure_subject"])
        self.assertTrue(rec["result"]["diagnostic_fingerprint"])

    def test_verify_unknown_check_denied(self):
        self.seal()
        code, out, err = self.cli("verify", "no-such-check")
        self.assertEqual(code, 1)
        self.assertIn("unknown check", decision_line(out))
        self.assertIn("ok-check", err)

    def test_registry_change_after_seal_blocks_task(self):
        self.seal()
        registry = dict(REGISTRY)
        registry["checks"] = dict(registry["checks"])
        registry["checks"]["ok-check"] = {"command": "echo tests passed"}
        self.write_json(".cgel/registry.json", registry)
        code, out, err = self.cli("verify", "ok-check")
        self.assertEqual(code, 1)
        self.assertIn("VERIFY BLOCKED", decision_line(out))
        self.assertIn("bundle changed: .cgel/registry.json", err)
        _, out, _ = self.cli("status")
        self.assertIn("STATUS BLOCKED", decision_line(out))
        # BLOCKED closes the edit gate too
        code, _, gate_err = run_hook(
            "contract_gate.py",
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": os.path.join(self.repo, "src/app.py")},
                "cwd": self.repo,
            },
            env=self.env,
        )
        self.assertEqual(code, 2, gate_err)

    def test_reseal_recovers_from_bundle_block(self):
        digest = self.seal()
        self.write_json(".cgel/registry.json", REGISTRY | {"note": "v2"})
        self.cli("verify", "ok-check")  # -> BLOCKED
        code, out, _ = self.cli("seal", "TASK-E1", "--digest", digest)
        self.assertEqual(code, 0, out)
        self.assertIn("(reseal)", decision_line(out))
        code, out, err = self.cli("verify", "ok-check")
        self.assertEqual(code, 0, out + err)

    # ------------------------------------------------------------- audit

    def test_audit_ok_after_verify(self):
        self.seal()
        self.cli("verify", "ok-check")
        code, out, _ = self.cli("audit")
        self.assertEqual(code, 0)
        self.assertIn("AUDIT OK", decision_line(out))
        self.assertIn("evidence=1", decision_line(out))

    def test_tampered_evidence_detected_by_audit(self):
        self.seal()
        self.cli("verify", "fail-check")
        path = os.path.join(self.task_store(), "evidence.jsonl")
        with open(path) as fh:
            rec = json.loads(fh.readline())
        rec["result"]["status"] = "pass"  # forge the verdict
        with open(path, "w") as fh:
            fh.write(json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n")
        code, out, _ = self.cli("audit")
        self.assertEqual(code, 1)
        self.assertIn("AUDIT FAIL", decision_line(out))
        self.assertIn("does not match hash", decision_line(out))

    # -------------------------------------------------------------- PASS

    def test_close_pass_denied_without_evidence(self):
        self.seal()
        code, out, err = self.cli("close", "--as", "PASS")
        self.assertEqual(code, 1)
        self.assertIn("CLOSE DENIED", decision_line(out))
        self.assertIn("AC-1/ok-check: no evidence", err)

    def test_close_pass_happy_path(self):
        self.seal()
        self.cli("verify", "ok-check")
        code, out, err = self.cli("close", "--as", "PASS")
        self.assertEqual(code, 0, out + err)
        self.assertIn("CLOSE OK — TASK-E1 -> PASS", decision_line(out))
        with open(os.path.join(self.task_store(), "state.json")) as fh:
            state = json.load(fh)
        self.assertEqual(state["terminal_status"], "PASS")
        self.assertTrue(state["evidence_chain_head"].startswith("sha256:"))

    def test_close_pass_denied_when_latest_evidence_fails(self):
        contract = json.loads(json.dumps(CONTRACT))
        contract["acceptance_criteria"][0]["required_checks"] = ["fail-check"]
        self.seal(contract)
        self.cli("verify", "fail-check")
        code, _, err = self.cli("close", "--as", "PASS")
        self.assertEqual(code, 1)
        self.assertIn("latest evidence is FAIL", err)

    def test_close_pass_denied_after_workspace_change(self):
        self.seal()
        self.cli("verify", "ok-check")
        with open(os.path.join(self.repo, "src", "app.py"), "a") as fh:
            fh.write("# drift after evidence\n")
        code, _, err = self.cli("close", "--as", "PASS")
        self.assertEqual(code, 1)
        self.assertIn("workspace changed", err)

    def test_close_pass_denied_when_ac_has_no_checks(self):
        contract = json.loads(json.dumps(CONTRACT))
        contract["acceptance_criteria"].append(
            {"id": "AC-2", "description": "manual look", "required_checks": []}
        )
        self.seal(contract)
        self.cli("verify", "ok-check")
        code, _, err = self.cli("close", "--as", "PASS")
        self.assertEqual(code, 1)
        self.assertIn("AC-2: no required_checks", err)

    def test_echo_tests_passed_is_worthless(self):
        """The Phase 1 goal literally: self-report does not create evidence."""
        self.seal()
        subprocess.run(
            ["sh", "-c", "echo tests passed"], cwd=self.repo, capture_output=True
        )
        code, _, err = self.cli("close", "--as", "PASS")
        self.assertEqual(code, 1)
        self.assertIn("no evidence", err)

    # ----------------------------------------------------------- recorder

    def edit_payload(self, rel):
        return {
            "hook_event_name": "PostToolUse",
            "tool_name": "Edit",
            "tool_input": {"file_path": os.path.join(self.repo, rel)},
            "cwd": self.repo,
        }

    def test_recorder_edit_marks_evidence_stale(self):
        self.seal()
        self.cli("verify", "ok-check")
        code, _, err = run_hook(
            "evidence_recorder.py", self.edit_payload("src/app.py"), env=self.env
        )
        self.assertEqual(code, 0, err)
        events_path = os.path.join(self.task_store(), "events.jsonl")
        with open(events_path) as fh:
            events = [json.loads(l) for l in fh if l.strip()]
        self.assertEqual(events[0]["type"], "edit")
        self.assertEqual(events[0]["path"], "src/app.py")
        code, _, err = self.cli("close", "--as", "PASS")
        self.assertEqual(code, 1)
        self.assertIn("edits recorded after", err)

    def test_recorder_ignores_task_mirror_and_records_cgel_bash(self):
        self.seal()
        code, _, _ = run_hook(
            "evidence_recorder.py", self.edit_payload(".task/notes.md"), env=self.env
        )
        self.assertEqual(code, 0)
        bash_payload = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "cgel verify ok-check"},
            "tool_response": {"exit_code": 0},
            "cwd": self.repo,
        }
        run_hook("evidence_recorder.py", bash_payload, env=self.env)
        with open(os.path.join(self.task_store(), "events.jsonl")) as fh:
            events = [json.loads(l) for l in fh if l.strip()]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "bash")
        self.assertEqual(events[0]["exit_code"], 0)

    def test_recorder_never_blocks_on_garbage(self):
        code, _, _ = run_hook(
            "evidence_recorder.py", None, env=self.env, raw_stdin="{not json"
        )
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
