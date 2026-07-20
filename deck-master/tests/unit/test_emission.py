"""The serializer must not be able to construct an invalid attribute.

Detecting a defect after the fact is worth less than making it unconstructible.
These two classes of defect are the serializer's own responsibility rather than
the content's, so they are fixed at the point of emission:

* a non-finite number reaching an attribute the schema types as an integer
* a control character XML forbids outright, which cannot be escaped because the
  escape sequence is itself illegal

Both are documented causes of PowerPoint's repair prompt, and both arose in
mature libraries from ordinary arithmetic and ordinary pasted text.
"""

from __future__ import annotations

import zipfile

import pytest

from deckmaster.layout import layout_deck
from deckmaster.model import Deck, TitleSlide
from deckmaster.serialize.pptx import emu, escape, hundredths, write_pptx
from deckmaster.theme import DEFAULT_THEME
from deckmaster.validate.opc import validate_package


class TestNumericGuard:
    def test_ordinary_values_convert(self):
        assert emu(1.0) == 12700
        assert emu(0.0) == 0
        assert emu(-1.0) == -12700

    def test_result_is_always_an_integer(self):
        """A decimal point in an EMU attribute is a schema violation.

        Python 3 true division producing '914400.0' is a documented repair
        cause, so the type is asserted rather than assumed.
        """
        for value in (0.1, 1.5, 33.333333, 959.9999):
            assert isinstance(emu(value), int)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_is_refused(self, bad):
        with pytest.raises(ValueError, match="non-finite"):
            emu(bad)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf")])
    def test_non_finite_hundredths_are_refused(self, bad):
        with pytest.raises(ValueError, match="non-finite"):
            hundredths(bad, "font size")

    def test_the_error_names_the_value_and_blames_the_right_layer(self):
        with pytest.raises(ValueError) as exc:
            emu(float("nan"))
        message = str(exc.value)
        assert "nan" in message.lower()
        assert "content" in message  # points at arithmetic, not the author's text


class TestEscaping:
    def test_markup_characters_are_escaped(self):
        assert escape('a & b < c > d "e"') == "a &amp; b &lt; c &gt; d &quot;e&quot;"

    def test_ampersand_is_escaped_first(self):
        """Otherwise the escapes introduced below would themselves be escaped."""
        assert escape("&lt;") == "&amp;lt;"

    def test_control_characters_are_stripped_not_encoded(self):
        """`&#x1F;` is itself illegal in XML 1.0, so encoding is not an option."""
        assert escape("before\x1fafter") == "beforeafter"
        assert escape("\x00\x01\x08") == ""

    def test_permitted_whitespace_survives(self):
        assert escape("a\tb\nc\rd") == "a\tb\nc\rd"

    def test_ordinary_text_is_untouched(self):
        assert escape("Plain title") == "Plain title"


def test_control_characters_are_refused_at_the_model_first(tmp_path):
    """The stripping in `escape` is the second line of defence, not the first.

    Content entering the model is checked against the metrics table, and a
    control character is not in it, so the failure names the field rather than
    silently deleting a character the author typed. That is the better outcome:
    stripping is what you want when nothing else can be done, not when the field
    is still known.
    """
    from deckmaster.text.metrics import UnsupportedCharacter

    with pytest.raises(UnsupportedCharacter) as exc:
        Deck(title="Deck", slides=(TitleSlide(title="R&D \x01 test"),))
    assert "slide title" in str(exc.value)
    assert "U+0001" in str(exc.value)


def test_markup_characters_survive_the_whole_pipeline(tmp_path):
    """Ampersands and angle brackets are legitimate content, not defects.

    They are also what breaks a naive writer, so this drives the real public API
    and then validates the package rather than inspecting `escape` alone.
    """
    deck = Deck(
        title="Ampersands & angles <b>",
        author='Quote " and & ampersand',
        slides=(
            TitleSlide(
                title="R&D <scale> test",
                subtitle='He said "yes" & left — 5 min',
            ),
        ),
    )
    path = tmp_path / "markup.pptx"
    write_pptx(layout_deck(deck, DEFAULT_THEME), path)

    report = validate_package(path)
    assert report.ok, "\n".join(report.errors)

    with zipfile.ZipFile(path) as archive:
        slide = archive.read("ppt/slides/slide1.xml").decode("utf-8")
        core = archive.read("docProps/core.xml").decode("utf-8")

    assert "R&amp;D &lt;scale&gt;" in slide
    assert "&amp;" in core  # the author field escaped too, not just slide text
