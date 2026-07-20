"""Layout engines: document model in, resolved geometry out.

One engine per slide idiom. Each is a pure function of (slide, theme) -- no
randomness, no clocks, no global state -- so the same deck always produces the
same coordinates. That is what makes byte-identical rebuilds possible.

Every engine follows the same discipline:

* Text is measured before a box is sized, never sized and hoped for.
* Every gap comes from the spacing scale.
* Shapes are appended in z-order: ground, containers, connectors, nodes, text.
"""

from __future__ import annotations

from .model import (
    Deck,
    DiagramSlide,
    Entry,
    Flow,
    KeyValueSlide,
    Node,
    Rank,
    Slide,
    StatementSlide,
    TitleSlide,
)
from .scene import Align, Anchor, LineShape, RectShape, RenderedDeck, RenderedSlide, Shape, Stroke, TextShape
from .text.metrics import TextStyle, layout_text
from .theme import Surface, Theme
from .units import CANVAS_H_PT, CANVAS_W_PT, Rect


class LayoutError(RuntimeError):
    """Raised when content cannot be laid out within the slide."""


# --------------------------------------------------------------------------
# Shared pieces
# --------------------------------------------------------------------------


def _title_style(theme: Theme) -> TextStyle:
    return TextStyle(theme.type_scale.title, bold=True, line_height=theme.type_scale.lh_title)


def _lead_style(theme: Theme) -> TextStyle:
    return TextStyle(theme.type_scale.lead, bold=False, line_height=theme.type_scale.lh_lead)


def _body_style(theme: Theme, bold: bool = False) -> TextStyle:
    return TextStyle(theme.type_scale.body, bold=bold, line_height=theme.type_scale.lh_body)


def _micro_style(theme: Theme, bold: bool = False) -> TextStyle:
    return TextStyle(theme.type_scale.micro, bold=bold, line_height=theme.type_scale.lh_label)


def _header(
    slide_title: str,
    subtitle: str | None,
    theme: Theme,
    surface: Surface,
) -> tuple[list[Shape], float]:
    """Emit the title (and optional deck line). Returns shapes and the y where the body may start.

    The title is the slide's one message, so it gets the strongest weight in the
    system and sits flush to the left margin on every slide. Consistency here is
    what lets a reader stop looking for the title after slide two.
    """
    shapes: list[Shape] = []
    style = _title_style(theme)
    block = layout_text(slide_title, style, theme.content_width)

    y = theme.margin_y
    shapes.append(
        TextShape(
            name="Slide title",
            rect=Rect(theme.margin, y, theme.content_width, block.height_pt),
            lines=block.lines,
            size_pt=style.size_pt,
            color=surface.ink,
            bold=True,
            line_height=style.line_height,
        )
    )
    y += block.height_pt

    if subtitle:
        lead = _lead_style(theme)
        lead_block = layout_text(subtitle, lead, theme.content_width)
        y += theme.space.sm
        shapes.append(
            TextShape(
                name="Slide deck line",
                rect=Rect(theme.margin, y, theme.content_width, lead_block.height_pt),
                lines=lead_block.lines,
                size_pt=lead.size_pt,
                color=surface.muted_ink,
                line_height=lead.line_height,
            )
        )
        y += lead_block.height_pt

    return shapes, y + theme.space.xl


def _accent_mark(theme: Theme, y: float) -> RectShape:
    """The small accent square that opens a dark slide.

    It is the deck's one recurring ornament, and it earns its place by marking
    where the eye should start. At 14 pt square it is well under the accent
    budget.
    """
    return RectShape(
        name="Accent mark",
        rect=Rect(theme.margin, y, 14.0, 14.0),
        fill=theme.palette.accent,
    )


# --------------------------------------------------------------------------
# Title slide
# --------------------------------------------------------------------------


def layout_title_slide(slide: TitleSlide, theme: Theme) -> RenderedSlide:
    surface = theme.palette.dark
    shapes: list[Shape] = []

    display = TextStyle(theme.type_scale.display, bold=True, line_height=theme.type_scale.lh_display)
    title_block = layout_text(slide.title, display, theme.content_width)

    sub_block = None
    if slide.subtitle:
        lead = _lead_style(theme)
        sub_block = layout_text(slide.subtitle, lead, theme.content_width * 0.8)

    mark_h = 14.0 + theme.space.xl
    rule_gap = theme.space.xl
    rule_h = theme.hairline * 2
    sub_h = (rule_gap + rule_h + theme.space.xl + sub_block.height_pt) if sub_block else 0.0
    total = mark_h + title_block.height_pt + sub_h

    # Optical centring: more space below than above, at roughly 1:1.3. A block
    # centred by arithmetic looks like it has slipped toward the bottom.
    free = CANVAS_H_PT - total
    if free < 0:
        raise LayoutError(f"title slide content is {-free:.1f} pt taller than the canvas")
    top = free * (1.0 / 2.3)

    y = top
    shapes.append(_accent_mark(theme, y))
    y += mark_h

    shapes.append(
        TextShape(
            name="Deck title",
            rect=Rect(theme.margin, y, theme.content_width, title_block.height_pt),
            lines=title_block.lines,
            size_pt=display.size_pt,
            color=surface.ink,
            bold=True,
            line_height=display.line_height,
        )
    )
    y += title_block.height_pt

    if sub_block:
        y += rule_gap
        shapes.append(
            RectShape(
                name="Accent rule",
                rect=Rect(theme.margin, y, 96.0, rule_h),
                fill=theme.palette.accent,
            )
        )
        y += rule_h + theme.space.xl
        shapes.append(
            TextShape(
                name="Deck subtitle",
                rect=Rect(theme.margin, y, theme.content_width * 0.8, sub_block.height_pt),
                lines=sub_block.lines,
                size_pt=theme.type_scale.lead,
                color=surface.muted_ink,
                line_height=theme.type_scale.lh_lead,
            )
        )

    return RenderedSlide(background=surface.fill, shapes=tuple(shapes))


# --------------------------------------------------------------------------
# Statement slide
# --------------------------------------------------------------------------


def layout_statement_slide(slide: StatementSlide, theme: Theme) -> RenderedSlide:
    """One idea on a dark ground, with most of the slide left empty.

    The emptiness is the design. A statement slide that fills up is a key-value
    slide that has not admitted it yet.
    """
    surface = theme.palette.dark
    shapes: list[Shape] = []

    display = TextStyle(theme.type_scale.display, bold=True, line_height=theme.type_scale.lh_display)
    width = theme.content_width * 0.82
    title_block = layout_text(slide.title, display, width)

    sub_block = None
    if slide.subtitle:
        sub_block = layout_text(slide.subtitle, _lead_style(theme), width * 0.85)

    mark_h = 14.0 + theme.space.xl
    total = mark_h + title_block.height_pt + ((theme.space.xl + sub_block.height_pt) if sub_block else 0.0)
    free = CANVAS_H_PT - total
    if free < 0:
        raise LayoutError(f"statement slide content is {-free:.1f} pt taller than the canvas")
    y = free * (1.0 / 2.3)

    shapes.append(_accent_mark(theme, y))
    y += mark_h

    shapes.append(
        TextShape(
            name="Statement",
            rect=Rect(theme.margin, y, width, title_block.height_pt),
            lines=title_block.lines,
            size_pt=display.size_pt,
            color=surface.ink,
            bold=True,
            line_height=display.line_height,
        )
    )
    y += title_block.height_pt

    if sub_block:
        y += theme.space.xl
        shapes.append(
            TextShape(
                name="Statement support",
                rect=Rect(theme.margin, y, width * 0.85, sub_block.height_pt),
                lines=sub_block.lines,
                size_pt=theme.type_scale.lead,
                color=surface.muted_ink,
                line_height=theme.type_scale.lh_lead,
            )
        )

    return RenderedSlide(background=surface.fill, shapes=tuple(shapes))


# --------------------------------------------------------------------------
# Key-value slide
# --------------------------------------------------------------------------


def layout_key_value_slide(slide: KeyValueSlide, theme: Theme) -> RenderedSlide:
    """Claims on the left, support on the right, separated by hairline rules.

    Rules rather than cards: a card would add a border, a fill, a corner radius
    and an inset to do the work one line already does.
    """
    surface = theme.palette.dark if slide.dark else theme.palette.light
    shapes: list[Shape] = []

    header_shapes, body_top = _header(slide.title, slide.subtitle, theme, surface)
    if slide.dark:
        mark_y = theme.margin_y
        shapes.append(_accent_mark(theme, mark_y))
        offset = 14.0 + theme.space.lg
        header_shapes = [_shift(s, offset) for s in header_shapes]
        body_top += offset
    shapes.extend(header_shapes)

    label_w = theme.content_width * 0.34
    gap = theme.space.x3
    body_w = theme.content_width - label_w - gap
    body_x = theme.margin + label_w + gap

    label_style = _body_style(theme, bold=True)
    body_style = _body_style(theme)

    rows: list[tuple[Entry, float, float]] = []
    for entry in slide.entries:
        label_block = layout_text(entry.label, label_style, label_w)
        body_block = layout_text(entry.body, body_style, body_w)
        rows.append((entry, label_block.height_pt, body_block.height_pt))

    row_pad = theme.space.xl
    total = sum(max(lh, bh) + 2 * row_pad for _, lh, bh in rows)
    available = CANVAS_H_PT - theme.margin_y - body_top
    if total > available:
        raise LayoutError(
            f"key-value rows need {total:.1f} pt but only {available:.1f} pt remain; "
            "shorten the entries or drop one"
        )

    y = body_top
    for index, (entry, label_h, body_h) in enumerate(rows):
        if index > 0:
            shapes.append(
                RectShape(
                    name=f"Rule {index}",
                    rect=Rect(theme.margin, y, theme.content_width, theme.hairline),
                    fill=theme.palette.neutral_300 if not slide.dark else theme.palette.muted,
                )
            )
        y += row_pad
        row_h = max(label_h, body_h)
        label_block = layout_text(entry.label, label_style, label_w)
        body_block = layout_text(entry.body, body_style, body_w)
        shapes.append(
            TextShape(
                name=f"Entry label {index + 1}",
                rect=Rect(theme.margin, y, label_w, row_h),
                lines=label_block.lines,
                size_pt=label_style.size_pt,
                color=surface.ink,
                bold=True,
                line_height=label_style.line_height,
            )
        )
        shapes.append(
            TextShape(
                name=f"Entry body {index + 1}",
                rect=Rect(body_x, y, body_w, row_h),
                lines=body_block.lines,
                size_pt=body_style.size_pt,
                color=surface.muted_ink,
                line_height=body_style.line_height,
            )
        )
        y += row_h + row_pad

    return RenderedSlide(background=surface.fill, shapes=tuple(shapes))


def _shift(shape: Shape, dy: float) -> Shape:
    """Move a shape down by dy. Used when a dark slide inserts its accent mark."""
    if isinstance(shape, TextShape):
        r = shape.rect
        return TextShape(
            name=shape.name,
            rect=Rect(r.x, r.y + dy, r.w, r.h),
            lines=shape.lines,
            size_pt=shape.size_pt,
            color=shape.color,
            bold=shape.bold,
            align=shape.align,
            anchor=shape.anchor,
            line_height=shape.line_height,
            inset=shape.inset,
        )
    if isinstance(shape, RectShape):
        r = shape.rect
        return RectShape(
            name=shape.name,
            rect=Rect(r.x, r.y + dy, r.w, r.h),
            fill=shape.fill,
            stroke=shape.stroke,
        )
    raise TypeError(f"cannot shift {type(shape).__name__}")


# --------------------------------------------------------------------------
# Diagram slide
# --------------------------------------------------------------------------


# Node padding is asymmetric on purpose. Horizontal space is plentiful on a 16:9
# slide and a tight side inset makes a label look cramped; vertical space is the
# scarce dimension, and line-height already contributes visual padding above and
# below the text. Matching them numerically would waste the dimension that runs
# out first.
def _node_pad_x(theme: Theme) -> float:
    return theme.space.md


def _node_pad_y(theme: Theme) -> float:
    return theme.space.sm


def _node_box_height(node: Node, width: float, theme: Theme) -> float:
    pad_x, pad_y = _node_pad_x(theme), _node_pad_y(theme)
    label_block = layout_text(node.label, _body_style(theme, bold=True), width - 2 * pad_x)
    height = label_block.height_pt
    if node.caption:
        caption_block = layout_text(node.caption, _micro_style(theme), width - 2 * pad_x)
        height += theme.space.xs + caption_block.height_pt
    return height + 2 * pad_y


def layout_diagram_slide(slide: DiagramSlide, theme: Theme) -> RenderedSlide:
    """A left-to-right layered flow: ranks of nodes, connected by arrows."""
    surface = theme.palette.light
    shapes: list[Shape] = []

    header_shapes, body_top = _header(slide.title, slide.subtitle, theme, surface)
    shapes.extend(header_shapes)

    body_bottom = CANVAS_H_PT - theme.margin_y
    footnote_block = None
    if slide.footnote:
        footnote_block = layout_text(slide.footnote, _micro_style(theme), theme.content_width)
        body_bottom -= footnote_block.height_pt + theme.space.xl

    flow = slide.flow
    n = len(flow.ranks)
    # Rank spacing stays at least twice node spacing so columns read as stages
    # without needing a label to say so. Past three ranks the wide gap would
    # squeeze the columns themselves, so it steps down rather than starving the
    # content it is meant to separate.
    base_gap = theme.space.x3 if n <= 3 else theme.space.xl
    node_gap = theme.space.md

    # A labelled connector needs somewhere to put its label. Rather than let the
    # label overhang the nodes on either side, the gap it crosses widens to hold
    # it -- the space between two ranks is the label's home, so it is the gap
    # that has to accommodate the content, not the content that has to shrink.
    rank_of = {node.id: i for i, rank in enumerate(flow.ranks) for node in rank.nodes}
    gaps = [base_gap] * max(0, n - 1)
    for edge in flow.edges:
        if not edge.label:
            continue
        left, right = rank_of[edge.source], rank_of[edge.target]
        if abs(right - left) != 1:
            continue
        index = min(left, right)
        needed = layout_text(edge.label, _micro_style(theme), theme.content_width).width_pt
        gaps[index] = max(gaps[index], needed + 2 * theme.space.sm)

    rank_w = (theme.content_width - sum(gaps)) / n
    if rank_w < 96:
        raise LayoutError(
            f"{n} ranks leave only {rank_w:.1f} pt per column; split the diagram across two slides"
        )

    # Measure every rank before placing anything, so the tallest one can be
    # centred and the rest aligned to the same optical centre.
    geometry: list[tuple[Rank, float, list[float], float]] = []
    for rank in flow.ranks:
        container_pad = theme.space.lg if rank.boxed else 0.0
        inner_w = rank_w - 2 * container_pad
        header_h = 0.0
        if rank.boxed:
            label_block = layout_text(rank.label or "", _body_style(theme, bold=True), inner_w)
            header_h = label_block.height_pt
            if rank.caption:
                caption_block = layout_text(rank.caption, _micro_style(theme), inner_w)
                header_h += theme.space.xs + caption_block.height_pt
            header_h += theme.space.lg
        heights = [_node_box_height(node, inner_w, theme) for node in rank.nodes]
        total = header_h + sum(heights) + node_gap * (len(heights) - 1) + 2 * container_pad
        geometry.append((rank, header_h, heights, total))

    tallest = max(total for _, _, _, total in geometry)
    available = body_bottom - body_top
    if tallest > available:
        raise LayoutError(
            f"diagram needs {tallest:.1f} pt of height but only {available:.1f} pt remain; "
            "reduce nodes per rank or shorten captions"
        )
    centre = body_top + available / 2

    node_rects: dict[str, Rect] = {}
    #: Nodes that live inside a drawn container, mapped to that container's
    #: bounds. A connector leaving such a node has to leave the container too,
    #: or it visibly crosses the border of the box it is escaping.
    container_of: dict[str, Rect] = {}
    node_shapes: list[Shape] = []
    text_shapes: list[Shape] = []

    for index, (rank, header_h, heights, total) in enumerate(geometry):
        rank_x = theme.margin + index * rank_w + sum(gaps[:index])
        rank_y = centre - total / 2
        container_pad = theme.space.lg if rank.boxed else 0.0
        inner_w = rank_w - 2 * container_pad

        if rank.boxed:
            container = Rect(rank_x, rank_y, rank_w, total)
            for node in rank.nodes:
                container_of[node.id] = container
            shapes.append(
                RectShape(
                    name=f"Group {rank.label}",
                    rect=container,
                    fill=None,
                    stroke=Stroke(theme.palette.accent_dark, theme.hairline),
                )
            )
            label_block = layout_text(rank.label or "", _body_style(theme, bold=True), inner_w)
            text_shapes.append(
                TextShape(
                    name=f"Group label {rank.label}",
                    rect=Rect(rank_x + container_pad, rank_y + container_pad, inner_w, label_block.height_pt),
                    lines=label_block.lines,
                    size_pt=theme.type_scale.body,
                    color=surface.ink,
                    bold=True,
                    line_height=theme.type_scale.lh_body,
                )
            )
            if rank.caption:
                caption_block = layout_text(rank.caption, _micro_style(theme), inner_w)
                text_shapes.append(
                    TextShape(
                        name=f"Group caption {rank.label}",
                        rect=Rect(
                            rank_x + container_pad,
                            rank_y + container_pad + label_block.height_pt + theme.space.xs,
                            inner_w,
                            caption_block.height_pt,
                        ),
                        lines=caption_block.lines,
                        size_pt=theme.type_scale.micro,
                        color=surface.muted_ink,
                        line_height=theme.type_scale.lh_label,
                    )
                )

        y = rank_y + container_pad + header_h
        for node, height in zip(rank.nodes, heights, strict=True):
            box = Rect(rank_x + container_pad, y, inner_w, height)
            node_rects[node.id] = box
            node_surface = theme.palette.accent_solid if node.emphasis else theme.palette.panel
            node_shapes.append(
                RectShape(
                    name=f"Node {node.id}",
                    rect=box,
                    fill=node_surface.fill,
                )
            )
            pad_x, pad_y = _node_pad_x(theme), _node_pad_y(theme)
            label_block = layout_text(node.label, _body_style(theme, bold=True), inner_w - 2 * pad_x)
            text_shapes.append(
                TextShape(
                    name=f"Node label {node.id}",
                    rect=Rect(box.x + pad_x, box.y + pad_y, inner_w - 2 * pad_x, label_block.height_pt),
                    lines=label_block.lines,
                    size_pt=theme.type_scale.body,
                    color=node_surface.ink,
                    bold=True,
                    line_height=theme.type_scale.lh_body,
                )
            )
            if node.caption:
                caption_block = layout_text(node.caption, _micro_style(theme), inner_w - 2 * pad_x)
                text_shapes.append(
                    TextShape(
                        name=f"Node caption {node.id}",
                        rect=Rect(
                            box.x + pad_x,
                            box.y + pad_y + label_block.height_pt + theme.space.xs,
                            inner_w - 2 * pad_x,
                            caption_block.height_pt,
                        ),
                        lines=caption_block.lines,
                        size_pt=theme.type_scale.micro,
                        color=node_surface.muted_ink,
                        line_height=theme.type_scale.lh_label,
                    )
                )
            y += height + node_gap

    # Connectors sit below nodes so an arrow can never cover a label.
    for edge in flow.edges:
        shapes.extend(_route(edge, node_rects, container_of, theme, text_shapes))

    shapes.extend(node_shapes)
    shapes.extend(text_shapes)

    if footnote_block:
        shapes.append(
            TextShape(
                name="Footnote",
                rect=Rect(
                    theme.margin,
                    CANVAS_H_PT - theme.margin_y - footnote_block.height_pt,
                    theme.content_width,
                    footnote_block.height_pt,
                ),
                lines=footnote_block.lines,
                size_pt=theme.type_scale.micro,
                color=surface.muted_ink,
                line_height=theme.type_scale.lh_label,
            )
        )

    return RenderedSlide(background=surface.fill, shapes=tuple(shapes))


def _route(
    edge,
    node_rects: dict[str, Rect],
    container_of: dict[str, Rect],
    theme: Theme,
    text_shapes: list[Shape],
) -> list[Shape]:
    """Route one connector from source to target.

    Adjacent, vertically-aligned nodes get a single straight segment. Anything
    else gets a three-segment elbow that turns at the midpoint of the gap, which
    keeps every connector orthogonal and every turn on the same vertical line.

    When a node sits inside a drawn container, the connector attaches to the
    *container's* edge rather than the node's -- unless both ends are in the same
    container, in which case the relationship is internal and the nodes are the
    right anchors.
    """
    source = node_rects[edge.source]
    target = node_rects[edge.target]
    src_box = container_of.get(edge.source)
    dst_box = container_of.get(edge.target)
    same_container = src_box is not None and src_box is dst_box

    stroke = Stroke(theme.palette.neutral_600, theme.hairline, dashed=edge.dashed)

    x1 = source.right if same_container or src_box is None else src_box.right
    x2 = target.x if same_container or dst_box is None else dst_box.x
    y1, y2 = source.cy, target.cy
    segments: list[Shape] = []

    if abs(y1 - y2) < 0.5:
        segments.append(
            LineShape(name=f"Edge {edge.source}-{edge.target}", x1=x1, y1=y1, x2=x2, y2=y2, stroke=stroke, arrow_end=True)
        )
        label_x, label_y = (x1 + x2) / 2, y1
    else:
        mid = (x1 + x2) / 2
        segments.append(LineShape(name=f"Edge {edge.source}-{edge.target} a", x1=x1, y1=y1, x2=mid, y2=y1, stroke=stroke))
        segments.append(LineShape(name=f"Edge {edge.source}-{edge.target} b", x1=mid, y1=y1, x2=mid, y2=y2, stroke=stroke))
        segments.append(
            LineShape(name=f"Edge {edge.source}-{edge.target} c", x1=mid, y1=y2, x2=x2, y2=y2, stroke=stroke, arrow_end=True)
        )
        label_x, label_y = mid, y1

    if edge.label:
        # The box is centred on the run so it occupies only the gap the routing
        # already reserved for it. A small width cushion absorbs EMU rounding --
        # a box sized to the exact predicted width can round a fraction short
        # and make the renderer wrap a single word onto two lines.
        block = layout_text(edge.label, _micro_style(theme), theme.content_width)
        label_w = block.width_pt + theme.space.xs
        # The label sits on whichever side of the horizontal run the elbow does
        # not descend into, so it never lands on the vertical segment.
        above = y2 >= y1
        label_top = (
            label_y - block.height_pt - theme.space.xs if above else label_y + theme.space.xs
        )
        text_shapes.append(
            TextShape(
                name=f"Edge label {edge.source}-{edge.target}",
                rect=Rect(
                    label_x - label_w / 2,
                    label_top,
                    label_w,
                    block.height_pt,
                ),
                lines=block.lines,
                size_pt=theme.type_scale.micro,
                color=theme.palette.muted,
                align=Align.CENTER,
                line_height=theme.type_scale.lh_label,
            )
        )
    return segments


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

_ENGINES = {
    TitleSlide: layout_title_slide,
    StatementSlide: layout_statement_slide,
    KeyValueSlide: layout_key_value_slide,
    DiagramSlide: layout_diagram_slide,
}


def layout_slide(slide: Slide, theme: Theme) -> RenderedSlide:
    engine = _ENGINES.get(type(slide))
    if engine is None:
        raise LayoutError(f"no layout engine for {type(slide).__name__}")
    return engine(slide, theme)


def layout_deck(deck: Deck, theme: Theme) -> RenderedDeck:
    return RenderedDeck(
        title=deck.title,
        author=deck.author,
        slides=tuple(layout_slide(slide, theme) for slide in deck.slides),
    )
