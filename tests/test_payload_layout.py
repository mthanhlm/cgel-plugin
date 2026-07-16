"""Only plugin/ ships.

Claude Code copies the marketplace `source` directory wholesale into every
user's plugin cache, and offers no ignore mechanism — so the only way to
keep tests and design docs out of an install is to leave them outside the
payload. That makes the split load-bearing rather than cosmetic, and easy
to undo by accident: a new top-level dir inside plugin/ ships forever, and
a payload dir left outside it silently stops shipping.
"""

import json
import os
import unittest

from hookrunner import PLUGIN_ROOT, REPO_ROOT

# Every component Claude Code loads, plus the CLI the hooks shell out to.
PAYLOAD_MEMBERS = (
    os.path.join(".claude-plugin", "plugin.json"),
    os.path.join("hooks", "hooks.json"),
    os.path.join("bin", "cgel"),
    "scripts",
    "agents",
    "skills",
    "schemas",
    "commands",
)

# Kept out of the payload on purpose: 104K of the 288K that used to ship.
NOT_SHIPPED = ("tests", "ARCHITECT.md", ".github", ".cgel")

MARKETPLACE_PATH = os.path.join(REPO_ROOT, ".claude-plugin", "marketplace.json")


def marketplace():
    with open(MARKETPLACE_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def payload_dirs():
    """Top-level dirs Claude Code would read as a plugin: the manifest is what
    makes one, so this finds payloads the marketplace forgot to publish."""
    return {
        name
        for name in os.listdir(REPO_ROOT)
        if os.path.isfile(
            os.path.join(REPO_ROOT, name, ".claude-plugin", "plugin.json")
        )
    }


class VacuousPassGuard(unittest.TestCase):
    def test_payload_dir_exists_and_is_populated(self):
        self.assertTrue(os.path.isdir(PLUGIN_ROOT))
        self.assertGreaterEqual(len(os.listdir(PLUGIN_ROOT)), len(PAYLOAD_MEMBERS))


class PayloadIsComplete(unittest.TestCase):
    def test_every_component_is_inside_the_payload(self):
        for member in PAYLOAD_MEMBERS:
            self.assertTrue(
                os.path.exists(os.path.join(PLUGIN_ROOT, member)),
                "plugin/%s is missing — it would stop shipping" % member,
            )

    def test_no_component_is_left_at_the_repo_root(self):
        for member in PAYLOAD_MEMBERS:
            top = member.split(os.sep)[0]
            if top == ".claude-plugin":
                continue  # marketplace.json legitimately lives at the root
            self.assertFalse(
                os.path.exists(os.path.join(REPO_ROOT, top)),
                "%s is at the repo root, outside the payload — it would stop "
                "shipping" % top,
            )


class MarketplacePointsAtThePayload(unittest.TestCase):
    def test_source_is_the_payload_dir(self):
        entry = marketplace()["plugins"][0]
        self.assertEqual(entry["source"], "./plugin")

    def test_marketplace_manifest_stays_at_the_repo_root(self):
        # Relative sources resolve against the dir holding .claude-plugin/.
        self.assertTrue(os.path.isfile(MARKETPLACE_PATH))

    def test_every_payload_in_the_repo_is_published(self):
        # An unpublished payload is dead weight that still costs review and
        # rots unnoticed, since no install ever exercises it. Publish it or
        # delete it; do not let it sit here half-built.
        published = {
            os.path.normpath(entry["source"])
            for entry in marketplace()["plugins"]
        }
        self.assertEqual(
            payload_dirs(),
            published,
            "the payloads in this repo are not the ones marketplace.json "
            "publishes",
        )


class NonPayloadStaysOut(unittest.TestCase):
    def test_tests_and_docs_do_not_ship(self):
        for name in NOT_SHIPPED:
            self.assertFalse(
                os.path.exists(os.path.join(PLUGIN_ROOT, name)),
                "plugin/%s would be copied into every install" % name,
            )

    def test_they_are_still_present_in_the_repo(self):
        # Guards the inverse mistake: deleting them instead of relocating.
        for name in ("tests", "ARCHITECT.md", ".github"):
            self.assertTrue(os.path.exists(os.path.join(REPO_ROOT, name)))


if __name__ == "__main__":
    unittest.main()
