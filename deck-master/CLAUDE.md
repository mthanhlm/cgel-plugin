# Deck Master

Generates editable `.pptx` decks from structured data with no presentation
library, no template and no rendering engine.

## Commands

```bash
python3 -m pytest tests -q                              # full suite
PYTHONPATH=src python3 -m deckmaster.cli build spec.json -o deck.pptx
PYTHONPATH=src python3 -m examples.pipeline_deck out.pptx

python3 tools/preview.py render spec.json -o preview/   # images to look at
python3 tools/preview.py check  spec.json               # drawn vs declared
```

`pyproject.toml` sets `pythonpath = ["src"]` for pytest, so tests need no
`PYTHONPATH`; direct module invocation does.

## Hard constraints

These are product requirements, not preferences. Breaking one breaks the point
of the tool.

- **Standard library only in the generation path.** No `python-pptx`, no
  `pptxgenjs`, no LibreOffice, no network. `tests/unit/test_standalone.py`
  builds a deck in a clean subprocess and fails if any third-party module is
  imported. `pytest` and `lxml` are dev extras and must stay out of `src/`.
  `lxml` exists solely so the test suite can validate output against the
  bundled ISO-29500 schemas; importing it from `src/` breaks the whole point
  of the tool.
- **Deterministic output.** Same input, same bytes, on any host. Fixed part
  order, `ZipInfo.create_system = 0`, frozen timestamps, and `ZIP_STORED`.
  Do not switch to `ZIP_DEFLATED` for file size: deflate output differs between
  zlib and zlib-ng for identical input, so compressing makes the bytes depend on
  the linked zlib build — a host dependency no same-machine test can catch.
  `tests/golden/pipeline_deck.sha256` is the canary — if it changes, look at the
  diff before regenerating it.
- **No magic numbers in layout.** Every colour, size and gap comes from
  `theme.py`. If a value is needed that does not exist, add it to the theme
  first. A hardcoded `17.0` in a layout engine is a bug even if it looks right.
- **Layout is pure.** No clocks, no randomness, no global state. Layout engines
  are `(slide, theme) -> RenderedSlide` and nothing else.

## Architecture

Each stage is a pure function of the one before it:

```
loader.py → model.py → layout.py → scene.py → audit.py → serialize/pptx.py → validate/opc.py
```

- `model.py` — content and structure, no coordinates. Content limits are
  enforced at construction, so bad content fails at the earliest, loudest point.
- `theme.py` — all design tokens. `Surface` pairs a fill with its ink so
  dark-text-on-dark-fill is unexpressible.
- `text/metrics.py` — measurement and line breaking. **Ceil-only, no kerning
  credit**, so predicted width is always ≥ rendered width. Unknown codepoints
  raise rather than measuring as zero.
- `layout.py` — one engine per idiom. Measures before it sizes; raises
  `LayoutError` rather than overflowing.
- `scene.py` — resolved primitives. **List order is z-order**: ground,
  containers, connectors, nodes, text.
- `audit.py` — blocking geometry findings, advisory style findings. It
  re-derives geometry independently rather than trusting layout; checking a
  claim with the code that made it proves nothing.
- `serialize/pptx.py` — hand-written OOXML. XML is emitted as strings, not via
  ElementTree, because byte-identity needs control over attribute order and
  self-closing tags.
- `validate/opc.py` — the offline gate for "opens without repair".

`tools/preview.py` sits **outside** the package and depends on it, never the
reverse. It shells out to LibreOffice and Poppler, which is exactly why it is
not in `src/`. Two tests hold that line: one greps the engine for imports of the
tool, the other parses every engine module and fails if a renderer name appears
in any string literal or identifier that is not a docstring.

The docstring exclusion is the whole subtlety. Excluding *all* strings was the
first attempt and made the check nearly useless, because a shell-out writes the
program name as a string — `subprocess.run(["soffice", …])` sailed straight
through a test whose only job was to catch it. Excluding nothing is no better:
several modules explain at length why a renderer is deliberately absent, and a
plain search flags that prose as the defect it describes. A companion test runs
the same detection over a sample that really does shell out, so the guard cannot
quietly stop working.

## Validation has two layers, and they are not redundant

**Packaging rules** (`validate/opc.py`, stdlib-only, ships to users): every
relationship resolves and is well-formed, every part is typed, identifiers are
unique and in range, no content-type is declared twice, no relationship target
carries an unescaped space. These live *between* parts, so no XML schema can
express them.

**Schema conformance** (`tests/integration/test_package.py`, needs `lxml`,
test-only): element order, cardinality and datatypes *inside* each part,
checked against the ISO-29500 schemas bundled in `tests/schemas/`. Those files
are redistributed from ECMA International under terms that require them to stay
**unmodified** with `tests/schemas/NOTICE` alongside — do not edit them, and do
not add one without a NOTICE entry; a test enforces both. This is
authoritative where a hand-written table is not — it covers the whole
specification rather than the elements someone remembered.

`CHILD_ORDER` in `validate/opc.py` still exists because the shipped validator
must run without a dependency. It is the smaller, hand-maintained mirror of what
the schema states completely. If the two ever disagree, **the schema is right.**

**What none of this proves.** Conformance to the published standard is not the
same as confirmation against PowerPoint, which has tolerances and strictnesses
of its own. No PowerPoint is available in this environment, so every rule here
takes the strict reading rather than relying on leniency that cannot be tested.
Do not describe the output as PowerPoint-verified.

## Two things that will bite you

**OOXML child order mixes `sequence` and `choice`.** `CHILD_ORDER` in
`validate/opc.py` models this with rank *groups*: same rank means an unordered
choice. Treating a choice as a sequence produces confident false positives — the
validator's first version rejected a real, working presentation for putting
`p:grpSp` before `p:sp`, which is perfectly legal.

**That guard is currently missing, and you should know it.** It was a real deck
authored by a real tool, kept at the repo root as a golden fixture, and it was
the only check that the validator does not reject files PowerPoint is happy
with. It was internal material and had to be removed before this repository
could be published. `tests/integration/test_package.py` still has the test; it
skips when the file is absent.

**If you tighten a validator rule, put a real presentation back first** — any
`.pptx` saved by PowerPoint, LibreOffice or Keynote, at
`kx-agent-spaces-roadmap-jul-sep-2026.pptx`, or change `REFERENCE_DECK` in
`tests/conftest.py` to point at yours. Without one, the suite cannot tell a
stricter rule from a wrong one, and a validator that produces confident false
positives is worse than one that misses.

**`slots=True` dataclasses break zero-argument `super()`.** The decorator builds
a replacement class, leaving the `super()` closure pointing at the discarded
original. `model.py` uses a module-level `_set_title()` helper instead. Do not
"fix" it back to inheritance.

## Font metrics

`data/arial_metrics.json` is generated once by
`text/_build_metrics.py` from Liberation Sans, which is metrically compatible
with Arial. Regenerate only if the character set needs extending:

```bash
PYTHONPATH=src python3 -m deckmaster.text._build_metrics \
  --regular /usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf \
  --bold    /usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf \
  --out     src/deckmaster/data/arial_metrics.json
```

`tests/unit/test_metrics.py` asserts the values against published Arial widths,
so a wrong source font is caught immediately.

## Why there are two ways to be wrong

The engine can prove a deck is geometrically sound and schema-valid. It cannot
prove the deck is any good, and it cannot notice that the font it measured is
not the font being drawn. Both need the rendered result, which is what
`tools/preview.py` is for.

`check` is mechanical and belongs in review: it reports text drawn outside the
box layout reserved for it. Tolerances are 1.5 pt horizontally and 8 pt
vertically, measured rather than chosen — on known-good output the worst
excursions are +0.04 pt and +4.65 pt. They differ by an order of magnitude
because the axes mean different things: horizontally a glyph box and a text box
measure the same quantity, so disagreement means a substituted font; vertically
a glyph box spans ascender to descender while the reserved box is built from
line heights, so a few points of disagreement is expected and meaningless.

`render` is for eyes, and the checklist is in
`skills/deck-master/references/audit.md`. Nothing enforces that anyone looks —
that is the honest limit of this half.

## Design rules

The visual system is documented in
`skills/deck-master/references/visual-system.md` and enforced in `theme.py` and
`audit.py`. When changing anything visual, change the token and the reference
doc together — the skill reads those docs, so a drifted doc silently teaches the
wrong thing.
