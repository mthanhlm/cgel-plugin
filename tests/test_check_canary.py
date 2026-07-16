"""A check that cannot fail is not a check.

The registry is the measure, and `cgel verify` trusts it completely: whatever
the command says, a hash-chained evidence record is minted for it and
`close --as PASS` accepts that record. So a command that exits 0 no matter
what mints perfect evidence for nothing — §15.8 Phase 1 names this as the
threat ("`echo tests passed` is worthless") and answered it with §15.7's
committed, reviewed registry. D-35 removed the reviewer, and review never
covered rot anyway: this repo's own `compileall -q scripts bin/cgel` was
correct when written and went vacuous when the payload moved.

The canary: run the command where the project is not. If it still passes, it
is not measuring the project.

It catches mistakes, not adversaries — a command can be built to fail in an
empty directory and still verify nothing.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from hookrunner import run_cli, decision_line, REPO_ROOT

# Exits 0 with no project present, so every run mints evidence for nothing.
VACUOUS = [
    "echo tests passed",
    "true",
    # Both of these are real regressions this repo shipped.
    "python3 -m compileall -q scripts bin/cgel",
    "python3 -c \"import json,glob; [json.load(open(f)) for f in "
    "sorted(glob.glob('schemas/*.json'))]\"",
    # Correct-looking and still vacuous: compileall exits 0 when its target is
    # absent, so this cannot tell 'src compiles' from 'src is gone'.
    "python3 -m compileall -q src",
]

# Break without the project, so their evidence means something.
DEPENDENT = [
    "python3 -m unittest discover",
    "test -f src/app.py",
    "test -d src && python3 -m compileall -q src",
]


class CanaryTestCase(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="cgel-canary-")
        self.state = tempfile.mkdtemp(prefix="cgel-canstate-")
        os.makedirs(os.path.join(self.repo, ".cgel"))
        os.makedirs(os.path.join(self.repo, ".task"))
        os.makedirs(os.path.join(self.repo, "src"))
        self.env = {"CGEL_STATE_DIR": self.state}
        self.write_json(".cgel/registry.json", {"checks": {}})
        with open(os.path.join(self.repo, "src", "app.py"), "w") as fh:
            fh.write("print('hello')\n")
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.state, ignore_errors=True)

    def cli(self, *args):
        return run_cli(list(args), cwd=self.repo, env=self.env)

    def write_json(self, rel, obj):
        with open(os.path.join(self.repo, rel), "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=1)

    def registry(self):
        with open(
            os.path.join(self.repo, ".cgel", "registry.json"), encoding="utf-8"
        ) as fh:
            return json.load(fh)


class VacuousPassGuard(CanaryTestCase):
    def test_the_fixtures_are_not_empty(self):
        # Otherwise every loop below would pass over nothing.
        self.assertGreaterEqual(len(VACUOUS), 5)
        self.assertGreaterEqual(len(DEPENDENT), 3)


class RegistrationRefusesChecksThatCannotFail(CanaryTestCase):
    def test_every_vacuous_command_is_refused(self):
        for index, command in enumerate(VACUOUS):
            code, out, _ = self.cli(
                "check", "add", "c%d" % index, "--command", command
            )
            self.assertEqual(code, 1, "registered a vacuous check: %s" % command)
            self.assertIn("CHECK DENIED", decision_line(out))

    def test_refusal_says_why_and_offers_the_way_out(self):
        code, out, err = self.cli(
            "check", "add", "t", "--command", "echo tests passed"
        )
        self.assertEqual(code, 1)
        self.assertIn("passes with no project present", decision_line(out))
        self.assertIn("--allow-unproven", err)

    def test_a_refused_check_is_not_written_to_the_registry(self):
        self.cli("check", "add", "t", "--command", "true")
        self.assertEqual(self.registry()["checks"], {})


class RegistrationAcceptsChecksThatMeasureSomething(CanaryTestCase):
    def test_every_dependent_command_registers_clean(self):
        for index, command in enumerate(DEPENDENT):
            code, out, err = self.cli(
                "check", "add", "d%d" % index, "--command", command
            )
            self.assertEqual(code, 0, "refused a real check: %s\n%s" % (command, err))
            self.assertIn("CHECK ADDED", decision_line(out))

    def test_guarding_a_weak_command_is_what_makes_it_registrable(self):
        # The remedy the refusal points at, and the one that fixed this repo.
        code, _, _ = self.cli(
            "check", "add", "bare", "--command", "python3 -m compileall -q src"
        )
        self.assertEqual(code, 1)
        code, _, err = self.cli(
            "check",
            "add",
            "guarded",
            "--command",
            "test -d src && python3 -m compileall -q src",
        )
        self.assertEqual(code, 0, err)

    def test_accepted_checks_carry_no_unproven_marker(self):
        self.cli("check", "add", "d", "--command", "test -f src/app.py")
        self.assertNotIn("unproven", self.registry()["checks"]["d"])


class TheOverrideRecordsTheAdmission(CanaryTestCase):
    def test_allow_unproven_registers_the_check(self):
        code, out, err = self.cli(
            "check", "add", "v", "--command", "true", "--allow-unproven"
        )
        self.assertEqual(code, 0, err)
        self.assertIn("CHECK ADDED", decision_line(out))

    def test_allow_unproven_marks_the_entry_in_the_registry(self):
        # The admission travels with the yardstick. A warning printed once to a
        # terminal is gone; `unproven: true` is still there at review time.
        self.cli("check", "add", "v", "--command", "true", "--allow-unproven")
        self.assertTrue(self.registry()["checks"]["v"]["unproven"])


class DoctorCatchesRegistriesTheCanaryNeverSaw(CanaryTestCase):
    """Registration-time refusal only helps registries created after it.

    Doctor is the migration path: every registry written by an earlier cgel —
    including this repo's own, where two of three checks verified nothing —
    was never put in front of a canary.
    """

    def test_doctor_fails_on_a_registry_written_before_the_canary(self):
        self.write_json(
            ".cgel/registry.json",
            {"checks": {"legacy": {"command": "echo tests passed"}}},
        )
        code, out, err = self.cli("check", "doctor")
        self.assertEqual(code, 1)
        self.assertIn("DOCTOR FAIL", decision_line(out))
        self.assertIn("legacy", err)

    def test_doctor_names_this_repos_actual_regression(self):
        self.write_json(
            ".cgel/registry.json",
            {"checks": {"byte-compile": {"command": "python3 -m compileall -q scripts"}}},
        )
        code, out, _ = self.cli("check", "doctor")
        self.assertEqual(code, 1)
        self.assertIn("byte-compile", decision_line(out))

    def test_doctor_passes_when_every_check_depends_on_the_project(self):
        # Both fail in an empty dir (so they measure something) AND pass in this
        # fixture's tree (so they can actually be satisfied). DOCTOR OK now
        # requires both — see DoctorAlsoCatchesChecksThatCannotPass.
        self.write_json(
            ".cgel/registry.json",
            {
                "checks": {
                    "a": {"command": "test -f src/app.py"},
                    "b": {"command": "test -d src && python3 -m compileall -q src"},
                }
            },
        )
        code, out, err = self.cli("check", "doctor")
        self.assertEqual(code, 0, err)
        self.assertIn("DOCTOR OK", decision_line(out))


class DoctorAlsoCatchesChecksThatCannotPass(CanaryTestCase):
    """The dual of vacuity: a check whose target is gone fails the canary (so it
    looks fine to the old doctor) yet can never pass. deck-compile pointed at a
    deleted deck/ and this repo's own doctor reported it `ok`. A one-sided
    canary is structurally blind to it; doctor now runs each check in the tree.
    """

    # Fails empty (test -d short-circuits) and fails here (no such path) — the
    # exact shape of the deck-compile/slide-compile regression.
    ROTTED = "test -d src/gone && python3 -m compileall -q src/gone"

    def test_a_check_that_cannot_pass_here_is_not_reported_ok(self):
        self.write_json(
            ".cgel/registry.json", {"checks": {"gone": {"command": self.ROTTED}}}
        )
        code, out, err = self.cli("check", "doctor")
        self.assertEqual(code, 1, "a check that cannot pass was reported ok")
        self.assertIn("DOCTOR FAIL", decision_line(out))
        self.assertIn("cannot pass here", decision_line(out))
        self.assertIn("gone", err)

    def test_failing_empty_is_no_longer_enough_to_be_ok(self):
        # Both checks fail in an empty dir, so the old canary-only doctor passed
        # both. Only one passes in the tree. The new doctor separates them.
        self.write_json(
            ".cgel/registry.json",
            {
                "checks": {
                    "healthy": {"command": "test -f src/app.py"},
                    "rotted": {"command": self.ROTTED},
                }
            },
        )
        code, out, _ = self.cli("check", "doctor")
        self.assertEqual(code, 1)
        line = decision_line(out)
        self.assertIn("rotted", line)
        self.assertNotIn("healthy", line)

    def test_wording_does_not_assert_rot_over_a_merely_broken_project(self):
        # Principle 1: doctor cannot tell a moved target from a broken build, so
        # it must not claim rot. If it did, a red CI would read as a bad check.
        self.write_json(
            ".cgel/registry.json", {"checks": {"gone": {"command": self.ROTTED}}}
        )
        _, _, err = self.cli("check", "doctor")
        self.assertIn("cannot tell which", err)

    def test_vacuous_and_cannot_pass_are_named_as_different_faults(self):
        self.write_json(
            ".cgel/registry.json",
            {
                "checks": {
                    "empty-pass": {"command": "echo tests passed"},
                    "gone": {"command": self.ROTTED},
                }
            },
        )
        code, out, _ = self.cli("check", "doctor")
        self.assertEqual(code, 1)
        line = decision_line(out)
        self.assertIn("verify nothing", line)
        self.assertIn("cannot pass here", line)
        self.assertIn("empty-pass", line)
        self.assertIn("gone", line)

    def test_doctor_refuses_an_empty_registry_rather_than_reporting_all_clear(self):
        # "0 checks, all fine" is the most dangerous thing it could say.
        code, out, _ = self.cli("check", "doctor")
        self.assertEqual(code, 1)
        self.assertIn("DOCTOR DENIED", decision_line(out))


class TheClaimStaysBelowWhatTheCodeEnforces(unittest.TestCase):
    """The failure mode for this feature is not a bug — it is overclaiming.

    A canary that catches the easy cases reads, to a hurried person, as making
    the registry safe. It does not. Principle 1 says never dress a weaker
    guarantee in a stronger word, so the limits are pinned here.
    """

    def read(self, *parts):
        with open(os.path.join(REPO_ROOT, *parts), encoding="utf-8") as fh:
            return re.sub(r"\s+", " ", fh.read())

    def test_architect_records_d37(self):
        self.assertIn("D-37", self.read("ARCHITECT.md"))

    def test_architect_separates_the_d35_half_from_the_real_gap(self):
        # Half of this compensates for a decision; half fills a genuine hole.
        # Blurring them would let a later reader think v1.0 was simply wrong.
        text = self.read("ARCHITECT.md")
        self.assertIn("compensates for D-35", text)
        self.assertIn("Rot had no answer at all", text)

    def test_readme_says_the_canary_catches_mistakes_not_adversaries(self):
        # Must name the canary: "catches mistakes, not adversaries" already
        # appears for the command guard, so a looser assertion would pass
        # without the canary being documented at all.
        self.assertIn(
            "canary catches mistakes, not adversaries", self.read("README.md")
        )

    def test_readme_does_not_claim_the_registry_is_now_trustworthy(self):
        self.assertIn(
            "does not make the registry trustworthy", self.read("README.md")
        )

    def test_readme_still_says_who_authors_the_yardstick(self):
        self.assertIn(
            "yardstick is still authored by whoever runs", self.read("README.md")
        )


if __name__ == "__main__":
    unittest.main()
