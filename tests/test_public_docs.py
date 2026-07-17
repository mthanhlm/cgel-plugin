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
import re
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


class TheProductionBarIsDescribedAsItIs(unittest.TestCase):
    """Every public description of the built-in rules must agree with
    plugin/rules/builtin.md, which is the only thing the parser reads.

    "Four blocking rules" was true of the prose and false of the product, and
    the prose is what a user decides to trust."""

    def _blocking(self):
        source = read("plugin", "rules", "builtin.md")
        rules = {}
        current = None
        for line in source.splitlines():
            if line.startswith("## CGEL-"):
                current = line.split()[1]
            elif line.startswith("Blocking:") and current:
                rules[current] = line.split(":", 1)[1].strip() == "yes"
        return rules

    def test_two_block_and_two_advise(self):
        rules = self._blocking()
        self.assertEqual(
            {r for r, b in rules.items() if b}, {"CGEL-IMPACT-1", "CGEL-SECRET-1"}
        )
        self.assertEqual(
            {r for r, b in rules.items() if not b},
            {"CGEL-DEBT-1", "CGEL-COMMENT-1"},
        )

    def _every_shipped_description(self):
        """README + manifest + every skill/agent/rule the model reads.

        This used to check README and the manifest only, while the docstring
        claimed "every public description" — and that gap is exactly what let
        loop/SKILL.md go on calling CGEL-DEBT-1 blocking after it was
        demoted. A test whose stated property is wider than its coverage is
        the same defect it is meant to catch."""
        yield "README.md", read("README.md")
        yield "plugin.json", plugin_manifest()["description"]
        for sub in ("skills", "agents", "rules", "commands"):
            base = os.path.join(PLUGIN_ROOT, sub)
            for root, _, files in os.walk(base):
                for name in files:
                    if not name.endswith(".md"):
                        continue
                    path = os.path.join(root, name)
                    with open(path, encoding="utf-8") as fh:
                        yield os.path.relpath(path, PLUGIN_ROOT), fh.read()

    def test_no_shipped_prose_calls_all_four_blocking(self):
        for label, text in self._every_shipped_description():
            flat = " ".join(text.split())
            self.assertNotIn("Four blocking rules", flat, label)
            self.assertNotIn("four blocking rules", flat, label)
            self.assertNotIn("blocking review rules (impacted code", flat, label)

    def test_no_shipped_prose_calls_an_advisory_rule_blocking(self):
        # The specific stale claim the verifier found: prose asserting that a
        # demoted rule still blocks.
        advisory = {r for r, b in self._blocking().items() if not b}
        for label, text in self._every_shipped_description():
            flat = " ".join(text.split())
            for rule_id in advisory:
                for claim in (
                    "%s are blocking" % rule_id,
                    "%s is blocking" % rule_id,
                    "%s blocks" % rule_id,
                ):
                    self.assertNotIn(claim, flat, "%s: %s" % (label, claim))
            # ...and the compound form that named two rules at once.
            self.assertNotIn(
                "CGEL-IMPACT-1 and CGEL-DEBT-1 are blocking", flat, label
            )

    def test_the_readme_names_which_rules_block(self):
        readme = " ".join(read("README.md").split())
        for rule_id in ("CGEL-IMPACT-1", "CGEL-SECRET-1"):
            self.assertIn(rule_id, readme)
        self.assertIn("Two block and two advise", readme)


class TheRiskLevelIsDocumentedAsAClaim(unittest.TestCase):
    """risk.level decides whether anything grades the work. It used to
    default to `low` — the level at which nothing does — and no document
    said so."""

    def test_readme_says_there_is_no_default(self):
        readme = " ".join(read("README.md").split())
        self.assertIn("no default", readme)
        self.assertIn("risk.level", readme)

    def test_the_task_skill_does_not_teach_a_reflex_low(self):
        # The worked example used `Risk: low` on an auth fix, which is the
        # reflex the old default trained.
        skill = " ".join(read("plugin", "skills", "task", "SKILL.md").split())
        self.assertNotIn("Risk: low — no API change", skill)
        self.assertIn("there is no default", skill)


class TheSchemasMatchTheValidator(unittest.TestCase):
    """A schema that disagrees with the validator is the same defect as a doc
    that disagrees with the code — and worse here, because task/SKILL.md tells
    the model to READ the contract schema. `default: "low"` in the schema
    taught exactly the reflex the validator now rejects.

    Caught by the verifier on this very task: the deletion was half-done."""

    def _schema(self, name):
        return json.loads(read("plugin", "schemas", name))

    def test_risk_is_required_and_has_no_default(self):
        risk = self._schema("task-contract.schema.json")["properties"]["risk"]
        self.assertNotIn("default", risk["properties"]["level"])
        self.assertEqual(set(risk["required"]), {"level", "reasons"})
        self.assertEqual(risk["properties"]["reasons"]["minItems"], 1)

    def test_the_contract_schema_requires_risk(self):
        self.assertIn("risk", self._schema("task-contract.schema.json")["required"])

    def test_the_retired_exceptions_key_is_gone_from_the_schema(self):
        self.assertNotIn(
            "exceptions", self._schema("task-contract.schema.json")["properties"]
        )

    def test_the_attestation_schema_does_not_advertise_unbuilt_policies(self):
        desc = self._schema("attestation.schema.json")["description"]
        self.assertNotIn("local (default) | ci-artifact", desc)
        self.assertIn("`local` only", desc)


class TheDecisionLogHasNoDanglingCitations(unittest.TestCase):
    """Every `D-NN` a document cites must be a decision the log defines.

    Found by the verifier, on the very task whose purpose was deleting
    pointers to things that do not exist: a correction here cited "see 15.11,
    D-46" when D-46 did not exist yet. The log is the repo's own claim that
    its history is recorded; a citation to a decision nobody wrote is the
    same defect as a schema field nothing reads."""

    def _text(self):
        return read("ARCHITECT.md") + read("ROADMAP.md") + read("README.md")

    def test_every_cited_decision_is_defined(self):
        architect = read("ARCHITECT.md")
        # Two shapes, both real: D-1..D-34 are accepted en bloc in 15.11
        # ("Accepted (D-1 … D-34)", with D-31..D-34 spelled out inline);
        # every post-v1.0 amendment gets its own **D-NN heading.
        amendments = set(re.findall(r"^\*\*(D-\d+)", architect, re.M))
        accepted_en_bloc = {"D-%d" % n for n in range(1, 35)}
        defined = amendments | accepted_en_bloc
        cited = {"D-" + n for n in re.findall(r"\bD-(\d+)\b", self._text())}
        dangling = cited - defined
        self.assertEqual(
            dangling,
            set(),
            "cited but never defined in ARCHITECT's decision log: %s"
            % ", ".join(sorted(dangling)),
        )

    def test_the_en_bloc_range_is_the_one_the_log_declares(self):
        # Guards the assumption above: if the log's accepted range moves, the
        # test must move with it rather than quietly widening.
        self.assertIn("**Accepted (D-1 … D-34):**", read("ARCHITECT.md"))

    def test_the_log_records_this_release(self):
        self.assertIn("**D-46", read("ARCHITECT.md"))

    def test_the_readme_does_not_understate_the_log(self):
        # README claimed "decision log D-1..D-34" while the log ran to D-45 —
        # a reader following the pointer found eleven decisions they were not
        # told about, including every one that changed what the gate does.
        readme = " ".join(read("README.md").split())
        self.assertNotIn("decision log D-1..D-34", readme)
        highest = max(
            int(n) for n in re.findall(r"^\*\*D-(\d+)", read("ARCHITECT.md"), re.M)
        )
        self.assertIn("D-%d" % highest, readme)


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
