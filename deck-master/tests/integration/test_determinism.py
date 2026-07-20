"""The same deck must produce the same bytes, on any machine, forever.

Determinism is what makes a generated deck reviewable: the diff of a rebuild
should be empty unless the content changed. Testing a build against itself is
not enough -- two builds on the same host agree even when the output encodes
that host. So the real assertion is against a committed hash.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

from deckmaster.layout import layout_deck
from deckmaster.serialize.pptx import FROZEN_ZIP_DATE, write_pptx
from deckmaster.theme import DEFAULT_THEME

GOLDEN = Path(__file__).resolve().parent.parent / "golden" / "pipeline_deck.sha256"


def _build_bytes(deck) -> bytes:
    buffer = io.BytesIO()
    write_pptx(layout_deck(deck, DEFAULT_THEME), buffer)
    return buffer.getvalue()


def test_two_builds_are_byte_identical(example_deck):
    assert _build_bytes(example_deck) == _build_bytes(example_deck)


def test_output_matches_the_committed_golden_hash(example_deck):
    """Catches host-dependent output that a build-twice check cannot see.

    If this fails after an intentional change, regenerate the golden file -- but
    only once the diff has been looked at, because an unexplained change here
    means the bytes moved without the content moving.
    """
    expected = GOLDEN.read_text(encoding="ascii").strip()
    actual = hashlib.sha256(_build_bytes(example_deck)).hexdigest()
    assert actual == expected, (
        f"output changed: expected {expected}, got {actual}. "
        "If the deck content changed deliberately, update tests/golden/pipeline_deck.sha256."
    )


def test_zip_entries_carry_no_host_or_clock_state(example_deck, tmp_path):
    """The two fields that silently differ across machines.

    `create_system` records the building OS, and the timestamp records when. Both
    are pinned; without the pin, Linux and macOS builds diverge byte-for-byte
    while every same-host test still passes.
    """
    path = tmp_path / "deck.pptx"
    write_pptx(layout_deck(example_deck, DEFAULT_THEME), path)
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
    assert infos
    for info in infos:
        assert info.create_system == 0, f"{info.filename} records host OS {info.create_system}"
        assert info.date_time == FROZEN_ZIP_DATE, f"{info.filename} carries a real timestamp"
        # DEFLATE output differs between zlib, zlib-ng and vendor-tuned builds
        # for identical input, so compressing would make the bytes depend on
        # which zlib CPython is linked against -- a host dependency no
        # same-machine test could reveal.
        assert info.compress_type == zipfile.ZIP_STORED, (
            f"{info.filename} is compressed; the output would then depend on the linked zlib build"
        )


def test_part_order_is_stable(example_deck, tmp_path):
    order = []
    for run in range(2):
        path = tmp_path / f"deck{run}.pptx"
        write_pptx(layout_deck(example_deck, DEFAULT_THEME), path)
        with zipfile.ZipFile(path) as archive:
            order.append(archive.namelist())
    assert order[0] == order[1]


def test_no_build_timestamp_leaks_into_the_document_properties(example_deck):
    payload = _build_bytes(example_deck)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        core = archive.read("docProps/core.xml").decode("utf-8")
    assert "2020-01-01T00:00:00Z" in core
