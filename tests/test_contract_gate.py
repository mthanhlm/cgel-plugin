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
    "risk": {"level": "low", "reasons": ["fixture: exercises the edit gate"]},
}


class GateFixture(unittest.TestCase):
    """Fixture only — no tests, so subclasses do not re-run each other's."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="cgel-repo-")
        self.state = tempfile.mkdtemp(prefix="cgel-state-")
        os.makedirs(os.path.join(self.repo, ".cgel"))
        os.makedirs(os.path.join(self.repo, ".task"))
        self.env = {"CGEL_STATE_DIR": self.state}
        # seal refuses a criterion naming an unregistered check: the
        # registry freezes at seal, so it could never produce evidence.
        with open(
            os.path.join(self.repo, ".cgel", "registry.json"), "w", encoding="utf-8"
        ) as fh:
            json.dump({"checks": {"unit-tests": {"command": "true"}}}, fh)

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


class GateTestCase(GateFixture):
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
            ["close", "--as", "ESCALATE", "--reason", "fixture close"], cwd=self.repo, env=self.env
        )
        self.assertEqual(code, 0, out + err)
        code, _, _ = self.edit("src/app.py")
        self.assertEqual(code, 2)

    # -------------------------------------------- root memory files (D-50)

    def test_root_claude_md_writable_before_any_seal(self):
        # The onboarding window: no task governs the repo yet, so a fresh
        # project can be given a tailored CLAUDE.md before the first seal.
        code, _, err = self.edit("CLAUDE.md")
        self.assertEqual(code, 0, err)

    def test_root_claude_local_md_writable_before_any_seal(self):
        code, _, err = self.edit("CLAUDE.local.md")
        self.assertEqual(code, 0, err)

    def test_claude_md_gated_once_a_task_is_sealed(self):
        # The moment a task governs the repo, CLAUDE.md follows normal scope:
        # the fixture scope (src/**, tests/**) does not name it, so the model
        # cannot rewrite its own memory mid-task, unscoped.
        self.seal()
        code, _, err = self.edit("CLAUDE.md")
        self.assertEqual(code, 2)
        self.assertIn("outside scope.allowed", err)

    def test_claude_md_writable_mid_task_when_deliberately_in_scope(self):
        # The exemption is not the only door in: a task that names CLAUDE.md
        # can still edit it.
        contract = json.loads(json.dumps(CONTRACT))
        contract["task"]["id"] = "TASK-MEM"
        contract["scope"]["allowed"] = ["CLAUDE.md"]
        self.seal(contract)
        code, _, err = self.edit("CLAUDE.md")
        self.assertEqual(code, 0, err)

    def test_dot_claude_claude_md_is_not_a_root_memory_file(self):
        # .claude/CLAUDE.md is a governance path, not a root memory file, so
        # the onboarding exemption never reaches it — blocked even with no
        # task open.
        code, _, _ = self.edit(".claude/CLAUDE.md")
        self.assertEqual(code, 2)

    def test_nested_claude_md_is_not_exempt(self):
        # Only the repo-root CLAUDE.md is a memory file; a nested one is
        # ordinary application content and stays gated.
        code, _, _ = self.edit("subdir/CLAUDE.md")
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
        # Passes for a NEW reason since rooting moved to the file: the target
        # has no project above it, so resolve_repo_root falls back to the
        # session's root (self.repo) and resolve_target reports in_repo=False.
        # Before, find_repo_root(cwd) found self.repo and the prefix test
        # rejected the path. Same verdict, different mechanism.
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


class RootingTestCase(GateFixture):
    """must-fix #5/#6 — the gate roots at the FILE, not at the session.

    Ubuntu-only CI cannot see the symlink class of defect unless a test builds
    the symlink itself, so these construct the aliases rather than assuming a
    host layout.
    """

    def gate_edit(self, cwd, file_path):
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": file_path},
            "cwd": cwd,
        }
        return run_hook("contract_gate.py", payload, env=self.env)[0]

    def test_session_above_the_project_still_gates_edits_inside_it(self):
        # must-fix #5: a session opened at a monorepo root has no .cgel/ above
        # it, so rooting at the session found nothing and stood aside — every
        # edit into every project below was ungated, silently.
        self.seal()
        mono = os.path.dirname(self.repo)
        self.assertFalse(os.path.isdir(os.path.join(mono, ".cgel")))
        self.assertEqual(
            self.gate_edit(mono, os.path.join(self.repo, "docs/x.md")), 2
        )
        self.assertEqual(
            self.gate_edit(mono, os.path.join(self.repo, "src/app.py")), 0
        )

    def test_symlinked_directory_alias_cannot_defeat_the_prefix_test(self):
        # must-fix #6: repo_root and the target were compared as strings, so
        # either side reached through an alias made startswith() false and the
        # edit ungated. Both are realpath'd at the directory now.
        self.seal()
        alias = os.path.join(tempfile.mkdtemp(prefix="cgel-alias-"), "link")
        try:
            os.symlink(self.repo, alias)
            self.assertEqual(
                self.gate_edit(alias, os.path.join(self.repo, "docs/x.md")), 2
            )
            self.assertEqual(
                self.gate_edit(self.repo, os.path.join(alias, "docs/x.md")), 2
            )
            self.assertEqual(
                self.gate_edit(alias, os.path.join(alias, "src/app.py")), 0
            )
        finally:
            shutil.rmtree(os.path.dirname(alias), ignore_errors=True)

    def test_symlinked_leaf_escaping_the_repo_is_judged_at_its_in_repo_name(self):
        # The asymmetry, and the reason resolve_repo_root stops at the dirname:
        # resolving the LEAF would move this decision to /etc, land outside
        # repo_root, and ungate an edit no scope authorised. Judged at
        # src/escape.py it is refused by a scope that does not name src/**.
        self.seal(
            dict(
                CONTRACT,
                scope={"allowed": ["docs/**"], "forbidden": []},
            )
        )
        os.makedirs(os.path.join(self.repo, "src"), exist_ok=True)
        escape = os.path.join(self.repo, "src", "escape.py")
        os.symlink("/etc/passwd", escape)
        code, _, err = run_hook(
            "contract_gate.py",
            {
                "tool_name": "Write",
                "tool_input": {"file_path": escape},
                "cwd": self.repo,
            },
            env=self.env,
        )
        self.assertEqual(code, 2)
        self.assertIn("src/escape.py", err)
        self.assertNotIn("/etc/passwd", err)

    def test_a_looping_symlink_does_not_fail_the_gate_open(self):
        # Non-strict realpath does not raise on a loop; it returns the path
        # unresolved. That is the safe answer — the target keeps its in-repo
        # name and is still judged. Pinned with an OUT-OF-SCOPE path, because
        # an in-scope one would return 0 whether the gate ran or stood aside.
        self.seal()
        os.makedirs(os.path.join(self.repo, "docs"), exist_ok=True)
        os.symlink(
            os.path.join(self.repo, "docs", "loop_b"),
            os.path.join(self.repo, "docs", "loop_a"),
        )
        os.symlink(
            os.path.join(self.repo, "docs", "loop_a"),
            os.path.join(self.repo, "docs", "loop_b"),
        )
        self.assertEqual(
            self.gate_edit(self.repo, os.path.join(self.repo, "docs/loop_a/x.md")), 2
        )

    def recorded_edits(self, task_id="TASK-T1"):
        paths = []
        for name in os.listdir(self.state):
            events_path = os.path.join(self.state, name, task_id, "events.jsonl")
            if os.path.isfile(events_path):
                with open(events_path, encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            event = json.loads(line)
                            if event.get("type") == "edit":
                                paths.append(event["path"])
        return paths

    def test_the_recorder_roots_at_the_file_too(self):
        # An edit the recorder does not see is an edit that never marks
        # evidence stale — the same hole as an ungated edit, one surface over.
        # The recorder rooted at the session, so a monorepo-root session wrote
        # no events at all.
        self.seal()
        mono = os.path.dirname(self.repo)
        code, _, _ = run_hook(
            "evidence_recorder.py",
            {
                "tool_name": "Write",
                "tool_input": {"file_path": os.path.join(self.repo, "src/app.py")},
                "cwd": mono,
                "hook_event_name": "PostToolUse",
            },
            env=self.env,
        )
        self.assertEqual(code, 0)
        self.assertIn("src/app.py", self.recorded_edits())

    def test_a_dangling_symlinked_directory_is_still_judged(self):
        self.seal()
        os.makedirs(os.path.join(self.repo, "docs"), exist_ok=True)
        os.symlink(
            os.path.join(self.repo, "docs", "nowhere"),
            os.path.join(self.repo, "docs", "dangling"),
        )
        self.assertEqual(
            self.gate_edit(self.repo, os.path.join(self.repo, "docs/dangling/x.md")), 2
        )


if __name__ == "__main__":
    unittest.main()
