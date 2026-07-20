"""Content limits and typographic normalisation, enforced at construction."""

from __future__ import annotations

import pytest

from deckmaster.model import (
    ContentTooLong,
    Deck,
    Edge,
    Entry,
    Flow,
    KeyValueSlide,
    Node,
    Rank,
    TitleSlide,
)
from deckmaster.typography import normalize


class TestTypography:
    def test_straight_quotes_become_typographic(self):
        assert normalize('He said "no"') == "He said “no”"

    def test_apostrophe_inside_a_word_closes(self):
        assert normalize("it's") == "it’s"

    def test_three_periods_become_an_ellipsis(self):
        assert normalize("wait...") == "wait…"

    def test_double_hyphen_becomes_an_em_dash(self):
        assert normalize("this -- that") == "this—that"

    def test_numeric_range_uses_an_en_dash(self):
        assert normalize("2024-2026") == "2024–2026"

    def test_quarter_range_uses_an_en_dash(self):
        assert normalize("Q1-Q3") == "Q1–Q3"

    def test_unit_takes_a_non_breaking_space(self):
        assert normalize("5 min") == "5 min"

    def test_longest_unit_wins_over_a_shorter_prefix(self):
        """'min' must not be matched as 'm' followed by stray text."""
        assert normalize("5 min") == "5 min"
        assert normalize("5 m") == "5 m"


class TestContentLimits:
    def test_overlong_title_is_rejected(self):
        with pytest.raises(ContentTooLong):
            TitleSlide(title="A title so long that it stopped being a title and became a paragraph instead")

    def test_empty_title_is_rejected(self):
        with pytest.raises(ValueError):
            TitleSlide(title="   ")

    def test_overlong_node_label_is_rejected(self):
        with pytest.raises(ContentTooLong):
            Node(id="n", label="This node label is far too long to sit inside a box")

    def test_titles_are_normalised_on_construction(self):
        assert TitleSlide(title='The "one" message').title == "The “one” message"

    def test_key_value_slide_caps_entries(self):
        entries = tuple(Entry(label=f"Label {i}", body=f"Body {i}") for i in range(5))
        with pytest.raises(ValueError, match="2-4 entries"):
            KeyValueSlide(title="Too many rows", entries=entries)


class TestFlow:
    def _rank(self, *ids):
        return Rank(nodes=tuple(Node(id=i, label=i.title()) for i in ids))

    def test_duplicate_node_ids_are_rejected(self):
        with pytest.raises(ValueError, match="duplicate node ids"):
            Flow(ranks=(self._rank("a"), self._rank("a")))

    def test_edge_to_unknown_node_is_rejected(self):
        with pytest.raises(ValueError, match="unknown node"):
            Flow(ranks=(self._rank("a"),), edges=(Edge(source="a", target="ghost"),))

    def test_self_edge_is_rejected(self):
        with pytest.raises(ValueError, match="itself"):
            Edge(source="a", target="a")

    def test_boxed_rank_requires_a_label(self):
        with pytest.raises(ValueError, match="needs a label"):
            Rank(nodes=(Node(id="a", label="A"),), boxed=True)


def test_deck_requires_at_least_one_slide():
    with pytest.raises(ValueError):
        Deck(title="Empty", slides=())
