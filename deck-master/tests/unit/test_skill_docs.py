"""The skill is read by a model, so a drifted instruction teaches the wrong thing.

Documentation that merely describes code can go stale quietly. Documentation
that *instructs* goes stale loudly and expensively: a command that no longer
exists produces a failed step, and a reviewer who then skips it. So the parts of
the skill that name commands are checked against the commands that exist.

This does not check prose quality, which nothing can. It checks the claims that
have a machine-verifiable counterpart.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL = REPO_ROOT / "skills" / "deck" / "SKILL.md"
AUDIT = REPO_ROOT / "skills" / "deck" / "references" / "audit.md"
PREVIEW = REPO_ROOT / "tools" / "preview.py"


def prose(path: Path) -> str:
    """Document text with line wrapping and emphasis flattened.

    Assertions about wording must survive reflowing a paragraph. Checking the
    raw text makes the test fail when a sentence wraps at a different column,
    which says nothing about whether the instruction is still there.
    """
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8").replace("*", ""))


def test_the_render_tool_exists_where_the_skill_says_it_does():
    assert PREVIEW.is_file(), "the skill instructs the reader to run a tool that is missing"


@pytest.mark.parametrize("document", [SKILL, AUDIT])
def test_documented_commands_are_real_subcommands(document):
    """Every `tools/preview.py <verb>` in the docs must be a verb the tool has.

    Checked against the parser's actual subcommand names, not against the text
    of `--help`. Matching the help output was the first attempt and was vacuous
    for `check`, because the word appears in the parser's own description -- so
    the verb could have been renamed or deleted and the test would still pass.

    The failure this prevents is specific: an instruction to run something that
    exits with a usage error, at the exact step where the reader is meant to be
    looking at pictures rather than debugging the tooling.
    """
    import argparse

    # Imported by putting tools/ on the path rather than through
    # spec_from_file_location: the tool defines slots=True dataclasses, and
    # building one requires its module to be registered in sys.modules, which
    # module_from_spec alone does not do.
    if str(REPO_ROOT / "tools") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "tools"))
    preview = pytest.importorskip("preview", reason="tools/preview.py not importable")

    subparsers = [
        action
        for action in preview.build_parser()._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    assert subparsers, "the render tool no longer defines any subcommands"
    available = set(subparsers[0].choices)

    documented = set(re.findall(r"tools/preview\.py\s+(\w+)", document.read_text(encoding="utf-8")))
    assert documented, f"{document.name} no longer mentions the render tool at all"

    missing = documented - available
    assert not missing, (
        f"{document.name} tells the reader to run {sorted(missing)}, which the tool "
        f"does not offer; it has {sorted(available)}"
    )


def test_the_skill_requires_looking_rather_than_suggesting_it():
    """The step has to read as mandatory, or it becomes the one that gets skipped."""
    text = prose(SKILL)
    assert "Look at it." in text, "the skill no longer has an explicit look-at-it step"
    assert "Not optional" in text, "the render step no longer reads as required"


def test_the_checklist_exists_and_is_specific():
    """A checklist short enough to skim is one that gets skimmed.

    Checked by counting the prompts a reviewer is asked to answer, not by
    length: the point is that the step cannot be satisfied by glancing.
    """
    text = AUDIT.read_text(encoding="utf-8")
    assert "## 2. Looking at the render" in text
    section = text.split("## 2. Looking at the render")[1].split("## 3.")[0]
    prompts = [line for line in section.splitlines() if line.startswith(("**", "- "))]
    assert len(prompts) >= 12, (
        f"the render checklist has only {len(prompts)} prompts; it was written with "
        "considerably more, so something has been trimmed away"
    )


def test_the_fix_cycle_is_bounded():
    """Unbounded polishing is its own failure mode, so the cap is asserted."""
    assert "One cycle" in prose(SKILL), "the skill no longer bounds the fix-and-verify loop"


def test_a_fresh_reviewer_is_requested():
    assert "different reviewer" in prose(SKILL), (
        "the skill no longer asks for a reviewer other than whoever built the deck"
    )
