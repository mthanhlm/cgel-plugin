"""Secondary smoke check: a real renderer opens the file.

This is deliberately *not* the correctness gate. LibreOffice is permissive
exactly where PowerPoint is strict -- it will happily render mis-ordered
elements, duplicate shape ids and dangling relationships -- so treating it as
the oracle would give false confidence. `test_package.py` holds that job.

What this adds is the one thing an offline validator cannot: evidence that an
independent implementation can parse and paint the file. It skips cleanly when
LibreOffice is absent, because the engine must never depend on it.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

soffice = shutil.which("soffice") or shutil.which("libreoffice")
requires_libreoffice = pytest.mark.skipif(
    soffice is None, reason="LibreOffice not installed; the engine does not require it"
)


@requires_libreoffice
def test_libreoffice_converts_the_deck_without_error(built_pptx, tmp_path):
    result = subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", str(built_pptx), "--outdir", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert result.returncode == 0, result.stderr

    produced = list(tmp_path.glob("*.pdf"))
    assert produced, f"no PDF produced; stdout={result.stdout} stderr={result.stderr}"
    # A PDF that exists but holds nothing means the slides rendered empty.
    assert produced[0].stat().st_size > 4096


pdftoppm = shutil.which("pdftoppm")


@requires_libreoffice
@pytest.mark.skipif(pdftoppm is None, reason="poppler not installed; page-count check is optional")
def test_every_slide_renders_to_a_page(built_pptx, rendered_deck, tmp_path):
    """Catches slides that convert without error but paint nothing.

    Pages are counted by rasterising rather than by pattern-matching the PDF
    bytes: LibreOffice writes compressed object streams, so the page objects are
    not visible in the raw file at all.
    """
    subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", str(built_pptx), "--outdir", str(tmp_path)],
        capture_output=True,
        timeout=240,
        check=True,
    )
    pdf = next(tmp_path.glob("*.pdf"))
    subprocess.run(
        [pdftoppm, "-png", "-r", "40", str(pdf), str(tmp_path / "page")],
        capture_output=True,
        timeout=240,
        check=True,
    )
    pages = sorted(tmp_path.glob("page*.png"))
    assert len(pages) == len(rendered_deck.slides), (
        f"expected {len(rendered_deck.slides)} pages, rendered {len(pages)}"
    )
    for page in pages:
        assert page.stat().st_size > 512, f"{page.name} rendered essentially blank"


# --------------------------------------------------------------------------
# The render-and-look loop
#
# These exercise tools/preview.py, which is a development tool outside the
# engine. They live here because this is the check that already tolerates the
# renderer being absent, and they skip with it.
# --------------------------------------------------------------------------

import sys as _sys
from pathlib import Path as _Path

_REPO = _Path(__file__).resolve().parent.parent.parent
if str(_REPO / "tools") not in _sys.path:
    _sys.path.insert(0, str(_REPO / "tools"))

EXAMPLE_SPEC = _REPO / "examples" / "pipeline_deck.json"


@pytest.fixture(scope="module")
def preview():
    return pytest.importorskip("preview", reason="tools/preview.py not importable")


@requires_libreoffice
def test_render_produces_one_image_per_slide(preview, tmp_path):
    deck, pptx = preview.build_deck(EXAMPLE_SPEC, tmp_path)
    pdf = preview.to_pdf(pptx, tmp_path)
    images = preview.to_images(pdf, tmp_path)
    assert len(images) == len(deck.slides)
    for image in images:
        assert image.stat().st_size > 1024, f"{image.name} rendered essentially blank"


@requires_libreoffice
def test_check_reports_nothing_on_a_correct_deck(preview):
    """The calibration assertion.

    On the example deck every rendered word sits inside the box layout reserved
    for it, with worst excursions of +0.04 pt horizontally and +4.65 pt
    vertically -- comfortably inside the thresholds. If this ever fires, either
    the tolerances are wrong or the fonts on this machine changed.
    """
    assert preview.check_deck(EXAMPLE_SPEC) == []


@requires_libreoffice
def test_check_detects_a_substituted_font(preview, tmp_path):
    """The defect no static check can reach.

    Every coordinate here was computed from Arial metrics and is left exactly
    as the engine emitted it; only the typeface name changes. The package still
    validates, the geometry audit still passes, and every width prediction is
    still internally consistent -- about a font nobody is drawing. Only
    comparing what was drawn against what was reserved can see it.
    """
    import zipfile

    from deckmaster.layout import layout_deck
    from deckmaster.loader import deck_from_json
    from deckmaster.serialize.pptx import write_pptx
    from deckmaster.theme import DEFAULT_THEME

    deck = layout_deck(deck_from_json(EXAMPLE_SPEC), DEFAULT_THEME)
    original = tmp_path / "original.pptx"
    write_pptx(deck, original)

    swapped = tmp_path / "swapped.pptx"
    with zipfile.ZipFile(original) as src, zipfile.ZipFile(swapped, "w", zipfile.ZIP_DEFLATED) as dst:
        for name in src.namelist():
            payload = src.read(name)
            if name.startswith("ppt/slides/slide") and name.endswith(".xml"):
                payload = payload.decode("utf-8").replace(
                    'typeface="Arial"', 'typeface="DejaVu Serif"'
                ).encode("utf-8")
            dst.writestr(name, payload)

    pdf = preview.to_pdf(swapped, tmp_path)
    findings = preview.compare(deck, preview.read_words(pdf))
    assert findings, "a metrically different font produced no excursions; the check is inert"


@requires_libreoffice
def test_page_size_mismatch_is_refused_rather_than_silently_compared(preview, tmp_path, monkeypatch):
    """Coordinates are only comparable because the page is the canvas.

    If a renderer ever emitted a differently sized page, comparing raw numbers
    would produce confident nonsense, so the assumption is checked rather than
    trusted.
    """
    pdf = preview.to_pdf(preview.build_deck(EXAMPLE_SPEC, tmp_path)[1], tmp_path)
    real = preview.subprocess.run

    def shrink(*args, **kwargs):
        result = real(*args, **kwargs)
        if "-bbox" in args[0]:
            result.stdout = result.stdout.replace('width="960.009449"', 'width="612.000000"')
        return result

    monkeypatch.setattr(preview.subprocess, "run", shrink)
    with pytest.raises(RuntimeError, match="not be comparable"):
        preview.read_words(pdf)


@requires_libreoffice
def test_rendering_into_a_reused_directory_shows_only_this_deck(preview, tmp_path):
    """The output directory is meant to be reused, so it must be cleared.

    A three-slide deck rendered over a nine-slide one would otherwise list and
    tile six images belonging to a deck that no longer exists -- misleading the
    reviewer this tool exists to serve, in the one artefact they are told to
    trust.
    """
    for n in range(1, 10):
        (tmp_path / f"slide-{n}.png").write_bytes(b"stale")

    deck, pptx = preview.build_deck(EXAMPLE_SPEC, tmp_path)
    pdf = preview.to_pdf(pptx, tmp_path)
    images = preview.to_images(pdf, tmp_path)

    assert len(images) == len(deck.slides), (
        f"{len(images)} images for {len(deck.slides)} slides; stale renders leaked in"
    )
    assert not any(p.read_bytes() == b"stale" for p in tmp_path.glob("slide-*.png"))


@requires_libreoffice
def test_images_are_ordered_numerically_not_lexically(preview, tmp_path):
    """A plain sort puts slide-10 before slide-2, mislabelling the contact sheet."""
    deck, pptx = preview.build_deck(EXAMPLE_SPEC, tmp_path)
    images = preview.to_images(preview.to_pdf(pptx, tmp_path), tmp_path)
    numbers = [int("".join(c for c in p.stem if c.isdigit())) for p in images]
    assert numbers == sorted(numbers) == list(range(1, len(images) + 1))
