# Deck Master

Builds editable `.pptx` decks from structured data. No presentation library, no
template, no rendering engine, and nothing to install beyond Python.

```bash
deckmaster build spec.json -o deck.pptx
```

The output is validated against the published OOXML standard, contains only
native editable shapes, and is byte-for-byte identical every time you rebuild
it.

## Why it exists

Tools that generate slides tend to fail in one of two ways. Either they produce
a valid file that looks generated — the same card grid, the same three-column
icon row, text shrunk until it fits — or they produce something that looks
plausible in a preview and greets you with *"PowerPoint found a problem with
content"*.

Deck Master treats both as bugs with tests attached:

- **Nothing overflows.** Text is measured against real Arial advance widths
  before any box is sized. When content will not fit, the build fails with an
  error naming the field, rather than shrinking type.
- **Nothing collides or escapes the canvas.** A geometric audit blocks partial
  overlaps, off-canvas shapes, dangling arrowheads, and text below the contrast
  floor.
- **It opens.** Two layers. A shipped, dependency-free validator checks the OPC
  packaging rules — relationships resolve, parts are typed, identifiers are
  unique and in range. The test suite additionally validates every slide, the
  presentation, master, layout and theme against the published ISO-29500
  schemas, which covers element order, cardinality and datatypes completely
  rather than by hand. Between them they catch the failures
  that make PowerPoint offer to repair a file and that permissive viewers render
  happily.
- **Rebuilds are identical.** Fixed part order, pinned ZIP metadata, frozen
  timestamps and uncompressed entries, asserted against a committed hash.
  Entries are stored rather than deflated because DEFLATE output differs
  between zlib builds, which would make the file depend on the host.

## Standalone by design

The engine imports only the Python standard library — `zipfile`, `json`,
`math`, `dataclasses`, `pathlib`, `argparse` and `xml.etree` for validation.
There is no `python-pptx`, no `pptxgenjs`, and no
LibreOffice anywhere in the generation path. A test imports every module in the
package, builds and validates a deck through the CLI in a clean interpreter, and
fails if a single third-party module gets imported.

LibreOffice, where present, is used only as an optional render smoke check in
the test suite, and those tests skip cleanly without it.

## Install

```bash
pip install -e .          # or just run it from source:
PYTHONPATH=src python3 -m deckmaster.cli build spec.json -o deck.pptx
```

Python 3.11 or newer.

## Usage

```bash
deckmaster build spec.json -o deck.pptx   # audit, then write
deckmaster audit spec.json                # findings only, writes nothing
deckmaster check deck.pptx                # validate any existing package
```

`build` refuses to write a deck carrying a blocking finding.

## The spec

Four slide types — `title`, `diagram`, `key_value`, `statement`. Diagrams are
the default: content with stages, tiers or a flow becomes a diagram rather than
a bullet list.

```json
{
  "title": "Platform review",
  "slides": [
    {"type": "title", "title": "The platform is ready; the migration is not"},
    {"type": "diagram", "title": "Every write goes through one path",
     "ranks": [
       {"nodes": [{"id": "client", "label": "Clients"}]},
       {"label": "Write path", "boxed": true,
        "nodes": [{"id": "api", "label": "API", "caption": "validates"},
                  {"id": "log", "label": "Commit log", "emphasis": true}]}
     ],
     "edges": [{"source": "client", "target": "api", "label": "requests"}]}
  ]
}
```

You choose content and structure. Colour, type, spacing and position come from
the design system and cannot be overridden — that is what keeps a deck coherent.
See `skills/deck-master/references/visual-system.md`.

A complete example is in `examples/`:

```bash
PYTHONPATH=src python3 -m examples.pipeline_deck out.pptx
```

## As a Claude Code plugin

Ships a `deck-master` skill and a `/deck` command. The skill carries the design
rules, the idiom catalogue, and a self-critique pass that runs before a deck is
handed over.

```
/deck our Q3 platform migration, for the architecture review
```

## Looking at the output

The engine proves a deck is geometrically sound. It cannot prove it is any
good, and it cannot notice that the font it measured is not the font being
drawn. Both need the rendered result:

```bash
python3 tools/preview.py render spec.json -o preview/   # one image per slide, plus a contact sheet
python3 tools/preview.py check  spec.json               # what was drawn vs what was planned
```

`check` reports any text drawn outside the box the layout reserved for it. In
practice that means a substituted font: every width prediction stays internally
consistent while being about a typeface nobody is looking at, so no static check
can see it.

This is a development tool. It needs LibreOffice and Poppler, which is exactly
why it lives outside the package — building and validating a deck needs neither.
Two tests hold that line: one for imports, one that parses every engine module
for a renderer named in any non-docstring string or identifier.

## Architecture

```
model.py       content and structure; no coordinates, limits enforced here
theme.py       design tokens: palette, type scale, spacing scale
text/metrics.py  Arial advance widths; measurement and line breaking
layout.py      one engine per idiom; model in, absolute geometry out
scene.py       resolved primitives; list order is z-order
audit.py       blocking geometry checks, advisory style checks
serialize/     OOXML emission
validate/      offline package validation
loader.py      JSON in
cli.py         build / audit / check
```

Each stage is a pure function of the one before it, which is what makes the
output deterministic and the failures easy to locate.

## Tests

```bash
python3 -m pytest tests -q
```

`tests/unit` covers measurement, content limits, the design system's own
invariants, layout purity, and that hostile input cannot produce an invalid
attribute. `tests/integration` validates the package against both the packaging
rules and the ISO-29500 schemas, injects specific defects to prove every check
can actually fail, asserts byte-stability against a committed hash, and — if
LibreOffice is installed — renders the deck and checks every slide produced a
page.

Schema validation needs `lxml`, which is a development extra alongside `pytest`.
Nothing a user installs changes: `tests/unit/test_standalone.py` builds and
validates a deck in a clean subprocess and fails on any third-party import.

One caveat stated plainly: conformance to the standard is a strong offline proxy
for "PowerPoint will open this", not proof of it. No PowerPoint was available
during development, so every rule takes the strict reading.

One test wants a golden fixture: a real presentation authored by a real tool,
to prove the validator does not reject files PowerPoint is happy with. That
guard caught a genuine defect during development — the validator was rejecting a
perfectly legal deck. The fixture was internal material and is not published
here, so the test skips. Drop any real `.pptx` at
`kx-agent-spaces-roadmap-jul-sep-2026.pptx`, or repoint `REFERENCE_DECK` in
`tests/conftest.py`, and it runs again. Do that before tightening any validator
rule.

## License

MIT
