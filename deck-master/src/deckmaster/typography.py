"""Punctuation normalisation.

Straight quotes, three periods for an ellipsis, and a double hyphen for a dash
are all clearly visible at projection scale, and together they read as "nobody
proof-read this". Normalising them is cheap and unconditional.

This runs on every string entering the document model, which also means every
character reaching the layout engine has passed through here -- so the metrics
table only ever has to cover what this function can emit.
"""

from __future__ import annotations

import re

#: Units that take a non-breaking space, so a figure never separates from its
#: unit across a line break.
_UNITS = (
    "kg", "g", "mg", "lb", "km", "m", "cm", "mm", "mi", "ft", "in",
    "ms", "s", "min", "h", "hr", "hrs", "d", "wk", "mo", "yr",
    "KB", "MB", "GB", "TB", "PB", "Hz", "kHz", "MHz", "GHz",
    "%", "px", "pt", "x",
)

_ELLIPSIS = re.compile(r"\.{3,}")
_EM_DASH = re.compile(r"(?<=\S)\s*--\s*(?=\S)")
_NUMERIC_RANGE = re.compile(r"(?<=\d)\s*-\s*(?=\d)")
# A range between capitalised period labels: Q1-Q3, Jul-Sep, 2024-2026.
_LABEL_RANGE = re.compile(r"(?<=\b[A-Z]\d)\s*-\s*(?=[A-Z]\d\b)")
# Longest-first so that "min" wins over "m" without relying on backtracking.
_UNIT_SPACE = re.compile(
    r"(?<=\d) (" + "|".join(re.escape(u) for u in sorted(_UNITS, key=len, reverse=True)) + r")\b"
)

#: U+00A0. Named rather than inlined so it is visible in the source.
NBSP = " "


def _curl_quotes(text: str) -> str:
    """Replace straight quotes with typographic ones based on position."""
    out: list[str] = []
    for i, char in enumerate(text):
        if char not in ("'", '"'):
            out.append(char)
            continue
        prev = text[i - 1] if i > 0 else ""
        # A quote opens when it follows nothing, whitespace, or an opening
        # bracket; otherwise it closes. An apostrophe inside a word therefore
        # always resolves to the closing form, which is correct.
        opening = prev == "" or prev.isspace() or prev in "([{—–"
        if char == '"':
            out.append("“" if opening else "”")
        else:
            out.append("‘" if opening else "’")
    return "".join(out)


def normalize(text: str) -> str:
    """Apply the house punctuation rules to a single string."""
    if not text:
        return text
    text = _ELLIPSIS.sub("…", text)
    text = _EM_DASH.sub("—", text)
    text = _LABEL_RANGE.sub("–", text)
    text = _NUMERIC_RANGE.sub("–", text)
    text = _curl_quotes(text)
    text = _UNIT_SPACE.sub(" \\1", text)
    return text
