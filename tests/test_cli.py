"""cgel CLI — subprocess tests: validate, summary, seal ceremony, close."""

import copy
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

    def test_reseal_of_the_same_task_is_the_amendment_path(self):
        # The task skill tells the model to answer a blocked path with "amend
        # the contract and reseal". That instruction is only true if resealing
        # an open task works; refusing it left the prescribed escape hatch
        # reachable only from BLOCKED.
        self.write_contract(CONTRACT)
        digest = self.summary_digest()
        code, out, _ = self.cli("seal", "TASK-C1", "--digest", digest)
        self.assertEqual(code, 0)
        self.assertIn("SEAL OK", decision_line(out))
        code, out, err = self.cli("seal", "TASK-C1", "--digest", digest)
        self.assertEqual(code, 0, err)
        self.assertIn("(reseal)", decision_line(out))

    def test_sealing_a_second_task_alongside_an_open_one(self):
        # D-39: several tasks may be open at once. Overlapping scopes are a
        # warned choice, not a refusal — and every verb must then say which
        # task it means.
        self.write_contract(CONTRACT)
        code, _, err = self.cli("seal", "TASK-C1", "--digest", self.summary_digest())
        self.assertEqual(code, 0, err)
        other = copy.deepcopy(CONTRACT)
        other["task"]["id"] = "TASK-C2"
        self.write_contract(other)
        code, out, err = self.cli("seal", "TASK-C2", "--digest", self.summary_digest())
        self.assertEqual(code, 0, out + err)
        self.assertIn("SEAL OK", decision_line(out))
        self.assertIn("overlaps open task(s) TASK-C1", err)
        code, out, err = self.cli("status")
        self.assertEqual(code, 0)
        self.assertIn("STATUS OPEN — 2 task(s)", decision_line(out))
        self.assertIn("TASK-C1", decision_line(out))
        self.assertIn("TASK-C2", decision_line(out))
        # an unaddressed verb must refuse rather than guess
        code, out, _ = self.cli("close", "--as", "ABORT")
        self.assertEqual(code, 1)
        self.assertIn("--task", decision_line(out))
        code, out, _ = self.cli("close", "--as", "ABORT", "--task", "TASK-C2")
        self.assertEqual(code, 0, out)
        code, out, _ = self.cli("status")
        self.assertIn("STATUS SEALED task=TASK-C1", decision_line(out))

    def test_disjoint_second_task_seals_without_overlap_warning(self):
        self.write_contract(CONTRACT)
        self.cli("seal", "TASK-C1", "--digest", self.summary_digest())
        other = copy.deepcopy(CONTRACT)
        other["task"]["id"] = "TASK-C2"
        other["scope"]["allowed"] = ["docs/**"]
        with open(
            os.path.join(self.repo, ".task", "TASK-C2.contract.json"),
            "w",
            encoding="utf-8",
        ) as fh:
            json.dump(other, fh)
        code, out, err = self.cli(
            "summary", "--contract", ".task/TASK-C2.contract.json"
        )
        self.assertEqual(code, 0, err)
        digest = decision_line(out).split("digest=")[1].split()[0]
        code, out, err = self.cli(
            "seal",
            "TASK-C2",
            "--digest",
            digest,
            "--contract",
            ".task/TASK-C2.contract.json",
        )
        self.assertEqual(code, 0, out + err)
        self.assertNotIn("overlaps", err)

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
        # close removes the matching draft: a stale contract.json squatting
        # in .task/ repeatedly blocked the next task in real use
        self.assertEqual(decision_line(out), "STATUS NO_TASK")
        self.assertFalse(
            os.path.isfile(os.path.join(self.repo, ".task", "contract.json"))
        )

    # ------------------------------------------- the output contract holds
    #
    # bin/cgel's docstring promises "one machine-parseable decision line on
    # stdout (last line)". Every caller — the skills, the hooks, these tests —
    # reads it. An unhandled exception used to break that promise silently:
    # a traceback on stderr, nothing on stdout, and a caller unable to tell
    # "denied" from "crashed".

    def _wedge(self):
        """A registry shape that reaches a live AttributeError inside
        _draft_warnings: (registry.get("checks") or {}).keys() on a str."""
        with open(
            os.path.join(self.repo, ".cgel", "registry.json"), "w", encoding="utf-8"
        ) as fh:
            fh.write('{"checks": "oops"}')
        self.write_contract(CONTRACT)

    def test_an_internal_error_still_emits_a_decision_line(self):
        self._wedge()
        code, out, err = self.cli("summary")
        self.assertNotEqual(code, 0)
        self.assertEqual(decision_line(out), "ERROR internal-error")
        self.assertNotIn("Traceback", out)
        self.assertIn("AttributeError", err)

    def test_internal_error_traceback_only_under_debug(self):
        self._wedge()
        code, out, err = run_cli(
            ["summary"],
            cwd=self.repo,
            env={"CGEL_STATE_DIR": self.state, "CGEL_DEBUG": "1"},
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(decision_line(out), "ERROR internal-error")
        self.assertIn("Traceback", err)

    def test_usage_exit_survives_the_guard(self):
        # SystemExit must be re-raised, not swallowed into internal-error:
        # require_repo_root's exit(3) and argparse's own exits are the CLI's
        # documented usage contract.
        code, out, err = run_cli(["status"], cwd=tempfile.gettempdir(), env=self.env)
        self.assertEqual(code, 3, out + err)
        self.assertNotIn("ERROR internal-error", out)

    def test_seal_refuses_over_an_unreadable_previous_run(self):
        # Sealing an id whose previous run cannot be archived used to proceed
        # silently: the new task inherited the old evidence chain and its spent
        # budgets. This must be a refusal the user can act on — and it must be
        # SEAL DENIED, not ERROR internal-error: the main() guard is a floor,
        # not a substitute for handling a case you know about.
        self.write_contract(CONTRACT)
        digest = self.summary_digest()
        self.cli("seal", "TASK-C1", "--digest", digest)
        self.cli("close", "--as", "ABORT")
        store = os.path.join(self.state, os.listdir(self.state)[0], "TASK-C1")
        with open(os.path.join(store, "state.json"), "w", encoding="utf-8") as fh:
            fh.write("[]")  # valid JSON, wrong shape
        self.write_contract(CONTRACT)
        digest = self.summary_digest()
        code, out, err = self.cli("seal", "TASK-C1", "--digest", digest)
        self.assertEqual(code, 1, out + err)
        self.assertIn("SEAL DENIED — stale task directory", decision_line(out))
        self.assertNotIn("ERROR internal-error", out)
        self.assertIn("not a JSON object", err)

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

    def test_seal_writes_legacy_current_and_close_removes_it(self):
        # transition compat: installed hooks one release behind still find
        # the task through CURRENT; new code never reads it
        self.write_contract(CONTRACT)
        self.cli("seal", "TASK-C1", "--digest", self.summary_digest())
        repos = os.listdir(self.state)
        current = os.path.join(self.state, repos[0], "CURRENT")
        with open(current, encoding="utf-8") as fh:
            self.assertEqual(fh.read().strip(), "TASK-C1")
        self.cli("close", "--as", "ABORT")
        self.assertFalse(os.path.exists(current))

    def test_summary_warns_without_intent_review_on_medium_risk(self):
        contract = json.loads(json.dumps(CONTRACT))
        contract["risk"] = {"level": "medium", "reasons": ["api change"]}
        self.write_contract(contract)
        code, _, err = self.cli("summary")
        self.assertEqual(code, 0)
        self.assertIn("no intent_review", err)
        contract["intent_review"] = {
            "assessed": True,
            "concerns": ["user's schema-per-tenant idea scales badly"],
            "alternative_chosen": "single schema + tenant_id column",
        }
        self.write_contract(contract)
        code, _, err = self.cli("summary")
        self.assertEqual(code, 0)
        self.assertNotIn("no intent_review", err)
        self.assertIn("Design review: 1 concern(s)", err)
        self.assertIn("tenant_id column", err)

    def test_low_risk_needs_no_intent_review(self):
        self.write_contract(CONTRACT)  # default risk: low
        code, _, err = self.cli("summary")
        self.assertEqual(code, 0)
        self.assertNotIn("intent_review", err)

    def test_malformed_intent_review_rejected(self):
        contract = json.loads(json.dumps(CONTRACT))
        contract["intent_review"] = {"concerns": "not-a-list"}
        self.write_contract(contract)
        code, out, err = self.cli("validate")
        self.assertEqual(code, 1)
        self.assertIn("intent_review.concerns", err)

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
