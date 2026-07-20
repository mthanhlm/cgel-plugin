"""Build-time tool: extract advance widths from a TrueType font into JSON.

This is **not** imported at generation time. It runs once, by hand, to produce
`deckmaster/data/arial_metrics.json`, which is committed to the repository. The
runtime only ever reads that JSON.

Why this exists
---------------
To guarantee that text never overflows its box, the layout engine must know how
wide a string will be *before* anything renders it. That requires per-character
advance widths. An advance-width table is data of the same category as a colour
palette -- it is not a layout engine, a shaper, or a renderer. We look up
numbers and add them up.

Source font
-----------
Liberation Sans is metrically compatible with Arial by design: for every
character both fonts share, the advance widths are identical. Extracting from
Liberation Sans therefore yields Arial's metrics, which is what PowerPoint will
use on Windows.

Usage
-----
    python3 -m deckmaster.text._build_metrics \
        --regular /usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf \
        --bold    /usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf \
        --out     src/deckmaster/data/arial_metrics.json
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

# The Latin range Deck Master supports, plus the typographic punctuation the
# house style mandates (curly quotes, en/em dash, ellipsis, non-breaking space).
# Anything outside this set is rejected at measurement time rather than silently
# measured as zero, which would produce a box too small for its text.
_EXTRA_CODEPOINTS = [
    0x00A0,  # no-break space
    0x00B0,  # degree sign
    0x00D7,  # multiplication sign
    0x2013,  # en dash
    0x2014,  # em dash
    0x2018,  # left single quote
    0x2019,  # right single quote / apostrophe
    0x201C,  # left double quote
    0x201D,  # right double quote
    0x2022,  # bullet
    0x2026,  # horizontal ellipsis
    0x2192,  # rightwards arrow
]
# Codepoints the source font has no glyph for are skipped rather than guessed,
# so this list is a request, not a guarantee -- U+2713 CHECK MARK was dropped
# for exactly that reason. Anything absent is rejected at content-validation
# time with the field named.


class TrueTypeFont:
    """A minimal TrueType reader: just enough to read horizontal metrics.

    Parses only the four tables we need -- head, hhea, hmtx, cmap -- using
    struct. No glyph outlines, no hinting, no shaping.
    """

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._tables = self._read_table_directory()
        self.units_per_em = self._read_units_per_em()
        self._cmap = self._read_cmap()
        self._advances = self._read_hmtx()

    def _read_table_directory(self) -> dict[str, tuple[int, int]]:
        # Offset table: sfntVersion(4) numTables(2) searchRange(2)
        # entrySelector(2) rangeShift(2), then numTables 16-byte records.
        (num_tables,) = struct.unpack(">H", self._data[4:6])
        tables: dict[str, tuple[int, int]] = {}
        for i in range(num_tables):
            base = 12 + i * 16
            tag, _checksum, offset, length = struct.unpack(">4sIII", self._data[base : base + 16])
            tables[tag.decode("latin-1")] = (offset, length)
        return tables

    def _table(self, tag: str) -> bytes:
        if tag not in self._tables:
            raise ValueError(f"font is missing the required {tag!r} table")
        offset, length = self._tables[tag]
        return self._data[offset : offset + length]

    def _read_units_per_em(self) -> int:
        head = self._table("head")
        (units_per_em,) = struct.unpack(">H", head[18:20])
        if units_per_em == 0:
            raise ValueError("font declares unitsPerEm = 0")
        return units_per_em

    def _read_hmtx(self) -> list[int]:
        hhea = self._table("hhea")
        (num_h_metrics,) = struct.unpack(">H", hhea[34:36])
        hmtx = self._table("hmtx")
        advances: list[int] = []
        for i in range(num_h_metrics):
            (advance,) = struct.unpack(">H", hmtx[i * 4 : i * 4 + 2])
            advances.append(advance)
        if not advances:
            raise ValueError("font declares zero horizontal metrics")
        return advances

    def _read_cmap(self) -> dict[int, int]:
        """Read a Unicode character-to-glyph map from a format 4 subtable."""
        cmap = self._table("cmap")
        (num_subtables,) = struct.unpack(">H", cmap[2:4])

        # Prefer Windows/Unicode BMP (3,1); fall back to any Unicode (0,x).
        chosen: int | None = None
        fallback: int | None = None
        for i in range(num_subtables):
            base = 4 + i * 8
            platform_id, encoding_id, offset = struct.unpack(">HHI", cmap[base : base + 8])
            if platform_id == 3 and encoding_id == 1:
                chosen = offset
            elif platform_id == 0 and fallback is None:
                fallback = offset
        subtable_offset = chosen if chosen is not None else fallback
        if subtable_offset is None:
            raise ValueError("font has no Unicode cmap subtable")

        sub = cmap[subtable_offset:]
        (fmt,) = struct.unpack(">H", sub[0:2])
        if fmt != 4:
            raise ValueError(f"unsupported cmap format {fmt}; only format 4 is handled")

        (seg_count_x2,) = struct.unpack(">H", sub[6:8])
        seg_count = seg_count_x2 // 2

        ends = struct.unpack(f">{seg_count}H", sub[14 : 14 + seg_count_x2])
        starts_at = 14 + seg_count_x2 + 2  # +2 skips the reservedPad field
        starts = struct.unpack(f">{seg_count}H", sub[starts_at : starts_at + seg_count_x2])
        deltas_at = starts_at + seg_count_x2
        deltas = struct.unpack(f">{seg_count}h", sub[deltas_at : deltas_at + seg_count_x2])
        ranges_at = deltas_at + seg_count_x2
        range_offsets = struct.unpack(f">{seg_count}H", sub[ranges_at : ranges_at + seg_count_x2])

        mapping: dict[int, int] = {}
        for seg in range(seg_count):
            start, end = starts[seg], ends[seg]
            if start == 0xFFFF:
                continue
            for code in range(start, end + 1):
                if range_offsets[seg] == 0:
                    glyph = (code + deltas[seg]) & 0xFFFF
                else:
                    # glyphIdArray is addressed relative to the range_offset slot
                    # itself, which is the format 4 quirk worth spelling out.
                    slot = ranges_at + seg * 2 + range_offsets[seg] + (code - start) * 2
                    if slot + 2 > len(sub):
                        continue
                    (glyph,) = struct.unpack(">H", sub[slot : slot + 2])
                    if glyph != 0:
                        glyph = (glyph + deltas[seg]) & 0xFFFF
                if glyph != 0:
                    mapping[code] = glyph
        return mapping

    def advance_width_em(self, codepoint: int) -> float | None:
        """Advance width as a fraction of the em, or None if unmapped."""
        glyph = self._cmap.get(codepoint)
        if glyph is None:
            return None
        # Glyphs beyond numberOfHMetrics all share the last advance value.
        advance = self._advances[glyph] if glyph < len(self._advances) else self._advances[-1]
        return advance / self.units_per_em


def _supported_codepoints() -> list[int]:
    return [*range(0x20, 0x7F), *range(0xA0, 0x100), *_EXTRA_CODEPOINTS]


def build(regular_path: Path, bold_path: Path) -> dict:
    fonts = {"regular": TrueTypeFont(regular_path.read_bytes()), "bold": TrueTypeFont(bold_path.read_bytes())}
    widths: dict[str, dict[str, float]] = {}
    for weight, font in fonts.items():
        table: dict[str, float] = {}
        for codepoint in _supported_codepoints():
            em = font.advance_width_em(codepoint)
            if em is None:
                continue
            # Six decimal places is far finer than any rounding we apply later
            # and keeps the JSON byte-stable across machines.
            table[f"{codepoint:04X}"] = round(em, 6)
        widths[weight] = table

    return {
        "family": "Arial",
        "source": "Liberation Sans (metrically compatible with Arial)",
        "note": (
            "Advance widths as a fraction of the em. Measurement is ceil-only and "
            "applies no kerning credit, so predicted width is always >= rendered width."
        ),
        "widths": widths,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regular", type=Path, required=True)
    parser.add_argument("--bold", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    payload = build(args.regular, args.bold)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # sort_keys plus a fixed separator keeps the committed file byte-stable.
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="ascii",
    )
    counts = {w: len(t) for w, t in payload["widths"].items()}
    print(f"wrote {args.out} ({counts})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
