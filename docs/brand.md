# Mosaic Robotics — brand identity for the HR Copilot

One page. Everything a later wave needs to dress the three surfaces in §2 of
`docs/superpowers/plans/2026-09-14-ux-remediation-plan.md` without asking a designer a
question. Assets live in `src/hrmosaic/web/static/brand/`; the token block in §7 is the whole
colour and spacing system and is reproduced verbatim in `brand/brand.css`.

---

## 1. The idea

**A mosaic is many small tiles that only make sense together.** Mosaic Robotics' handbook is
the same shape: a Remote & Hybrid Work Policy here, a Tax & Location Addendum there, a PTO
accrual table, a benefits matrix — dozens of separate tesserae. The assistant's whole job is
to pick the few that answer *this* question and set them into one calm paragraph. So the mark
is a grid that **resolves**: four loose tesserae, then two joined pairs, then one whole tile.
Many policies, one answer.

**Robotics supplies the manners, not the decoration.** Precise, calm, quiet. That means square
corners rather than soft ones, hairlines rather than drop shadows, a 4 px grid nothing escapes,
and one accent used sparingly. Nothing in this identity glows, floats, or celebrates.

The tone follows the plan's own rule for the copy: *plain language, shown work*. The assistant
is never chirpy and never mysterious, and the brand should not be either.

### Explicitly not this

The house style of a machine-generated interface, which this must not be mistaken for:
Inter or Space Grotesk on defaults; a violet-to-blue gradient across a hero; cream and
terracotta; emoji as section markers; 16 px corner radii on everything; soft purple glows
behind cards; a "✨" anywhere. None of those appear in these files, and the do/don't list in
§8 says so in enforceable terms.

---

## 2. Wordmark and mark

### `wordmark.svg` — the product lockup

    [mark]  Mosaic HR Copilot

`Mosaic` is set in **Archivo SemiBold** in `--ink`; `HR Copilot` in **Public Sans Regular** in
`--ink-soft`. The parent company supplies the name, the product supplies the descriptor, and
the weight and colour difference does the separating — no bullet, no slash, no pipe. Every
letter is **converted to paths**, so the file needs no font to render correctly (6.3 KB).

Geometry, on the file's 219 × 30 viewBox: mark 19.2 units, its bottom on the baseline
(y = 22.5) and its top a little above the cap; 10 units between mark and `Mosaic`;
6.4 units between `Mosaic` and `HR Copilot`. Set at font-size 22, tracking left at the
face's own default — Archivo is already tight enough at this size.

* Minimum width **132 px**. Below that use `mark.svg` alone.
* Clear space on all four sides = **half the mark's height**. Nothing enters it, including
  the masthead's own nav.
* The lockup is the masthead's `h1` content on both chat and dashboard. The accessible name
  is carried by the SVG's `<title>`/`aria-label`; if it is inlined, keep visually hidden text
  in the `h1` as well rather than relying on the image alone.

**The corporate wordmark**, if one is ever needed for a document header rather than the app,
is `MOSAIC ROBOTICS` in Archivo SemiBold, all caps, tracking `+0.06em`, `--ink`, with the mark
at cap height to its left and one tessera of clear space between. It is not shipped as a file
because nothing in this app uses it.

### `mark.svg` — the tile mark

A 24 × 24 grid, 1 unit gutters, 0.5 unit corner radius:

| Group | Geometry | Token | Reads as |
|---|---|---|---|
| `.ta` | four 5 × 5 tesserae, top-left quadrant | `--mark-a` | the loose policy fragments |
| `.tb` | two 11 × 5 bars top-right, two 5 × 11 bars bottom-left | `--mark-b` | fragments joining |
| `.tc` | one 11 × 11 tile, bottom-right | `--mark-c` | the single answer |

It is legible down to 16 px because the largest element is nearly half the frame. It carries
its own light/dark fallback, so it is correct as `<img>`, as CSS `background-image`, and
inlined — see §7's note on `--mark-*`.

### `favicon.svg`

The same grid **knocked out of one solid tile** — a 32 × 32 rounded square (radius 6) filled
`--accent`, tesserae in three tints of white. A tab icon has to hold at 16 px against browser
chrome of unknown colour, so the silhouette does the work and the grid is the detail. It flips
to a light verdigris ground with dark tesserae under `prefers-color-scheme: dark`.

Never: the mark rotated, in a circle, in a gradient, over a photograph, or recoloured outside
the three `--mark-*` tones.

---

## 3. Colour

One accent, three neutral grounds, three ink weights, three semantics. The accent is
**verdigris** — the blue-green of oxidised metal. It is the one colour in the system, it means
"the product is speaking or the product is interactive", and it never decorates.

The neutrals are **porcelain**, not the usual blue-grey: a faint green cast (hue ≈ 175°) that
sits under the accent without arguing with it, and reads as unglazed ceramic rather than as a
default UI palette.

### 3.1 Light theme

| Token | Hex | Role |
|---|---|---|
| `--paper` | `#F3F6F5` | the window; the ground everything else sits on |
| `--card` | `#FFFFFF` | a raised surface: message, panel, table, tile |
| `--sunk` | `#E9EEEC` | an inset surface: table header, code block, disabled field |
| `--ink` | `#101D1C` | body copy, headings, table values |
| `--ink-soft` | `#4C5F5D` | ledes, labels, metadata, the lockup's descriptor |
| `--ink-mute` | `#586967` | the least important text on the page; never below 14 px |
| `--accent` | `#0D5C57` | links, buttons, current nav, focus, the resolved tile |
| `--accent-strong` | `#083F3B` | hover and pressed states of an accent fill |
| `--accent-soft` | `#D5E6E2` | the user's own message, a selected chip, an accent ground |
| `--on-accent` | `#FFFFFF` | any label on an accent fill |
| `--line` | `#DBE2E0` | decorative hairline: card edge, table rule, divider |
| `--line-strong` | `#7F8D8B` | the edge of a real control — input, select, secondary button |
| `--focus` | `#0D5C57` | focus ring |
| `--warn` | `#7A4B04` | caution, on `--warn-soft` `#FAEFD9` |
| `--danger` | `#96251E` | destructive or failed, on `--danger-soft` `#FBE7E4` |
| `--ok` | `#1E6335` | passed, allowed, on `--ok-soft` `#E2EFE6` |
| `--mark-a/b/c` | `#58958E` / `#2C736C` / `#0D5C57` | the mark's three tones |

Measured contrast (WCAG 2.1 relative-luminance formula; **4.5:1** is the AA floor for text,
**3:1** for a UI boundary, a focus indicator or a meaningful graphic):

| Pair | Ratio | Needs | |
|---|---|---|---|
| `--ink` on `--card` | **17.29:1** | 4.5 | pass |
| `--ink` on `--paper` | **15.90:1** | 4.5 | pass |
| `--ink` on `--sunk` | **14.74:1** | 4.5 | pass |
| `--ink` on `--accent-soft` | **13.38:1** | 4.5 | pass |
| `--ink-soft` on `--card` | **6.77:1** | 4.5 | pass |
| `--ink-soft` on `--paper` | **6.23:1** | 4.5 | pass |
| `--ink-soft` on `--sunk` | **5.77:1** | 4.5 | pass |
| `--ink-soft` on `--accent-soft` | **5.24:1** | 4.5 | pass |
| `--ink-mute` on `--card` | **5.78:1** | 4.5 | pass |
| `--ink-mute` on `--paper` | **5.32:1** | 4.5 | pass |
| `--ink-mute` on `--sunk` | **4.93:1** | 4.5 | pass |
| `--accent` on `--card` | **7.82:1** | 4.5 | pass |
| `--accent` on `--paper` | **7.19:1** | 4.5 | pass |
| `--accent` on `--sunk` | **6.67:1** | 4.5 | pass |
| `--accent` on `--accent-soft` | **6.05:1** | 4.5 | pass |
| `--on-accent` on `--accent` fill | **7.82:1** | 4.5 | pass |
| `--on-accent` on `--accent-strong` fill | **11.77:1** | 4.5 | pass |
| `--warn` on `--warn-soft` / `--card` / `--paper` | **6.49 / 7.41 / 6.81:1** | 4.5 | pass |
| `--danger` on `--danger-soft` / `--card` / `--paper` | **6.84 / 8.14 / 7.48:1** | 4.5 | pass |
| `--ok` on `--ok-soft` / `--card` / `--paper` | **6.13 / 7.26 / 6.68:1** | 4.5 | pass |
| `--line-strong` on `--card` / `--paper` | **3.45 / 3.17:1** | 3.0 | pass |
| `--focus` on `--card` / `--paper` | **7.82 / 7.19:1** | 3.0 | pass |
| `--mark-a` on `--card` / `--paper` | **3.44 / 3.16:1** | 3.0 | pass |
| `--mark-b` on `--card` / `--paper` | **5.56 / 5.11:1** | 3.0 | pass |
| `--mark-c` on `--card` / `--paper` | **7.82 / 7.19:1** | 3.0 | pass |
| favicon tesserae on the accent ground | **3.24 / 5.07 / 7.82:1** | 3.0 | pass |

Ground separations, which are *not* contrast requirements but are what makes the layering
visible: `--card` / `--paper` 1.09:1, `--sunk` / `--card` 1.17:1, `--accent-soft` / `--paper`
1.19:1, `--line` / `--card` 1.32:1.

### 3.2 Dark theme

Not an inversion. The grounds are a deep porcelain-green near-black — never `#000` — the
accent lifts to a verdigris that can carry text, and shadows are replaced by hairlines.

| Token | Hex | Role |
|---|---|---|
| `--paper` | `#0C1413` | the window |
| `--card` | `#131E1C` | a raised surface |
| `--sunk` | `#080F0E` | an inset surface — in dark, "sunk" is *darker* than the window |
| `--ink` | `#E8EEEC` | body copy |
| `--ink-soft` | `#A2B2AF` | ledes, labels, metadata |
| `--ink-mute` | `#8C9C99` | least important text |
| `--accent` | `#6ACFC2` | links, current nav, focus, accent fills |
| `--accent-strong` | `#93E1D6` | hover and pressed |
| `--accent-soft` | `#11312D` | the user's own message, an accent ground |
| `--on-accent` | `#08100F` | labels on an accent fill (dark ink on a light fill) |
| `--line` | `#24302E` | decorative hairline |
| `--line-strong` | `#5F6E6A` | the edge of a real control |
| `--focus` | `#6ACFC2` | focus ring |
| `--warn` | `#E0B063` | on `--warn-soft` `#2C2211` |
| `--danger` | `#F0918A` | on `--danger-soft` `#33191A` |
| `--ok` | `#72C990` | on `--ok-soft` `#12291B` |
| `--mark-a/b/c` | `#3A7C75` / `#4E9E95` / `#6ACFC2` | the mark's three tones |

| Pair | Ratio | Needs | |
|---|---|---|---|
| `--ink` on `--card` | **14.53:1** | 4.5 | pass |
| `--ink` on `--paper` | **15.89:1** | 4.5 | pass |
| `--ink` on `--sunk` | **16.47:1** | 4.5 | pass |
| `--ink` on `--accent-soft` | **11.91:1** | 4.5 | pass |
| `--ink-soft` on `--card` | **7.74:1** | 4.5 | pass |
| `--ink-soft` on `--paper` | **8.46:1** | 4.5 | pass |
| `--ink-soft` on `--sunk` | **8.78:1** | 4.5 | pass |
| `--ink-soft` on `--accent-soft` | **6.34:1** | 4.5 | pass |
| `--ink-mute` on `--card` | **5.96:1** | 4.5 | pass |
| `--ink-mute` on `--paper` | **6.52:1** | 4.5 | pass |
| `--ink-mute` on `--sunk` | **6.76:1** | 4.5 | pass |
| `--accent` on `--card` | **9.20:1** | 4.5 | pass |
| `--accent` on `--paper` | **10.06:1** | 4.5 | pass |
| `--accent` on `--sunk` | **10.43:1** | 4.5 | pass |
| `--accent` on `--accent-soft` | **7.54:1** | 4.5 | pass |
| `--on-accent` on `--accent` fill | **10.37:1** | 4.5 | pass |
| `--on-accent` on `--accent-strong` fill | **12.81:1** | 4.5 | pass |
| `--warn` on `--warn-soft` / `--card` / `--paper` | **7.86 / 8.58 / 9.39:1** | 4.5 | pass |
| `--danger` on `--danger-soft` / `--card` / `--paper` | **7.05 / 7.42 / 8.11:1** | 4.5 | pass |
| `--ok` on `--ok-soft` / `--card` / `--paper` | **7.71 / 8.51 / 9.31:1** | 4.5 | pass |
| `--line-strong` on `--card` / `--paper` | **3.19 / 3.49:1** | 3.0 | pass |
| `--focus` on `--card` / `--paper` | **9.20 / 10.06:1** | 3.0 | pass |
| `--mark-a` on `--card` / `--paper` | **3.51 / 3.84:1** | 3.0 | pass |
| `--mark-b` on `--card` / `--paper` | **5.40 / 5.91:1** | 3.0 | pass |
| `--mark-c` on `--card` / `--paper` | **9.20 / 10.06:1** | 3.0 | pass |
| favicon tesserae on the accent ground | **3.00 / 3.95 / 10.06:1** | 3.0 | pass |

Separations: `--card` / `--paper` 1.09:1, `--sunk` / `--card` 1.13:1, `--accent-soft` /
`--paper` 1.33:1, `--line` / `--card` 1.25:1.

**Rule for anything added later:** a new colour is only in the system once its ratio against
`--paper`, `--card` and `--sunk` is measured and written into this table. There is no
"decorative" text colour.

---

## 4. Type

Two faces, both SIL Open Font License 1.1, both self-hosted from this repository. No Google
Fonts link, no CDN, no `@import` off-origin — the fonts are files in
`src/hrmosaic/web/static/brand/` and `brand.css` points at them relatively.

### Archivo — display

Omnibus-Type's grotesque, drawn for highlights and headlines at small sizes: flat terminals,
squared-off counters, tight apertures. It is a *machined* face rather than a friendly one,
which is the robotics half of the idea, and its squarish shapes rhyme with the tesserae.
Used for the wordmark, every heading, the eyebrow labels and nothing else.

### Public Sans — body

The USWDS face, drawn for plain-language public interfaces, from Libre Franklin. It is open,
even-coloured, and unusually good at the thing this app does most — long, careful sentences
that must be easy to read and impossible to misread. It also ships `tnum`, which the dashboard
needs for columns of numbers. Used for all body copy, UI labels, table content and data.

The pairing works because the two faces share a skeleton but not a temperament: Archivo is
narrower, tighter and darker at the same size, so a heading separates from its paragraph by
texture rather than by size alone.

### Scale

| Role | Token | Face / weight | Size / leading | Tracking |
|---|---|---|---|---|
| Eyebrow | `--text-eyebrow` | Archivo Medium 500, uppercase | 12 px / 1.2 | `+0.08em` |
| Page title | `--text-h1` | Archivo SemiBold 600 | 22 px / 1.25 | `-0.011em` |
| Section | `--text-h2` | Archivo SemiBold 600 | 18 px / 1.3 | `-0.011em` |
| Sub-section | `--text-h3` | Archivo SemiBold 600 | 16 px / 1.35 | `-0.011em` |
| Body | `--text-body` | Public Sans 400 | 16 px / 1.55 | 0 |
| Small / label | `--text-small` | Public Sans 400 (600 for labels) | 14 px / 1.5 | 0 |
| Meta | `--text-meta` | Public Sans 400 | 13 px / 1.45 | 0 |
| Id / code | `--mono` | system mono stack | 13 px | 0 |

Measure: **40 rem** (`--measure`) for the conversation — about 80 characters of Public Sans at
16 px, against today's 107.

Numbers that get compared down a column — every dashboard table cell, every KPI tile value —
carry `font-variant-numeric: tabular-nums lining-nums` (the `.tabular` helper in `brand.css`).

**Uppercase** is allowed in exactly one place: the eyebrow above a group heading
(`Traffic`, `Quality & safety`). Never on a badge, a KPI label, a table header or a status
pill — that is the pattern the audit flagged (`POLICY FACT`, `SESSIONS (24 H)`, `ESCALATION`).

No third family. Ids and JSON stay on the system mono stack (`--mono`): it costs nothing to
ship, and a fourth downloaded file would buy less than 100 characters of the interface.

### Files and provenance

| File | Bytes | Upstream | Licence |
|---|---|---|---|
| `Archivo-Medium-latin.woff2` | 22,004 | [`Omnibus-Type/Archivo`](https://github.com/Omnibus-Type/Archivo) `fonts/ttf/Archivo-Medium.ttf` | OFL 1.1 — `OFL-Archivo.txt` |
| `Archivo-SemiBold-latin.woff2` | 21,800 | same repo, `fonts/ttf/Archivo-SemiBold.ttf` | OFL 1.1 |
| `PublicSans-Regular-latin.woff2` | 20,200 | [`uswds/public-sans`](https://github.com/uswds/public-sans) `fonts/ttf/PublicSans-Regular.ttf` | OFL 1.1 — `OFL-PublicSans.txt` |
| `PublicSans-Italic-latin.woff2` | 21,120 | same repo, `fonts/ttf/PublicSans-Italic.ttf` | OFL 1.1 |
| `PublicSans-SemiBold-latin.woff2` | 20,188 | same repo, `fonts/ttf/PublicSans-SemiBold.ttf` | OFL 1.1 |
| | **105,312 (102.8 KB)** | budget 400 KB | |

* Archivo: © 2020 The Archivo Project Authors. Upstream version 2.001; the TTFs were taken
  from `master` at commit `b5d63988ce19d044d3e10362de730af00526b672`. Licence copied verbatim
  from the repository root as `OFL-Archivo.txt`.
* Public Sans: © 2015 The Public Sans Project Authors. Upstream version 2.001; commit
  `052e128daf9dc880db9789e045867ffc0e1e87dd`. Licence copied verbatim as `OFL-PublicSans.txt`.
* Both were subset and converted with `fonttools` 4.65 (`pyftsubset --flavor=woff2`) to the
  Google Fonts `latin` range **plus** `U+2190–2193` (arrows), `U+25A0–25A1`, `U+25B2–25BC`
  (the disclosure triangles and the status dot) and `U+2713`, because the plan's copy uses
  them. Layout features kept: `kern, liga, ccmp, locl, mark, mkmk, calt, tnum, lnum, frac,
  sups, subs, case`. Every output file was re-opened with `fontTools.ttLib.TTFont` and the
  OFL name record (ID 13) confirmed present.
* The OFL permits this: the fonts are redistributed with their licences, and neither the
  subsets nor the wordmark outlines are sold on their own. **Reserved Font Names are not used**
  — the font families keep their names, and nothing here is called "Archivo …" or
  "Public Sans …".

---

## 5. Space, radius, elevation

### The tessera grid

Every length is a multiple of **4 px**. `--space-1` … `--space-8` = 4, 8, 12, 16, 24, 32, 48,
64. Nothing uses an off-grid value; if a gap looks wrong at 12, it is 16, not 14.

Typical application: 8 inside a chip, 12 inside a control, 16 inside a card, 24 between cards,
32 between page sections, 48 above a page title.

### Radius

| Token | Value | Used on |
|---|---|---|
| `--radius-tile` | **3 px** | chips, badges, buttons, inputs, selects, id code chips |
| `--radius` | **6 px** | cards, panels, message bubbles, table containers |
| `--radius-bar` | **0** | anything full-bleed: masthead, sticky nav row, mobile composer |

Small on purpose. Large radii are the single loudest tell of a templated interface, and a
mosaic is made of squares. **There is no pill.** Status badges are `--radius-tile` too — a
`border-radius: 999px` anywhere in this app is a bug.

### Elevation

Three levels, and the first two use no shadow at all.

1. **Flat** — `--lift-0: none` plus `--edge` (1 px `--line`). Cards, messages, tables, panels.
   This is the default and covers almost everything.
2. **Raised** — `--edge` plus `--lift-1`. Only the sticky chrome (`.app-chrome`: masthead +
   dashboard nav) once the page has scrolled under it. In dark, `--lift-1` is a hairline
   rather than a shadow, because a blur on a near-black ground reads as a smudge.
3. **Floating** — `--lift-2`. Popovers and the mobile composer's lifted edge. Nothing else.

No coloured shadows, no glows, no `filter: drop-shadow` on the mark, no gradient on any
surface. A card is distinguished from its ground by a hairline and 1.09:1 of luminance, and
that is enough.

### Focus

`--focus-ring: 0 0 0 2px var(--card), 0 0 0 4px var(--focus)` — a 2 px gap in the surface
colour, then a 2 px accent ring. At 7.19:1 minimum against every ground it clears the 3:1
non-text requirement with room to spare, and unlike an outline it follows `--radius-tile`.
Applied with `:focus-visible`, never removed.

---

## 6. Applying it — the surfaces in the plan

Guidance, not markup; W2 owns the templates.

* **Masthead (§2 shell).** `--card` ground, `--radius-bar`, bottom `--edge`, sticky with
  `--lift-1`. `wordmark.svg` at 26 px tall as the `h1`. The segmented `Chat | Dashboard`
  switch: `--radius-tile`, `--line-strong` edge, the current half filled `--accent` with
  `--on-accent` text and `aria-current="page"`.
* **Chat turn (§3.3).** The user's message on `--accent-soft`, no border, `--radius`; the
  assistant's on `--card` with `--edge`. Answer prose at `--text-body` on `--measure`. An
  inline source reference is a `button` in `--accent` with a dotted 1 px underline — accent
  colour is never the *only* signal. The `Sources (6)` strip is `--sunk` with `--edge`.
* **Demo & grader panel (§3.7).** `--sunk` ground, `2px dashed var(--line-strong)`,
  `--radius`. Its `[DEMO]` marker is an eyebrow in `--warn` on `--warn-soft` at
  `--radius-tile` — the one place warn is used for something that is not a warning, because
  "this is scaffolding" is exactly what it means. No emoji, ever.
* **Dashboard table (§3.10).** Header row `--sunk`, `--text-small` at weight 600 in
  `--ink-soft`, bottom `--edge`; body rows `--card` separated by `--edge`; numeric cells
  right-aligned `.tabular`. An id chip is `--mono` 13 px on `--sunk`, `--radius-tile`.
* **KPI tile (§3.10 #1).** `--card`, `--edge`, `--radius`, `--space-4` padding, a 3 px
  `--accent` rule down the left edge. Value in Archivo SemiBold 28 px `.tabular` in `--ink`;
  label in `--text-small` **sentence case** in `--ink-soft`; sub-line in `--text-meta`
  `--ink-mute`.
* **Access page (§3.8).** `--paper` window, one `--card` panel at `--radius`, the lockup above
  the sentence. Error text in `--danger`, and the field's edge goes `--line-strong` →
  `--danger` with `aria-invalid` — never colour alone.

See `docs/evidence/brand-preview.html` for all six rendered, in both themes, from these files.

---

## 7. The CSS custom-property block

Paste into `app.css` above everything else (or `@import url("brand/brand.css")`, which also
brings the `@font-face` rules). Names that already exist in `app.css` — `--ink`, `--ink-soft`,
`--paper`, `--card`, `--line`, `--accent`, `--accent-soft`, `--warn`, `--warn-soft`,
`--danger`, `--radius`, `--mono` — are kept, so the swap is a replacement, not a rename. The
`@font-face` rules are in `brand/brand.css` only.

```css
:root {
  color-scheme: light dark;

  /* -- type --------------------------------------------------------------------------- */
  --font-display: "Archivo", "Helvetica Neue", Helvetica, Arial, sans-serif;
  --font-body: "Public Sans", "Helvetica Neue", Helvetica, Arial, sans-serif;
  --mono: ui-monospace, "SF Mono", "Cascadia Mono", Menlo, Consolas, monospace;

  --text-eyebrow: 500 0.75rem/1.2 var(--font-display);
  --text-h1: 600 1.375rem/1.25 var(--font-display);
  --text-h2: 600 1.125rem/1.3 var(--font-display);
  --text-h3: 600 1rem/1.35 var(--font-display);
  --text-body: 400 1rem/1.55 var(--font-body);
  --text-small: 400 0.875rem/1.5 var(--font-body);
  --text-meta: 400 0.8125rem/1.45 var(--font-body);
  --track-display: -0.011em;
  --track-eyebrow: 0.08em;

  /* -- the tessera grid: every length is a multiple of 4px ----------------------------- */
  --space-1: 0.25rem;   /*  4px */
  --space-2: 0.5rem;    /*  8px */
  --space-3: 0.75rem;   /* 12px */
  --space-4: 1rem;      /* 16px */
  --space-5: 1.5rem;    /* 24px */
  --space-6: 2rem;      /* 32px */
  --space-7: 3rem;      /* 48px */
  --space-8: 4rem;      /* 64px */

  --radius-tile: 3px;   /* chips, buttons, inputs, badges, the id code chips */
  --radius: 6px;        /* cards, panels, message bubbles, tables */
  --radius-bar: 0;      /* anything full-bleed: masthead, sticky nav, composer on mobile */

  --measure: 40rem;     /* the conversation column — about 80 characters of Public Sans */

  /* -- elevation: hairlines first, shadow only where something really floats ----------- */
  --edge: 1px solid var(--line);
  --edge-strong: 1px solid var(--line-strong);
  --lift-0: none;
  --lift-1: 0 1px 2px rgb(16 29 28 / 0.07);
  --lift-2: 0 2px 8px rgb(16 29 28 / 0.11);
  --focus-ring: 0 0 0 2px var(--card), 0 0 0 4px var(--focus);

  /* -- light: porcelain grounds, verdigris accent -------------------------------------- */
  --paper: #f3f6f5;
  --card: #ffffff;
  --sunk: #e9eeec;

  --ink: #101d1c;
  --ink-soft: #4c5f5d;
  --ink-mute: #586967;

  --accent: #0d5c57;
  --accent-strong: #083f3b;
  --accent-soft: #d5e6e2;
  --on-accent: #ffffff;

  --line: #dbe2e0;
  --line-strong: #7f8d8b;
  --focus: #0d5c57;

  --warn: #7a4b04;
  --warn-soft: #faefd9;
  --danger: #96251e;
  --danger-soft: #fbe7e4;
  --ok: #1e6335;
  --ok-soft: #e2efe6;

  --mark-a: #58958e;
  --mark-b: #2c736c;
  --mark-c: #0d5c57;
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --paper: #0c1413;
    --card: #131e1c;
    --sunk: #080f0e;

    --ink: #e8eeec;
    --ink-soft: #a2b2af;
    --ink-mute: #8c9c99;

    --accent: #6acfc2;
    --accent-strong: #93e1d6;
    --accent-soft: #11312d;
    --on-accent: #08100f;

    --line: #24302e;
    --line-strong: #5f6e6a;
    --focus: #6acfc2;

    --warn: #e0b063;
    --warn-soft: #2c2211;
    --danger: #f0918a;
    --danger-soft: #33191a;
    --ok: #72c990;
    --ok-soft: #12291b;

    --mark-a: #3a7c75;
    --mark-b: #4e9e95;
    --mark-c: #6acfc2;

    /* shadows read as smudges on a dark ground; the hairline carries the elevation */
    --lift-1: 0 0 0 1px #24302e;
    --lift-2: 0 2px 10px rgb(0 0 0 / 0.5);
  }
}

:root[data-theme="dark"] {
  --paper: #0c1413;
  --card: #131e1c;
  --sunk: #080f0e;

  --ink: #e8eeec;
  --ink-soft: #a2b2af;
  --ink-mute: #8c9c99;

  --accent: #6acfc2;
  --accent-strong: #93e1d6;
  --accent-soft: #11312d;
  --on-accent: #08100f;

  --line: #24302e;
  --line-strong: #5f6e6a;
  --focus: #6acfc2;

  --warn: #e0b063;
  --warn-soft: #2c2211;
  --danger: #f0918a;
  --danger-soft: #33191a;
  --ok: #72c990;
  --ok-soft: #12291b;

  --mark-a: #3a7c75;
  --mark-b: #4e9e95;
  --mark-c: #6acfc2;

  --lift-1: 0 0 0 1px #24302e;
  --lift-2: 0 2px 10px rgb(0 0 0 / 0.5);
}
```

`[data-theme="light"]` needs no rules of its own: it simply stops the `prefers-color-scheme`
block from applying, leaving `:root`. A theme toggle sets `data-theme` on `<html>`; with no
attribute the OS decides.

**On `--mark-*`.** `mark.svg` and `wordmark.svg` paint their tiles with
`fill: var(--mark-a, <literal>)` and swap the literal inside their own
`@media (prefers-color-scheme: dark)`. So the same file is correct as an `<img>` or a favicon
(nothing defines `--mark-a`; the literal wins; the OS switches it) *and* inlined into the page
(the tokens are in scope, so an explicit `data-theme="dark"` reaches the mark). Do not
re-declare `--mark-*` on `.brand-mark` in `app.css` or the two paths diverge.

---

## 8. Do / don't

**Do**

* Use `--accent` for one thing per view: the thing the person is meant to act on.
* Let hairlines and the 4 px grid do the separating. Whitespace is cheaper than a border,
  and a border is cheaper than a shadow.
* Set every heading in Archivo and every sentence in Public Sans, and nothing the other way.
* Pair colour with a second signal — an icon, a label, an underline, `aria-invalid`. Someone
  reading `--danger` as grey must still understand the state.
* Keep `.tabular` on anything a reader will scan down a column.
* State a number's unit and denominator in words: `11% (1 of 9 turns)`, not `0.111`.
* Measure any new colour against `--paper`, `--card` and `--sunk` and add it to §3.

**Don't**

* No gradient anywhere — not on a button, not behind a hero, not in the mark. Especially not
  purple-to-blue.
* No emoji in the interface. Not as a bullet, not as a status marker, not in a heading. The
  disclosure triangle is `▸`, the pending dot is `●`, and both are in the subset.
* No `border-radius` above 6 px, and no pills.
* No drop shadow on a card, a table, a chip or the mark.
* No uppercase outside `--text-eyebrow`. `POLICY FACT`, `ESCALATION`, `SESSIONS (24 H)` and
  `HR ADMIN` are all deleted by the plan; do not reintroduce the shape.
* No Inter, no Space Grotesk, no system-UI fallback chain that lands on Inter. The stack ends
  at Helvetica/Arial on purpose.
* No second accent hue. `--warn`, `--danger` and `--ok` are semantics, not decoration, and
  colouring a neutral chip with one is a misuse.
* No external font host, no CDN, no webfont `@import`. Every byte ships from this repo.
* Don't restate the brand inside answers. The assistant's copy is plain English; the identity
  is carried by the frame around it.
