"""The agent-facing surface: skill prose and hook wiring.

The Python gates are HARD_ENFORCED and tested elsewhere. The seal ceremony
is HUMAN_GATED, and it is carried entirely by sentences in skills/*/SKILL.md
— prose is the only thing standing between a user and a double gate, a
smuggled seal, or a PASS claimed without evidence. Untested prose that
enforces something is just a wish, so these tests pin it.

Assertions run against whitespace-normalized text: rewrapping a paragraph is
fine, deleting the rule is not.

The read-only `tools:` frontmatter of the verifier and explorer agents is
pinned in test_semantic.py — not duplicated here.
"""

import json
import os
import re
import unittest

from hookrunner import PLUGIN_ROOT

SKILLS = ("task", "loop", "attest")
HOOK_EVENTS = (
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "Stop",
    "SessionStart",
)

# A hook may only invoke a bundled script. Anything else — notably echoing
# instructions at the model — makes hooks a prompt channel instead of a
# control plane, which is the one thing they must never be.
HOOK_COMMAND_RE = re.compile(
    r'^python3 "\$\{CLAUDE_PLUGIN_ROOT\}/scripts/[a-z_]+\.py"$'
)


def flat(text):
    """Collapse whitespace so prose can be rewrapped without breaking tests."""
    return re.sub(r"\s+", " ", text)


def skill_text(name):
    path = os.path.join(PLUGIN_ROOT, "skills", name, "SKILL.md")
    with open(path, encoding="utf-8") as fh:
        return flat(fh.read())


def hook_commands():
    path = os.path.join(PLUGIN_ROOT, "hooks", "hooks.json")
    with open(path, encoding="utf-8") as fh:
        events = json.load(fh)["hooks"]
    commands = []
    for entries in events.values():
        for entry in entries:
            for hook in entry["hooks"]:
                commands.append(hook["command"])
    return events, commands


class VacuousPassGuard(unittest.TestCase):
    """If the readers silently stop finding anything, fail loudly here
    rather than let every assertion below pass over empty strings."""

    def test_every_skill_is_found_and_substantial(self):
        for name in SKILLS:
            text = skill_text(name)
            self.assertGreater(len(text), 500, "skills/%s/SKILL.md too short" % name)

    def test_hook_commands_are_found(self):
        events, commands = hook_commands()
        self.assertEqual(len(events), len(HOOK_EVENTS))
        self.assertGreaterEqual(len(commands), len(HOOK_EVENTS))


class SealCeremonyProse(unittest.TestCase):
    def test_seal_is_one_gate_not_two(self):
        # The permission prompt IS the approval; asking for a chat "approve"
        # on top of it trains users to click through both.
        self.assertIn("one gate, not two", skill_text("task"))

    def test_protected_seal_cannot_be_smuggled(self):
        self.assertIn("never smuggle a protected seal past them", skill_text("task"))

    def test_seal_binds_the_exact_digest(self):
        self.assertIn("Seal with the EXACT digest", skill_text("task"))

    def test_contract_may_not_reinterpret_intent(self):
        self.assertIn(
            "the contract must not silently reinterpret their intent",
            skill_text("task"),
        )

    def test_dirty_tree_seal_needs_explicit_confirmation(self):
        self.assertIn(
            "only reseal with `--allow-dirty` after their explicit confirmation",
            skill_text("task"),
        )


class EvidenceProse(unittest.TestCase):
    def test_self_reported_output_is_not_evidence(self):
        self.assertIn(
            "running commands yourself and pasting output creates NO evidence",
            skill_text("task"),
        )

    def test_manual_runs_are_not_evidence(self):
        self.assertIn("Manual command runs are not evidence.", skill_text("loop"))

    def test_no_pass_without_recorded_evidence(self):
        self.assertIn(
            "Never claim a criterion passed without recorded evidence",
            skill_text("task"),
        )

    def test_blocking_findings_may_not_be_buried(self):
        self.assertIn("Never bury a blocking finding", skill_text("attest"))

    def test_denied_pass_is_not_an_obstacle_to_route_around(self):
        self.assertIn(
            "A denied PASS is information, not an obstacle to route around",
            skill_text("attest"),
        )

    def test_verifier_is_never_handed_write_tools(self):
        self.assertIn("never hand it write tools", skill_text("attest"))

    def test_attestations_are_not_committed_by_default(self):
        self.assertIn(
            "Attestations are never committed to the repository by default",
            skill_text("attest"),
        )


class GovernanceProse(unittest.TestCase):
    def test_registry_changes_go_only_through_the_cli(self):
        self.assertIn(
            "Registry changes go ONLY through `cgel check add`", skill_text("task")
        )

    def test_governance_paths_are_not_editable(self):
        self.assertIn("never Edit/Write on `.cgel/**`", skill_text("task"))

    def test_gate_may_not_be_worked_around(self):
        self.assertIn("do NOT work around it (no Bash writes)", skill_text("task"))

    def test_only_the_user_unblocks(self):
        text = skill_text("loop")
        self.assertIn("only the USER unblocks", text)
        self.assertIn("Never run `unblock` on your own initiative", text)

    def test_cgel_never_touches_the_checkout(self):
        self.assertIn("CGEL never touches the checkout", skill_text("loop"))


class HooksAreAControlPlane(unittest.TestCase):
    def test_every_hook_only_invokes_a_bundled_script(self):
        _, commands = hook_commands()
        for command in commands:
            self.assertRegex(command, HOOK_COMMAND_RE)

    def test_all_five_events_are_registered(self):
        events, _ = hook_commands()
        self.assertEqual(set(events), set(HOOK_EVENTS))

    def test_edits_and_bash_are_both_gated_before_they_run(self):
        events, _ = hook_commands()
        matchers = {entry["matcher"] for entry in events["PreToolUse"]}
        self.assertIn("Edit|Write|NotebookEdit", matchers)
        self.assertIn("Bash", matchers)


class NeverSuppressTheHumanGate(unittest.TestCase):
    """Nothing the plugin ships may tell the model to skip asking the user.

    Prompts and hooks are GUIDANCE_ONLY — the model is free to ignore them —
    so an imperative that suppresses confirmation buys no enforcement and
    spends the one boundary a human actually controls.
    """

    SUPPRESSION = re.compile(
        r"do not ask (the user )?for confirmation|without asking the user|just do it",
        re.I,
    )

    def shipped_agent_facing_files(self):
        paths = []
        for name in SKILLS:
            paths.append(os.path.join(PLUGIN_ROOT, "skills", name, "SKILL.md"))
        agents_dir = os.path.join(PLUGIN_ROOT, "agents")
        for entry in sorted(os.listdir(agents_dir)):
            if entry.endswith(".md"):
                paths.append(os.path.join(agents_dir, entry))
        paths.append(os.path.join(PLUGIN_ROOT, "hooks", "hooks.json"))
        return paths

    def test_guard_actually_scans_files(self):
        self.assertGreaterEqual(len(self.shipped_agent_facing_files()), 6)

    def test_nothing_shipped_suppresses_confirmation(self):
        for path in self.shipped_agent_facing_files():
            with open(path, encoding="utf-8") as fh:
                match = self.SUPPRESSION.search(fh.read())
            self.assertIsNone(
                match,
                "%s suppresses a human gate: %r"
                % (os.path.relpath(path, PLUGIN_ROOT), match.group(0) if match else ""),
            )


if __name__ == "__main__":
    unittest.main()
