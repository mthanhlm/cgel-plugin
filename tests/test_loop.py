"""Phase 2 — loop control: iterations, budgets, default-same failure guard,
BLOCKED semantics, unblock, stop gate, session-start resume."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

from hookrunner import run_cli, run_hook, decision_line

CONTRACT = {
    "task": {"id": "TASK-L1", "type": "bug-fix", "goal": "Loop control demo"},
    "acceptance_criteria": [
        {"id": "AC-1", "description": "check passes", "required_checks": ["ok-check"]}
    ],
    "scope": {"allowed": ["src/**"]},
    "budgets": {"max_iterations": 3, "max_replans": 1},
}

REGISTRY = {
    "checks": {
        "ok-check": {"command": "echo all good"},
        "fail-check": {
            "command": "sh -c 'echo FAILED: assertion broke; exit 1'",
            "kind": "test",
        },
        "other-fail": {
            "command": "sh -c 'echo FAILED: different subsystem crashed badly; exit 1'",
            "kind": "build",
        },
    }
}


class LoopTestCase(unittest.TestCase):
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

    def write_json(self, rel, obj):
        with open(os.path.join(self.repo, rel), "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=1)

    def seal(self, contract=CONTRACT):
        self.write_json(".task/contract.json", contract)
        code, out, err = self.cli("summary")
        self.assertEqual(code, 0, err)
        digest = decision_line(out).split("digest=")[1].split()[0]
        code, out, err = self.cli("seal", contract["task"]["id"], "--digest", digest)
        self.assertEqual(code, 0, out + err)

    def open_iteration(self, n_expected=None):
        code, out, err = self.cli(
            "iterate", "open", "--intended-change", "poke the bug"
        )
        self.assertEqual(code, 0, out + err)
        if n_expected:
            self.assertIn("iteration %d/" % n_expected, decision_line(out))

    # -------------------------------------------------------- lifecycle

    def test_first_iteration_activates(self):
        self.seal()
        _, out, _ = self.cli("status")
        self.assertIn("STATUS SEALED", decision_line(out))
        self.open_iteration(1)
        _, out, _ = self.cli("status")
        self.assertIn("STATUS ACTIVE", decision_line(out))

    def test_second_open_requires_decision(self):
        self.seal()
        self.open_iteration(1)
        code, out, _ = self.cli("iterate", "open", "--intended-change", "more")
        self.assertEqual(code, 1)
        self.assertIn("no decision yet", decision_line(out))

    def test_decide_requires_open_iteration(self):
        self.seal()
        code, out, _ = self.cli("iterate", "decide", "RETRY")
        self.assertEqual(code, 1)
        self.assertIn("no open iteration", decision_line(out))

    def test_open_requires_intended_change(self):
        self.seal()
        code, out, _ = self.cli("iterate", "open")
        self.assertEqual(code, 1)
        self.assertIn("--intended-change required", decision_line(out))

    # ---------------------------------------------- default-same guard

    def test_retry_allowed_once_then_forced_replan(self):
        self.seal()
        self.open_iteration(1)
        self.cli("verify", "fail-check")
        code, out, _ = self.cli("iterate", "decide", "RETRY")
        self.assertEqual(code, 0, out)

        self.open_iteration(2)
        self.cli("verify", "fail-check")  # identical failure
        code, out, err = self.cli("iterate", "decide", "RETRY")
        self.assertEqual(code, 1)
        self.assertIn("RETRY forbidden", decision_line(out))
        self.assertIn("REPLAN", err)

    def test_different_failure_signature_allows_retry(self):
        self.seal()
        self.open_iteration(1)
        self.cli("verify", "fail-check")
        self.cli("iterate", "decide", "RETRY")
        self.open_iteration(2)
        self.cli("verify", "other-fail")  # different check, kind, fingerprint
        code, out, _ = self.cli("iterate", "decide", "RETRY")
        self.assertEqual(code, 0, out)

    def test_signature_surviving_replan_forces_escalate(self):
        self.seal()
        self.open_iteration(1)
        self.cli("verify", "fail-check")
        code, _, _ = self.cli("iterate", "decide", "REPLAN")
        self.assertEqual(code, 0)
        self.open_iteration(2)
        self.cli("verify", "fail-check")  # same signature survived the replan
        code, out, err = self.cli("iterate", "decide", "RETRY")
        self.assertEqual(code, 1)
        self.assertIn("survived a REPLAN", decision_line(out))
        self.assertIn("ESCALATE or ABORT", err)

    def test_override_with_approver_permits_retry(self):
        self.seal()
        self.open_iteration(1)
        self.cli("verify", "fail-check")
        self.cli("iterate", "decide", "RETRY")
        self.open_iteration(2)
        self.cli("verify", "fail-check")
        code, out, _ = self.cli(
            "iterate", "decide", "RETRY", "--override-reason", "flaky infra, user saw it"
        )
        self.assertEqual(code, 1)  # override without approver is refused
        code, out, _ = self.cli(
            "iterate",
            "decide",
            "RETRY",
            "--override-reason",
            "flaky infra, user saw it",
            "--approved-by",
            "user",
        )
        self.assertEqual(code, 0, out)

    # ------------------------------------------------------------ budgets

    def test_iteration_budget_exhaustion_blocks(self):
        self.seal()
        for n in (1, 2, 3):
            self.open_iteration(n)
            self.cli("verify", "ok-check")
            self.cli("iterate", "decide", "ROLLBACK_ITERATION")
        code, out, _ = self.cli("iterate", "open", "--intended-change", "one more")
        self.assertEqual(code, 1)
        self.assertIn("ITERATE BLOCKED", decision_line(out))
        _, out, _ = self.cli("status")
        self.assertIn("STATUS BLOCKED", decision_line(out))
        self.assertIn("budget-exhausted-iterations", decision_line(out))
        # BLOCKED shuts the edit gate
        code, _, _ = run_hook(
            "contract_gate.py",
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": os.path.join(self.repo, "src/app.py")},
                "cwd": self.repo,
            },
            env=self.env,
        )
        self.assertEqual(code, 2)

    def test_unblock_extends_budget_and_reactivates(self):
        self.seal()
        for n in (1, 2, 3):
            self.open_iteration(n)
            self.cli("iterate", "decide", "ROLLBACK_ITERATION")
        self.cli("iterate", "open", "--intended-change", "x")  # -> BLOCKED
        code, out, _ = self.cli("unblock")
        self.assertEqual(code, 1)  # blocked on iterations: needs --add-iterations
        code, out, _ = self.cli("unblock", "--add-iterations", "2")
        self.assertEqual(code, 0, out)
        self.assertIn("UNBLOCK OK", decision_line(out))
        self.open_iteration(4)

    def test_replan_budget_exhaustion_blocks(self):
        self.seal()  # max_replans: 1
        self.open_iteration(1)
        self.cli("verify", "fail-check")
        self.cli("iterate", "decide", "REPLAN")
        self.open_iteration(2)
        self.cli("verify", "other-fail")
        code, out, _ = self.cli("iterate", "decide", "REPLAN")
        self.assertEqual(code, 1)
        self.assertIn("replan budget exhausted", decision_line(out))
        _, out, _ = self.cli("status")
        self.assertIn("budget-exhausted-replans", decision_line(out))

    def test_unblock_cannot_fix_bundle_change(self):
        self.seal()
        self.open_iteration(1)
        registry = json.loads(json.dumps(REGISTRY))
        registry["note"] = "moved goalposts"
        self.write_json(".cgel/registry.json", registry)
        self.cli("verify", "ok-check")  # -> BLOCKED (bundle changed)
        code, out, _ = self.cli("unblock", "--add-iterations", "5")
        self.assertEqual(code, 1)
        self.assertIn("only a reseal fixes this", decision_line(out))

    # ---------------------------------------------------------- stop gate

    def stop_payload(self):
        return {"hook_event_name": "Stop", "cwd": self.repo}

    def test_stop_gate_blocks_undecided_iteration_bounded(self):
        self.seal()
        self.open_iteration(1)
        code, _, err = run_hook("stop_gate.py", self.stop_payload(), env=self.env)
        self.assertEqual(code, 2)
        self.assertIn("no decision", err)
        code, _, _ = run_hook("stop_gate.py", self.stop_payload(), env=self.env)
        self.assertEqual(code, 2)
        code, _, _ = run_hook("stop_gate.py", self.stop_payload(), env=self.env)
        self.assertEqual(code, 0)  # bound (2) reached — never an infinite loop

    def test_stop_gate_allows_when_iteration_decided(self):
        self.seal()
        self.open_iteration(1)
        self.cli("iterate", "decide", "ROLLBACK_ITERATION")
        code, _, _ = run_hook("stop_gate.py", self.stop_payload(), env=self.env)
        self.assertEqual(code, 0)

    def test_stop_gate_silent_outside_task(self):
        code, _, _ = run_hook("stop_gate.py", self.stop_payload(), env=self.env)
        self.assertEqual(code, 0)
        code, _, _ = run_hook(
            "stop_gate.py", None, env=self.env, raw_stdin="{broken"
        )
        self.assertEqual(code, 0)

    # ------------------------------------------------------------- resume

    def test_session_start_injects_state_summary(self):
        self.seal()
        self.open_iteration(1)
        self.cli("verify", "fail-check")
        code, out, err = run_hook(
            "session_start.py",
            {"hook_event_name": "SessionStart", "source": "resume", "cwd": self.repo},
            env=self.env,
        )
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        context = payload["hookSpecificOutput"]["additionalContext"]
        self.assertIn("TASK-L1", context)
        self.assertIn("Open iteration 1", context)
        self.assertIn("fail-check", context)
        self.assertIn("iterations 1/3", context)

    def test_session_start_without_task_injects_only_standing_rules(self):
        code, out, _ = run_hook(
            "session_start.py",
            {"hook_event_name": "SessionStart", "cwd": self.repo},
            env=self.env,
        )
        self.assertEqual(code, 0)
        context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("no AI attribution", context)
        self.assertNotIn("CGEL resume", context)

    def test_session_start_injects_attribution_rule_alongside_task(self):
        self.seal()
        code, out, err = run_hook(
            "session_start.py",
            {"hook_event_name": "SessionStart", "cwd": self.repo},
            env=self.env,
        )
        self.assertEqual(code, 0, err)
        context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("no AI attribution", context)
        self.assertIn("CGEL resume", context)

    def test_session_start_attribution_rule_kill_switch(self):
        C_path = os.path.join(self.repo, ".cgel", "config.json")
        with open(C_path, "w", encoding="utf-8") as fh:
            json.dump({"ai_attribution_guard": "off"}, fh)
        code, out, _ = run_hook(
            "session_start.py",
            {"hook_event_name": "SessionStart", "cwd": self.repo},
            env=self.env,
        )
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")

    def test_resume_preserves_evidence_chain(self):
        self.seal()
        self.open_iteration(1)
        self.cli("verify", "ok-check")
        self.cli("iterate", "decide", "ROLLBACK_ITERATION")
        # nothing session-scoped: a fresh process sees intact chains
        code, out, _ = self.cli("audit")
        self.assertEqual(code, 0)
        self.assertIn("chain=intact", decision_line(out))


class SymlinkTestCase(unittest.TestCase):
    """SessionStart auto-links bin/cgel into ~/.local/bin — safely."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="cgel-home-")
        self.link = os.path.join(self.home, ".local", "bin", "cgel")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def run_ss(self, extra_env=None):
        env = {"HOME": self.home}
        env.update(extra_env or {})
        return run_hook("session_start.py", {"cwd": self.home}, env=env)

    def test_symlink_created_and_idempotent(self):
        code, _, err = self.run_ss()
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.islink(self.link))
        self.assertTrue(os.readlink(self.link).endswith("bin/cgel"))
        code, _, _ = self.run_ss()
        self.assertEqual(code, 0)
        self.assertTrue(os.path.islink(self.link))

    def test_never_clobbers_foreign_file(self):
        os.makedirs(os.path.dirname(self.link))
        with open(self.link, "w") as fh:
            fh.write("#!/bin/sh\necho mine\n")
        code, _, _ = self.run_ss()
        self.assertEqual(code, 0)
        self.assertFalse(os.path.islink(self.link))
        with open(self.link) as fh:
            self.assertIn("mine", fh.read())

    def test_repairs_stale_cgel_link_only(self):
        os.makedirs(os.path.dirname(self.link))
        stale = os.path.join(self.home, "old-install", "bin", "cgel")
        os.symlink(stale, self.link)
        self.run_ss()
        self.assertTrue(os.path.islink(self.link))
        self.assertNotEqual(os.readlink(self.link), stale)
        foreign = os.path.join(self.home, "somewhere", "else")
        os.unlink(self.link)
        os.symlink(foreign, self.link)
        self.run_ss()
        self.assertEqual(os.readlink(self.link), foreign)  # left alone

    def test_opt_out(self):
        code, _, _ = self.run_ss({"CGEL_NO_SYMLINK": "1"})
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(self.link))


if __name__ == "__main__":
    unittest.main()
