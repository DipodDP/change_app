---
name: Change
description: Find the cheapest currency conversion route through exchanges you have actually made
colors:
  ground: "#0f172a"
  ground-deep: "#0a0f1e"
  surface: "#172033"
  surface-raised: "#1e293b"
  surface-hover: "#26344c"
  line: "#2c3a52"
  line-soft: "#223049"
  line-hover: "#3b4d69"
  line-field: "#64779a"
  line-field-hover: "#8496ab"
  ink: "#f8fafc"
  ink-dim: "#94a3b8"
  ink-faint: "#8496ab"
  amber: "#f59e0b"
  amber-soft: "#fbbf24"
  violet: "#4f46e5"
  violet-deep: "#4338ca"
  violet-hi: "#a5b4fc"
  violet-hi-hover: "#c7d2fe"
  on-accent: "#ffffff"
  green: "#34d399"
  red: "#f87171"
  red-soft: "#fca5a5"
  success-line: "#1d6a52"
  success-ink: "#a7f3d0"
  danger-line: "#7f2b2b"
  danger-wash: "#3a1a1a"
typography:
  display:
    fontFamily: "Fira Code, ui-monospace, Menlo, monospace"
    fontSize: "26px"
    fontWeight: 600
    letterSpacing: "-0.02em"
    fontFeature: "tabular-nums"
  headline:
    fontFamily: "Fira Sans, system-ui, -apple-system, sans-serif"
    fontSize: "18px"
    fontWeight: 600
    lineHeight: 1.25
  title:
    fontFamily: "Fira Sans, system-ui, -apple-system, sans-serif"
    fontSize: "16px"
    fontWeight: 600
    letterSpacing: "0.02em"
  body:
    fontFamily: "Fira Sans, system-ui, -apple-system, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.6
  bodySm:
    fontFamily: "Fira Sans, system-ui, -apple-system, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Fira Sans, system-ui, -apple-system, sans-serif"
    fontSize: "13px"
    fontWeight: 500
  eyebrow:
    fontFamily: "Fira Sans, system-ui, -apple-system, sans-serif"
    fontSize: "12px"
    fontWeight: 600
    letterSpacing: "0.04em"
    textTransform: "uppercase"
  micro:
    fontFamily: "Fira Sans, system-ui, -apple-system, sans-serif"
    fontSize: "11px"
    fontWeight: 600
    letterSpacing: "0.04em"
    textTransform: "uppercase"
  numeric:
    fontFamily: "Fira Code, ui-monospace, Menlo, monospace"
    fontSize: "15px"
    fontFeature: "tabular-nums"
rounded:
  sm: "8px"
  md: "12px"
  pill: "999px"
  focus: "4px"
spacing:
  s-1: "4px"
  s-2: "8px"
  s-3: "12px"
  s-4: "16px"
  s-5: "24px"
  s-6: "32px"
  s-7: "48px"
components:
  button-primary:
    backgroundColor: "{colors.violet}"
    textColor: "#ffffff"
    rounded: "{rounded.sm}"
    padding: "11px 18px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "{colors.violet-deep}"
    textColor: "#ffffff"
  button-ghost:
    backgroundColor: "{colors.surface-raised}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "11px 18px"
  button-ghost-hover:
    backgroundColor: "{colors.surface-hover}"
    textColor: "{colors.ink}"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.ink-dim}"
    rounded: "{rounded.sm}"
  button-danger:
    backgroundColor: "transparent"
    textColor: "{colors.red}"
    rounded: "{rounded.sm}"
  card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.md}"
    padding: "{spacing.s-5}"
  card-result:
    backgroundColor: "{colors.surface-raised}"
    rounded: "{rounded.md}"
    padding: "{spacing.s-5}"
  input:
    backgroundColor: "{colors.ground-deep}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "11px 12px"
    height: "44px"
  tag-best:
    backgroundColor: "rgba(245, 158, 11, .16)"
    textColor: "{colors.amber-soft}"
    rounded: "{rounded.pill}"
    padding: "3px 10px"
  tag-cost:
    backgroundColor: "rgba(248, 113, 113, .14)"
    textColor: "{colors.red}"
    rounded: "{rounded.pill}"
    padding: "3px 10px"
---

# Design System: Change

## Overview

**Creative North Star: "The Ledger Light"**

A dark room where only the numbers glow. The ground is near-black because the
figures written on it are the entire product; amber is the money, and
everything else — labels, chrome, borders — recedes into slate so that nothing
competes with a payout figure. The interface is the page a ledger is written
on, not an instrument panel.

This system is flat on purpose. A ledger has no shadows: depth comes from tonal
layering, one surface tone lifted off another, with a single hairline border to
separate them. Motion is similarly restrained — one duration, one easing, used
only to acknowledge a pointer. Nothing animates to impress.

Numbers are set in Fira Code with tabular figures wherever they appear, so
digits align in a column and two amounts can be compared by eye without
reading them. Prose is set in Fira Sans and stays quiet. The typographic
hierarchy inverts the usual arrangement: the largest type on the page is not a
heading but a sum of money.

**Key Characteristics:**
- Near-black OLED ground; tonal layering instead of shadow
- Amber reserved for money and the winning route
- Indigo for actions, never for data
- Monospaced tabular numerals for every figure
- One motion duration (180ms ease), pointer feedback only
- Bilingual EN/RU; layouts absorb ~30% string growth

## Colors

A cold slate ground with two signals: amber for value, indigo for intent.

### Primary
- **Signal Amber** (#f59e0b): Money and the winning route. The best payout
  figure, the "best rate" tag, the brand mark, and the focus ring. Its scarcity
  is what makes a winning route unmistakable at a glance.
- **Lifted Amber** (#fbbf24): Text-weight amber on dark washes, where the base
  amber would not clear contrast on a tinted surface.

### Secondary
- **Action Indigo** (#4f46e5): Buttons and controls the user presses. Never
  applied to data. Darkens to #4338ca on hover so white text gains contrast
  (6.29:1 at rest, 7.90:1 pressed) rather than losing it. The token is still
  named `--violet`; the hue moved to indigo, the role did not.
- **Link Indigo** (#a5b4fc): Links, and the mark on a transfer hop, on the dark
  ground (8.96:1) where the solid accent would fail contrast.

### Tertiary
- **Confirm Green** (#34d399): Successful outcomes only.
- **Alert Red** (#f87171): Losing-route deltas, destructive actions, errors.
- **Lifted Red** (#fca5a5): Text-weight red on a red wash — the shortfall tag —
  where the base red falls to 4.33:1 (6.31:1 here).

### Neutral
- **Ledger Black** (#0f172a): The page ground.
- **Recessed Black** (#0a0f1e): Input wells — fields sit *below* the surface,
  not above it.
- **Slate Surface** (#172033): Standard card ground.
- **Raised Slate** (#1e293b): The result card and route cards; one step nearer
  the reader than a standard card.
- **Hairline** (#2c3a52) / **Soft Hairline** (#223049): Separation at 1px.
- **Field Line** (#64779a, #8496ab on hover): The edge of an input or select.
  A field must be findable by its boundary (WCAG 1.4.11, 3:1); the hairline is
  1.6:1, so controls get their own line — 3.6:1 on a card.
- **Paper White** (#f8fafc): Primary text.
- **Muted Slate** (#94a3b8): Secondary text. 6.9:1 on the ground.
- **Faint Slate** (#8496ab): Tertiary text. Clears 4.5:1 on every surface it
  lands on, including the lightest (4.83:1 on Raised Slate).

### Named Rules

**The Money Rule.** Amber marks money and the winner — nothing else. The
winning payout, the tag that names it, and the brand mark. The focus ring is
the one carve-out, because an accessibility affordance must be the most
visible thing on the page when it appears. When everything is amber, no route
is the best one.

**The Actions Are Not Data Rule.** The accent belongs to controls the user
presses, and to the transfer mark that says money moved without converting.
A figure is never indigo; a button is never amber.

**The Recession Rule.** Inputs are darker than the surface holding them. A
field is a well the user fills, not a raised element.

## Typography

**Display / Numeric Font:** Fira Code (with ui-monospace, Menlo, monospace)
**Body Font:** Fira Sans (with system-ui, -apple-system, sans-serif)

**Character:** An engineer's pairing, used for a plain reason rather than a
technical costume: every number in this product is compared against another
number, and tabular figures make columns line up so the comparison is visual
rather than arithmetic. Fira Sans handles language; Fira Code handles money.

**The scale**

| Role | Size | Family | Use |
|---|---|---|---|
| Display | 26px / 600 / -0.02em | Mono | The payout figure — the largest type on any screen |
| Headline | 18px / 600 | Sans | Empty-state headings |
| Title | 16px / 600 / 0.02em, uppercase | Sans | Section headings; 17px in Paper White for the result section |
| Body | 16px / 1.6 | Sans | Prose |
| Numeric | 15px, tabular | Mono | Table figures, rates, chain hops |
| Label | 13px / 500 | Sans | Field labels, hints |
| Micro | 11–12px / 600, 0.06em, uppercase | Sans | Payout captions, mobile row labels |

**Rules.** Every figure uses `font-variant-numeric: tabular-nums`. Section
headings are uppercase with positive tracking; the result section's heading is
one step larger and in Paper White, because the answer outranks the evidence.

## Layout

**Container:** 880px max width, centered, with safe-area-aware gutters
(`max(20px, env(safe-area-inset-*))`) and 72px of bottom padding above the
inset.

**Spacing scale:** a 4-unit base — 4, 8, 12, 16, 24, 32, 48px. The steps are
far enough apart to be felt; values between them (11px vs 12px) say the same
thing to the eye and are drift, not rhythm.

**The 2:1 rhythm.** The gap between two sections is twice the padding inside
one (48px vs 24px; 32px vs 16px on narrow viewports). This ratio is what makes
proximity carry grouping, so a heading belongs to the rows beneath it before
any border is drawn. Borders confirm grouping; they never create it.

**Breakpoints:** 720px (the query bar puts the amount on its own row, then
From → To side by side with the arrow kept between them) and 640px (cards
tighten their padding). The ledger does not follow the viewport: it is a
container, and below 760px of its own width the table becomes one card per
row, each column header traveling with its value as a label. Six columns need
about 770px to keep every figure on one line, and figures never wrap.

**Density:** the ledger is reference material and is set tighter (8px cell
padding, 16px between columns) than the comparison it supports. Two usage scenes are equally
first-class: a phone at the counter and a desk reviewing later.

## Elevation & Depth

**Tonal by default.** Depth is a three-step tonal ramp — Ledger Black →
Slate Surface → Raised Slate — with 1px hairlines for separation. No shadow is
used on any flat surface; a card that appears nearer is a lighter tone, not a
lifted one.

**Shadows are permitted only for genuinely floating overlays** — modals,
popovers, toasts — none of which exist in the product today. Any such shadow
must carry both an offset and a soft blur; a zero-offset colored halo is
decoration, not depth. The sticky masthead uses a backdrop blur with a
translucent ground rather than a shadow.

**State is carried by border and tone, never by lift.** A hovered card
brightens its border; the winning route is bordered in amber over a faint
amber gradient wash.

## Shapes

- **12px** — cards, route cards, and the result panel
- **8px** — buttons, inputs, chips, and hops
- **999px** — tags and mode pills
- **4px** — the focus ring's own radius

Borders are 1px, always. A colored border wider than a hairline is not part of
this language. Corners are uniformly rounded; no single-corner or asymmetric
treatments.

## Components

**Buttons.** 44px minimum height, 8px radius, 15px/600 label, 180ms transition
on color and border. Five variants, each with a distinct job: `primary`
(indigo, the one action per view), `ghost` (raised slate with a hairline),
`quiet` (transparent, for masthead chrome), `danger` (transparent with a dark
red hairline, filling to a red wash on hover), and `sm` (36px, 13px label) for
in-row actions. `.btn-reset` is a bare-button normalizer, not a visual variant.

**The destructive-action pattern.** A destructive control sits quiet at rest so
the masthead stays calm, and turns unmistakably red the moment a pointer or
focus ring reaches it. Destructive actions that lose data are confirmed on
their own page, never in a modal.

**Cards.** 12px radius, 24px padding, one hairline border. The result card
lifts to Raised Slate; the ledger card drops its background entirely and dims
its heading, so the evidence recedes behind the answer. Cards are never nested.

**Inputs.** Recessed to Recessed Black, 8px radius, 44px minimum height, edged
in Field Line. Number and date fields are mono with tabular figures; text
fields stay in Fira Sans. Border brightens on hover; the amber focus ring
carries focus.

**Tags.** Pill-shaped, 12px/600, on a tinted wash of their own hue — amber for
the winner, red for a shortfall percentage.

**The chain.** A route renders as monospaced currency hops joined by arrows,
with the bank named above each arrow. The bank belongs to the arrow — the
conversion — not to the currency.

**Tables.** Hairline row separators, no vertical rules, no zebra striping.
Figures are mono and right-aligned; the row action sits at the end. When the
ledger is narrower than 760px the table becomes cards and the header cells
become inline labels.

## Do's and Don'ts

**Do**
- Set every figure in mono with tabular numerals
- Keep amber for money and the winner; let its rarity do the work
- Express depth as tone, and grouping as space
- Give a destructive action its own confirmation page with real counts
- Name the bank on the arrow, where the conversion happens
- Write for EN and RU together; leave room for ~30% growth
- State a rate as historical; it came from a conversion already made

**Don't**
- Add a shadow to a flat surface, or a halo with no offset
- Use amber for ordinary emphasis, or the action accent for a number
- Nest a card inside a card
- Introduce a spacing value between the scale's steps
- Let a section's internal padding rival the gap between sections
- Imply a rate is a live market quote — it never is
- Add a second motion duration or an entrance animation
- Use an emoji or a Unicode glyph where an icon belongs (icons are drawn SVG,
  2–2.5px stroke, `currentColor`)
