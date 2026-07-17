"""The repo's public claims stay true and stay legal.

Two failure modes this guards. First, a manifest that declares a license the
repo does not contain — GitHub then reports no license at all, which legally
means all rights reserved, so nobody can use the thing. Second, and worse for
a governance tool: a public claim drifting above what the code enforces.
CGEL's first principle is enforcement honesty, so the honest statements are
load-bearing product, not boilerplate, and deleting one has to fail a test.
"""

import json
import os
import unittest

from hookrunner import PLUGIN_ROOT, REPO_ROOT

ENFORCEMENT_CLASSES = (
    "HARD_ENFORCED",
    "EVIDENCE_GATED",
    "HUMAN_GATED",
    "GUIDANCE_ONLY",
)


def read(*parts):
    with open(os.path.join(REPO_ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def plugin_manifest():
    with open(
        os.path.join(PLUGIN_ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8"
    ) as fh:
        return json.load(fh)


class VacuousPassGuard(unittest.TestCase):
    def test_documents_are_found_and_substantial(self):
        for name in ("LICENSE", "SECURITY.md", "README.md"):
            self.assertGreater(len(read(name)), 400, "%s too short" % name)


class InstallInstructionsResolve(unittest.TestCase):
    """A README whose install command dangles is a first-run failure that
    every new user hits and no test could see. The path is machine-checkable
    against this repo, so check it."""

    def test_the_documented_manual_symlink_path_exists_in_this_repo(self):
        line = next(
            l for l in read("README.md").splitlines() if l.strip().startswith("ln -s ")
        )
        src = line.split()[2]
        marker = "marketplaces/cgel/"
        self.assertIn(marker, src, "the documented link no longer names the install")
        tail = src.split(marker, 1)[1]
        self.assertTrue(
            os.path.isfile(os.path.join(REPO_ROOT, tail)),
            "README documents `ln -s ...%s` but this repo has no such file — "
            "following the README yields a dangling symlink" % tail,
        )

    def test_readme_does_not_promise_automatic_path(self):
        # The hook links into ~/.local/bin, which is not on PATH by default on
        # stock macOS/zsh. "lands on your PATH automatically" was false there.
        readme = read("README.md")
        self.assertNotIn("lands on your PATH automatically", readme)
        self.assertIn("not** on\nPATH by default", readme)


class TheBypassIsNotAdvertisedToTheModel(unittest.TestCase):
    """`CGEL_GIT=allow` is a plain string test, not an identity check. A
    model that reads the prefix can type it as easily as a user can, so
    naming it anywhere the model reads hands the blocked party the key.

    It stays in the README (where the user reads) and in command_guard's own
    source (where it is implemented and explained)."""

    def _shipped_model_facing_files(self):
        paths = []
        for sub in ("skills", "agents", "commands", "rules"):
            base = os.path.join(PLUGIN_ROOT, sub)
            for root, _, files in os.walk(base):
                for name in files:
                    if name.endswith(".md"):
                        paths.append(os.path.join(root, name))
        return paths

    def test_no_shipped_prose_advertises_the_git_bypass(self):
        for path in self._shipped_model_facing_files():
            with open(path, encoding="utf-8") as fh:
                self.assertNotIn(
                    "CGEL_GIT",
                    fh.read(),
                    "%s tells the model how to bypass the guard" % path,
                )

    def test_the_guard_only_names_the_bypass_where_it_implements_it(self):
        with open(
            os.path.join(PLUGIN_ROOT, "scripts", "command_guard.py"), encoding="utf-8"
        ) as fh:
            source = fh.read()
        # The docstring explains it and APPROVAL_PREFIX implements it. What
        # must never come back is a block message naming it: those are the
        # strings the model reads at exactly the moment it wants a way out.
        for line in source.splitlines():
            if "CGEL guard [" in line:
                self.assertNotIn("CGEL_GIT", line)

    def test_readme_does_not_claim_the_bypass_is_an_identity(self):
        # Prose wraps; assert on the claim, not on the line breaks.
        readme = " ".join(read("README.md").split())
        self.assertNotIn(
            "override typed by the user",
            readme,
            "CGEL_GIT=allow is a plain string test — nothing tells a user's "
            "keystrokes from the model's",
        )
        self.assertIn("string, not an identity", readme)


class LicenseMatchesTheManifest(unittest.TestCase):
    def test_license_file_carries_mit_text(self):
        text = read("LICENSE")
        self.assertIn("MIT License", text)
        self.assertIn("Permission is hereby granted, free of charge", text)
        self.assertIn("WITHOUT WARRANTY OF ANY KIND", text)

    def test_manifest_declares_the_same_license(self):
        # plugin.json said MIT for eight releases while no LICENSE existed.
        self.assertEqual(plugin_manifest()["license"], "MIT")

    def test_declared_license_is_the_one_shipped(self):
        declared = plugin_manifest()["license"]
        self.assertIn("%s License" % declared, read("LICENSE"))


class SecurityStatesTheRealBoundary(unittest.TestCase):
    def test_profile_a_is_not_claimed_as_a_trust_boundary(self):
        self.assertIn("not a hard trust boundary", read("SECURITY.md"))

    def test_tamper_evidence_is_distinguished_from_prevention(self):
        text = read("SECURITY.md")
        self.assertIn("tamper-evident", text)
        self.assertIn("Profile B", text)

    def test_profile_b_is_not_advertised_as_shipping(self):
        self.assertIn("Profile B is not implemented yet", read("SECURITY.md"))

    def test_the_known_gaps_are_listed_as_out_of_scope(self):
        # A vulnerability report about a documented limitation wastes
        # everyone's time; saying so up front is part of the honesty.
        text = read("SECURITY.md")
        self.assertIn("Out of scope", text)
        self.assertIn("echo tests passed", text)


class ReadmeCarriesTheTaxonomy(unittest.TestCase):
    def test_all_four_enforcement_classes_are_named(self):
        text = read("README.md")
        for cls in ENFORCEMENT_CLASSES:
            self.assertIn(cls, text)

    def test_profile_a_limitations_are_documented(self):
        text = read("README.md")
        self.assertIn("Explicit limitations (Profile A honesty)", text)
        self.assertIn("Bash writes are not blocked", text)

    def test_the_local_registry_cost_is_documented(self):
        # D-35 traded principle #3 for keeping .cgel/ out of git history.
        # A trade that is never written down reads as a free win later.
        text = read("README.md")
        self.assertIn("The registry is local, never shared", text)
        self.assertIn("D-35", text)


if __name__ == "__main__":
    unittest.main()
