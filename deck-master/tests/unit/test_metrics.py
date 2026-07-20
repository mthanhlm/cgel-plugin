"""Text measurement is the foundation every layout guarantee rests on."""

from __future__ import annotations

import pytest

from deckmaster.text.metrics import (
    TextStyle,
    UnsupportedCharacter,
    layout_text,
    measure,
    wrap,
)


def test_widths_match_published_arial_metrics():
    """The table must be Arial's, not an approximation of it.

    These are the published advance widths in 1/1000 em. If the extraction ever
    silently picks up a different font, this is what notices.
    """
    style = TextStyle(1000.0)  # 1000pt makes 1 unit == 1/1000 em
    expected = {" ": 278, "A": 667, "M": 833, "W": 944, "a": 556, "i": 222, "0": 556, ".": 278}
    for char, width in expected.items():
        assert round(measure(char, style)) == width, char


def test_bold_is_wider_than_regular():
    regular = TextStyle(16.0, bold=False)
    bold = TextStyle(16.0, bold=True)
    assert measure("Hamburgefonstiv", bold) > measure("Hamburgefonstiv", regular)


def test_measurement_scales_linearly_with_size():
    assert measure("Deck", TextStyle(32.0)) == pytest.approx(2 * measure("Deck", TextStyle(16.0)))


def test_unknown_codepoint_is_rejected_not_measured_as_zero():
    """A missing glyph must raise.

    Measuring it as zero would size a box smaller than its own text, which is
    the exact defect the audit exists to prevent -- and it would do so silently.
    """
    with pytest.raises(UnsupportedCharacter) as exc:
        measure("hello 世界", TextStyle(16.0))
    assert "U+4E16" in str(exc.value)


def test_wrap_never_exceeds_the_given_width():
    style = TextStyle(16.0)
    text = "The layout engine measures text before it sizes any box that has to hold it."
    for line in wrap(text, style, 200.0):
        assert measure(line, style) <= 200.0


def test_wrap_honours_hard_newlines():
    assert wrap("one\ntwo", TextStyle(16.0), 500.0) == ["one", "two"]


def test_overlong_word_is_not_silently_hyphenated():
    """Splitting a word is a content decision the engine must not make alone."""
    style = TextStyle(16.0)
    lines = wrap("antidisestablishmentarianism", style, 40.0)
    assert lines == ["antidisestablishmentarianism"]
    assert measure(lines[0], style) > 40.0  # left for the audit to report


def test_layout_height_includes_headroom():
    style = TextStyle(16.0, line_height=1.4)
    block = layout_text("one line", style, 500.0)
    assert block.line_count == 1
    assert block.height_pt > style.line_pt  # cushion applied


def test_measurement_is_deterministic():
    style = TextStyle(16.0)
    assert measure("determinism", style) == measure("determinism", style)


def test_documented_character_set_matches_the_table():
    """Guards the claim in SKILL.md against the data that backs it.

    A documented character the table lacks would be rejected at load with an
    error the author was told not to expect, which is worse than not documenting
    it at all.
    """
    from deckmaster.text.metrics import supported_codepoints

    supported = supported_codepoints()
    for char in "$£—–“”‘’…•→°×":
        assert ord(char) in supported, f"{char!r} is documented as supported but is missing"
    for char in "€✓":
        assert ord(char) not in supported, f"{char!r} is documented as unsupported but is present"


def test_weight_tables_have_matching_coverage():
    """Validation checks one set of codepoints; measurement selects by weight.

    If a character existed in regular but not bold, it would pass validation at
    load and then fail from inside layout on a bold run -- exactly the late,
    misattributed failure that validating early exists to prevent.
    """
    from deckmaster.text.metrics import _tables

    tables = _tables()
    assert set(tables["regular"]) == set(tables["bold"])


def test_supported_codepoints_is_the_intersection_of_all_weights():
    from deckmaster.text.metrics import _tables, supported_codepoints

    expected = frozenset.intersection(*(frozenset(t) for t in _tables().values()))
    assert supported_codepoints() == expected
