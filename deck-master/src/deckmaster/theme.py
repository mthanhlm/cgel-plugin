"""Design tokens: the deck's whole visual vocabulary in one place.

Nothing downstream is allowed to invent a colour, a size, or a gap. Layout code
asks the theme for a token; if the token does not exist, the answer is to add it
here deliberately, not to hardcode a value at the call site. This is the single
rule that keeps a deck from drifting to eight colours by the third edit.

The vocabulary is derived from the reference deck's visual grammar, corrected on
three points where that deck used renderer defaults rather than deliberate
choices: pure black connectors, pure white paper, and untinted greys all read as
"untouched template" and are replaced here with tinted equivalents.
"""

from __future__ import annotations

from dataclasses import dataclass


# --------------------------------------------------------------------------
# Colour
# --------------------------------------------------------------------------


def _srgb_channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    """WCAG relative luminance of an ``RRGGBB`` colour."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"expected a 6-digit hex colour, got {hex_color!r}")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _srgb_channel(r) + 0.7152 * _srgb_channel(g) + 0.0722 * _srgb_channel(b)


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG contrast ratio between two colours, from 1.0 to 21.0."""
    l1, l2 = relative_luminance(fg), relative_luminance(bg)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


@dataclass(frozen=True, slots=True)
class Surface:
    """A fill paired with the ink that is legible on it.

    Pairing them in one object is deliberate. The most common mechanical defect
    in a generated deck is a shape whose fill changed while its text colour did
    not, leaving dark text on a dark fill. Making ink inseparable from fill means
    that defect cannot be expressed.
    """

    fill: str
    ink: str
    muted_ink: str
    stroke: str | None = None

    def contrast(self) -> float:
        return contrast_ratio(self.ink, self.fill)

    def muted_contrast(self) -> float:
        return contrast_ratio(self.muted_ink, self.fill)


@dataclass(frozen=True, slots=True)
class Palette:
    """Four layers: paper, ink, a neutral ramp, and exactly one accent."""

    paper: str = "FBFCFD"  # cool-tinted white; never pure FFFFFF
    paper_dark: str = "1B2732"  # dark-slide ground, L ~15%
    ink: str = "22303C"  # primary text on light
    ink_inverse: str = "F2F5F8"  # primary text on dark
    muted: str = "5B6670"  # secondary text on light
    muted_inverse: str = "9AA4AE"  # secondary text on dark

    # Neutral ramp, all carrying a slight cool tint toward the accent hue.
    neutral_100: str = "EEF2F6"  # panel fill
    neutral_200: str = "DCE4EC"  # emphasised panel fill
    neutral_300: str = "D9E0E6"  # hairline rules
    neutral_600: str = "3D4A57"  # connectors; never pure black

    # Exactly one accent, plus a darker and lighter tone of the same hue.
    accent: str = "1F5FA8"
    accent_dark: str = "123A66"
    accent_light: str = "4F86C4"

    # ---- Surfaces: every fill in the system, pre-paired with its ink ----

    @property
    def light(self) -> Surface:
        return Surface(fill=self.paper, ink=self.ink, muted_ink=self.muted)

    @property
    def dark(self) -> Surface:
        return Surface(fill=self.paper_dark, ink=self.ink_inverse, muted_ink=self.muted_inverse)

    @property
    def panel(self) -> Surface:
        return Surface(fill=self.neutral_100, ink=self.ink, muted_ink=self.muted)

    @property
    def panel_strong(self) -> Surface:
        return Surface(fill=self.neutral_200, ink=self.ink, muted_ink=self.muted)

    @property
    def accent_solid(self) -> Surface:
        # Ink flips to near-white here; this is the pairing that prevents the
        # dark-text-on-dark-fill defect.
        return Surface(fill=self.accent, ink="FFFFFF", muted_ink="D6E3F2")


# --------------------------------------------------------------------------
# Type
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TypeScale:
    """A 1.25-ratio scale, capped at five sizes for the whole deck.

    Additional hierarchy comes from weight and colour, not from a sixth size:
    at projection distance a single 1.25 step reads as an accident rather than
    as a level.

    The floor is 14 pt on a 540 pt canvas -- roughly 18 px at 720p. Slides are
    read at three to ten metres, so the comfortable web floor is far too small.
    """

    display: float = 48.0  # title-slide statement
    title: float = 31.0  # slide titles
    lead: float = 20.0  # subtitle / deck line
    body: float = 16.0  # node labels, key-value values
    micro: float = 14.0  # edge labels, footnotes -- the absolute floor

    family: str = "Arial"

    # Weight contrast is 300 units, so hierarchy survives projection.
    weight_regular: int = 400
    weight_bold: int = 700

    # Line heights: tight for display, open for prose.
    lh_display: float = 1.08
    lh_title: float = 1.12
    lh_lead: float = 1.35
    lh_body: float = 1.40
    lh_label: float = 1.25

    def all_sizes(self) -> tuple[float, ...]:
        return (self.display, self.title, self.lead, self.body, self.micro)


# --------------------------------------------------------------------------
# Space
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SpaceScale:
    """A 4 pt base scale. Every gap, inset and offset comes from here.

    An arbitrary value -- a shape nudged by eye to 17 pt -- is the single most
    reliable sign that a layout was assembled by hand rather than designed.
    """

    xs: float = 4.0
    sm: float = 8.0
    md: float = 12.0
    lg: float = 16.0
    xl: float = 24.0
    x2: float = 32.0
    x3: float = 48.0
    x4: float = 64.0
    x5: float = 96.0
    x6: float = 128.0

    def steps(self) -> tuple[float, ...]:
        return (self.xs, self.sm, self.md, self.lg, self.xl, self.x2, self.x3, self.x4, self.x5, self.x6)

    def is_on_scale(self, value: float, tolerance: float = 0.01) -> bool:
        return any(abs(value - step) < tolerance for step in self.steps())


@dataclass(frozen=True, slots=True)
class Theme:
    """The complete visual system for a deck."""

    palette: Palette = Palette()
    type_scale: TypeScale = TypeScale()
    space: SpaceScale = SpaceScale()

    #: Outer safe margins, identical on every slide. Content touching the slide
    #: edge reads as an overflow accident rather than as a full-bleed decision.
    #:
    #: They differ because the canvas does. On a 960x540 pt slide, 64 pt is 6.7%
    #: of the width but 11.9% of the height -- the same number is a comfortable
    #: side margin and a wasteful top one. Matching the *optical* inset rather
    #: than the numeric one is what keeps the body area usable.
    margin: float = 64.0
    margin_y: float = 48.0

    #: Stroke weights. Below 1 pt, lines disappear when projected.
    hairline: float = 1.0
    stroke: float = 1.5
    stroke_strong: float = 2.0

    #: Accent may cover at most this fraction of a slide's area. Beyond it,
    #: nothing is emphasised because everything is.
    max_accent_area: float = 0.05

    #: Contrast floors. Body text is held to the WCAG AA threshold; shape
    #: outlines are held to the UI-component threshold, because a hairline at
    #: 2:1 vanishes on a poor projector.
    min_text_contrast: float = 4.5
    min_stroke_contrast: float = 3.0

    @property
    def content_width(self) -> float:
        from .units import CANVAS_W_PT

        return CANVAS_W_PT - 2 * self.margin

    @property
    def content_height(self) -> float:
        from .units import CANVAS_H_PT

        return CANVAS_H_PT - 2 * self.margin_y


DEFAULT_THEME = Theme()
