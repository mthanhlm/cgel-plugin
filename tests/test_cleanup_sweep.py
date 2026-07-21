"""The closing ceremony's cleanup sweep (D-56) is carried entirely by prose
in the attest skill — untested prose that bounds an action is a wish."""

import unittest

from test_skill_prose import skill_text


class CleanupSweepProseTestCase(unittest.TestCase):

    def test_sweep_runs_before_the_verifier(self):
        text = skill_text("attest")
        self.assertIn("Sweep the change clean — before any verifier runs", text)
        # The ordering argument, not just the ordering: cleanup after the
        # record stales findings and forces a second verifier run.
        self.assertIn("This pass runs BEFORE the verifier on purpose", text)

    def test_sweep_is_bounded_to_touched_files(self):
        text = skill_text("attest")
        self.assertIn("Only the files this task touched.", text)
        self.assertIn("The diff IS the boundary", text)

    def test_sweep_is_behavior_preserving(self):
        text = skill_text("attest")
        self.assertIn("Behavior-preserving deletions only.", text)
        self.assertIn(
            "If removing it changes what the code does, it is not cleanup", text
        )

    def test_sweep_with_nothing_to_do_is_skipped(self):
        self.assertIn(
            "a ceremony with nothing to do is noise", skill_text("attest")
        )


if __name__ == "__main__":
    unittest.main()
