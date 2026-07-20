#!/usr/bin/env python3
"""Render a deck so it can be looked at, and check what was actually drawn.

This is a development tool. It lives outside ``src/`` on purpose: it shells out
to LibreOffice and Poppler, and the engine's defining constraint is that
generating a deck needs neither. Nothing here is imported by the engine, and
``tests/unit/test_standalone.py`` fails if that ever changes.

It exists because two things cannot be established from the model alone.

**Whether the deck is any good.** The audit proves nothing overflows, collides
or leaves the canvas. It cannot tell you the hierarchy is weak, the whitespace
is lopsided, or the slide looks like every other generated slide. That needs
eyes, and eyes need pictures.

**Whether the font being measured is the font being drawn.** Every width
prediction is computed from a metrics table for Arial. If Arial is missing and
something metrically different is substituted, the predictions stay internally
consistent and every static check still passes -- they are simply correct about
a typeface nobody is looking at. Comparing drawn glyph boxes against the boxes
layout reserved is the only way to see it.

Usage::

    python3 tools/preview.py render examples/pipeline_deck.json -o out/
    python3 tools/preview.py check  examples/pipeline_deck.json
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from deckmaster.layout import layout_deck  # noqa: E402
from deckmaster.loader import deck_from_json  # noqa: E402
from deckmaster.scene import RenderedDeck, TextShape  # noqa: E402
from deckmaster.serialize.pptx import write_pptx  # noqa: E402
from deckmaster.theme import DEFAULT_THEME  # noqa: E402
from deckmaster.units import CANVAS_H_PT, CANVAS_W_PT  # noqa: E402

# --------------------------------------------------------------------------
# Tolerances
#
# Both are measured, not guessed. On the example deck every rendered word is
# matched to the box layout reserved for it, and the worst excursions past a
# declared edge are +0.04 pt horizontally and +4.65 pt vertically. The
# thresholds below sit well clear of those so ordinary output never trips them.
#
# They differ by an order of magnitude because the axes mean different things.
# Horizontally, a glyph box and a text box measure the same thing, so agreement
# should be near-exact -- which is precisely why this axis detects a substituted
# font. Vertically, a glyph box spans ascender to descender while the reserved
# box is built from line heights, so a few points of legitimate disagreement is
# expected and says nothing about correctness.
# --------------------------------------------------------------------------

H_TOLERANCE_PT = 1.5
V_TOLERANCE_PT = 8.0

#: Slack when deciding which reserved box a word belongs to. Only affects
#: attribution, not whether an excursion is reported.
OWNERSHIP_SLACK_X = 2.0
OWNERSHIP_SLACK_Y = 6.0

_WORD = re.compile(
    r'xMin="([\d.-]+)"\s+yMin="([\d.-]+)"\s+xMax="([\d.-]+)"\s+yMax="([\d.-]+)"\s*>([^<]*)</word>'
)


class ToolMissing(RuntimeError):
    """Raised when an external program this tool needs is not installed."""


@dataclass(frozen=True, slots=True)
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass(frozen=True, slots=True)
class Excursion:
    slide: int
    word: str
    axis: str
    amount: float
    shape: str

    #: Set when a word landed inside no reserved box at all, rather than
    #: spilling past the edge of one it can be attributed to.
    ESCAPED = "no reserved box"

    def __str__(self) -> str:
        if self.axis == self.ESCAPED:
            return f"slide {self.slide}: {self.word!r} was drawn outside every reserved box"
        return (
            f"slide {self.slide}: {self.word!r} extends {self.amount:.2f} pt past the "
            f"{self.axis} edge of {self.shape!r}"
        )


def _tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise ToolMissing(
            f"{name} is not installed. This is a development tool; the engine itself "
            "needs neither LibreOffice nor Poppler, so a deck can still be built and "
            "validated without them."
        )
    return path


def _soffice() -> str:
    for candidate in ("soffice", "libreoffice"):
        if shutil.which(candidate):
            return shutil.which(candidate)
    raise ToolMissing(
        "LibreOffice is not installed (looked for soffice and libreoffice). "
        "This is a development tool; building and validating a deck does not need it."
    )


def build_deck(spec: Path, workdir: Path) -> tuple[RenderedDeck, Path]:
    """Build a deck from a spec and write it into `workdir`.

    The caller supplies the directory and therefore owns its lifetime. An
    earlier version allocated its own with `mkdtemp` and never removed it, so
    every invocation -- including every test run -- left a deck behind in the
    system temp directory.
    """
    rendered = layout_deck(deck_from_json(spec), DEFAULT_THEME)
    workdir.mkdir(parents=True, exist_ok=True)
    pptx = workdir / f"{spec.stem}.pptx"
    write_pptx(rendered, pptx)
    return rendered, pptx


def to_pdf(pptx: Path, outdir: Path) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            _soffice(),
            "--headless",
            # Without an explicit user profile LibreOffice aborts in sandboxes
            # and CI containers with "User installation could not be completed".
            f"-env:UserInstallation=file://{outdir / '.lo-profile'}",
            "--convert-to",
            "pdf",
            str(pptx),
            "--outdir",
            str(outdir),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    pdf = outdir / f"{pptx.stem}.pdf"
    if not pdf.is_file():
        # LibreOffice exits 0 even when it produces nothing, so the file's
        # existence is the only trustworthy signal that conversion worked.
        raise RuntimeError(
            f"LibreOffice produced no PDF.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return pdf


def to_images(pdf: Path, outdir: Path, dpi: int = 110) -> list[Path]:
    """Render every page to a PNG, returning only this run's output.

    Previous renders are deleted first. The output directory is meant to be
    reused -- `preview/` by default -- and the results are read by globbing, so
    without this a three-slide deck rendered over a nine-slide one would list
    and tile six images belonging to a deck that no longer exists. That misleads
    precisely the reviewer this tool exists to serve.

    Zero-padding makes it worse rather than better: pdftoppm pads the page
    number to the width of the last page, so a nine-slide run leaves `slide-1`
    while a twelve-slide run writes `slide-01`, and the two interleave under a
    sort.
    """
    for previous in outdir.glob("slide-*.png"):
        previous.unlink()

    subprocess.run(
        [_tool("pdftoppm"), "-png", "-r", str(dpi), str(pdf), str(outdir / "slide")],
        capture_output=True,
        check=True,
        timeout=300,
    )
    # Sort numerically: a plain sort puts slide-10 before slide-2.
    return sorted(
        outdir.glob("slide-*.png"),
        key=lambda p: int(re.sub(r"\D", "", p.stem) or 0),
    )


def contact_sheet(images: list[Path], out: Path, columns: int = 3) -> Path | None:
    """Tile every slide into one image, so the whole deck can be taken in at once.

    Optional: it needs Pillow, and the individual images are the important
    output. Returning None rather than failing keeps the tool useful on a
    machine that has a renderer but no imaging library.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    if not images:
        return None

    tiles = [Image.open(p).convert("RGB") for p in images]
    width, height = tiles[0].size
    scale = 420 / width
    tw, th = int(width * scale), int(height * scale)
    label = 18
    rows = (len(tiles) + columns - 1) // columns
    pad = 10

    sheet = Image.new(
        "RGB",
        (columns * tw + (columns + 1) * pad, rows * (th + label) + (rows + 1) * pad),
        (245, 246, 248),
    )
    draw = ImageDraw.Draw(sheet)
    for index, tile in enumerate(tiles):
        row, col = divmod(index, columns)
        x = pad + col * (tw + pad)
        y = pad + row * (th + label + pad)
        sheet.paste(tile.resize((tw, th)), (x, y))
        draw.text((x + 2, y + th + 3), f"slide {index + 1}", fill=(70, 80, 90))

    sheet.save(out)
    return out


def read_words(pdf: Path) -> list[list[Word]]:
    """Word bounding boxes per page, in points with a top-left origin.

    Poppler reports these in the PDF's own coordinate space, which for these
    decks is the slide canvas itself -- the page measures 960x540 pt, so no
    transform is needed. That is asserted rather than assumed.
    """
    xml = subprocess.run(
        [_tool("pdftotext"), "-bbox", str(pdf), "-"],
        capture_output=True,
        text=True,
        check=True,
        timeout=300,
    ).stdout

    pages: list[list[Word]] = []
    for chunk in xml.split("<page ")[1:]:
        header = chunk[: chunk.find(">")]
        size = re.search(r'width="([\d.]+)"\s+height="([\d.]+)"', header)
        if size:
            page_w, page_h = float(size.group(1)), float(size.group(2))
            if abs(page_w - CANVAS_W_PT) > 1.0 or abs(page_h - CANVAS_H_PT) > 1.0:
                raise RuntimeError(
                    f"rendered page is {page_w:.1f}x{page_h:.1f} pt but the canvas is "
                    f"{CANVAS_W_PT:.0f}x{CANVAS_H_PT:.0f} pt; coordinates would not be comparable"
                )
        pages.append(
            [
                Word(float(a), float(b), float(c), float(d), text)
                for a, b, c, d, text in _WORD.findall(chunk)
            ]
        )
    return pages


def compare(deck: RenderedDeck, pages: list[list[Word]]) -> list[Excursion]:
    """Report text drawn outside the box layout reserved for it."""
    findings: list[Excursion] = []

    for index, (slide, words) in enumerate(zip(deck.slides, pages), start=1):
        boxes = [s for s in slide.shapes if isinstance(s, TextShape)]
        for word in words:
            if not word.text.strip():
                continue
            # Attribute the word to the tightest reserved box containing its
            # centre. Centre containment is unambiguous where nearest-edge
            # matching is not: neighbouring boxes in a diagram overlap on one
            # axis constantly, and a word's centre lands in exactly one of them.
            owners = [
                b
                for b in boxes
                if b.rect.x - OWNERSHIP_SLACK_X <= word.cx <= b.rect.right + OWNERSHIP_SLACK_X
                and b.rect.y - OWNERSHIP_SLACK_Y <= word.cy <= b.rect.bottom + OWNERSHIP_SLACK_Y
            ]
            if not owners:
                findings.append(
                    Excursion(index, word.text, Excursion.ESCAPED, 0.0, "-")
                )
                continue

            box = min(owners, key=lambda b: b.rect.w * b.rect.h)
            r = box.rect
            for amount, axis in (
                (word.x1 - r.right, "right"),
                (r.x - word.x0, "left"),
            ):
                if amount > H_TOLERANCE_PT:
                    findings.append(Excursion(index, word.text, axis, amount, box.name))
            for amount, axis in (
                (word.y1 - r.bottom, "bottom"),
                (r.y - word.y0, "top"),
            ):
                if amount > V_TOLERANCE_PT:
                    findings.append(Excursion(index, word.text, axis, amount, box.name))

    return findings


def check_deck(spec: Path) -> list[Excursion]:
    """Build, render and compare drawn text against declared geometry."""
    with tempfile.TemporaryDirectory(prefix="deckmaster-check-") as tmp:
        deck, pptx = build_deck(spec, Path(tmp))
        pdf = to_pdf(pptx, Path(tmp))
        pages = read_words(pdf)
    if len(pages) != len(deck.slides):
        raise RuntimeError(
            f"the renderer produced {len(pages)} pages for {len(deck.slides)} slides"
        )
    return compare(deck, pages)


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def cmd_render(args: argparse.Namespace) -> int:
    outdir = args.output
    outdir.mkdir(parents=True, exist_ok=True)
    deck, pptx = build_deck(args.spec, outdir)

    pdf = to_pdf(pptx, outdir)
    images = to_images(pdf, outdir, dpi=args.dpi)
    if len(images) != len(deck.slides):
        raise RuntimeError(
            f"rendered {len(images)} image(s) for {len(deck.slides)} slide(s); "
            "the images in this directory do not describe this deck"
        )

    # The renderer's scratch profile is not output; leaving it in a directory
    # the user opens is noise.
    shutil.rmtree(outdir / ".lo-profile", ignore_errors=True)

    print(f"rendered {len(images)} slide(s) to {outdir}/")
    for image in images:
        print(f"  {image}")

    sheet = contact_sheet(images, outdir / "contact-sheet.png")
    if sheet:
        print(f"contact sheet: {sheet}")
    else:
        print("contact sheet skipped (Pillow not installed); the per-slide images are above")

    print("\nNow look at them. The checklist is in")
    print("skills/deck/references/audit.md, under 'Looking at the render'.")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    findings = check_deck(args.spec)
    if not findings:
        print("no text was drawn outside the box reserved for it")
        return 0
    print(f"{len(findings)} excursion(s):", file=sys.stderr)
    for finding in findings:
        print(f"  {finding}", file=sys.stderr)
    print(
        "\nText drawn outside its reserved box usually means the font being measured is "
        "not the font being drawn -- check that Arial, or a metric-compatible substitute "
        "such as Liberation Sans, is installed.",
        file=sys.stderr,
    )
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="preview",
        description="Render a deck to images, and check what was drawn against what was planned.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    render = sub.add_parser("render", help="render each slide to an image for inspection")
    render.add_argument("spec", type=Path)
    render.add_argument("-o", "--output", type=Path, default=Path("preview"))
    render.add_argument("--dpi", type=int, default=110)
    render.set_defaults(func=cmd_render)

    check = sub.add_parser("check", help="compare drawn text against declared geometry")
    check.add_argument("spec", type=Path)
    check.set_defaults(func=cmd_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ToolMissing as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
