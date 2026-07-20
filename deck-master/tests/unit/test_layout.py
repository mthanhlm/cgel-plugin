"""Layout is a pure function, and it refuses rather than overflows."""

from __future__ import annotations

import pytest

from deckmaster.layout import LayoutError, layout_slide
from deckmaster.model import DiagramSlide, Edge, Entry, Flow, KeyValueSlide, Node, Rank, TitleSlide
from deckmaster.scene import LineShape, RectShape, TextShape
from deckmaster.theme import DEFAULT_THEME
from deckmaster.units import CANVAS


def _flow(rank_count: int, nodes_per_rank: int = 1) -> Flow:
    ranks = tuple(
        Rank(nodes=tuple(Node(id=f"n{r}_{c}", label=f"Node {r}{c}") for c in range(nodes_per_rank)))
        for r in range(rank_count)
    )
    return Flow(ranks=ranks)


def test_layout_is_deterministic():
    slide = TitleSlide(title="Same input", subtitle="Same output, every time.")
    first = layout_slide(slide, DEFAULT_THEME)
    second = layout_slide(slide, DEFAULT_THEME)
    assert first == second


def test_every_shape_lands_on_the_canvas():
    slide = DiagramSlide(title="Three stages", flow=_flow(3))
    rendered = layout_slide(slide, DEFAULT_THEME)
    for shape in rendered.shapes:
        rect = shape.bounds() if isinstance(shape, LineShape) else shape.rect
        assert CANVAS.contains(rect, tolerance=0.5), shape.name


def test_too_many_ranks_is_refused_rather_than_squeezed():
    """The engine says no instead of producing an unreadable diagram."""
    with pytest.raises(LayoutError, match="per column"):
        layout_slide(DiagramSlide(title="Far too many stages", flow=_flow(9)), DEFAULT_THEME)


def test_content_taller_than_the_slide_is_refused():
    flow = _flow(2, nodes_per_rank=12)
    with pytest.raises(LayoutError, match="height"):
        layout_slide(DiagramSlide(title="Too tall", flow=flow), DEFAULT_THEME)


def test_emphasis_changes_fill_not_geometry():
    """Emphasis must not resize a node, or it falls out of its rank's alignment."""
    plain = Rank(nodes=(Node(id="a", label="Node A"),))
    marked = Rank(nodes=(Node(id="a", label="Node A", emphasis=True),))

    def node_rect(rank):
        rendered = layout_slide(DiagramSlide(title="Emphasis", flow=Flow(ranks=(rank,))), DEFAULT_THEME)
        return next(s.rect for s in rendered.shapes if isinstance(s, RectShape) and s.name == "Node a")

    assert node_rect(plain) == node_rect(marked)


def test_emphasised_node_flips_its_ink():
    flow = Flow(ranks=(Rank(nodes=(Node(id="a", label="Node A", emphasis=True),)),))
    rendered = layout_slide(DiagramSlide(title="Emphasis", flow=flow), DEFAULT_THEME)
    fill = next(s.fill for s in rendered.shapes if isinstance(s, RectShape) and s.name == "Node a")
    ink = next(s.color for s in rendered.shapes if isinstance(s, TextShape) and s.name == "Node label a")
    assert fill == DEFAULT_THEME.palette.accent
    assert ink == DEFAULT_THEME.palette.accent_solid.ink


def test_connectors_are_drawn_beneath_nodes():
    """Z-order must keep an arrow from covering the label it points at."""
    flow = Flow(
        ranks=(Rank(nodes=(Node(id="a", label="A"),)), Rank(nodes=(Node(id="b", label="B"),))),
        edges=(Edge(source="a", target="b"),),
    )
    rendered = layout_slide(DiagramSlide(title="Order", flow=flow), DEFAULT_THEME)
    last_line = max(i for i, s in enumerate(rendered.shapes) if isinstance(s, LineShape))
    first_node = min(
        i for i, s in enumerate(rendered.shapes) if isinstance(s, RectShape) and s.name.startswith("Node ")
    )
    assert last_line < first_node


def test_key_value_rows_are_separated_by_rules_not_boxes():
    slide = KeyValueSlide(
        title="Two claims",
        entries=(Entry(label="First", body="One line of support."), Entry(label="Second", body="Another line.")),
    )
    rendered = layout_slide(slide, DEFAULT_THEME)
    rules = [s for s in rendered.shapes if isinstance(s, RectShape) and s.name.startswith("Rule")]
    assert len(rules) == 1  # n-1 rules for n rows
    assert rules[0].rect.h == DEFAULT_THEME.hairline


def test_title_block_sits_above_the_geometric_centre():
    """Optical centring: more room below than above."""
    rendered = layout_slide(TitleSlide(title="Optically centred", subtitle="Not arithmetically."), DEFAULT_THEME)
    shapes = [s for s in rendered.shapes if isinstance(s, (RectShape, TextShape))]
    top = min(s.rect.y for s in shapes)
    bottom = max(s.rect.bottom for s in shapes)
    assert top < CANVAS.h - bottom
