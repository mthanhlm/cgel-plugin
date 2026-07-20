# The audit, the render, and the self-critique

Three gates, in this order. The engine runs the first. The second needs your
eyes on a picture. The third is a judgement about the deck as a whole.

## 1. The engine's audit

Runs automatically on `build` and `audit`.

**Blocking — geometric facts, no judgement involved. The build stops.**

- Text wider or taller than its box
- Any shape extending past the canvas
- Two shapes partially overlapping (containment is fine — a label belongs inside
  its node)
- An arrowhead ending anywhere other than on a shape
- Text below the contrast floor on the fill behind it

**Advisory — defensible taste. Reported, not enforced.**

- Accent covering more than 5% of a slide
- A type size not on the deck's scale, or more than four sizes on one slide
- A title opening with an empty marketing phrase

Advisory findings are not optional for you. They are advisory because a human
might have a reason; you usually do not, so fix them.

## 2. Looking at the render

```bash
python3 tools/preview.py render spec.json -o preview/
python3 tools/preview.py check  spec.json
```

`check` is mechanical: it reports any text drawn outside the box the layout
reserved for it. In practice that means a font substituted to different widths,
because everything else is already caught earlier. If it fires, the fix is
almost never in the deck — check that Arial, or a metric-compatible substitute
like Liberation Sans, is installed.

**Then open the images.** The engine has already proved nothing overflows,
collides or leaves the canvas, so do not re-check geometry. Look for what is
true of the picture and invisible in the model.

Say each finding out loud, one line — "slide 3: the two right-hand nodes read as
a pair but are not one" — because a finding you have to phrase is a finding you
actually had.

**"No findings" is a real answer for a slide.** Everything below is
fault-finding, and a list of only faults quietly pressures you to produce one
per slide. A manufactured finding is worse than a missed one: it sends the next
person to fix something that was fine. Say a slide is good and move on.

### Per slide

**In two seconds, where does your eye land?**
If it lands nowhere, or somewhere unimportant, the slide has no primary element.
The most valuable question here, and the hardest to answer honestly, because you
know where you *meant* it to land.

**Then where does it go second, and third?**
The first landing tells you the slide has a focus. The path afterwards tells you
whether the focus is the right one. If the eye reads a diagram against its own
flow direction, the heaviest element is not the most important one.

**Does the whitespace look distributed, or left over?**
Cramped in one region and empty in another is the tell. Whitespace should look
like a decision.

**Does anything group that should not — or fail to group that should?**
Proximity and sameness both imply relationship, whatever the model says. Two
unrelated nodes closer to each other than to their own rank read as a pair. A
row of identically-styled boxes reads as peers even when one is a parent.

**Read only the words, ignoring every shape. Does the slide still make its
point?**
If not, the diagram is carrying meaning the labels should carry.

**Can you say what each shape is for, in one sentence?**
"It marks a dark slide" is not a purpose. Neither is "branding".

### Across slides

**Do two slides depict the same thing differently?**
The most damaging defect that reaches this stage, and the only place it can be
caught. If slide 2 shows four stages and slide 5 shows the same pipeline with
five, one of them is wrong and a reader will believe whichever they saw last.

**Do two adjacent slides look like the same picture with the words swapped?**
Reusing a layout is fine. Reusing it *next to itself* reads as a template.

**Does the deck end, or merely stop?**
A deck can pass every per-slide check and still trail off. The last slide should
land something.

### From the contact sheet alone

- At thumbnail size, can you still tell what each slide claims? If the titles
  carry it, that is a real strength — say so.
- Would you know which slide matters most?
- Does one slide look like it came from a different deck?
- Would swapping any two slides' backgrounds break anything? If not, the
  light/dark pattern is decoration rather than structure. Do not go looking for
  a story that fits — almost any arrangement will accept one.

### Anti-slop

These survive geometry checks because none of them is a geometry problem. Full
rules in `anti-slop.md`.

- Three or more boxes in a row, same size, same treatment, no reason
- A container that groups nothing, or a box inside a box for decoration
- Colour, weight or dashing that varies without meaning anything
- A title that names a topic instead of making a claim
- The same thing called two different names on two slides

**When something is wrong, fix the content or the structure — never the
numbers.** There is no manual positioning here by design. A slide that looks
wrong is a slide whose content is wrong for its idiom.

## 3. The self-critique

**Run this before handing the deck over, on the deck as a whole.** Score each
axis 1–5. Anything below 3 means another pass. Two passes is normal; three
usually means the brief is wrong, not the deck.

**Philosophy — does this deck take a position?**
Read the titles alone, in order. Do they make an argument, or do they name
topics? A deck whose titles are all nouns has not decided anything yet.

**Hierarchy — in two seconds, what is primary on each slide?**
That is roughly how long a slide gets. If the eye has to search, the slide has
either two messages or none.

**Execution — is everything actually in spec?**
Zero blocking findings, zero advisory findings, no invented figures, consistent
naming across every slide.

**Specificity — does this look like *this* deck?**
Would these slides work for a different subject with the nouns swapped? If so,
the structure is generic. A diagram that reflects the real shape of the real
system cannot be reused for a different one.

**Restraint — has everything that does not earn its place been removed?**
The strongest single edit is usually deleting a slide. Look for the one that
restates the previous one.

**Variety — is this structurally different from the last deck you built?**
Not colour-different — structurally different. Same idiom in the same order for
every deck is template repetition even when the words change.

## When a slide fails

Fix it in this order, and stop at the first one that works:

1. **Cut content.** Almost always the right answer. A slide that will not fit is
   a slide carrying two ideas.
2. **Split the slide.** Two clear slides beat one dense one; there is no prize
   for a low page count.
3. **Change the idiom.** Content that resists a diagram may be a `key_value`;
   content that resists that may be a `statement`.

Never shrink type, never remove whitespace, never use `--force`. Those trade a
visible problem for an invisible one.
