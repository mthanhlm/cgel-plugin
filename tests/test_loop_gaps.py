"""The four gaps found by running CGEL on itself.

Every one of these was a case where the design's own prescribed path did not
work, so the honest move looked like an override:

  1. No success-shaped decision, so a passing iteration had to be logged as
     RETRY — which quietly made the retry-rate metric measure nothing.
  2. `cgel seal` refused to reseal an open task, so "amend the contract and
     reseal" — the skill's answer to a blocked path — was only reachable from
     BLOCKED.
  3. The dirty check could not tell a task's own authorised edits from the
     user's, so the reseal in (2) demanded --allow-dirty every time. An
     override that is mandatory on the normal path stops being a decision.
  4. Together those made a modify-governance task impossible to finish
     cleanly.

The bundle-changed BLOCK is deliberately NOT relaxed here: a task that edits
the measure and keeps running would be grading itself with a yardstick it
just wrote. It is the recovery that is fixed, not the guard.
"""

import copy
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from hookrunner import run_cli, decision_line, REPO_ROOT

CONTRACT = {
    "task": {"id": "TASK-G1", "type": "bug-fix", "goal": "Loop gap demo"},
    "acceptance_criteria": [
        {"id": "AC-1", "description": "check passes", "required_checks": ["ok-check"]}
    ],
    "scope": {"allowed": ["src/**"]},
    "risk": {"level": "low", "reasons": ["fixture: exercises loop edge cases"]},
    "budgets": {"max_iterations": 3, "max_replans": 1},
}

REGISTRY = {
    "checks": {
        "ok-check": {"command": "echo all good"},
        "fail-check": {
            "command": "sh -c 'echo FAILED: assertion broke; exit 1'",
            "kind": "test",
        },
    }
}


class GapTestCase(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="cgel-gap-")
        self.state = tempfile.mkdtemp(prefix="cgel-gapstate-")
        os.makedirs(os.path.join(self.repo, ".cgel"))
        os.makedirs(os.path.join(self.repo, ".task"))
        os.makedirs(os.path.join(self.repo, "src"))
        self.env = {"CGEL_STATE_DIR": self.state}
        self.write_json(".cgel/registry.json", REGISTRY)
        self.write_file("src/app.py", "print('hello')\n")
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        self.commit()

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.state, ignore_errors=True)

    # ------------------------------------------------------------ helpers

    def cli(self, *args):
        return run_cli(list(args), cwd=self.repo, env=self.env)

    def write_json(self, rel, obj):
        with open(os.path.join(self.repo, rel), "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=1)

    def write_file(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def commit(self):
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-q", "-m", "wip"],
            cwd=self.repo,
            check=True,
        )

    def digest(self):
        code, out, err = self.cli("summary")
        self.assertEqual(code, 0, err)
        return decision_line(out).split("digest=")[1].split()[0]

    def seal(self, contract=CONTRACT, allow_dirty=False):
        self.write_json(".task/contract.json", contract)
        args = ["seal", contract["task"]["id"], "--digest", self.digest()]
        if allow_dirty:
            args.append("--allow-dirty")
        return self.cli(*args)

    def seal_ok(self, contract=CONTRACT):
        code, out, err = self.seal(contract)
        self.assertEqual(code, 0, out + err)
        return out

    def open_iteration(self, *expected):
        args = ["iterate", "open", "--intended-change", "poke it"]
        if expected:
            args += ["--expected-checks", ",".join(expected)]
        code, out, err = self.cli(*args)
        self.assertEqual(code, 0, out + err)


class AdvanceIsEvidenceGated(GapTestCase):
    """ADVANCE is only safe because it has to prove itself.

    Ungated it would be a hole straight through the default-same guard: fail a
    check, decide ADVANCE instead of the RETRY that would have been refused,
    and the failure travels on wearing a success-shaped label.
    """

    def test_advance_accepted_when_the_iteration_proved_its_claim(self):
        self.seal_ok()
        self.open_iteration("ok-check")
        code, _, err = self.cli("verify", "ok-check")
        self.assertEqual(code, 0, err)
        code, out, err = self.cli("iterate", "decide", "ADVANCE")
        self.assertEqual(code, 0, out + err)
        self.assertIn("ADVANCE", decision_line(out))

    def test_advance_refused_for_a_failing_check(self):
        self.seal_ok()
        self.open_iteration("fail-check")
        self.cli("verify", "fail-check")
        code, out, _ = self.cli("iterate", "decide", "ADVANCE")
        self.assertEqual(code, 1)
        self.assertIn("DECIDE DENIED", decision_line(out))

    def test_advance_refused_when_the_iteration_claimed_nothing(self):
        self.seal_ok()
        self.open_iteration()  # no --expected-checks
        code, out, _ = self.cli("iterate", "decide", "ADVANCE")
        self.assertEqual(code, 1)
        self.assertIn("DECIDE DENIED", decision_line(out))

    def test_advance_refused_when_evidence_went_stale(self):
        self.seal_ok()
        self.open_iteration("ok-check")
        code, _, err = self.cli("verify", "ok-check")
        self.assertEqual(code, 0, err)
        self.write_file("src/app.py", "print('changed after the check ran')\n")
        code, out, _ = self.cli("iterate", "decide", "ADVANCE")
        self.assertEqual(code, 1)
        self.assertIn("DECIDE DENIED", decision_line(out))

    def test_advance_does_not_spend_replan_budget(self):
        # The whole reason RETRY was being misused: the alternatives either
        # meant "I failed" or cost budget a success should not cost.
        self.seal_ok()
        for _ in range(3):
            self.open_iteration("ok-check")
            code, _, err = self.cli("verify", "ok-check")
            self.assertEqual(code, 0, err)
            code, out, err = self.cli("iterate", "decide", "ADVANCE")
            self.assertEqual(code, 0, out + err)


class ResealIsTheAmendmentPath(GapTestCase):
    def test_reseal_from_active_is_allowed(self):
        self.seal_ok()
        self.open_iteration("ok-check")  # SEALED -> ACTIVE
        code, out, err = self.cli("status")
        self.assertIn("STATUS ACTIVE", decision_line(out))
        code, out, err = self.seal()
        self.assertEqual(code, 0, out + err)
        self.assertIn("(reseal)", decision_line(out))

    def test_reseal_can_widen_scope_after_the_gate_blocks_a_needed_path(self):
        self.seal_ok()
        wider = copy.deepcopy(CONTRACT)
        wider["scope"]["allowed"] = ["src/**", "lib/**"]
        code, out, err = self.seal(wider)
        self.assertEqual(code, 0, out + err)
        self.assertIn("(reseal)", decision_line(out))


class DirtyCheckKnowsWhoseWorkItIs(GapTestCase):
    def test_first_seal_still_denies_dirty_paths_in_scope(self):
        # Unchanged behaviour: before a seal exists, an uncommitted file in
        # scope really might be the user's.
        self.write_file("src/app.py", "print('uncommitted user work')\n")
        code, out, _ = self.seal()
        self.assertEqual(code, 1)
        self.assertIn("SEAL DENIED", decision_line(out))

    def test_reseal_ignores_paths_the_previous_seal_authorised(self):
        self.seal_ok()  # authorises src/**
        self.write_file("src/app.py", "print('this task did this')\n")
        code, out, err = self.seal()  # no --allow-dirty
        self.assertEqual(code, 0, out + err)
        self.assertIn("(reseal)", decision_line(out))

    def test_reseal_still_denies_dirty_paths_the_previous_seal_did_not_cover(self):
        # Widening scope over someone else's uncommitted work is exactly what
        # the check exists to stop, and it still stops it.
        self.seal_ok()  # authorises src/** only
        self.write_file("docs/notes.md", "someone else's uncommitted work\n")
        wider = copy.deepcopy(CONTRACT)
        wider["scope"]["allowed"] = ["src/**", "docs/**"]
        code, out, _ = self.seal(wider)
        self.assertEqual(code, 1)
        self.assertIn("SEAL DENIED", decision_line(out))


class GovernanceTaskCanFinish(GapTestCase):
    def test_bundle_change_still_blocks(self):
        # The guard itself is not relaxed. If this ever passes, the sealed
        # measure has stopped meaning anything.
        self.seal_ok()
        self.open_iteration("ok-check")
        registry = copy.deepcopy(REGISTRY)
        registry["checks"]["added-later"] = {"command": "echo new"}
        self.write_json(".cgel/registry.json", registry)
        code, out, _ = self.cli("verify", "ok-check")
        self.assertEqual(code, 1)
        self.assertIn("BLOCKED", decision_line(out))

    def test_edit_block_reseal_verify_pass_without_any_override(self):
        self.seal_ok()
        self.open_iteration("ok-check")
        # The task's own in-scope work — this is what used to force
        # --allow-dirty on the reseal below.
        self.write_file("src/app.py", "print('the fix')\n")
        registry = copy.deepcopy(REGISTRY)
        registry["checks"]["added-later"] = {"command": "echo new"}
        self.write_json(".cgel/registry.json", registry)

        code, out, _ = self.cli("verify", "ok-check")
        self.assertEqual(code, 1)
        self.assertIn("BLOCKED", decision_line(out))

        code, out, err = self.seal()  # adopts the new measure, no override
        self.assertEqual(code, 0, out + err)
        self.assertIn("(reseal)", decision_line(out))

        code, _, err = self.cli("verify", "ok-check")
        self.assertEqual(code, 0, err)
        code, out, err = self.cli("iterate", "decide", "ADVANCE")
        self.assertEqual(code, 0, out + err)
        code, out, err = self.cli("close", "--as", "PASS")
        self.assertEqual(code, 0, out + err)
        self.assertIn("CLOSE OK", decision_line(out))


class ResealKeepsWhatTheUserGranted(GapTestCase):
    def test_budget_granted_by_unblock_survives_a_reseal(self):
        # Budgets are the user's to widen. Silently taking one back during an
        # amendment is the same violation as the model widening one itself.
        self.seal_ok()
        for _ in range(3):
            self.open_iteration("ok-check")
            self.cli("verify", "ok-check")
            self.cli("iterate", "decide", "ADVANCE")
        code, out, _ = self.cli("iterate", "open", "--intended-change", "one more")
        self.assertEqual(code, 1)
        self.assertIn("BLOCKED", decision_line(out))

        code, out, err = self.cli("unblock", "--add-iterations", "2")
        self.assertEqual(code, 0, out + err)

        code, out, err = self.seal()
        self.assertEqual(code, 0, out + err)

        code, out, err = self.cli(
            "iterate", "open", "--intended-change", "using the granted budget"
        )
        self.assertEqual(code, 0, out + err)


class TheRecordMatchesTheCode(unittest.TestCase):
    """A design record describing yesterday's behaviour still reads as current.

    D-35 exists because a stale doc is worse than a missing one; these keep
    D-36 honest the same way, and pin the skill prose the model actually acts on.
    """

    def read(self, *parts):
        with open(os.path.join(REPO_ROOT, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_architect_records_d36(self):
        self.assertIn("D-36", self.read("ARCHITECT.md"))

    def test_architect_still_records_why_the_bundle_block_was_kept(self):
        # The one part of D-36 a future reader must not mistake for an
        # oversight: the guard was kept on purpose.
        text = re.sub(r"\s+", " ", self.read("ARCHITECT.md"))
        self.assertIn("sealed-guidebook-bundle-changed", text)
        self.assertIn("deliberately kept", text)

    def test_architect_vocabulary_lists_advance(self):
        self.assertRegex(self.read("ARCHITECT.md"), r"Iteration decisions:.*ADVANCE")

    def test_loop_skill_documents_advance_and_its_gate(self):
        text = re.sub(r"\s+", " ", self.read("plugin", "skills", "loop", "SKILL.md"))
        self.assertIn("cgel iterate decide ADVANCE", text)
        self.assertIn("Evidence-gated", text)

    def test_readme_command_reference_lists_advance(self):
        self.assertIn("ADVANCE", self.read("README.md"))


if __name__ == "__main__":
    unittest.main()
