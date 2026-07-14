"""ARCHITECT.md is English, and still says what it said.

The document is the project's design record and the most substantive thing
in the repo; publishing it in a language most of the audience cannot read
wastes it. But a translation has a failure mode a spellcheck cannot catch:
fluent English that quietly drops or softens a decision. Checking only for
"no Vietnamese left" would be passed by an empty file, so the assertions
below pin the decision log, the load-bearing phrases, and the size.
"""

import os
import re
import unittest

from hookrunner import REPO_ROOT

ARCHITECT_PATH = os.path.join(REPO_ROOT, "ARCHITECT.md")

VIETNAMESE_RE = re.compile(
    "[ăâđêôơưĂÂĐÊÔƠƯ"
    "áàảãạấầẩẫậắằẳẵặ"
    "éèẻẽẹếềểễệ"
    "íìỉĩị"
    "óòỏõọốồổỗộớờởỡợ"
    "úùủũụứừửữự"
    "ýỳỷỹỵ]",
    re.I,
)

# Every id that appears literally in the source document. The decision log is
# the point of the file: an id that vanishes in translation is a decision
# nobody can cite afterwards.
DECISION_IDS = (
    "D-1", "D-3", "D-4", "D-12", "D-13", "D-17", "D-26", "D-30",
    "D-31", "D-32", "D-33", "D-34", "D-35",
    "X-1", "X-8", "X-10", "X-12",
    "V-1", "V-2", "V-3", "V-4", "V-5", "V-7",
)

REQUIRED_PHRASES = (
    "Contract-Gated Evidence Loop",
    "HARD_ENFORCED",
    "EVIDENCE_GATED",
    "HUMAN_GATED",
    "GUIDANCE_ONLY",
    "tamper-evident",
    "tamper-proof",
    "Profile A",
    "Profile B",
    "not a hard trust boundary",
)

# The Vietnamese original was 33792 bytes. English runs a little longer than
# Vietnamese for the same content, so anything much under this lost material.
MIN_LENGTH = 28000


def architect():
    with open(ARCHITECT_PATH, encoding="utf-8") as fh:
        return fh.read()


class VacuousPassGuard(unittest.TestCase):
    def test_document_is_found_and_substantial(self):
        # Without this, "no Vietnamese characters" would pass on an empty
        # or truncated file.
        self.assertGreater(
            len(architect()),
            MIN_LENGTH,
            "ARCHITECT.md is far shorter than the original — content was lost",
        )


class DocumentIsEnglish(unittest.TestCase):
    def test_no_vietnamese_text_remains(self):
        text = architect()
        leftovers = []
        for number, line in enumerate(text.splitlines(), 1):
            if VIETNAMESE_RE.search(line):
                leftovers.append("%d: %s" % (number, line.strip()[:70]))
        self.assertEqual(
            leftovers,
            [],
            "untranslated lines remain:\n%s" % "\n".join(leftovers[:10]),
        )


class TranslationIsFaithful(unittest.TestCase):
    def test_every_decision_id_survives(self):
        text = architect()
        for decision_id in DECISION_IDS:
            self.assertRegex(
                text,
                r"\b%s\b" % re.escape(decision_id),
                "%s is gone — a decision that can no longer be cited" % decision_id,
            )

    def test_load_bearing_phrases_survive(self):
        text = architect()
        for phrase in REQUIRED_PHRASES:
            self.assertIn(phrase, text, "%r did not survive translation" % phrase)

    def test_d35_override_and_its_cost_survive(self):
        # The override is only honest while the price stays written next to it.
        text = architect()
        self.assertIn("D-35", text)
        self.assertIn("principle #3", text)


if __name__ == "__main__":
    unittest.main()
