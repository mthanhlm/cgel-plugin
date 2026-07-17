"""Phase 2 — loop control: iterations, budgets, default-same failure guard,
BLOCKED semantics, unblock, stop gate, session-start resume."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from hookrunner import run_cli, run_hook, decision_line, SCRIPTS_DIR

CONTRACT = {
    "task": {"id": "TASK-L1", "type": "bug-fix", "goal": "Loop control demo"},
    "acceptance_criteria": [
        {"id": "AC-1", "description": "check passes", "required_checks": ["ok-check"]}
    ],
    "scope": {"allowed": ["src/**"]},
    "risk": {"level": "low", "reasons": ["fixture: exercises the iteration loop"]},
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


class LoopFixture(unittest.TestCase):
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


class LoopTestCase(LoopFixture):
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
        # The remedy is copy-pasteable now, not a description of one.
        self.assertIn('cgel close --as ESCALATE --reason "..."', err)

        # ...and REPLAN closes with it. Guarding only RETRY made the loop
        # look bounded while leaving the door open: the exit from a refused
        # RETRY was another REPLAN against the same failure, around until the
        # replan budget ran out.
        code, out, err = self.cli("iterate", "decide", "REPLAN")
        self.assertEqual(code, 1)
        self.assertIn("survived a REPLAN", decision_line(out))
        self.assertIn('cgel close --as ESCALATE --reason "..."', err)

        # The override still works — the user can always overrule the guard.
        code, out, _ = self.cli(
            "iterate", "decide", "RETRY",
            "--override-reason", "flaky infra, not the approach",
            "--approved-by", "user",
        )
        self.assertEqual(code, 0, out)

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

    # ------------------------------------------- the monorepo-session floor
    #
    # command_guard and approval_gate root at the session's directory by
    # design (rooting a Bash hook by scanning below cwd means a walk on every
    # Bash call, ambiguous with two projects). A session above a project is
    # therefore ungated at the Bash level, and the only honest thing to do is
    # say so once, at the top.

    def test_session_above_a_project_says_nothing_here_is_gated(self):
        # A private monorepo, not dirname(self.repo): that is /tmp, which
        # collects every other test's project and would make this assert on
        # whatever else ran today.
        mono = tempfile.mkdtemp(prefix="cgel-mono-")
        try:
            project = os.path.join(mono, "proj")
            os.makedirs(os.path.join(project, ".cgel"))
            code, out, err = run_hook(
                "session_start.py",
                {"hook_event_name": "SessionStart", "cwd": mono},
                env=self.env,
            )
            self.assertEqual(code, 0, err)
            context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
            self.assertIn("nothing in this session is gated", context)
            self.assertIn(os.path.realpath(project), context)
            self.assertIn("cgel -C", context)
        finally:
            shutil.rmtree(mono, ignore_errors=True)

    def test_session_in_a_plain_directory_stays_silent(self):
        plain = tempfile.mkdtemp(prefix="cgel-plain-")
        try:
            code, out, _ = run_hook(
                "session_start.py",
                {"hook_event_name": "SessionStart", "cwd": plain},
                env=self.env,
            )
            self.assertEqual(code, 0)
            self.assertEqual(out.strip(), "")
        finally:
            shutil.rmtree(plain, ignore_errors=True)

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
        # the standing rule is gone; other context (e.g. the registered
        # checks line) may still be injected
        self.assertNotIn("no AI attribution", out)

    def test_resume_preserves_evidence_chain(self):
        self.seal()
        self.open_iteration(1)
        self.cli("verify", "ok-check")
        self.cli("iterate", "decide", "ROLLBACK_ITERATION")
        # nothing session-scoped: a fresh process sees intact chains
        code, out, _ = self.cli("audit")
        self.assertEqual(code, 0)
        self.assertIn("chain=intact", decision_line(out))


class LoopWedgeTestCase(LoopFixture):
    """Phase D/AC-6 — the loop must always be able to come to rest.

    A control that cannot be satisfied is not a control; it is a wedge, and
    the only exit from a wedge is the off switch. That is how a governance
    gate teaches its user to disable it.
    """

    def block_task(self, reason):
        for name in os.listdir(self.state):
            path = os.path.join(self.state, name, "TASK-L1", "state.json")
            if os.path.isfile(path):
                with open(path) as fh:
                    state = json.load(fh)
                state["lifecycle_before_block"] = state.get("lifecycle", "ACTIVE")
                state["lifecycle"] = "BLOCKED"
                state["blocked_reason"] = reason
                with open(path, "w") as fh:
                    json.dump(state, fh)

    def test_rollback_is_legal_while_blocked(self):
        # The wedge: BLOCKED refused every decision, so a task blocked while
        # an iteration was open could not close that iteration — and
        # `iterate open` refuses while BLOCKED, so nothing could move at all.
        self.seal()
        self.open_iteration(1)
        self.block_task("sealed-guidebook-bundle-changed")
        code, out, err = self.cli("iterate", "decide", "ROLLBACK_ITERATION")
        self.assertEqual(code, 0, out + err)
        self.assertIn("ROLLBACK_ITERATION", decision_line(out))

    def test_advance_stays_refused_while_blocked_by_a_moved_yardstick(self):
        # Evidence measured against the SEALED digest is not evidence about
        # what is here now.
        self.seal()
        self.open_iteration(1)
        self.cli("verify", "ok-check")
        self.block_task("sealed-guidebook-bundle-changed")
        code, out, err = self.cli("iterate", "decide", "ADVANCE")
        self.assertEqual(code, 1)
        self.assertIn("BLOCKED", decision_line(out))
        self.assertIn("ROLLBACK_ITERATION", err)
        self.assertIn("close --as ESCALATE", err)

    def test_advance_is_legal_while_blocked_on_an_exhausted_budget(self):
        # The user widened the budget; the yardstick never moved.
        self.seal()
        self.cli(
            "iterate", "open", "--intended-change", "poke", "--expect", "ok-check"
        )
        self.cli("verify", "ok-check")
        self.block_task("budget-exhausted-iterations")
        code, out, err = self.cli("iterate", "decide", "ADVANCE")
        self.assertEqual(code, 0, out + err)

    def test_a_governance_task_does_not_freeze_itself(self):
        # A task the user approved WITH modify-verification-registry was
        # refused by its own seal: the freeze counted every open task, so the
        # one task allowed to change the registry could not, and its only
        # exit was to close unfinished.
        contract = json.loads(json.dumps(CONTRACT))
        contract["task"]["id"] = "TASK-L1"
        contract["protected_capabilities"] = ["modify-verification-registry"]
        contract["acceptance_criteria"] = [
            {"id": "AC-1", "description": "registry gains a check",
             "required_checks": []}
        ]
        contract["risk"] = {"level": "high", "reasons": ["changes the measure"]}
        self.seal(contract)
        # not `true`: the check canary refuses a command that passes with no
        # project present, which is the two-sided doctor doing its job.
        code, out, err = self.cli(
            "check", "add", "new-check",
            "--command", "test -f src/app.py", "--kind", "test",
        )
        self.assertEqual(code, 0, out + err)

    def test_another_open_task_still_freezes_the_registry_and_names_them_all(self):
        self.seal()
        code, out, err = self.cli(
            "check", "add", "late", "--command", "test -f src/app.py", "--kind", "test"
        )
        self.assertEqual(code, 1)
        self.assertIn("CHECK DENIED", decision_line(out))
        self.assertIn("TASK-L1", decision_line(out))
        self.assertIn("modify-verification-registry", err)

    def test_seal_refuses_a_criterion_naming_an_unregistered_check(self):
        # The registry freezes AT seal, so such a criterion can never produce
        # evidence: PASS was structurally impossible from the moment of seal,
        # and nothing said so until close.
        contract = json.loads(json.dumps(CONTRACT))
        contract["acceptance_criteria"] = [
            {"id": "AC-1", "description": "x", "required_checks": ["never-registered"]}
        ]
        self.write_json(".task/contract.json", contract)
        code, out, err = self.cli("summary")
        digest = decision_line(out).split("digest=")[1].split()[0]
        code, out, err = self.cli("seal", "TASK-L1", "--digest", digest)
        self.assertEqual(code, 1)
        self.assertIn("not registered", decision_line(out))
        self.assertIn("never-registered", decision_line(out))
        self.assertIn("ok-check", err)  # names what IS registered
        self.assertIn("check add", err)

    def test_a_criterion_with_no_checks_still_seals(self):
        # required_checks: [] is the governance-task shape. It cannot PASS,
        # which is by design, and is not the seal's business to refuse.
        contract = json.loads(json.dumps(CONTRACT))
        contract["acceptance_criteria"] = [
            {"id": "AC-1", "description": "x", "required_checks": []}
        ]
        self.seal(contract)


class ProjectScanTestCase(unittest.TestCase):
    """_projects_below runs on EVERY session start in EVERY directory.

    Its budget is the feature: a notice is never worth real time, so a
    partial answer is fine and no answer is acceptable. These pin the
    refusals, because a walk of / or $HOME on every session start would be a
    worse defect than the one the notice reports.
    """

    def setUp(self):
        sys.path.insert(0, SCRIPTS_DIR)
        import session_start

        self.session_start = session_start
        self.base = tempfile.mkdtemp(prefix="cgel-scan-")

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def make_project(self, rel):
        path = os.path.join(self.base, rel)
        os.makedirs(os.path.join(path, ".cgel"))
        return path

    def test_refuses_the_filesystem_root(self):
        self.assertEqual(self.session_start._projects_below("/"), [])

    def test_refuses_home(self):
        self.assertEqual(
            self.session_start._projects_below(os.path.expanduser("~")), []
        )

    def test_finds_projects_one_and_two_levels_down(self):
        a = self.make_project("a")
        b = self.make_project("group/b")
        self.assertEqual(
            self.session_start._projects_below(self.base),
            sorted([os.path.realpath(a), os.path.realpath(b)]),
        )

    def test_checks_the_deepest_legal_level_before_pruning(self):
        # Pruning at depth BEFORE checking the level would never see this.
        deep = self.make_project("x/y/z")
        self.assertEqual(
            self.session_start._projects_below(self.base, max_depth=3),
            [os.path.realpath(deep)],
        )

    def test_skips_vendored_trees_before_checking_them(self):
        self.make_project("node_modules/pkg")
        self.assertEqual(self.session_start._projects_below(self.base), [])

    def test_a_project_inside_a_project_is_not_reported_twice(self):
        outer = self.make_project("outer")
        os.makedirs(os.path.join(outer, "inner", ".cgel"))
        self.assertEqual(
            self.session_start._projects_below(self.base),
            [os.path.realpath(outer)],
        )

    def test_the_limit_caps_the_result(self):
        for name in "abcdefgh":
            self.make_project(name)
        self.assertEqual(
            len(self.session_start._projects_below(self.base, limit=5)), 5
        )


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

    # ------------------------------------------- the link can succeed and
    # the CLI still be unreachable (~/.local/bin is not on PATH by default
    # on stock macOS/zsh). The model then sees `command not found` and
    # improvises around the gate — so say so, with the absolute path.

    def test_path_miss_injects_the_absolute_cli_path(self):
        os.makedirs(os.path.join(self.home, ".cgel"))
        empty = tempfile.mkdtemp(prefix="cgel-nopath-")
        self.addCleanup(shutil.rmtree, empty, True)
        code, out, err = self.run_ss(
            {"PATH": empty, "CGEL_STATE_DIR": tempfile.mkdtemp(prefix="cgel-st-")}
        )
        self.assertEqual(code, 0, err)
        self.assertIn("NOT on this session's PATH", out)
        self.assertIn(os.path.join("bin", "cgel"), out)

    def test_no_path_notice_when_cgel_is_reachable(self):
        # The notice must not become always-on noise.
        os.makedirs(os.path.join(self.home, ".cgel"))
        bindir = tempfile.mkdtemp(prefix="cgel-bin-")
        self.addCleanup(shutil.rmtree, bindir, True)
        shim = os.path.join(bindir, "cgel")
        with open(shim, "w") as fh:
            fh.write("#!/bin/sh\nexit 0\n")
        os.chmod(shim, 0o755)
        code, out, err = self.run_ss(
            {"PATH": bindir, "CGEL_STATE_DIR": tempfile.mkdtemp(prefix="cgel-st-")}
        )
        self.assertEqual(code, 0, err)
        self.assertNotIn("NOT on this session's PATH", out)

    def test_path_notice_is_silent_outside_a_cgel_project(self):
        # CGEL is opt-in per project; an unreachable CLI is not a reason to
        # start speaking in someone else's repo.
        empty = tempfile.mkdtemp(prefix="cgel-nopath-")
        self.addCleanup(shutil.rmtree, empty, True)
        code, out, err = self.run_ss({"PATH": empty})
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "")


if __name__ == "__main__":
    unittest.main()
