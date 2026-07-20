"""Text measurement and line breaking.

The one job here: predict, before anything renders, how wide a string is and how
many lines it needs at a given width. Layout depends on this being *conservative*
-- a prediction that is slightly too wide costs a little whitespace, while a
prediction that is too narrow costs a text overflow, which is a visible defect.

Three rules keep the prediction on the safe side:

1. **Ceil, never round.** Every width is rounded up at the point it becomes a
   layout decision.
2. **No kerning credit.** Real renderers apply pair kerning, which only ever
   makes text *narrower* than the sum of advances. Ignoring kerning therefore
   biases the prediction wide, which is the safe direction.
3. **Unknown codepoints raise.** A character absent from the table would
   otherwise measure as zero width and silently produce a box too small for its
   own text. Rejecting it turns a silent visual defect into a loud error.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "arial_metrics.json"

#: Multiplied by font size to get the distance between baselines. Arial's own
#: ascent+descent+lineGap is ~1.15em; the layout engine applies its own leading
#: on top of this, so this constant is the *typographic* line box only.
DEFAULT_LINE_HEIGHT = 1.2

#: Extra height added to every measured text block, as a fraction. PowerPoint's
#: Arial, LibreOffice's Liberation Sans and this table agree on advance widths
#: but not on every rendering detail (hinting, subpixel positioning). A 12%
#: cushion absorbs that disagreement without visibly loosening the layout.
HEIGHT_HEADROOM = 0.12


class UnsupportedCharacter(ValueError):
    """Raised when a string contains a codepoint absent from the metrics table."""

    def __init__(self, char: str, context: str) -> None:
        self.char = char
        super().__init__(
            f"character {char!r} (U+{ord(char):04X}) is not in the Arial metrics table, "
            f"so its width cannot be predicted; found in: {context!r}. "
            "Replace it, or extend the table via deckmaster.text._build_metrics."
        )


@lru_cache(maxsize=1)
def _tables() -> dict[str, dict[int, float]]:
    raw = json.loads(_DATA_PATH.read_text(encoding="ascii"))
    return {
        weight: {int(code, 16): width for code, width in table.items()}
        for weight, table in raw["widths"].items()
    }


@dataclass(frozen=True, slots=True)
class TextStyle:
    """Everything measurement needs to know about how text is set."""

    size_pt: float
    bold: bool = False
    line_height: float = DEFAULT_LINE_HEIGHT

    @property
    def weight_key(self) -> str:
        return "bold" if self.bold else "regular"

    @property
    def line_pt(self) -> float:
        return self.size_pt * self.line_height


@dataclass(frozen=True, slots=True)
class TextBlock:
    """The measured result: the exact lines, and the space they occupy."""

    lines: tuple[str, ...]
    width_pt: float
    height_pt: float

    @property
    def line_count(self) -> int:
        return len(self.lines)


def assert_supported(text: str, role: str) -> None:
    """Raise if `text` contains a character this engine cannot measure.

    Called when content enters the document model, so an unmeasurable character
    is reported against the field that holds it. Without this the failure
    surfaces much later, from inside layout, as a traceback with no indication of
    which slide is at fault.

    Checked against every weight, not just the regular one. The two tables are
    extracted from different font files and each skips codepoints its own source
    lacks, so their coverage is not structurally guaranteed to match. Validating
    against the intersection means a character that exists in regular but not
    bold cannot pass here and then fail later from a bold run -- which would
    defeat the whole point of validating early.
    """
    supported = supported_codepoints()
    for char in text:
        if ord(char) not in supported:
            raise UnsupportedCharacter(char, role)


@lru_cache(maxsize=1)
def supported_codepoints() -> frozenset[int]:
    """Codepoints covered by *every* weight, so any run can be measured."""
    tables = _tables().values()
    return frozenset.intersection(*(frozenset(t) for t in tables))


def char_width(char: str, style: TextStyle) -> float:
    """Advance width of a single character in points."""
    table = _tables()[style.weight_key]
    width_em = table.get(ord(char))
    if width_em is None:
        raise UnsupportedCharacter(char, char)
    return width_em * style.size_pt


def measure(text: str, style: TextStyle) -> float:
    """Width of `text` in points, set on a single line.

    Sums advance widths with no kerning credit, so the result is an upper bound
    on what any real renderer will produce.
    """
    table = _tables()[style.weight_key]
    total = 0.0
    for char in text:
        width_em = table.get(ord(char))
        if width_em is None:
            raise UnsupportedCharacter(char, text)
        total += width_em
    return total * style.size_pt


def wrap(text: str, style: TextStyle, max_width_pt: float) -> list[str]:
    """Greedily break `text` into lines no wider than `max_width_pt`.

    Breaks at spaces. A single word longer than the available width is *not*
    split -- it is emitted on its own line and will be reported by the audit as
    an overflow, because silently hyphenating a word the author wrote is a
    content decision the layout engine has no business making.

    Explicit newlines in the source are honoured as hard breaks.
    """
    if max_width_pt <= 0:
        raise ValueError(f"max_width_pt must be positive, got {max_width_pt}")

    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue

        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if measure(candidate, style) <= max_width_pt:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def layout_text(
    text: str,
    style: TextStyle,
    max_width_pt: float,
    *,
    headroom: float = HEIGHT_HEADROOM,
) -> TextBlock:
    """Wrap `text` and report the space it needs.

    The returned height already includes the headroom cushion, so callers can
    size a shape directly from it.
    """
    lines = wrap(text, style, max_width_pt)
    widest = max((measure(line, style) for line in lines), default=0.0)
    height = len(lines) * style.line_pt * (1.0 + headroom)
    return TextBlock(
        lines=tuple(lines),
        width_pt=math.ceil(widest * 100) / 100,
        height_pt=math.ceil(height * 100) / 100,
    )


def fits(text: str, style: TextStyle, width_pt: float, height_pt: float) -> bool:
    """True when `text` fits inside the given box at this style."""
    block = layout_text(text, style, width_pt)
    return block.width_pt <= width_pt and block.height_pt <= height_pt
