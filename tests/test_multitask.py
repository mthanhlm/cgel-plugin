"""Several open tasks per repo (D-39) — CLI resolution, per-task hooks,
batched verify, decide --verify, budget widening, and the superseded
failure signature fix. Subprocess tests, like everything else here.
"""

import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from hookrunner import run_hook, run_cli, decision_line

TASK_A = {
    "task": {"id": "TASK-A", "type": "feature", "goal": "Code work"},
    "acceptance_criteria": [
        {"id": "AC-1", "description": "code ok", "required_checks": ["ok-check"]}
    ],
    "scope": {"allowed": ["src/**"]},
    "risk": {"level": "low", "reasons": ["fixture: parallel-task code work"]},
}
TASK_B = {
    "task": {"id": "TASK-B", "type": "docs", "goal": "Docs work"},
    "acceptance_criteria": [
        {"id": "AC-1", "description": "docs ok", "required_checks": ["ok-check"]}
    ],
    "scope": {"allowed": ["docs/**"]},
    # Floored to high by normalize_contract: docs/** contains
    # docs/standards/**, so this scope really can rewrite the rules that
    # judge it. Literally true, and the escape is a tighter scope
    # (docs/guide/**) rather than an argument.
    "risk": {"level": "low", "reasons": ["fixture: parallel-task docs work"]},
}


class MultiTaskTestCase(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="cgel-repo-")
        self.state = tempfile.mkdtemp(prefix="cgel-state-")
        os.makedirs(os.path.join(self.repo, ".cgel"))
        os.makedirs(os.path.join(self.repo, ".task"))
        self.env = {"CGEL_STATE_DIR": self.state}
        self.cli(
            "check", "add", "ok-check",
            "--command", "test -d src || test -d docs || test -f marker",
            "--kind", "test",
        )
        self.cli(
            "check", "add", "flaky",
            "--command", "test -f ok-marker",
            "--kind", "test",
        )

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.state, ignore_errors=True)

    def cli(self, *args):
        return run_cli(list(args), cwd=self.repo, env=self.env)

    def seal(self, contract, contract_path=None):
        rel = contract_path or ".task/contract.json"
        with open(os.path.join(self.repo, rel), "w", encoding="utf-8") as fh:
            json.dump(contract, fh)
        code, out, err = self.cli("summary", "--contract", rel)
        self.assertEqual(code, 0, err)
        digest = decision_line(out).split("digest=")[1].split()[0]
        code, out, err = self.cli(
            "seal", contract["task"]["id"], "--digest", digest, "--contract", rel
        )
        self.assertEqual(code, 0, out + err)
        return digest

    def seal_both(self):
        os.makedirs(os.path.join(self.repo, "src"), exist_ok=True)
        os.makedirs(os.path.join(self.repo, "docs"), exist_ok=True)
        self.seal(TASK_A)
        self.seal(TASK_B, ".task/TASK-B.contract.json")

    def edit_hook(self, rel_path):
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": os.path.join(self.repo, rel_path)},
            "cwd": self.repo,
        }
        return run_hook("contract_gate.py", payload, env=self.env)

    # --------------------------------------- scope.forbidden is repo-wide
    #
    # "Must never change" is the one line in a contract a user writes
    # expecting it to hold no matter what else is going on. It was checked
    # per task inside the allow loop, so the FIRST task whose scope.allowed
    # matched returned allow() and another task's forbidden never ran.

    def seal_veto_pair(self, blocked=False):
        """TASK-A forbids src/vendor/**; TASK-B may write all of src/**."""
        os.makedirs(os.path.join(self.repo, "src", "vendor"), exist_ok=True)
        os.makedirs(os.path.join(self.repo, "docs"), exist_ok=True)
        a = copy.deepcopy(TASK_A)
        a["scope"] = {"allowed": ["docs/**"], "forbidden": ["src/vendor/**"]}
        b = copy.deepcopy(TASK_B)
        b["task"]["id"] = "TASK-B"
        b["scope"] = {"allowed": ["src/**"]}
        self.seal(a)
        self.seal(b, ".task/TASK-B.contract.json")

    def test_one_tasks_forbidden_vetoes_another_tasks_allowed(self):
        self.seal_veto_pair()
        code, _, err = self.edit_hook("src/vendor/lib.py")
        self.assertEqual(code, 2)
        self.assertIn("scope.forbidden", err)
        self.assertIn("TASK-A", err)
        # ...without breaking the rest of TASK-B's scope
        self.assertEqual(self.edit_hook("src/app.py")[0], 0)

    def test_a_blocked_tasks_forbidden_still_vetoes(self):
        # Blocked is not withdrawn. A task frozen mid-flight has not stopped
        # caring what happens to the paths it said must never change.
        self.seal_veto_pair()
        code, _, err = self.cli("unblock")  # no-op unless blocked; ignore
        state_dirs = []
        for name in os.listdir(self.state):
            path = os.path.join(self.state, name, "TASK-A", "state.json")
            if os.path.isfile(path):
                state_dirs.append(path)
        self.assertTrue(state_dirs)
        for path in state_dirs:
            with open(path) as fh:
                state = json.load(fh)
            state["lifecycle"] = "BLOCKED"
            state["blocked_reason"] = "test: frozen mid-flight"
            with open(path, "w") as fh:
                json.dump(state, fh)
        code, _, err = self.edit_hook("src/vendor/lib.py")
        self.assertEqual(code, 2)
        self.assertIn("TASK-A", err)

    # ------------------------------------------------------------ hooks

    def test_gate_routes_each_path_to_its_covering_task(self):
        self.seal_both()
        code, _, err = self.edit_hook("src/app.py")
        self.assertEqual(code, 0, err)
        code, _, err = self.edit_hook("docs/guide.md")
        self.assertEqual(code, 0, err)
        code, _, err = self.edit_hook("infra/main.tf")
        self.assertEqual(code, 2)
        self.assertIn("TASK-A", err)
        self.assertIn("TASK-B", err)

    def test_recorder_writes_the_edit_to_every_open_task(self):
        self.seal_both()
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": os.path.join(self.repo, "src/app.py")},
            "cwd": self.repo,
            "hook_event_name": "PostToolUse",
        }
        code, _, _ = run_hook("evidence_recorder.py", payload, env=self.env)
        self.assertEqual(code, 0)
        for task_id in ("TASK-A", "TASK-B"):
            events = []
            store = os.path.join(self.state)
            for name in os.listdir(store):
                task_dir = os.path.join(store, name, task_id)
                events_path = os.path.join(task_dir, "events.jsonl")
                if os.path.isfile(events_path):
                    with open(events_path, encoding="utf-8") as fh:
                        events = [json.loads(l) for l in fh if l.strip()]
            self.assertTrue(
                any(e.get("type") == "edit" for e in events), task_id
            )

    def test_stop_gate_names_the_dangling_task(self):
        self.seal_both()
        code, out, err = self.cli(
            "iterate", "open", "--task", "TASK-A",
            "--change", "x", "--expect", "ok-check",
        )
        self.assertEqual(code, 0, out + err)
        code, _, err = run_hook(
            "stop_gate.py", {"cwd": self.repo}, env=self.env
        )
        self.assertEqual(code, 2)
        self.assertIn("TASK-A", err)
        self.assertIn("--task TASK-A", err)

    # -------------------------------------------------------------- CLI

    def test_unaddressed_verbs_refuse_to_guess(self):
        self.seal_both()
        for args in (
            ("verify", "ok-check"),
            ("iterate", "open", "--change", "x"),
            ("close", "--as", "ABORT", "--reason", "fixture close"),
            ("audit",),
        ):
            code, out, _ = self.cli(*args)
            self.assertEqual(code, 1, args)
            self.assertIn("--task", decision_line(out))

    def test_deciding_the_other_task_cannot_steal_an_iteration(self):
        # The observed cross-session bug: one session decided another
        # session's open iteration. Addressed verbs make that impossible.
        self.seal_both()
        self.cli(
            "iterate", "open", "--task", "TASK-A",
            "--change", "x", "--expect", "ok-check",
        )
        code, out, _ = self.cli("iterate", "decide", "RETRY", "--task", "TASK-B")
        self.assertEqual(code, 1)
        self.assertIn("no open iteration", decision_line(out))
        code, out, err = self.cli(
            "iterate", "decide", "ADVANCE", "--verify", "--task", "TASK-A"
        )
        self.assertEqual(code, 0, out + err)

    def test_verify_batches_checks_in_one_call(self):
        os.makedirs(os.path.join(self.repo, "src"), exist_ok=True)
        with open(os.path.join(self.repo, "ok-marker"), "w") as fh:
            fh.write("x")
        contract = copy.deepcopy(TASK_A)
        contract["acceptance_criteria"][0]["required_checks"] = ["ok-check", "flaky"]
        self.seal(contract)
        code, out, err = self.cli("verify", "--required")
        self.assertEqual(code, 0, out + err)
        self.assertIn("VERIFY PASS — 2/2 checks", decision_line(out))
        self.assertIn("ok-check", err)
        os.unlink(os.path.join(self.repo, "ok-marker"))
        code, out, _ = self.cli("verify", "ok-check", "flaky")
        self.assertEqual(code, 1)
        self.assertIn("VERIFY FAIL — 1/2 checks failed (flaky)", decision_line(out))

    def test_single_check_verify_line_is_unchanged(self):
        os.makedirs(os.path.join(self.repo, "src"), exist_ok=True)
        self.seal(TASK_A)
        code, out, _ = self.cli("verify", "ok-check")
        self.assertEqual(code, 0)
        self.assertIn("VERIFY PASS check=ok-check exit=0 evidence=", decision_line(out))

    def test_decide_accepts_unique_prefixes_and_rejects_ambiguity(self):
        os.makedirs(os.path.join(self.repo, "src"), exist_ok=True)
        self.seal(TASK_A)
        self.cli("iterate", "open", "--change", "x", "--expect", "ok-check")
        code, out, _ = self.cli("iterate", "decide", "R")
        self.assertEqual(code, 1)
        self.assertIn("unknown decision", decision_line(out))
        code, out, err = self.cli("iterate", "decide", "adv", "--verify")
        self.assertEqual(code, 0, out + err)
        self.assertIn("ADVANCE", decision_line(out))

    def test_budget_widens_before_exhaustion(self):
        os.makedirs(os.path.join(self.repo, "src"), exist_ok=True)
        contract = copy.deepcopy(TASK_A)
        contract["budgets"] = {"max_iterations": 1, "max_replans": 0}
        self.seal(contract)
        code, out, err = self.cli("iterate", "open", "--change", "a", "--expect", "ok-check")
        self.assertEqual(code, 0, out + err)
        code, out, _ = self.cli("unblock", "--add-iterations", "2")
        self.assertEqual(code, 0, out)
        self.assertIn("budget extended", decision_line(out))
        self.cli("iterate", "decide", "ADVANCE", "--verify")
        code, out, err = self.cli("iterate", "open", "--change", "b", "--expect", "ok-check")
        self.assertEqual(code, 0, out + err)
        self.assertIn("iteration 2/3", decision_line(out))

    def test_unblock_still_refuses_with_nothing_to_do(self):
        os.makedirs(os.path.join(self.repo, "src"), exist_ok=True)
        self.seal(TASK_A)
        code, out, _ = self.cli("unblock")
        self.assertEqual(code, 1)
        self.assertIn("not BLOCKED", decision_line(out))

    def test_superseded_failure_signature_no_longer_trips_the_guard(self):
        # Observed misfire: check failed, later passed, and the guard still
        # refused RETRY/forced ESCALATE because the stale failure lingered.
        os.makedirs(os.path.join(self.repo, "src"), exist_ok=True)
        contract = copy.deepcopy(TASK_A)
        contract["acceptance_criteria"][0]["required_checks"] = ["flaky"]
        contract["budgets"] = {"max_iterations": 5, "max_replans": 2}
        self.seal(contract)
        self.cli("iterate", "open", "--change", "a", "--expect", "flaky")
        code, _, _ = self.cli("verify", "flaky")
        self.assertEqual(code, 1)
        self.cli("iterate", "decide", "RETRY")
        with open(os.path.join(self.repo, "ok-marker"), "w") as fh:
            fh.write("x")
        self.cli("iterate", "open", "--change", "b", "--expect", "flaky")
        code, _, _ = self.cli("verify", "flaky")
        self.assertEqual(code, 0)
        code, out, err = self.cli("iterate", "decide", "RETRY")
        self.assertEqual(code, 0, out + err)

    def test_close_frees_the_draft_and_reseal_starts_fresh(self):
        os.makedirs(os.path.join(self.repo, "src"), exist_ok=True)
        contract = copy.deepcopy(TASK_A)
        contract["budgets"] = {"max_iterations": 1, "max_replans": 0}
        digest = self.seal(contract)
        self.cli("iterate", "open", "--change", "a", "--expect", "ok-check")
        self.cli("iterate", "decide", "ADVANCE", "--verify")
        code, out, _ = self.cli("close", "--as", "ABORT", "--reason", "fixture close")
        self.assertEqual(code, 0)
        self.assertFalse(
            os.path.isfile(os.path.join(self.repo, ".task", "contract.json"))
        )
        # fresh seal of the same id: spent budget must not carry over
        self.seal(contract)
        code, out, err = self.cli(
            "iterate", "open", "--change", "again", "--expect", "ok-check"
        )
        self.assertEqual(code, 0, out + err)
        self.assertIn("iteration 1/1", decision_line(out))

    def test_open_without_expected_checks_warns(self):
        os.makedirs(os.path.join(self.repo, "src"), exist_ok=True)
        self.seal(TASK_A)
        code, out, err = self.cli("iterate", "open", "--change", "x")
        self.assertEqual(code, 0)
        self.assertIn("ADVANCE will be refused", err)

    def test_draft_warnings_surface_before_seal(self):
        contract = copy.deepcopy(TASK_A)
        contract["acceptance_criteria"][0]["required_checks"] = []
        contract["acceptance_criteria"].append(
            {"id": "AC-2", "description": "x", "required_checks": ["ghost-check"]}
        )
        with open(
            os.path.join(self.repo, ".task", "contract.json"), "w", encoding="utf-8"
        ) as fh:
            json.dump(contract, fh)
        code, _, err = self.cli("summary")
        self.assertEqual(code, 0)
        self.assertIn("PASS will be impossible", err)
        self.assertIn("ghost-check", err)

    def test_schema_prints_without_a_repo(self):
        plain = tempfile.mkdtemp(prefix="cgel-plain-")
        try:
            code, out, err = run_cli(
                ["schema", "task-contract"], cwd=plain, env=self.env
            )
            self.assertEqual(code, 0, err)
            self.assertIn("SCHEMA OK — task-contract", decision_line(out))
            body = out.rsplit("SCHEMA OK", 1)[0]
            self.assertIn('"acceptance_criteria"', body)
        finally:
            shutil.rmtree(plain, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
