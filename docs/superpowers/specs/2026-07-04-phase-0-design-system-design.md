# Phase 0 — Design System (`@penny/ui`) Design

> Part of the [Multi-Account Epic](../plans/2026-06-27-multi-account-epic-overview.md).
> Supersedes the [plan stub](../plans/2026-07-03-phase-0-design-system.md)'s open
> questions (now decided). Canonical visual reference:
> [`frontend/design-reference/`](../../../frontend/design-reference/)
> (`index.html`, `preview.jpeg`, `DESIGN-SYSTEM.md`, and the two logo PNGs).

## Goal

Turn the provided "Penny — your finance savant" template into a **reusable,
portable component library** — `@penny/ui` — that supplies every UI primitive the
UI-bearing phases (2 auth, 4 signup, 5 onboarding) depend on: an app shell,
header/footer/logo, the color + type tokens, the font stack, and the core
controls. Built once, up front, so no phase invents bespoke styling.

## Decisions (locked)

1. **A real workspace package**, `@penny/ui`, at `frontend/packages/ui/` —
   portable to other projects, zero Penny-specific coupling.
2. **Tokens as a Tailwind-v4 `@theme` block** in `theme.css` (which *is* both the
   CSS-variable source and the utility-generator in Tailwind v4 — one source of
   truth), mirrored as typed constants in `tokens.ts` for non-Tailwind JS
   consumers, kept in sync by a drift test.
3. **The library owns the presentational shell** (`AppShell`, `Header`, `Footer`,
   `Logo`, and the controls); the **app owns nav items and routing**, passed in as
   props/children.
4. **v1 component set is exactly:** `AppShell`, `Header`, `Footer`, `Logo`,
   `Button`, `Input`, `Chip`, `Card`, `EyebrowPill`. The marketing landing page
   is out of scope (not on the auth/signup/onboarding path).
5. **Logos** are the two user-provided marks now in `design-reference/`:
   `penny-primary-logo.png` (full-color emblem) and
   `penny-two-tone-flat-logo.png` (flat single-tone), vendored into the package as
   `logo-emblem` / `logo-flat` and traced to SVG.

## Architecture

### Package boundary

`frontend/` becomes an npm-workspace root (`"workspaces": ["packages/*"]`); the
existing Vite app stays at the `frontend/` root and consumes `@penny/ui` as a
workspace dependency. This mirrors the **agent-ui** integration already in the
repo: source-aliased in `vite.config.ts` for HMR, with React deduped so a second
React copy can't blank the screen.

```
frontend/
├── package.json              # workspace root: "workspaces": ["packages/*"], deps @penny/ui
├── vite.config.ts            # + @penny/ui and @penny/ui/styles.css aliases (dev HMR)
├── packages/ui/              # → @penny/ui
│   ├── package.json          # name, "exports": { ".": …, "./styles.css": … }
│   ├── tsconfig.json
│   └── src/
│       ├── index.ts          # barrel: components + tokens
│       ├── theme.css         # @theme tokens + @font-face  (the Tailwind "preset")
│       ├── tokens.ts         # typed re-export of the same values
│       ├── assets/
│       │   ├── logo-emblem.{svg,png}
│       │   ├── logo-flat.{svg,png}
│       │   └── fonts/*.woff2 # Fraunces, Cormorant Garamond, Work Sans
│       ├── primitives/       # Button, Input, Chip, Card, EyebrowPill
│       ├── logo/Logo.tsx
│       ├── shell/            # AppShell, Header, Footer
│       └── Gallery.tsx       # renders every primitive (preview + E2E target)
```

### Tokens

`theme.css` carries a single `@theme` block with the nine palette tokens
(`--paper`, `--cream`, `--cream-soft`, `--ink`, `--navy`, `--navy-700`,
`--steel`, `--orange`, `--orange-soft`), the three font families, and a small
type scale. In Tailwind v4 those declarations both expose the CSS variables and
generate the utilities (`bg-navy`, `text-ink`, `font-display`), so screens can use
utilities or raw `var(--…)` without a second config. `tokens.ts` re-exports the
identical values as typed constants for JS that needs them (e.g. inline styles,
charts); a unit test parses `theme.css` and asserts `tokens.ts` matches, so the
two homes cannot drift.

### Components

All are presentational, prop-driven, and free of app state, data fetching, or
routing:

- **`AppShell`** — the cream-paper page frame. Slots: `header`, `footer`,
  `children`. Sets the page background, max-width, and vertical rhythm.
- **`Header`** — `Logo` + `PENNY` wordmark (left), `nav` slot (center), `actions`
  slot (right), thin bottom border. Nav *content* comes from the app.
- **`Footer`** — flat-logo mark + `children` slots.
- **`Logo`** — `variant: "emblem" | "flat"`, `size`. Emblem is the primary
  full-color mark; flat is the single-tone mark for small/single-color contexts.
- **`Button`** — `variant: "filled" | "outlined"`, rounded-full pill; forwards
  native button props.
- **`Input`** — the rounded search-bar-with-inset-button combo; controlled value +
  `onSubmit`, optional trailing button label.
- **`Chip`** — suggestion chip: optional emoji + label, `onClick`.
- **`Card`** — bordered rounded surface (the chat/product panel).
- **`EyebrowPill`** — small teal-filled letter-spaced caps pill.

### Fonts

Fraunces (display), Cormorant Garamond (serif labels + wordmark), Work Sans
(UI/body) — all open-license — are **self-hosted** as woff2 in
`src/assets/fonts/` with `@font-face` in `theme.css`. Self-hosting keeps the
package portable and removes the CDN/privacy dependency. Fallback stacks match the
template (`'Fraunces',Georgia,serif`; `'Cormorant Garamond',…`; `'Work
Sans',system-ui,sans-serif`).

### Logos

The two PNGs are copied from `design-reference/` into `src/assets/` as
`logo-emblem.png` / `logo-flat.png` and traced to SVG (crisp at any size; PNG kept
as a raster fallback). `design-reference/` remains the canonical source of the
originals.

### App wiring

`vite.config.ts` gains an alias block for `@penny/ui` → `packages/ui/src/index.ts`
and `@penny/ui/styles.css` → `packages/ui/src/theme.css`, mirroring the agent-ui
block and reusing the existing `resolve.dedupe` for React. The app imports the
stylesheet once and renders its top-level screen inside `AppShell`.

## Render harness & testing

- **Gallery** — `<Gallery/>` renders one labeled example of every primitive. The
  app mounts it at a **dev-only `/ui` route** (reusing the app's Vite; the Gallery
  component itself stays in the package, so the package remains portable).
- **Playwright** — extend the phase-1a `frontend/e2e/` harness with a spec that
  loads `/ui` and asserts (a) each primitive renders, and (b) a screen is wrapped
  in `AppShell` with the palette tokens applied (computed `background-color`
  resolves to `--paper`). This is the "screens use the shell" guard the plan stub
  called for.
- **Token drift** — a unit test asserts `tokens.ts` equals the values parsed from
  `theme.css`.

## Non-goals

- The marketing landing page and any content pages.
- Dark mode / theming beyond the single provided palette.
- Charts, tables, and data-display components (added by the phase that needs
  them, per the epic's "add the knob when the second caller exists" rule).
- Wiring `@penny/ui` into existing chat screens — phases 2/4/5 adopt it; Phase 0
  only ships the package + Gallery + E2E guard.

## Modularization

This phase *is* the epic's clearest reusable artifact: `@penny/ui` is a
standalone, portable package with no Penny coupling, publishable/vendorable into
other projects exactly as agent-ui is here.

## Requirements

- The UI-bearing phases (2/4/5) can build every screen from `@penny/ui` primitives
  without inventing bespoke styling.
- Color and type tokens have exactly one source of truth (`theme.css`), consumable
  as Tailwind utilities, raw CSS vars, and typed TS constants without drift.
- The library is presentational and portable: no app state, data fetching, or
  routing; nav content and routing are supplied by the app.
- Every primitive is render-verified and a screen is asserted to use `AppShell`
  with the palette applied, via the Playwright E2E harness.
