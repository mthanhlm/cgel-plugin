"""Shared fixtures.

The example deck is the integration fixture for the whole suite: it exercises
every shipped idiom, so if the engine breaks, these tests break with it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

REFERENCE_DECK = REPO_ROOT / "kx-agent-spaces-roadmap-jul-sep-2026.pptx"


@pytest.fixture(scope="session")
def example_deck():
    from examples.pipeline_deck import build

    return build()


@pytest.fixture(scope="session")
def rendered_deck(example_deck):
    from deckmaster.layout import layout_deck
    from deckmaster.theme import DEFAULT_THEME

    return layout_deck(example_deck, DEFAULT_THEME)


@pytest.fixture(scope="session")
def built_pptx(rendered_deck, tmp_path_factory) -> Path:
    from deckmaster.serialize.pptx import write_pptx

    path = tmp_path_factory.mktemp("deck") / "example.pptx"
    write_pptx(rendered_deck, path)
    return path
