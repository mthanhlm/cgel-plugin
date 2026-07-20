"""The scene graph: resolved geometry, ready to serialize.

Layout engines turn the document model into a flat, ordered list of these
primitives. Serializers consume that list and know nothing about slides, ranks,
or design tokens -- by this point every colour is a hex string and every
position is a number in points.

List order *is* z-order. Layout emits in one fixed sequence -- ground, then
containers, then connectors, then nodes, then text, then annotations -- so a
connector can never land on top of the node it points at.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .units import Rect


class Align(str, Enum):
    LEFT = "l"
    CENTER = "ctr"
    RIGHT = "r"


class Anchor(str, Enum):
    TOP = "t"
    MIDDLE = "ctr"
    BOTTOM = "b"


@dataclass(frozen=True, slots=True)
class Stroke:
    color: str
    width: float = 1.0
    dashed: bool = False


@dataclass(frozen=True, slots=True)
class Shape:
    """Base for every drawable. `name` shows up in PowerPoint's selection pane."""

    name: str


@dataclass(frozen=True, slots=True)
class RectShape(Shape):
    """A rectangle. Corners are always square -- the system has no rounded boxes."""

    rect: Rect
    fill: str | None = None
    stroke: Stroke | None = None


@dataclass(frozen=True, slots=True)
class TextShape(Shape):
    """Pre-wrapped text in a fixed box.

    `lines` is already broken by the measurement layer, and the serializer emits
    each line as its own paragraph with autofit disabled. PowerPoint therefore
    reproduces exactly the line breaks the layout planned, instead of re-wrapping
    at its own discretion and invalidating every height the audit checked.
    """

    rect: Rect
    lines: tuple[str, ...]
    size_pt: float
    color: str
    bold: bool = False
    align: Align = Align.LEFT
    anchor: Anchor = Anchor.TOP
    line_height: float = 1.2
    inset: float = 0.0


@dataclass(frozen=True, slots=True)
class LineShape(Shape):
    """A straight segment, optionally with an arrowhead at its end.

    Elbowed connectors are emitted as several of these. Each segment stays an
    editable native line in PowerPoint, which is the point: a reader can grab a
    connector and move it.
    """

    x1: float
    y1: float
    x2: float
    y2: float
    stroke: Stroke
    arrow_end: bool = False
    arrow_start: bool = False

    def bounds(self) -> Rect:
        return Rect(
            min(self.x1, self.x2),
            min(self.y1, self.y2),
            abs(self.x2 - self.x1),
            abs(self.y2 - self.y1),
        )


@dataclass(frozen=True, slots=True)
class RenderedSlide:
    """One laid-out slide: its ground colour and everything drawn on it."""

    background: str
    shapes: tuple[Shape, ...]
    notes: str = ""


@dataclass(frozen=True, slots=True)
class RenderedDeck:
    title: str
    author: str
    slides: tuple[RenderedSlide, ...]
