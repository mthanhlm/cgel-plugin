"""Geometry primitives and the unit system.

Every layout computation in Deck Master happens in **points** on a 960x540 pt
canvas. Points are converted to EMU only at serialization time, in one place, so
that rounding happens once and layout code never carries six-digit integers.

    1 pt = 12700 EMU        1 in = 914400 EMU = 72 pt

A 960x540 pt canvas is exactly 13.333 x 7.5 in, which is PowerPoint's standard
16:9 slide. Choosing points as the design unit means the spacing scale and the
type scale live in the same unit, so "24pt gap, 16pt text" is directly legible.
"""

from __future__ import annotations

from dataclasses import dataclass

EMU_PER_PT = 12700
EMU_PER_INCH = 914400

# Standard PowerPoint 16:9 slide.
CANVAS_W_PT = 960.0
CANVAS_H_PT = 540.0


def pt_to_emu(value: float) -> int:
    """Convert points to EMU.

    Rounds half-up to the nearest EMU. EMU are integral in OOXML, and at
    12700 EMU per point a one-EMU rounding difference is 1/12700 pt -- far below
    any visible threshold -- but it must be *deterministic*, so this never uses
    banker's rounding.
    """
    return int(value * EMU_PER_PT + 0.5) if value >= 0 else -int(-value * EMU_PER_PT + 0.5)


@dataclass(frozen=True, slots=True)
class Rect:
    """An axis-aligned rectangle in points, anchored at its top-left corner."""

    x: float
    y: float
    w: float
    h: float

    def __post_init__(self) -> None:
        if self.w < 0 or self.h < 0:
            raise ValueError(f"Rect must have non-negative size, got w={self.w} h={self.h}")

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def inset(self, dx: float, dy: float | None = None) -> "Rect":
        """Shrink on all sides by dx horizontally and dy vertically."""
        dy = dx if dy is None else dy
        return Rect(self.x + dx, self.y + dy, max(0.0, self.w - 2 * dx), max(0.0, self.h - 2 * dy))

    def intersects(self, other: "Rect", tolerance: float = 0.0) -> bool:
        """True when the two rectangles overlap by more than `tolerance` points.

        Shapes that merely touch edge-to-edge do not count as intersecting; the
        audit uses a small positive tolerance so that a shared boundary between
        two adjacent cells is not reported as a collision.
        """
        return not (
            self.right - tolerance <= other.x
            or other.right - tolerance <= self.x
            or self.bottom - tolerance <= other.y
            or other.bottom - tolerance <= self.y
        )

    def contains(self, other: "Rect", tolerance: float = 0.01) -> bool:
        """True when `other` lies entirely inside this rectangle."""
        return (
            other.x >= self.x - tolerance
            and other.y >= self.y - tolerance
            and other.right <= self.right + tolerance
            and other.bottom <= self.bottom + tolerance
        )


CANVAS = Rect(0.0, 0.0, CANVAS_W_PT, CANVAS_H_PT)
