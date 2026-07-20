# The visual system

Every value here is enforced in code. This document explains *why* each one is
what it is, so that when a slide looks wrong you can tell whether the content is
at fault or the system is.

## Canvas

960 x 540 pt — PowerPoint's standard 16:9 slide, in points rather than EMU so
that type sizes and gaps are expressed in the same unit.

Margins are 64 pt at the sides and 48 pt top and bottom. They differ on purpose:
64 pt is 6.7% of the width but 11.9% of the height, so using one number for both
would spend the dimension that runs out first. Content never touches the edge —
a shape at the boundary reads as an overflow accident rather than a full-bleed
decision.

## Colour

Four layers, and exactly one accent.

| Role | Value | Notes |
|---|---|---|
| Paper (light) | `FBFCFD` | Cool-tinted. Never pure white. |
| Paper (dark) | `1B2732` | ~15% lightness. Never pure black. |
| Ink | `22303C` / `F2F5F8` | Primary text, light and dark ground. |
| Muted ink | `5B6670` / `9AA4AE` | Secondary text. |
| Neutrals | `EEF2F6` `DCE4EC` `D9E0E6` `3D4A57` | Panel fills, rules, connectors. |
| Accent | `1F5FA8` | One hue. `123A66` and `4F86C4` are tones of it. |

**Pure `#000` and `#FFF` are the signature of an untouched template**, so
neither appears. Connectors are `3D4A57`, not black. Every grey carries a slight
cool tint toward the accent hue, because flat greys read as a default.

**Accent covers at most 5% of a slide.** Past that nothing is emphasised,
because everything is. The audit reports a slide that exceeds it. Legitimate
uses: the mark beside a title, one emphasised node, a single rule.

**Every fill ships paired with its ink.** A `Surface` carries both, so a shape
whose fill changes cannot keep the old text colour — the dark-text-on-dark-fill
defect is not expressible. Contrast floors: 4.5:1 for text, 3:1 for large text
and shape outlines.

## Type

One family: Arial. It is metric-stable across platforms, which is what makes
overflow predictable — and predictability matters more here than novelty,
because a font substitution reflows the entire deck on someone else's machine.

Five sizes, a 1.25 ratio, and no sixth:

| Token | Size | Role |
|---|---|---|
| display | 48 pt | Title and statement slides |
| title | 31 pt | Slide titles |
| lead | 20 pt | Subtitles, deck lines |
| body | 16 pt | Node labels, entry text |
| micro | 14 pt | Captions, edge labels, footnotes — **the floor** |

Nothing goes below 14 pt. A slide is read at three to ten metres, so the
comfortable web floor of 16 px is far too small here.

Further hierarchy comes from **weight and colour, not another size**: 700 for
headings against 400 for body is a 300-unit gap that survives projection, where
a single 1.25 size step reads as an accident.

Line heights: 1.08 display, 1.12 title, 1.35 lead, 1.40 body, 1.25 labels.

## Space

A 4 pt scale: 4, 8, 12, 16, 24, 32, 48, 64, 96, 128. Every gap, inset and offset
is one of these. An arbitrary value — a shape nudged to 17 pt by eye — is the
most reliable sign that a layout was assembled rather than designed.

Rank spacing is at least twice node spacing, so columns read as stages without a
label saying so. Node padding is asymmetric (12 pt sides, 8 pt top and bottom)
because line-height already contributes visual padding vertically, and vertical
space is the dimension that runs out.

## Geometry

Rectangles, lines and ellipses. **No rounded corners, no gradients, no shadows,
no icons.** Depth comes from weight and fill lightness; a drop shadow on a slide
shape is the template signature. Emphasis changes fill and ink, never stroke
weight — thickening a stroke changes a node's outer bounds and pulls it out of
alignment with its rank.

## Z-order

Fixed, and emitted in this sequence: ground, containers, connectors, nodes,
text, annotations. Connectors sit beneath nodes so an arrow can never cover the
label it points at.

## Text measurement

Line breaks are computed before any box is sized, using real Arial advance
widths extracted from a metrically-compatible font. Measurement is **ceil-only
and applies no kerning credit**, so the prediction is always at least as wide as
what renders — erring toward a little extra whitespace rather than an overflow.
A character outside the table raises rather than measuring as zero, because a
zero-width character would silently produce a box too small for its own text.

Shapes are emitted with autofit disabled and explicit zero insets, so PowerPoint
reproduces the planned line breaks instead of re-wrapping and invalidating every
height the audit checked.
