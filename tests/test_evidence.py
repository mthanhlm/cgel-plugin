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


class EvidenceFixture(unittest.TestCase):
    """Fixture only — no tests, so subclasses do not re-run each other's."""

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


class EvidenceTestCase(EvidenceFixture):
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
        code, out, err = self.cli("close", "--as", "PASS", "--reason", "fixture close")
        self.assertEqual(code, 1)
        self.assertIn("CLOSE DENIED", decision_line(out))
        self.assertIn("AC-1/ok-check: no evidence", err)

    def test_close_pass_happy_path(self):
        self.seal()
        self.cli("verify", "ok-check")
        code, out, err = self.cli("close", "--as", "PASS", "--reason", "fixture close")
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
        code, _, err = self.cli("close", "--as", "PASS", "--reason", "fixture close")
        self.assertEqual(code, 1)
        self.assertIn("latest evidence is FAIL", err)

    def test_close_pass_denied_after_workspace_change(self):
        self.seal()
        self.cli("verify", "ok-check")
        with open(os.path.join(self.repo, "src", "app.py"), "a") as fh:
            fh.write("# drift after evidence\n")
        code, _, err = self.cli("close", "--as", "PASS", "--reason", "fixture close")
        self.assertEqual(code, 1)
        self.assertIn("workspace changed", err)

    def test_close_pass_denied_when_ac_has_no_checks(self):
        contract = json.loads(json.dumps(CONTRACT))
        contract["acceptance_criteria"].append(
            {"id": "AC-2", "description": "manual look", "required_checks": []}
        )
        self.seal(contract)
        self.cli("verify", "ok-check")
        code, _, err = self.cli("close", "--as", "PASS", "--reason", "fixture close")
        self.assertEqual(code, 1)
        self.assertIn("AC-2: no required_checks", err)

    def test_echo_tests_passed_is_worthless(self):
        """The Phase 1 goal literally: self-report does not create evidence."""
        self.seal()
        subprocess.run(
            ["sh", "-c", "echo tests passed"], cwd=self.repo, capture_output=True
        )
        code, _, err = self.cli("close", "--as", "PASS", "--reason", "fixture close")
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
        code, _, err = self.cli("close", "--as", "PASS", "--reason", "fixture close")
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


class CloseSymmetryTestCase(EvidenceFixture):
    """Phase D — every terminal status is a record, not just PASS.

    PASS was validated, attested and chained. ESCALATE and ABORT were a
    lifecycle flip and a decision line: no reason required, no attestation,
    no record of what was left undone. The status a task reaches when
    something went WRONG is the one whose record matters most, and it was the
    one with no record at all.
    """

    @property
    def C(self):
        import sys

        from hookrunner import SCRIPTS_DIR

        sys.path.insert(0, SCRIPTS_DIR)
        import cgel_common

        return cgel_common

    def close(self, status, reason="a fixture reason"):
        return self.cli("close", "--as", status, "--reason", reason)

    def test_every_terminal_status_needs_a_reason(self):
        self.seal()
        self.cli("verify", "ok-check")
        for status in ("PASS", "ESCALATE", "ABORT"):
            code, out, err = self.cli("close", "--as", status)
            self.assertEqual(code, 1, status)
            self.assertIn("--reason must not be empty", decision_line(out), status)
        # ...and whitespace is not a reason
        code, out, _ = self.cli("close", "--as", "ABORT", "--reason", "   ")
        self.assertEqual(code, 1)
        self.assertIn("--reason must not be empty", decision_line(out))

    def test_every_terminal_status_exports_an_attestation(self):
        for status in ("ESCALATE", "ABORT"):
            with self.subTest(status=status):
                self.setUp()
                self.seal()
                code, out, err = self.close(status, "stopped early")
                self.assertEqual(code, 0, out + err)
                path = os.path.join(self.task_store(), "attestation", "attestation.json")
                self.assertTrue(os.path.isfile(path), status)
                with open(path) as fh:
                    att = json.load(fh)
                self.assertEqual(att["terminal_status"], status)
                self.assertEqual(att["terminal_reason"], "stopped early")
                self.assertIsInstance(att["pass_blockers"], list)
                self.assertIn("user_sentence", att)

    def test_a_non_pass_close_says_what_could_not_be_certified(self):
        self.seal()  # no evidence at all
        code, out, err = self.close("ESCALATE", "needs a human decision")
        self.assertEqual(code, 0, out + err)
        self.assertIn("could not have certified", err)
        self.assertIn("no evidence", err)

    def test_a_non_pass_close_is_never_refused(self):
        # The loop must always be able to come to rest. A close that cannot
        # certify is the NORMAL exit for a task that went wrong.
        self.seal()
        code, out, _ = self.close("ABORT", "wrong approach entirely")
        self.assertEqual(code, 0)
        self.assertIn("CLOSE OK", decision_line(out))

    def test_a_non_pass_close_does_not_block_the_task_on_its_way_out(self):
        # The PASS validator BLOCKS the task when the governance bundle
        # moved. A non-PASS close only probes it, so the probe must not have
        # that side effect: `close --as ABORT` would mark the task blocked
        # while closing it.
        self.seal()
        with open(os.path.join(self.repo, ".cgel", "registry.json"), "a") as fh:
            fh.write("\n")  # move the sealed governance bundle
        code, out, err = self.close("ABORT", "abandoning after a bundle change")
        self.assertEqual(code, 0, out + err)
        with open(os.path.join(self.task_store(), "state.json")) as fh:
            state = json.load(fh)
        self.assertEqual(state["lifecycle"], "TERMINAL")
        self.assertEqual(state["terminal_status"], "ABORT")
        self.assertNotEqual(state.get("blocked_reason"), "sealed-guidebook-bundle-changed")

    def test_the_close_record_joins_the_chain_and_the_attestation_covers_it(self):
        self.seal()
        self.cli("verify", "ok-check")
        code, out, err = self.close("PASS", "all criteria have fresh evidence")
        self.assertEqual(code, 0, out + err)
        events = [
            json.loads(l)
            for l in open(os.path.join(self.task_store(), "events.jsonl"))
            if l.strip()
        ]
        closes = [e for e in events if e.get("type") == "close"]
        self.assertEqual(len(closes), 1)
        self.assertEqual(closes[0]["terminal_status"], "PASS")
        self.assertEqual(closes[0]["reason"], "all criteria have fresh evidence")
        self.assertIn("user_sentence", closes[0])
        # The record is chained: it carries the previous record's hash.
        self.assertIn("prev", closes[0]["chain"])
        # ...and the attestation's events head COVERS it, which is the whole
        # reason the record is appended before the head is read.
        with open(os.path.join(self.task_store(), "attestation", "attestation.json")) as fh:
            att = json.load(fh)
        self.assertEqual(att["events_chain_head"], closes[0]["chain"]["hash"])
        # NOTE: `cgel audit` cannot check this — it resolves only OPEN tasks,
        # so a closed task cannot be audited at all. That predates this change
        # (audit is DENIED after close on the shipped tree too) and is not in
        # this task's acceptance criteria; recorded rather than widened here.

    def test_the_close_record_is_inert_to_the_edit_counters(self):
        """Every EVENTS_FILE reader filters on type. If one did not, the close
        record would read as an edit and mark evidence stale.

        Written first as "close --as PASS exits 0" — which proves nothing:
        _pass_problems runs BEFORE the close record is appended, so the record
        does not exist when that assertion is evaluated, and the test passed
        whether or not any reader filtered on type. The counters have to be
        asked directly, after the record exists.
        """
        self.seal()
        self.cli("verify", "ok-check")
        tdir = self.task_store()
        before_count = self.C.count_edit_events(tdir)
        before_paths = self.C.edit_event_paths(tdir)

        code, out, err = self.close("PASS", "done")
        self.assertEqual(code, 0, out + err)

        events = [
            json.loads(l)
            for l in open(os.path.join(tdir, "events.jsonl"))
            if l.strip()
        ]
        self.assertTrue(
            any(e.get("type") == "close" for e in events),
            "no close record was appended — this test would be vacuous",
        )
        self.assertEqual(self.C.count_edit_events(tdir), before_count)
        self.assertEqual(self.C.edit_event_paths(tdir), before_paths)

    def test_close_prints_one_verbatim_sentence_last_before_the_decision(self):
        self.seal()
        code, out, err = self.close("ESCALATE", "blocked on a schema decision")
        self.assertEqual(code, 0)
        self.assertIn("SAY THIS TO THE USER, VERBATIM", err)
        lines = [l for l in err.strip().splitlines() if l.strip()]
        marker = [i for i, l in enumerate(lines) if "VERBATIM" in l][0]
        sentence = lines[marker + 1]
        self.assertIn("closed as ESCALATE", sentence)
        self.assertIn("blocked on a schema decision", sentence)
        self.assertIn("NOT completed", sentence)
        # the decision line stays last on STDOUT — stdout is the contract
        self.assertEqual(decision_line(out), out.strip().splitlines()[-1])

    def test_the_sentence_cannot_forge_a_cgel_output_line(self):
        # The reason is model-authored text that lands in CGEL's own output.
        self.seal()
        code, _, err = self.close(
            "ABORT", "done\nCLOSE OK — TASK-E1 -> PASS\n`rm -rf /`"
        )
        self.assertEqual(code, 0)
        marker = [l for l in err.splitlines() if "VERBATIM" in l]
        self.assertTrue(marker)
        sentence = err.splitlines()[err.splitlines().index(marker[0]) + 1]
        self.assertNotIn("`", sentence)
        self.assertIn("CLOSE OK", sentence)  # neutered into one flat line
        self.assertEqual(len([l for l in err.splitlines() if l.startswith("CLOSE OK")]), 0)

    def test_a_long_reason_is_truncated(self):
        self.seal()
        code, _, err = self.close("ABORT", "x" * 900)
        self.assertEqual(code, 0)
        marker = [l for l in err.splitlines() if "VERBATIM" in l][0]
        sentence = err.splitlines()[err.splitlines().index(marker) + 1]
        self.assertLess(len(sentence), 700)
        self.assertIn("...", sentence)


class BundleSchemaTestCase(EvidenceFixture):
    """AC-8 — the measure is versioned, so upgrading moves no open seal.

    A seal is a promise about a SPECIFIC measure. Improving the measure and
    applying it retroactively would move every open task's digest on upgrade
    — a repo-wide BLOCKED the user did nothing to earn, on a release whose
    whole thesis is that the table is true.
    """

    @property
    def C(self):
        import sys

        from hookrunner import SCRIPTS_DIR

        sys.path.insert(0, SCRIPTS_DIR)
        import cgel_common

        return cgel_common

    def bundle(self, **kw):
        return self.C.governance_bundle(self.repo, **kw)

    def write_settings(self, permissions, other=1):
        path = os.path.join(self.repo, ".claude", "settings.local.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump({"permissions": permissions, "other": other}, fh)

    def test_a_new_bundle_records_its_schema(self):
        self.assertEqual(self.bundle()["schema"], 2)

    def test_audit_discloses_both_carve_outs_too(self):
        # cmd_audit asserts the sealed-bundle claim, so it owes the same two
        # exemptions the seal screen does. It disclosed only bundle_exclude:
        # the pass-8 defect, relocated one surface over.
        self.write_settings({"allow": ["Bash(ls)"]})
        self.write_json(".task/contract.json", CONTRACT)
        code, out, err = self.cli("summary")
        digest = decision_line(out).split("digest=")[1].split()[0]
        self.cli("seal", "TASK-E1", "--digest", digest)
        self.cli("verify", "ok-check")
        code, out, err = self.cli("audit")
        self.assertEqual(code, 0, err)
        self.assertIn("not measured by design", err)
        self.assertIn(".claude/settings.local.json", err)

    def test_a_truncated_exclusion_list_says_it_is_truncated(self):
        # A count of N printed over a list of 5 with no tell drops the
        # remainder silently — a disclosure that hides part of what it
        # discloses is not one. Exercised through the real surface: bin/cgel
        # has no .py suffix and is not importable, and the CLI's output is
        # the thing being claimed anyway.
        skills = os.path.join(self.repo, ".claude", "skills")
        os.makedirs(skills)
        for i in range(9):
            with open(os.path.join(skills, "s%d.md" % i), "w") as fh:
                fh.write("# skill %d\n" % i)
        with open(os.path.join(self.repo, ".cgel", "config.json"), "w") as fh:
            json.dump({"bundle_exclude": [".claude/skills/**"]}, fh)
        self.write_json(".task/contract.json", CONTRACT)
        code, out, err = self.cli("summary")
        digest = decision_line(out).split("digest=")[1].split()[0]
        code, out, err = self.cli("seal", "TASK-E1", "--digest", digest)
        self.assertEqual(code, 0, out + err)
        self.assertIn("9 governance file(s) are EXCLUDED", err)
        self.assertIn("(+4 more)", err)

    def test_seal_discloses_the_projection_where_it_makes_the_claim(self):
        """The seal screen says "changing one moves the task to BLOCKED" over
        the member count — and settings.local.json IS a member, projected
        rather than excluded, so its most frequent change moves nothing.

        The README row was qualified first and this line was not, which is
        the same claim standing unqualified at the one screen the user reads
        while deciding. The sibling carve-out (bundle_exclude) was already
        disclosed here, and a screen that names one of two exemptions reads
        as if there were one.
        """
        self.write_settings({"allow": ["Bash(ls)"]})
        self.write_json(".task/contract.json", CONTRACT)
        code, out, err = self.cli("summary")
        self.assertEqual(code, 0, err)
        digest = decision_line(out).split("digest=")[1].split()[0]
        code, out, err = self.cli("seal", "TASK-E1", "--digest", digest)
        self.assertEqual(code, 0, out + err)
        self.assertNotIn("Changing any of them", err)
        self.assertIn("not measured, by design", err)
        self.assertIn(".claude/settings.local.json", err)
        self.assertIn("permissions", err)

    def test_schema_1_is_unchanged_by_the_v2_projection(self):
        # The upgrade-safety property. If this drifts, every 0.12.0 seal in
        # the world goes BLOCKED on upgrade.
        self.write_settings({"allow": ["Bash(ls)"]})
        before = self.bundle(schema=1)["digest"]
        self.write_settings({"allow": ["Bash(ls)", "Bash(git status)"]})
        after = self.bundle(schema=1)["digest"]
        self.assertNotEqual(before, after)  # v1 measured permissions; it still does

    def test_schema_2_does_not_measure_the_permissions_the_user_edits(self):
        # The harness rewrites `permissions` every time the user approves a
        # tool, so measuring it meant the user's own approval BLOCKED every
        # open task — which teaches them the block is noise.
        self.write_settings({"allow": ["Bash(ls)"]})
        before = self.bundle()["digest"]
        self.write_settings({"allow": ["Bash(ls)", "Bash(git status)"]})
        self.assertEqual(self.bundle()["digest"], before)

    def test_schema_2_still_measures_the_rest_of_that_file(self):
        self.write_settings({"allow": []}, other=1)
        before = self.bundle()["digest"]
        self.write_settings({"allow": []}, other=2)
        self.assertNotEqual(self.bundle()["digest"], before)

    def test_a_malformed_member_is_measured_whole_not_skipped(self):
        path = os.path.join(self.repo, ".claude", "settings.local.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write("{not json")
        before = self.bundle()["digest"]
        with open(path, "w") as fh:
            fh.write("{still not json")
        self.assertNotEqual(self.bundle()["digest"], before)

    @unittest.skipIf(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        "root reads through mode 000, so the unreadable case cannot be staged",
    )
    def test_an_unreadable_member_is_recorded_not_dropped(self):
        """sha256_file returns None for a member it cannot read, and dropping
        it REMOVED it from the measure: chmod 000 on a governance file took
        that file out of the bundle without moving the digest.

        Written first with the assertion behind `if members.get(...) is not
        None`, which is False in exactly the buggy case — the test passed
        whether or not the fix existed. A guard that cannot fail is not a
        guard, so this now stages the condition and asserts unconditionally,
        and skips outright where the condition cannot be staged rather than
        pretending to cover it.
        """
        path = os.path.join(self.repo, ".cgel", "registry.json")
        os.chmod(path, 0o000)
        try:
            with open(path):  # if this succeeds the premise does not hold
                self.skipTest("this filesystem ignores mode 000")
        except PermissionError:
            pass
        try:
            members = {m["path"]: m["digest"] for m in self.bundle()["members"]}
            self.assertIn(".cgel/registry.json", members)
            self.assertEqual(members[".cgel/registry.json"], "unreadable")
        finally:
            os.chmod(path, 0o644)

    def test_an_open_v1_seal_is_not_blocked_by_the_upgrade(self):
        # End to end: seal (recording schema 2 today), then rewrite the state
        # to look like a pre-0.13 seal with no schema, and confirm the task
        # stays healthy rather than BLOCKED.
        self.write_settings({"allow": ["Bash(ls)"]})
        self.seal()
        sealed_path = os.path.join(self.task_store(), "sealed_task.json")
        with open(sealed_path) as fh:
            sealed = json.load(fh)
        v1 = self.bundle(schema=1)
        sealed["governance_bundle"] = {"digest": v1["digest"], "members": v1["members"]}
        with open(sealed_path, "w") as fh:
            json.dump(sealed, fh)
        code, out, err = self.cli("verify", "ok-check")
        self.assertEqual(code, 0, out + err)
        code, out, _ = self.cli("status")
        self.assertNotIn("BLOCKED", decision_line(out))

    def test_a_same_size_edit_inside_one_mtime_tick_still_moves_the_digest(self):
        """The bundle cache lied, and the seal believed it.

        Found by dogfooding, and present in the SHIPPED tree: filesystem
        timestamp granularity is coarser than a write, so two same-size
        rewrites inside one tick are indistinguishable by stat — identical
        mtime AND ctime AND size AND inode. The (mtime, size) cache then
        served the OLD digest for a governance file that had changed, the
        bundle did not move, and the task was not blocked. The sealed
        measure went stale in silence, which is the one thing the governance
        freeze exists to prevent.

        Both schemas: this is not a change to WHAT is measured (so it does
        not belong to the v2 projection), it is a fix to the cache lying
        about it, and v1's cache lies the same way.
        """
        registry = os.path.join(self.repo, ".cgel", "registry.json")
        for schema in (1, 2):
            with self.subTest(schema=schema):
                with open(registry, "w") as fh:
                    json.dump({"checks": {"ok-check": {"command": "pytest -q"}}}, fh)
                before = self.bundle(schema=schema)["digest"]
                # Same byte length, different meaning: the check now runs a
                # different command, so the measure genuinely moved.
                with open(registry, "w") as fh:
                    json.dump({"checks": {"ok-check": {"command": "pytest -x"}}}, fh)
                self.assertNotEqual(self.bundle(schema=schema)["digest"], before)

    def test_the_cache_still_serves_a_settled_file(self):
        """The settle window must not defeat the cache it guards: the cost is
        bounded to files written seconds ago.

        Written first as `first["digest"] == second["digest"]` on an unmoved
        file — which is true whether the digest was cached or rehashed, and
        passed with the cache disabled entirely. A digest is a pure function
        of content, so equality observes nothing.

        The second attempt tried to observe a HIT by changing the content
        while restoring the stat key with os.utime — but utime cannot restore
        ctime, and schema 2's key includes it, so the cache correctly missed
        and the test failed for a reason that was not the bug. Both attempts
        were the same mistake: asserting on a VALUE rather than on the
        mechanism.

        So count the hashing. A cache hit is precisely "sha256_file was not
        called for this member", and nothing else is.
        """
        import time

        path = os.path.join(self.repo, ".cgel", "registry.json")
        settled = time.time() - 3600
        os.utime(path, (settled, settled))
        self.bundle()  # populate the cache under this stat key

        hashed = []
        real = self.C.sha256_file
        self.C.sha256_file = lambda p: (hashed.append(p), real(p))[1]
        try:
            self.bundle()
        finally:
            self.C.sha256_file = real
        self.assertNotIn(
            path, hashed,
            "a settled, unmodified file was rehashed — the settle window has "
            "swallowed the cache it was meant to guard",
        )

    def test_a_bundle_change_names_what_moved_and_offers_the_same_digest(self):
        self.seal()
        with open(os.path.join(self.repo, ".cgel", "registry.json"), "a") as fh:
            fh.write("\n")
        code, out, err = self.cli("verify", "ok-check")
        self.assertIn(".cgel/registry.json", err)
        self.assertIn("reseal the SAME digest", err)


if __name__ == "__main__":
    unittest.main()
