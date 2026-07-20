"""The reference example: a deck about Deck Master, built with Deck Master.

Run it with::

    python3 -m examples.pipeline_deck out.pptx

It is deliberately a real deck rather than a feature demo -- it argues a
position, it leads with a diagram, and every slide carries one message. It is
also the fixture the integration tests build, so if it stops looking right, the
tests notice.
"""

from __future__ import annotations

import sys
from pathlib import Path

from deckmaster.audit import audit_deck
from deckmaster.layout import layout_deck
from deckmaster.model import (
    Deck,
    DiagramSlide,
    Edge,
    Entry,
    Flow,
    KeyValueSlide,
    Node,
    Rank,
    StatementSlide,
    TitleSlide,
)
from deckmaster.serialize.pptx import write_pptx
from deckmaster.theme import DEFAULT_THEME


def build() -> Deck:
    return Deck(
        title="Deck Master",
        author="Deck Master",
        slides=(
            TitleSlide(
                title="Slides are a layout problem",
                subtitle="Deck Master treats them like one. Structured data in, editable decks out.",
            ),
            DiagramSlide(
                title="Four stages, no renderer",
                subtitle="Each stage is a pure function of the one before it.",
                flow=Flow(
                    ranks=(
                        Rank(nodes=(Node(id="input", label="Structured input", caption="JSON or Python"),)),
                        Rank(nodes=(Node(id="model", label="Document model", caption="meaning, not coordinates"),)),
                        Rank(
                            label="Layout",
                            caption="measures, then places",
                            boxed=True,
                            nodes=(
                                Node(id="measure", label="Measure text", caption="real Arial metrics"),
                                Node(id="place", label="Place shapes", caption="on the spacing scale"),
                            ),
                        ),
                        Rank(nodes=(Node(id="pptx", label="OOXML package", caption="editable shapes", emphasis=True),)),
                    ),
                    edges=(
                        Edge(source="input", target="model"),
                        Edge(source="model", target="measure"),
                        Edge(source="place", target="pptx", label="emit"),
                    ),
                ),
                footnote="Nothing is rasterised. Every box, line and label stays a native shape you can select and edit.",
            ),
            DiagramSlide(
                title="The audit runs before the file exists",
                subtitle="Geometry findings block the build. Style findings are advisory.",
                flow=Flow(
                    ranks=(
                        Rank(nodes=(Node(id="laid", label="Laid-out slide", caption="absolute geometry"),)),
                        Rank(
                            label="Audit",
                            caption="blocking checks",
                            boxed=True,
                            nodes=(
                                Node(id="overflow", label="Text overflow", caption="measured, not guessed"),
                                Node(id="collide", label="Collisions", caption="pairwise bounds"),
                                Node(id="canvas", label="Off-canvas", caption="every shape in frame"),
                            ),
                        ),
                        Rank(nodes=(Node(id="write", label="Write package", caption="only if clean", emphasis=True),)),
                    ),
                    edges=(
                        Edge(source="laid", target="overflow"),
                        Edge(source="canvas", target="write", label="pass"),
                    ),
                ),
            ),
            KeyValueSlide(
                title="Three guarantees",
                subtitle="Each one is a test, not an intention.",
                dark=True,
                entries=(
                    Entry(
                        label="Opens without repair",
                        body="A package validator checks element order, identifier ranges and relationships offline.",
                    ),
                    Entry(
                        label="Nothing overflows",
                        body="Text is measured against real Arial advance widths before any box is sized.",
                    ),
                    Entry(
                        label="Rebuilds are identical",
                        body="Fixed part order and a frozen timestamp make the bytes stable across machines.",
                    ),
                ),
            ),
            StatementSlide(
                title="One message per slide",
                subtitle="If a slide needs two, it is two slides.",
            ),
        ),
    )


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else Path("pipeline_deck.pptx")
    deck = build()
    rendered = layout_deck(deck, DEFAULT_THEME)

    report = audit_deck(rendered, DEFAULT_THEME)
    for finding in report.findings:
        print(f"  [{finding.severity}] slide {finding.slide}: {finding.message}", file=sys.stderr)
    if report.blocking:
        print(f"audit failed with {len(report.blocking)} blocking finding(s)", file=sys.stderr)
        return 1

    write_pptx(rendered, out)
    print(f"wrote {out} ({len(rendered.slides)} slides)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
