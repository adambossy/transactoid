# Phase 0 — Design System (`@penny/ui`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.
> Spec: [Phase 0 design](../specs/2026-07-04-phase-0-design-system-design.md).
> Part of the [Multi-Account Epic](2026-06-27-multi-account-epic-overview.md).

**Goal:** Ship `@penny/ui` — a portable React component library carrying the
Penny design tokens, fonts, logos, app shell, and core controls — so phases 2/4/5
build screens from shared primitives instead of bespoke styles.

**Architecture:** A workspace package at `frontend/packages/ui/`, consumed by the
existing Vite app via a source alias (mirroring the agent-ui integration, React
deduped). Tokens live once in a Tailwind-v4 `@theme` block (`theme.css`) that both
exposes CSS vars and generates utilities; `tokens.ts` re-exports the same values
for JS, guarded against drift by a test. Components are presentational and
prop-driven; the app owns nav content and routing.

**Tech Stack:** React 19, TypeScript, Tailwind v4 (`@tailwindcss/vite`), Vite 8,
Vitest (unit), Playwright (E2E, extending phase 1a's `frontend/e2e/`).

## Global Constraints

- **Package is portable and presentational.** No app state, data fetching, or
  routing in `@penny/ui`; nav content and routing come from the app as
  props/children.
- **One token source of truth:** `theme.css`'s `@theme` block. `tokens.ts` mirrors
  it; a test fails on drift. Never hand-duplicate a hex value elsewhere.
- **Palette (verbatim):** `--paper #FAF4E7`, `--cream #ECE0C0`,
  `--cream-soft #F3E9CF`, `--ink #1C3E3A`, `--navy #1E4846`, `--navy-700 #2A625D`,
  `--steel #3C7A72`, `--orange #D69E3D`, `--orange-soft #E3B255`.
- **Fonts:** Fraunces (display), Cormorant Garamond (serif labels/wordmark), Work
  Sans (UI/body); self-hosted woff2; fallbacks per the template.
- **Preserve `resolve.dedupe`** for React in `vite.config.ts` — removing it blanks
  the screen from a second React copy.
- **v1 component set is exactly** `AppShell, Header, Footer, Logo, Button, Input,
  Chip, Card, EyebrowPill`. No landing page, dark mode, or data-display components.
- Commit after each task; keep the app booting green between tasks.

---

### Task 1: Workspace scaffold + `@penny/ui` skeleton + Vite alias

**Files:**
- Modify: `frontend/package.json` (add `workspaces`, add `@penny/ui` dep)
- Create: `frontend/packages/ui/package.json`, `frontend/packages/ui/tsconfig.json`,
  `frontend/packages/ui/src/index.ts` (empty barrel), `frontend/packages/ui/src/theme.css` (empty)
- Modify: `frontend/vite.config.ts` (alias block)

**Interfaces:**
- Produces: package name `@penny/ui`; entry `packages/ui/src/index.ts`; stylesheet
  export `@penny/ui/styles.css` → `packages/ui/src/theme.css`.

- [ ] **Step 1:** In `frontend/package.json` add `"workspaces": ["packages/*"]`
  and `"@penny/ui": "*"` under `dependencies`.
- [ ] **Step 2:** Create `frontend/packages/ui/package.json`:

```json
{
  "name": "@penny/ui",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "main": "./src/index.ts",
  "types": "./src/index.ts",
  "exports": {
    ".": "./src/index.ts",
    "./styles.css": "./src/theme.css"
  },
  "scripts": {
    "test": "vitest run",
    "check:tokens": "vitest run tokens.drift.test.ts"
  },
  "peerDependencies": { "react": "^19", "react-dom": "^19" },
  "devDependencies": { "vitest": "^3.0.0" }
}
```

- [ ] **Step 3:** Create `frontend/packages/ui/tsconfig.json` extending the app's
  compiler options (jsx `react-jsx`, `moduleResolution` bundler, `strict`).
- [ ] **Step 4:** Create empty `src/index.ts` (`export {};`) and empty
  `src/theme.css`.
- [ ] **Step 5:** In `frontend/vite.config.ts`, add to the alias array (both the
  vendor and source branches keep working; add these to the source branch):

```ts
{ find: "@penny/ui/styles.css", replacement: path.resolve(__dirname, "packages/ui/src/theme.css") },
{ find: "@penny/ui", replacement: path.resolve(__dirname, "packages/ui/src/index.ts") },
```

- [ ] **Step 6:** `cd frontend && npm install` (links the workspace). Run
  `npm run dev` and confirm the app still boots (blank barrel imports fine).
- [ ] **Step 7:** Commit `feat(ui): scaffold @penny/ui workspace package + vite alias`.

---

### Task 2: Design tokens (`theme.css` `@theme` + `tokens.ts`) + drift test

**Files:**
- Modify: `frontend/packages/ui/src/theme.css`
- Create: `frontend/packages/ui/src/tokens.ts`, `frontend/packages/ui/src/tokens.drift.test.ts`,
  `frontend/packages/ui/vitest.config.ts`
- Modify: `frontend/packages/ui/src/index.ts` (export tokens)

**Interfaces:**
- Produces: `export const tokens` (typed record of the 9 colors + font families);
  Tailwind utilities `bg-<name>`, `text-<name>`, `font-{display,serif,ui}`.

- [ ] **Step 1: Write the failing drift test** `tokens.drift.test.ts`: read
  `theme.css` via `fs`, extract every `--color-*` / font var from the `@theme`
  block, and assert it deep-equals the values in `tokens.ts`. Run: expect FAIL
  (files not yet populated).
- [ ] **Step 2:** Write `theme.css` `@theme` block — the 9 palette tokens as
  `--color-paper: #FAF4E7;` … `--color-orange-soft: #E3B255;`, plus
  `--font-display: 'Fraunces',Georgia,serif;`,
  `--font-serif: 'Cormorant Garamond','Fraunces',Georgia,serif;`,
  `--font-ui: 'Work Sans',system-ui,sans-serif;`. (Tailwind v4 turns
  `--color-navy` into `bg-navy`/`text-navy`, `--font-display` into `font-display`.)
- [ ] **Step 3:** Write `tokens.ts` mirroring the same values as a typed const
  (`export const tokens = { paper: "#FAF4E7", …, fontDisplay: "…" } as const;`).
- [ ] **Step 4:** Export `tokens` from `index.ts`; add `vitest.config.ts` (node env).
- [ ] **Step 5:** Run `npm --workspace @penny/ui run test`. Expected: PASS.
- [ ] **Step 6:** Commit `feat(ui): design tokens (@theme + tokens.ts) with drift guard`.

---

### Task 3: Self-hosted fonts + vendored logos (raster + SVG)

**Files:**
- Create: `frontend/packages/ui/src/assets/fonts/*.woff2`,
  `frontend/packages/ui/src/assets/logo-emblem.{png,svg}`,
  `frontend/packages/ui/src/assets/logo-flat.{png,svg}`
- Modify: `frontend/packages/ui/src/theme.css` (`@font-face` rules)

- [ ] **Step 1:** Fetch woff2 for Fraunces, Cormorant Garamond, Work Sans (the
  weights the template uses — Fraunces 400/600/700, Cormorant 500/600, Work Sans
  400/500/600) into `assets/fonts/`. Add `@font-face` rules to `theme.css`
  referencing them with `font-display: swap`.
- [ ] **Step 2:** Copy `frontend/design-reference/penny-primary-logo.png` →
  `assets/logo-emblem.png` and `penny-two-tone-flat-logo.png` →
  `assets/logo-flat.png`.
- [ ] **Step 3:** Trace each PNG to SVG (e.g. `vtracer`/`potrace`, or hand-clean);
  save `logo-emblem.svg` / `logo-flat.svg`. Keep PNGs as raster fallback.
- [ ] **Step 4:** Boot the app importing `theme.css`; confirm Fraunces renders on a
  test heading (fonts load, no CDN request).
- [ ] **Step 5:** Commit `feat(ui): self-host fonts + vendor logo assets (png+svg)`.

---

### Task 4: `Logo` component

**Files:** Create `frontend/packages/ui/src/logo/Logo.tsx`; modify `index.ts`.

**Interfaces:**
- Produces: `Logo({ variant?: "emblem" | "flat"; size?: number; className?: string })`.
  Default `variant="emblem"`. Imports the SVG asset; renders `<img>` (or inline
  SVG) at `size` px square-ish, `alt="Penny"`.

- [ ] **Step 1:** Implement `Logo`, importing `logo-emblem.svg` / `logo-flat.svg`
  and selecting by `variant`. Export from `index.ts`.
- [ ] **Step 2:** Add a temporary render in the app; confirm both variants show.
- [ ] **Step 3:** Commit `feat(ui): Logo component (emblem/flat variants)`.

---

### Task 5: Controls — `Button`, `Chip`, `EyebrowPill`, `Card`, `Input`

**Files:** Create `frontend/packages/ui/src/primitives/{Button,Chip,EyebrowPill,Card,Input}.tsx`;
modify `index.ts`.

**Interfaces (exact):**
- `Button(props: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "filled" | "outlined" })`
- `Chip({ emoji?: string; label: string; onClick?: () => void; className?: string })`
- `EyebrowPill({ children: React.ReactNode; className?: string })`
- `Card(props: React.HTMLAttributes<HTMLDivElement>)`
- `Input({ value: string; onChange: (v: string) => void; onSubmit?: () => void; placeholder?: string; buttonLabel?: string })`

- [ ] **Step 1:** Implement `Button` as the styling pattern for the set:

```tsx
import type { ButtonHTMLAttributes } from "react";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "filled" | "outlined" };

export function Button({ variant = "filled", className = "", ...rest }: Props) {
  const base = "rounded-full px-5 py-2 font-ui text-sm transition-colors disabled:opacity-50";
  const styles =
    variant === "filled"
      ? "bg-navy text-cream hover:bg-navy-700"
      : "border border-ink text-ink hover:bg-cream-soft";
  return <button className={`${base} ${styles} ${className}`} {...rest} />;
}
```

- [ ] **Step 2:** Implement `Chip` (rounded-full thin-border pill, optional emoji +
  label), `EyebrowPill` (small `bg-navy text-cream` letter-spaced uppercase pill),
  `Card` (`rounded-2xl border border-cream bg-cream-soft` surface, forwards div
  props), and `Input` (rounded search bar with an inset filled `Button`; `Enter`
  or the button fires `onSubmit`). Use only token utilities. Export all from
  `index.ts`.
- [ ] **Step 3:** Render each in the app scratch page; verify styling matches
  `design-reference/preview.jpeg`.
- [ ] **Step 4:** Commit `feat(ui): core controls (Button, Chip, EyebrowPill, Card, Input)`.

---

### Task 6: App shell — `AppShell`, `Header`, `Footer`

**Files:** Create `frontend/packages/ui/src/shell/{AppShell,Header,Footer}.tsx`;
modify `index.ts`.

**Interfaces (exact):**
- `AppShell({ header?: React.ReactNode; footer?: React.ReactNode; children: React.ReactNode })`
  — sets `min-h-screen bg-paper text-ink font-ui`, centers a max-width column.
- `Header({ nav?: React.ReactNode; actions?: React.ReactNode })` — `Logo` + `PENNY`
  wordmark (`font-serif`) left, `nav` center, `actions` right, thin bottom border.
- `Footer({ children?: React.ReactNode })` — `Logo variant="flat"` + `children`.

- [ ] **Step 1:** Implement the three. `AppShell` composes `header` above
  `children` above `footer`. Nav/actions are slots — no nav items or links
  hardcoded (the app supplies them). Export from `index.ts`.
- [ ] **Step 2:** Compose a demo screen in the app: `<AppShell header={<Header nav={…} actions={<Button/>}/>}>…</AppShell>`;
  confirm layout matches the reference header.
- [ ] **Step 3:** Commit `feat(ui): AppShell + Header + Footer presentational shell`.

---

### Task 7: `Gallery` + dev-only `/ui` route in the app

**Files:** Create `frontend/packages/ui/src/Gallery.tsx`; modify `index.ts`;
modify the app's router/entry to mount `Gallery` at `/ui` in dev only.

**Interfaces:**
- Produces: `Gallery()` — renders one labeled example of every primitive inside
  `AppShell`, each in a container with a stable `data-testid` (e.g.
  `data-testid="ui-button-filled"`).

- [ ] **Step 1:** Implement `Gallery` covering all nine components; export it.
- [ ] **Step 2:** In the app, mount `Gallery` at `/ui` guarded by `import.meta.env.DEV`
  (no route in production builds).
- [ ] **Step 3:** `npm run dev`, open `/ui`; confirm every primitive renders with
  tokens applied.
- [ ] **Step 4:** Commit `feat(ui): Gallery preview + dev-only /ui route`.

---

### Task 8: Playwright E2E guard (extends phase-1a harness)

**Files:** Create `frontend/e2e/ui-gallery.spec.ts`.

- [ ] **Step 1:** Write a Playwright spec that navigates to `/ui` and asserts:
  (a) each primitive's `data-testid` is visible; (b) the `AppShell` root's computed
  `background-color` equals the `--paper` value (`rgb(250, 244, 231)`), proving
  tokens are applied and the screen uses the shell.
- [ ] **Step 2:** Run `npm run e2e -- ui-gallery.spec.ts`. Expected: PASS (dev
  server auto-started per `playwright.config.ts`).
- [ ] **Step 3:** Commit `test(ui): E2E gallery guard (primitives render + shell/tokens applied)`.

---

### Task 9: Verification + REQUIREMENTS.txt

**Files:** Modify `REQUIREMENTS.txt` (Product section).

- [ ] **Step 1:** Run the full frontend gate: `npm --workspace @penny/ui run test`,
  `npm run build` (app builds with the workspace dep), `npm run e2e`. All green.
- [ ] **Step 2:** Add a Product requirement to `REQUIREMENTS.txt`: Penny's UI is
  built from a shared, portable `@penny/ui` design system (tokens, fonts, logos,
  app shell, controls); UI phases compose screens from it rather than bespoke
  styles.
- [ ] **Step 3:** Commit `docs: record @penny/ui design-system requirement`.

---

## Self-Review

**Spec coverage:** package boundary + alias → Task 1; tokens single-source + drift
→ Task 2; fonts + logos (png+svg) → Task 3; Logo → Task 4; controls → Task 5;
shell (app owns nav/routing) → Task 6; Gallery harness → Task 7; E2E "screens use
the shell + tokens" guard → Task 8; verification + requirements → Task 9. All spec
sections mapped.

**Placeholder scan:** component APIs, token values, the Button pattern, the drift
test, and the E2E assertions are concrete; sibling controls carry exact
signatures + styling notes rather than repeated boilerplate. No TBD.

**Type consistency:** `variant` unions (`"filled" | "outlined"`, `"emblem" |
"flat"`) and prop names are identical across spec and plan; `tokens` shape matches
the `@theme` keys the drift test parses.

## Execution Handoff

Single focused package — well-suited to one executor running Tasks 1–9
sequentially in a worktree off `feat/account-creation`, reviewed and merged as a
unit (the orchestration pattern used for Phase 1a).
