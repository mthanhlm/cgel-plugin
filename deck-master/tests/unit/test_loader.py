"""The loader takes untrusted input, so malformed input must produce a message.

Every case here is something a hand-written or model-written spec plausibly
contains. The requirement is not that the loader accepts it -- it is that the
failure names the offending field instead of surfacing a traceback from deep
inside the parser.
"""

from __future__ import annotations

import json

import pytest

from deckmaster.loader import DeckSpecError, deck_from_dict, deck_from_json

VALID = {
    "title": "Spec",
    "slides": [{"type": "title", "title": "A claim worth making"}],
}


def test_a_valid_spec_loads():
    assert len(deck_from_dict(VALID).slides) == 1


@pytest.mark.parametrize(
    "spec",
    [
        pytest.param({"slides": [{"type": "title", "title": "x"}]}, id="missing-deck-title"),
        pytest.param({"title": "t"}, id="missing-slides"),
        pytest.param({"title": "t", "slides": []}, id="empty-slides"),
        pytest.param({"title": "t", "slides": "nope"}, id="slides-not-a-list"),
        pytest.param({"title": "t", "slides": [None]}, id="null-slide"),
        pytest.param({"title": "t", "slides": [5]}, id="scalar-slide"),
        pytest.param({"title": "t", "slides": [{"type": "title"}]}, id="slide-missing-title"),
        pytest.param({"title": "t", "slides": [{"type": "wat", "title": "x"}]}, id="unknown-type"),
        pytest.param(
            {"title": "t", "slides": [{"type": "key_value", "title": "x", "entries": [5]}]},
            id="scalar-entry",
        ),
        pytest.param(
            {"title": "t", "slides": [{"type": "key_value", "title": "x", "entries": "no"}]},
            id="entries-not-a-list",
        ),
        pytest.param(
            {"title": "t", "slides": [{"type": "diagram", "title": "x", "ranks": [None]}]},
            id="null-rank",
        ),
        pytest.param(
            {"title": "t", "slides": [{"type": "diagram", "title": "x", "ranks": [{"nodes": [None]}]}]},
            id="null-node",
        ),
        pytest.param(
            {
                "title": "t",
                "slides": [
                    {
                        "type": "diagram",
                        "title": "x",
                        "ranks": [{"nodes": [{"id": "a", "label": "A"}]}],
                        "edges": [None],
                    }
                ],
            },
            id="null-edge",
        ),
        pytest.param("not an object", id="top-level-not-an-object"),
        pytest.param(None, id="top-level-null"),
    ],
)
def test_malformed_specs_raise_a_clear_error(spec):
    """Never a TypeError or AttributeError from inside the parser."""
    with pytest.raises(DeckSpecError):
        deck_from_dict(spec)


def test_missing_file_reports_the_path(tmp_path):
    with pytest.raises(DeckSpecError, match="cannot read"):
        deck_from_json(tmp_path / "nope.json")


def test_invalid_json_reports_a_syntax_problem(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(DeckSpecError, match="not valid JSON"):
        deck_from_json(path)


def test_round_trip_from_a_file(tmp_path):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(VALID), encoding="utf-8")
    assert deck_from_json(path).title == "Spec"


def test_the_shipped_example_spec_loads():
    from tests.conftest import REPO_ROOT

    deck = deck_from_json(REPO_ROOT / "examples" / "pipeline_deck.json")
    assert len(deck.slides) == 5


def test_non_utf8_spec_reports_an_encoding_problem(tmp_path):
    """UnicodeDecodeError is a ValueError, not an OSError, so it needs its own arm."""
    path = tmp_path / "latin1.json"
    path.write_bytes('{"title": "café", "slides": []}'.encode("latin-1"))
    with pytest.raises(DeckSpecError, match="not valid UTF-8"):
        deck_from_json(path)


def test_unmeasurable_character_fails_at_load_naming_the_field():
    """A character with no metrics must fail here, not from inside layout.

    Reaching layout turns a content problem into a traceback with no indication
    of which slide caused it.
    """
    from deckmaster.text.metrics import UnsupportedCharacter

    with pytest.raises(UnsupportedCharacter) as exc:
        deck_from_dict({"title": "t", "slides": [{"type": "title", "title": "Costs 5 €"}]})
    assert "slide title" in str(exc.value)
    assert "U+20AC" in str(exc.value)
