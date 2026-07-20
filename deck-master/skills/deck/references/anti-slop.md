# Writing slides that do not read as generated

These rules are adapted from web anti-slop practice to slides and diagrams.
Where a web rule has no analogue on a slide — hover states, breakpoints, scroll
behaviour, motion — it is simply dropped rather than forced.

## The tells, and what to do instead

**The three-column icon grid.** Three equal columns, an icon above a heading
above two lines of body. It is the single most recognisable generated-slide
shape. If three things are genuinely peers, a diagram rank says so more
precisely. If they are not peers, stop pretending they are.

**Card-in-card.** A bordered panel holding bordered tiles. Pick one containment
layer — usually the outer one is the wrong one. This engine gives you exactly
one grouping device, the boxed rank, and nesting them is not possible.

**Decoration without meaning.** Every shape must encode something. A colour that
means nothing, a container that groups nothing, a shape difference that carries
no distinction — all noise. **If a visual property is not explainable, it should
not vary.**

**Bullet lists in disguise.** Four boxes in a column with a label each is a
bullet list that costs more ink. Use `key_value` and hold it to 2–4 rows, or
find the actual structure and draw it.

**Redrawn UI chrome.** A hand-drawn browser bar or phone frame around a
screenshot. It is a picture of a picture frame. Use the real thing or crop it
away.

**Invented numbers.** Never write a metric the user did not give you. Not
"40% faster", not "99.9% uptime", not "10x". If a slide needs a figure that does
not exist, ask for it or build the slide without the claim. A stat slide with no
stat is the wrong slide.

**Emoji and mixed icon sets.** Neither is available here, which is deliberate.

**Italic emphasis in a heading.** One word italicised inside an upright title is
a reliable tell. Emphasis comes from weight, colour, or an emphasised node.

## Copy

**Titles are claims, not labels.** "Architecture" is a label. "Every write goes
through one path" is a claim. A claim can be argued with, which is what makes
the audience read the slide.

Ban these openings outright — they promise something and say nothing. The audit
flags them:

> Built for the modern team · Unleash your… · Empower your… · Reimagine the way…
> · Supercharge your workflow · Innovative solutions · Seamless integration ·
> In today's digital landscape · Next-generation · Where X meets Y

**One name per thing.** If a node is "Auth Service" on slide 4, it is not
"AuthN" on slide 9. Inconsistent naming is read as two different systems.

**Edge labels are verbs.** `writes to`, `polls`, `emits` — not `data` or
`connection`. An arrow already implies a relationship; the label's job is to say
which one.

**Titles stand alone.** If a title only makes sense while you are talking over
it, it fails the handout test.

Punctuation is normalised automatically: curly quotes, en dashes in ranges
(`Q1–Q3`), a real ellipsis, and a non-breaking space before units so `5 min`
never splits across a line.

## Composition

**Asymmetry reads as intentional; symmetry reads as generated.** The system
holds everything to a left margin for exactly this reason, and it holds it deck-
wide so the consistency itself becomes structure.

**Whitespace is not a gap to fill.** A statement slide is mostly empty on
purpose. The instinct to add a supporting graphic to a slide that has made its
point is the instinct to make it generic.

**Vary rhythm between slides, not within a rank.** Sibling nodes in one rank get
uniform spacing — irregularity there reads as a mistake. Variation belongs
between ranks and between slides.

**One emphasis per slide.** `emphasis` marks the single node under discussion.
Two emphasised nodes emphasise nothing.
