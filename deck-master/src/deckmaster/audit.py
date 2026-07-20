"""The visual audit: the gate a slide must pass before it is written.

Two severities, and the distinction matters.

**Blocking** findings are geometric facts. Text that does not fit its box,
shapes that collide, content off the canvas, an arrow that ends in empty space --
these are defects with no judgement involved, and a deck carrying one is not
written to disk.

**Advisory** findings are matters of taste with a defensible rule behind them:
accent used past its budget, too many type sizes, a title opening with a phrase
that means nothing. These are reported, not enforced, because a human may have a
reason and the audit does not get to overrule them silently.

The audit deliberately re-derives what layout computed rather than trusting it.
Checking a claim against the same code that made it proves nothing; measuring the
final geometry independently is what makes this a gate rather than an assertion.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .scene import LineShape, RectShape, RenderedDeck, RenderedSlide, Shape, TextShape
from .text.metrics import HEIGHT_HEADROOM, TextStyle, measure, wrap
from .theme import Theme, contrast_ratio
from .units import CANVAS, CANVAS_H_PT, CANVAS_W_PT, Rect

BLOCKING = "blocking"
ADVISORY = "advisory"

#: Slack allowed when comparing measured text against its box, in points.
#: Absorbs float accumulation without hiding a real overflow.
TOLERANCE = 0.75

#: Openings that promise something and say nothing. A slide title is the worst
#: possible place for them, because it is the one line everyone reads.
EMPTY_OPENINGS = (
    "built for the modern",
    "unleash your",
    "empower your",
    "reimagine the way",
    "supercharge your",
    "innovative solution",
    "seamless integration",
    "in today's digital",
    "next-generation",
    "where * meets *",
)


@dataclass(frozen=True, slots=True)
class Finding:
    severity: str
    slide: int
    message: str
    shape: str = ""


@dataclass(slots=True)
class AuditReport:
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == BLOCKING]

    @property
    def advisory(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == ADVISORY]

    @property
    def ok(self) -> bool:
        return not self.blocking

    def __bool__(self) -> bool:
        return self.ok


def _bounds(shape: Shape) -> Rect:
    if isinstance(shape, (RectShape, TextShape)):
        return shape.rect
    if isinstance(shape, LineShape):
        return shape.bounds()
    raise TypeError(f"no bounds for {type(shape).__name__}")


def _text_style(shape: TextShape) -> TextStyle:
    return TextStyle(shape.size_pt, bold=shape.bold, line_height=shape.line_height)


def _behind(shape: TextShape, slide: RenderedSlide) -> str:
    """The fill a text shape actually sits on.

    Walks the shape list backwards so the topmost filled rectangle wins, which
    matches how the renderer composites. Falls back to the slide ground.
    """
    for other in reversed(slide.shapes):
        if other is shape:
            continue
        if isinstance(other, RectShape) and other.fill and other.rect.contains(shape.rect, tolerance=1.0):
            return other.fill
    return slide.background


def _check_on_canvas(slide: RenderedSlide, index: int, out: list[Finding]) -> None:
    for shape in slide.shapes:
        rect = _bounds(shape)
        if not CANVAS.contains(rect, tolerance=0.5):
            out.append(
                Finding(
                    BLOCKING,
                    index,
                    f"extends outside the {CANVAS_W_PT:.0f}x{CANVAS_H_PT:.0f} pt canvas "
                    f"(x {rect.x:.1f}..{rect.right:.1f}, y {rect.y:.1f}..{rect.bottom:.1f})",
                    shape.name,
                )
            )


def _check_text_fits(slide: RenderedSlide, index: int, out: list[Finding]) -> None:
    """Check that the planned text really fits the box it was given.

    Be precise about what each part of this proves.

    The **width** check is genuinely independent: it re-measures every line
    against the box actually emitted, and nothing about how that box was sized
    is taken on trust.

    The **re-wrap** check catches a specific, real class of bug: text wrapped at
    one width and then placed in a box of another. That is not hypothetical --
    edge labels are wrapped against the full content width and then given a box
    sized to the measured text, and an early version of that code produced a
    label that split a single word across two lines. When the two widths do
    match, re-wrapping is a no-op and this check is silent.

    The **height** check is a consistency assertion, not an independent one.
    Where a box was sized from the very text it holds, layout derived the height
    from the same line count used here, so the two agree by construction and it
    cannot fire. It earns its place guarding boxes sized from something else --
    a key-value row takes the height of the taller of its two columns -- and as
    a regression guard if a layout engine ever sizes a box too small.
    """
    for shape in slide.shapes:
        if not isinstance(shape, TextShape):
            continue
        style = _text_style(shape)

        rendered_lines = 0
        for line in shape.lines:
            if not line:
                rendered_lines += 1
                continue
            width = measure(line, style)
            if width > shape.rect.w + TOLERANCE:
                out.append(
                    Finding(
                        BLOCKING,
                        index,
                        f"line {line!r} needs {width:.1f} pt but its box is {shape.rect.w:.1f} pt wide",
                        shape.name,
                    )
                )
            # Re-break at the real box width rather than trusting the plan.
            split = wrap(line, style, max(shape.rect.w, 1.0))
            if len(split) > 1:
                out.append(
                    Finding(
                        BLOCKING,
                        index,
                        f"line {line!r} would re-wrap onto {len(split)} lines in a "
                        f"{shape.rect.w:.1f} pt box, pushing the text past its height",
                        shape.name,
                    )
                )
            rendered_lines += len(split)

        needed = rendered_lines * style.line_pt * (1 + HEIGHT_HEADROOM)
        if needed > shape.rect.h + TOLERANCE:
            out.append(
                Finding(
                    BLOCKING,
                    index,
                    f"{rendered_lines} rendered line(s) need {needed:.1f} pt "
                    f"but its box is {shape.rect.h:.1f} pt tall",
                    shape.name,
                )
            )


def _check_collisions(slide: RenderedSlide, index: int, out: list[Finding]) -> None:
    """Report shapes that overlap without one containing the other.

    Containment is legitimate and everywhere: a label sits inside its node, a
    node sits inside its group container. What is never legitimate is a partial
    overlap, which is always either a layout bug or an accident.

    Lines are excluded. A connector's bounding box necessarily crosses the gap
    between the nodes it joins, and treating that as a collision would flag
    every diagram that works.
    """
    solid = [s for s in slide.shapes if not isinstance(s, LineShape)]
    for i, a in enumerate(solid):
        for b in solid[i + 1 :]:
            ra, rb = _bounds(a), _bounds(b)
            if not ra.intersects(rb, tolerance=0.5):
                continue
            if ra.contains(rb, tolerance=0.5) or rb.contains(ra, tolerance=0.5):
                continue
            out.append(
                Finding(
                    BLOCKING,
                    index,
                    f"overlaps {b.name!r} without containing it",
                    a.name,
                )
            )


def _check_connectors(slide: RenderedSlide, index: int, out: list[Finding]) -> None:
    """Every arrowhead must land on a shape.

    An arrow ending in whitespace is the diagram equivalent of a dangling
    pointer: it reads as a relationship that does not exist.
    """
    targets = [s.rect for s in slide.shapes if isinstance(s, RectShape)]
    for shape in slide.shapes:
        if not isinstance(shape, LineShape) or not shape.arrow_end:
            continue
        x, y = shape.x2, shape.y2
        if not any(
            r.x - 1.0 <= x <= r.right + 1.0 and r.y - 1.0 <= y <= r.bottom + 1.0 for r in targets
        ):
            out.append(
                Finding(
                    BLOCKING,
                    index,
                    f"arrow ends at ({x:.1f}, {y:.1f}), which is not on any shape",
                    shape.name,
                )
            )


def _check_contrast(slide: RenderedSlide, index: int, theme: Theme, out: list[Finding]) -> None:
    for shape in slide.shapes:
        if not isinstance(shape, TextShape):
            continue
        background = _behind(shape, slide)
        ratio = contrast_ratio(shape.color, background)
        # WCAG treats >=18pt bold or >=24pt as large text, which needs less
        # contrast to stay legible.
        large = shape.size_pt >= 24 or (shape.bold and shape.size_pt >= 18)
        floor = theme.min_stroke_contrast if large else theme.min_text_contrast
        if ratio < floor:
            out.append(
                Finding(
                    BLOCKING,
                    index,
                    f"text {shape.color} on {background} has contrast {ratio:.2f}:1, below the {floor}:1 floor",
                    shape.name,
                )
            )


def _check_accent_budget(slide: RenderedSlide, index: int, theme: Theme, out: list[Finding]) -> None:
    accent_colors = {theme.palette.accent, theme.palette.accent_light}
    area = sum(
        s.rect.w * s.rect.h
        for s in slide.shapes
        if isinstance(s, RectShape) and s.fill in accent_colors
    )
    fraction = area / (CANVAS_W_PT * CANVAS_H_PT)
    if fraction > theme.max_accent_area:
        out.append(
            Finding(
                ADVISORY,
                index,
                f"accent covers {fraction:.1%} of the slide, over the {theme.max_accent_area:.0%} budget; "
                "past that nothing is emphasised because everything is",
            )
        )


def _check_type_discipline(slide: RenderedSlide, index: int, theme: Theme, out: list[Finding]) -> None:
    sizes = {s.size_pt for s in slide.shapes if isinstance(s, TextShape)}
    allowed = set(theme.type_scale.all_sizes())
    off_scale = sizes - allowed
    if off_scale:
        out.append(
            Finding(
                ADVISORY,
                index,
                f"type sizes {sorted(off_scale)} are not on the deck's scale {sorted(allowed)}",
            )
        )
    if len(sizes) > 4:
        out.append(
            Finding(
                ADVISORY,
                index,
                f"{len(sizes)} type sizes on one slide; hierarchy past three or four reads as noise",
            )
        )


def _check_titles(slide: RenderedSlide, index: int, out: list[Finding]) -> None:
    for shape in slide.shapes:
        if not isinstance(shape, TextShape) or "title" not in shape.name.lower():
            continue
        text = " ".join(shape.lines).lower().replace("’", "'")
        for phrase in EMPTY_OPENINGS:
            if phrase.replace("*", "") in text or (
                "*" in phrase and all(part in text for part in phrase.split("*") if part.strip())
            ):
                out.append(
                    Finding(
                        ADVISORY,
                        index,
                        f"title uses the empty opening {phrase!r}; say what is actually true instead",
                        shape.name,
                    )
                )
                break


def audit_slide(slide: RenderedSlide, theme: Theme, index: int) -> list[Finding]:
    findings: list[Finding] = []
    _check_on_canvas(slide, index, findings)
    _check_text_fits(slide, index, findings)
    _check_collisions(slide, index, findings)
    _check_connectors(slide, index, findings)
    _check_contrast(slide, index, theme, findings)
    _check_accent_budget(slide, index, theme, findings)
    _check_type_discipline(slide, index, theme, findings)
    _check_titles(slide, index, findings)
    return findings


def audit_deck(deck: RenderedDeck, theme: Theme) -> AuditReport:
    report = AuditReport()
    for index, slide in enumerate(deck.slides, start=1):
        report.findings.extend(audit_slide(slide, theme, index))
    return report
