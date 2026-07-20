"""Build a Deck from plain JSON.

This is the interface a Claude skill uses. The skill decides *what the deck
says*; this module turns that decision into the document model, and every
content limit and typographic rule applies exactly as it would from Python.

The format is deliberately narrow. There is no styling, no positioning, no
colour, and no font control -- those come from the theme, and exposing them here
would let a caller defeat the design system one override at a time.

Shape::

    {
      "title": "Deck title",
      "author": "optional",
      "slides": [
        {"type": "title",     "title": "...", "subtitle": "..."},
        {"type": "statement", "title": "...", "subtitle": "..."},
        {"type": "key_value", "title": "...", "subtitle": "...", "dark": true,
         "entries": [{"label": "...", "body": "..."}]},
        {"type": "diagram",   "title": "...", "subtitle": "...", "footnote": "...",
         "ranks": [
           {"label": "...", "caption": "...", "boxed": true,
            "nodes": [{"id": "a", "label": "...", "caption": "...", "emphasis": false}]}
         ],
         "edges": [{"source": "a", "target": "b", "label": "...", "dashed": false}]}
      ]
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import (
    Deck,
    DiagramSlide,
    Edge,
    Entry,
    Flow,
    KeyValueSlide,
    Node,
    Rank,
    Slide,
    StatementSlide,
    TitleSlide,
)


class DeckSpecError(ValueError):
    """Raised when the input JSON does not describe a deck this engine can build."""


def _object(value: Any, where: str) -> dict[str, Any]:
    """Assert that `value` is a JSON object before anything indexes into it.

    Input arriving here is untrusted -- a hand-written or model-written file.
    Without this, a scalar or null where an object belongs (``"slides": [null]``)
    raises TypeError from a membership test deep inside the parser, and the
    caller sees a traceback instead of a message naming the offending field.
    """
    if not isinstance(value, dict):
        raise DeckSpecError(
            f"{where}: expected an object, got {type(value).__name__}"
        )
    return value


def _require(data: Any, key: str, where: str) -> Any:
    obj = _object(data, where)
    if key not in obj:
        raise DeckSpecError(f"{where}: missing required key {key!r}")
    return obj[key]


def _node(data: Any, where: str) -> Node:
    data = _object(data, where)
    return Node(
        id=str(_require(data, "id", where)),
        label=str(_require(data, "label", where)),
        caption=(str(data["caption"]) if data.get("caption") else None),
        emphasis=bool(data.get("emphasis", False)),
    )


def _rank(data: Any, where: str) -> Rank:
    data = _object(data, where)
    nodes = _require(data, "nodes", where)
    if not isinstance(nodes, list) or not nodes:
        raise DeckSpecError(f"{where}: 'nodes' must be a non-empty list")
    return Rank(
        nodes=tuple(_node(n, f"{where}.nodes[{i}]") for i, n in enumerate(nodes)),
        label=(str(data["label"]) if data.get("label") else None),
        caption=(str(data["caption"]) if data.get("caption") else None),
        boxed=bool(data.get("boxed", False)),
    )


def _slide(data: Any, index: int) -> Slide:
    where = f"slides[{index}]"
    data = _object(data, where)
    kind = str(_require(data, "type", where))
    title = str(_require(data, "title", where))
    subtitle = str(data["subtitle"]) if data.get("subtitle") else None

    if kind == "title":
        return TitleSlide(title=title, subtitle=subtitle)

    if kind == "statement":
        return StatementSlide(title=title, subtitle=subtitle)

    if kind == "key_value":
        entries = _require(data, "entries", where)
        if not isinstance(entries, list):
            raise DeckSpecError(f"{where}: 'entries' must be a list")
        return KeyValueSlide(
            title=title,
            subtitle=subtitle,
            dark=bool(data.get("dark", False)),
            entries=tuple(
                Entry(
                    label=str(_require(e, "label", f"{where}.entries[{i}]")),
                    body=str(_require(e, "body", f"{where}.entries[{i}]")),
                )
                for i, e in enumerate(entries)
            ),
        )

    if kind == "diagram":
        ranks = _require(data, "ranks", where)
        if not isinstance(ranks, list) or not ranks:
            raise DeckSpecError(f"{where}: 'ranks' must be a non-empty list")
        edges = data.get("edges", [])
        if not isinstance(edges, list):
            raise DeckSpecError(f"{where}: 'edges' must be a list")
        return DiagramSlide(
            title=title,
            subtitle=subtitle,
            footnote=(str(data["footnote"]) if data.get("footnote") else None),
            flow=Flow(
                ranks=tuple(_rank(r, f"{where}.ranks[{i}]") for i, r in enumerate(ranks)),
                edges=tuple(
                    Edge(
                        source=str(_require(e, "source", f"{where}.edges[{i}]")),
                        target=str(_require(e, "target", f"{where}.edges[{i}]")),
                        label=(str(e["label"]) if e.get("label") else None),
                        dashed=bool(e.get("dashed", False)),
                    )
                    for i, e in enumerate(edges)
                ),
            ),
        )

    raise DeckSpecError(
        f"{where}: unknown slide type {kind!r}; expected one of "
        "'title', 'statement', 'key_value', 'diagram'"
    )


def deck_from_dict(data: Any) -> Deck:
    data = _object(data, "deck")
    slides = _require(data, "slides", "deck")
    if not isinstance(slides, list) or not slides:
        raise DeckSpecError("deck: 'slides' must be a non-empty list")
    return Deck(
        title=str(_require(data, "title", "deck")),
        author=str(data.get("author", "")),
        slides=tuple(_slide(s, i) for i, s in enumerate(slides)),
    )


def deck_from_json(path: str | Path) -> Deck:
    """Load a deck spec, reporting file and syntax problems as DeckSpecError."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise DeckSpecError(f"cannot read {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        # Not an OSError -- a non-UTF-8 spec would otherwise escape this
        # function by an exception type its own contract promises to convert.
        raise DeckSpecError(f"{path} is not valid UTF-8: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DeckSpecError(f"{path} is not valid JSON: {exc}") from exc
    return deck_from_dict(data)
