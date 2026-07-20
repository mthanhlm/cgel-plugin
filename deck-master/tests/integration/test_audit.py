"""The audit must pass a good deck and fail a broken one.

A gate that only ever passes is indistinguishable from no gate, so most of this
file constructs slides with a specific defect and asserts the audit names it.
"""

from __future__ import annotations

from deckmaster.audit import BLOCKING, audit_deck, audit_slide
from deckmaster.scene import Align, LineShape, RectShape, RenderedSlide, Stroke, TextShape
from deckmaster.theme import DEFAULT_THEME
from deckmaster.units import Rect

THEME = DEFAULT_THEME


def _messages(slide: RenderedSlide) -> str:
    return " | ".join(f.message for f in audit_slide(slide, THEME, 1))


def _blocking(slide: RenderedSlide):
    return [f for f in audit_slide(slide, THEME, 1) if f.severity == BLOCKING]


class TestTheExampleDeckIsClean:
    def test_no_blocking_findings(self, rendered_deck):
        report = audit_deck(rendered_deck, THEME)
        assert report.ok, "\n".join(f"slide {f.slide}: {f.message}" for f in report.blocking)

    def test_report_is_truthy_when_clean(self, rendered_deck):
        assert audit_deck(rendered_deck, THEME)


class TestBlockingFindings:
    def test_text_wider_than_its_box(self):
        slide = RenderedSlide(
            background=THEME.palette.paper,
            shapes=(
                TextShape(
                    name="Too wide",
                    rect=Rect(64, 64, 40, 40),
                    lines=("a line far wider than forty points",),
                    size_pt=16.0,
                    color=THEME.palette.ink,
                ),
            ),
        )
        assert _blocking(slide)
        assert "wide" in _messages(slide)

    def test_text_taller_than_its_box(self):
        slide = RenderedSlide(
            background=THEME.palette.paper,
            shapes=(
                TextShape(
                    name="Too tall",
                    rect=Rect(64, 64, 400, 10),
                    lines=("one", "two", "three"),
                    size_pt=16.0,
                    color=THEME.palette.ink,
                ),
            ),
        )
        assert _blocking(slide)
        assert "tall" in _messages(slide)

    def test_planned_line_that_would_re_wrap(self):
        """The independent part of the fits-check.

        A stored line count compared against a height derived from that same
        count can never disagree. Re-breaking each line at the real box width is
        what a renderer will actually do, so that is what gets recomputed.
        """
        slide = RenderedSlide(
            background=THEME.palette.paper,
            shapes=(
                TextShape(
                    name="Narrow box",
                    rect=Rect(64, 64, 60, 400),  # tall enough, far too narrow
                    lines=("this line was planned as one line but cannot stay one",),
                    size_pt=16.0,
                    color=THEME.palette.ink,
                ),
            ),
        )
        assert _blocking(slide)
        assert "re-wrap" in _messages(slide)

    def test_box_shorter_than_its_own_content(self):
        """Guards against a layout engine sizing a box smaller than its text."""
        slide = RenderedSlide(
            background=THEME.palette.paper,
            shapes=(
                TextShape(
                    name="Squashed",
                    rect=Rect(64, 64, 600, 8),
                    lines=("one line that needs more than eight points of height",),
                    size_pt=16.0,
                    color=THEME.palette.ink,
                ),
            ),
        )
        assert any("tall" in f.message for f in _blocking(slide))

    def test_shape_off_the_canvas(self):
        slide = RenderedSlide(
            background=THEME.palette.paper,
            shapes=(RectShape(name="Escapee", rect=Rect(900, 64, 200, 50), fill=THEME.palette.accent),),
        )
        assert _blocking(slide)
        assert "outside" in _messages(slide)

    def test_partial_overlap_between_shapes(self):
        slide = RenderedSlide(
            background=THEME.palette.paper,
            shapes=(
                RectShape(name="Left", rect=Rect(64, 64, 200, 50), fill=THEME.palette.neutral_100),
                RectShape(name="Right", rect=Rect(200, 64, 200, 50), fill=THEME.palette.neutral_100),
            ),
        )
        assert _blocking(slide)
        assert "overlaps" in _messages(slide)

    def test_containment_is_not_reported_as_overlap(self):
        """A label inside its node is the normal case, not a collision."""
        slide = RenderedSlide(
            background=THEME.palette.paper,
            shapes=(
                RectShape(name="Node", rect=Rect(64, 64, 300, 80), fill=THEME.palette.neutral_100),
                TextShape(
                    name="Node label",
                    rect=Rect(76, 72, 200, 24),
                    lines=("Inside",),
                    size_pt=16.0,
                    color=THEME.palette.ink,
                ),
            ),
        )
        assert not _blocking(slide)

    def test_arrow_ending_in_empty_space(self):
        slide = RenderedSlide(
            background=THEME.palette.paper,
            shapes=(
                RectShape(name="Node", rect=Rect(64, 64, 100, 50), fill=THEME.palette.neutral_100),
                LineShape(
                    name="Dangling edge",
                    x1=164, y1=89, x2=500, y2=89,
                    stroke=Stroke(THEME.palette.neutral_600, 1.0),
                    arrow_end=True,
                ),
            ),
        )
        assert _blocking(slide)
        assert "not on any shape" in _messages(slide)

    def test_dark_text_on_a_dark_fill(self):
        """The fill/ink pairing defect, injected by hand."""
        slide = RenderedSlide(
            background=THEME.palette.paper,
            shapes=(
                RectShape(name="Dark panel", rect=Rect(64, 64, 400, 100), fill=THEME.palette.paper_dark),
                TextShape(
                    name="Unreadable",
                    rect=Rect(80, 80, 300, 30),
                    lines=("invisible",),
                    size_pt=16.0,
                    color=THEME.palette.ink,  # dark ink on a dark fill
                ),
            ),
        )
        assert _blocking(slide)
        assert "contrast" in _messages(slide)


class TestAdvisoryFindings:
    def test_accent_over_budget(self):
        slide = RenderedSlide(
            background=THEME.palette.paper,
            shapes=(RectShape(name="Accent flood", rect=Rect(0, 0, 900, 400), fill=THEME.palette.accent),),
        )
        assert any("budget" in f.message for f in audit_slide(slide, THEME, 1))

    def test_off_scale_type_size(self):
        slide = RenderedSlide(
            background=THEME.palette.paper,
            shapes=(
                TextShape(
                    name="Odd size",
                    rect=Rect(64, 64, 600, 60),
                    lines=("seventeen point text",),
                    size_pt=17.0,
                    color=THEME.palette.ink,
                ),
            ),
        )
        assert any("not on the deck" in f.message for f in audit_slide(slide, THEME, 1))

    def test_empty_marketing_opening_in_a_title(self):
        slide = RenderedSlide(
            background=THEME.palette.paper,
            shapes=(
                TextShape(
                    name="Slide title",
                    rect=Rect(64, 48, 800, 60),
                    lines=("Supercharge your workflow",),
                    size_pt=31.0,
                    color=THEME.palette.ink,
                    bold=True,
                ),
            ),
        )
        findings = audit_slide(slide, THEME, 1)
        assert any("empty opening" in f.message for f in findings)
        # Taste is advisory: it is reported, but it does not stop a build.
        assert not [f for f in findings if f.severity == BLOCKING]
