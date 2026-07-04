# Penny Design System — extracted reference

Source: `index.html` (the user-provided template, "Penny — Your finance
savant" landing page) + `preview.jpeg` (rendered screenshot). This is the
**canonical reference** for Phase 0 (the shared UI template / `@penny/ui`) and
for all UI/UX across the epic. Tailwind-utility based.

## Color tokens (from `:root`)

| Token           | Hex       | Role                                                |
| --------------- | --------- | --------------------------------------------------- |
| `--paper`       | `#FAF4E7` | page background (warm cream)                        |
| `--cream`       | `#ECE0C0` | section bands / muted surfaces                      |
| `--cream-soft`  | `#F3E9CF` | soft surface / hover                                |
| `--ink`         | `#1C3E3A` | darkest text / deep green                           |
| `--navy`        | `#1E4846` | primary brand green (filled buttons, eyebrow pills) |
| `--navy-700`    | `#2A625D` | secondary green                                     |
| `--steel`       | `#3C7A72` | tertiary green / muted accent                       |
| `--orange`      | `#D69E3D` | primary gold accent (underlines, accent circle)     |
| `--orange-soft` | `#E3B255` | soft gold                                           |

Additional accents seen: `#5C2B2E` / `#2A1215` (deep plum/maroon),
`#FF8A80` (coral). Ground = warm cream; ink = deep teal-green; accent = gold.

## Typography (Google Fonts)

- **Libre Baskeville** — display headlines (e.g. "Meet Penny, your finance savant."),
  large serif, often with a gold underline swash.
- **Cormorant Garamond** — elegant serif for section labels / feature words
  ("Root-cause", "Scenario", "Forward", "Goal-based") and the `PENNY` wordmark.
- **Work Sans** — body copy, nav, buttons, chips, tables (UI sans).
- Fallbacks in file: `'Libre Baskeville',Georgia,serif`;
  `'Cormorant Garamond','Libre Baskeville',Georgia,serif`;
  `'Work Sans',system-ui,sans-serif`.

## Logos

Two raster marks (a circular emblem — a classical "savant" profile in teal +
gold within a ringed border), embedded in `index.html` and loaded as blobs at
runtime:

- **Avatar (small):** ~891×891, used in the header beside the `PENNY` wordmark
  (`h-10`/`h-11`). Internal GUID `371b0953-…`.
- **Emblem (large):** ~874×889, hero mark on a cream blob with a gold accent
  circle (`max-w-[260px]`, `h-24`). Internal GUID `703fd356-…`.

**To vendor in Phase 0:** extract both from the reference (render + canvas
export, or parse the bundle) into `@penny/ui` assets as `logo-avatar.png` and
`logo-emblem.png` (ideally also traced to SVG).

## Components (observed)

- **App shell / header:** logo + wordmark (left), centered nav
  (Analyze · Project · Budget · Forecast · Trends), an **outlined rounded-full
  pill CTA** ("Meet Penny") right; thin bottom border.
- **Eyebrow pill:** small teal-filled, letter-spaced caps ("YOUR FINANCE SAVANT").
- **Buttons:** rounded-full; **filled** (navy/teal bg, cream text — "Ask Penny")
  and **outlined** (border, ink text — "Meet Penny").
- **Suggestion chips:** rounded-full, thin border, emoji + label.
- **Input+button combo:** a rounded search bar with an inset filled pill button.
- **Cards:** rounded (~`1rem`), thin border, cream-soft surface — used for the
  chat/product-surface preview (Penny answer + a data table).
- **Feature labels:** big Cormorant serif word + tiny letter-spaced caps sublabel.
- **Accent motifs:** gold underline swash under serif headlines; floating
  gold/teal accent circles.
- Radii seen: `1rem` (cards), `8px`/`6px` (small); generous whitespace.

## Notes for the app (vs. the landing page)

The template is a **marketing landing page**; the product is a chat app. Phase 0
extracts the _system_ (tokens, fonts, logo, shell chrome, button/pill/card
primitives, the chat-card styling) — not the marketing sections. The chat
surface styling (bordered rounded card, Penny bubble, data tables) is the most
directly reusable for the actual app.
