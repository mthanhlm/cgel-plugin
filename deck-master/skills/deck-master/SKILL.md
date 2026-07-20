---
name: deck-master
description: Build an editable .pptx deck from structured content — architecture diagrams, flows, comparisons, roadmaps, technical or strategy decks. Use whenever the user asks for slides, a deck, a presentation, or a diagram-led explanation of a system. Produces native editable shapes with no template, no library and no rendering engine; guarantees no text overflow, no collisions, and a file PowerPoint opens without repair.
---

# Deck Master

You are writing a deck, not filling a template. The engine handles geometry,
typography, colour and file format. Your job is the part it cannot do: decide
what each slide says and choose the shape that says it.

## The rule that matters most

**Every slide carries exactly one message, and that message is the title.**

If a slide needs two titles, it is two slides. If the title needs a clause to
make sense, the thinking is not finished. Write the title first, then build the
slide that proves it.

## Work in this order

1. **Find the spine.** What is the argument, start to finish? Five slides that
   build on each other beat twelve that each restate the topic.
2. **Choose a shape per slide** from the four idioms below. Reach for `diagram`
   first — if content has stages, parts, tiers or a flow, it is a diagram, not a
   list.
3. **Write the JSON spec** (format below).
4. **Build it**: `deckmaster build spec.json -o deck.pptx`
5. **Read every finding the audit prints.** Blocking findings stop the build.
   Advisory findings are about taste, and you fix those too.
6. **Look at it.** Not optional, and not a glance:

   ```bash
   python3 tools/preview.py render spec.json -o preview/
   python3 tools/preview.py check  spec.json
   ```

   `render` gives you one image per slide and a contact sheet. **Open the
   images and actually look at them**, against the checklist in
   `references/audit.md`. `check` compares what was drawn against what the
   layout planned, which is the only way to notice a font substituting to
   different widths.

7. **Fix what you found, rebuild, look once more — then stop.** One cycle. A
   second is for defects the first introduced, not for nudging things by a
   point.

If the deck came out of a subagent or a previous session, get a **different
reviewer** to do step 6. Whoever built it will see what they intended rather
than what is on the slide, and that is not a failure of attention — it is what
knowing the intent does to you.

## The four idioms

| Type | Use it for | Never use it for |
|---|---|---|
| `title` | The cover. State the deck's claim, not its subject. | A bare topic name. |
| `diagram` | Architecture, flows, stages, tiers, pipelines, comparisons. **The default.** | Prose that has been chopped into boxes. |
| `key_value` | Two to four claims, each with one line of support. | A bullet list wearing a disguise. |
| `statement` | One idea, alone on a dark slide, as a section break or a closing line. | Anything that needs support to land. |

Read `references/slide-idioms.md` before choosing, and
`references/anti-slop.md` before writing any copy.

## The spec format

```json
{
  "title": "Deck title",
  "author": "optional",
  "slides": [
    {"type": "title", "title": "...", "subtitle": "..."},

    {"type": "diagram", "title": "...", "subtitle": "...", "footnote": "...",
     "ranks": [
       {"nodes": [{"id": "a", "label": "Ingest", "caption": "from the queue"}]},
       {"label": "Core", "caption": "the part under discussion", "boxed": true,
        "nodes": [
          {"id": "b", "label": "Router", "caption": "picks a handler"},
          {"id": "c", "label": "Store", "caption": "append only", "emphasis": true}
        ]}
     ],
     "edges": [{"source": "a", "target": "b", "label": "events", "dashed": false}]},

    {"type": "key_value", "title": "...", "subtitle": "...", "dark": true,
     "entries": [{"label": "Claim", "body": "One line of support."}]},

    {"type": "statement", "title": "...", "subtitle": "..."}
  ]
}
```

**Diagram vocabulary.** A `rank` is one column — one stage of a left-to-right
flow. `boxed: true` draws it as a titled container, which is how you show that
several nodes belong to one system; a boxed rank needs a `label`. `emphasis`
marks the *one* node under discussion. `dashed` means a secondary or
asynchronous relationship — never use it for decoration.

## Hard limits

The engine rejects content that breaks these, with an error naming the field.
They are not stylistic preferences; they are what keeps a slide readable at
three metres.

| Field | Limit |
|---|---|
| Slide title | 60 characters, 9 words |
| Subtitle, footnote | 120 characters |
| Node label | 28 characters, 5 words |
| Node caption | 48 characters |
| Edge label | 3 words |
| Key-value entry label | 34 characters |
| Key-value entry body | 160 characters |
| Key-value entries per slide | 2 to 4 |
| Ranks per diagram | up to 4 comfortably; more gets refused |

If content will not fit, the answer is fewer ideas on that slide — never
smaller type. The engine will not shrink text to make room, and neither should
you.

**Characters.** Latin-1 plus typographic punctuation: curly quotes, en and em
dashes, ellipsis, bullet, right arrow, degree, multiplication sign. Anything
else — `€`, `✓`, CJK, emoji — is rejected at load with the field named, because
a character with no metrics cannot be measured and so cannot be guaranteed to
fit. Straight quotes, `--` and `...` are converted for you.

## What you do not control

Colour, font, size, spacing and position all come from the design system. There
is no override, deliberately: a deck stays coherent because nothing can opt out
of it. If a slide looks wrong, the content is wrong. See
`references/visual-system.md` for what the system is and why.

## Commands

```bash
deckmaster build spec.json -o deck.pptx   # audit, then write
deckmaster audit spec.json                # findings only, writes nothing
deckmaster check deck.pptx                # validate an existing package
```

If `deckmaster` is not on PATH, run it from the repository as
`PYTHONPATH=src python3 -m deckmaster.cli`.

`build` refuses to write a deck with a blocking finding. Do not reach for
`--force` — it exists for debugging the engine, and a deck that needs it is a
deck with a defect in it.
