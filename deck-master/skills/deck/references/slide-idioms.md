# Choosing an idiom

Four shapes. Most decks use `diagram` for the majority of slides, and that is
the intended balance — the engine exists because slides default to prose when
the content is structural.

## `diagram` — the default

A left-to-right flow of ranks. Each rank is a column; each column is a stage,
tier or category. Edges connect nodes across ranks.

**Reach for it when the content has any of:** stages, a pipeline, tiers, layers,
before/after, request paths, ownership boundaries, a sequence, or parts of a
system.

```json
{"type": "diagram",
 "title": "Every write goes through one path",
 "subtitle": "No service writes to storage directly.",
 "ranks": [
   {"nodes": [{"id": "client", "label": "Clients", "caption": "web and mobile"}]},
   {"label": "Write path", "caption": "the only way in", "boxed": true,
    "nodes": [
      {"id": "api", "label": "API", "caption": "validates"},
      {"id": "log", "label": "Commit log", "caption": "append only", "emphasis": true}
    ]},
   {"nodes": [{"id": "store", "label": "Storage", "caption": "read replicas"}]}
 ],
 "edges": [
   {"source": "client", "target": "api", "label": "requests"},
   {"source": "log", "target": "store", "label": "replicates", "dashed": true}
 ]}
```

**Ranks:** two to four. One rank is not a flow — use `key_value`. Five or more
gets refused, because the columns become too narrow to read; split the diagram
across two slides instead.

**Nodes per rank:** one to four. More than four is a list, not a stage.

**`boxed`:** use it for the rank the slide is actually about. One container per
diagram — nested containers are the diagram version of card-in-card.

**`emphasis`:** exactly one node, the one under discussion.

**`dashed`:** secondary, asynchronous, or optional. Never decorative.

**Edges:** only the ones that carry meaning. A diagram where everything connects
to everything says nothing. Omitting an obvious edge is usually fine — the
left-to-right order already implies sequence.

## `key_value` — claims with support

Two to four rows, each a claim and one line backing it, separated by hairline
rules. Set `dark: true` to make it a section-weight slide.

Use it for guarantees, principles, comparisons of two or three options, or
decisions with rationale. Do **not** use it as a bullet list with extra steps:
if the rows do not each make a claim, the content wants a diagram.

## `title` — the cover

State the deck's claim, not its subject. "Q3 Platform Review" names a meeting;
"The platform is ready; the migration is not" starts an argument.

## `statement` — one idea, alone

A dark slide with a single line and most of the space empty. Use it as a section
break, a pivot, or the last thing you want remembered. The emptiness is the
design — a statement slide that fills up has become a `key_value` slide without
admitting it.

Use at most one or two in a deck. They work by contrast, and contrast does not
survive repetition.

## Deck shape

A reliable spine, not a template to follow blindly:

1. `title` — the claim
2. `diagram` — the situation as it is
3. `diagram` — what changes
4. `key_value` — what that guarantees, or what it costs
5. `statement` — the one thing to remember

Vary it to the argument. A deck that always uses this exact order is template
repetition even when every word differs.
