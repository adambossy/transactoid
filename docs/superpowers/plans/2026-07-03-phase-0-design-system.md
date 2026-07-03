# Phase 0 — Design System (Shared UI Template) — Plan Stub

> **Status: Roadmap — awaiting HTML templates from the user, then brainstorm → spec → plan.**
> Part of the [Multi-Account Epic](2026-06-27-multi-account-epic-overview.md).
> **Precedes** the UI-bearing phases ([2 auth](2026-07-02-phase-2-auth-social-login.md),
> [4 signup](2026-07-02-phase-4-signup-ui.md), [5 onboarding](2026-07-03-phase-5-onboarding.md)),
> which all reference "the shared UI template primitives."

**Goal:** Turn the user-provided HTML web templates into a **reusable design
system / component library** that supplies the primitives every UI phase depends
on — Header, Footer, Logo, color tokens, type scale, font stack, and the app
shell — so no phase invents bespoke styling.

**Why it's a phase (and comes first):** phases 2/4/5 were written assuming these
primitives exist. Building them once, up front, is the precondition for any UI
work and prevents divergent one-off styles.

## Scope (to be specced once templates arrive)

- Convert the provided HTML templates into a **component library** (likely a
  small React package, e.g. workspace-local `@penny/ui`), exporting:
  `Header`, `Footer`, `Logo`, the color-token set, the type scale, the font
  stack, and an `AppShell` wrapper.
- **Design tokens** (colors, spacing, typography) as the single source of truth,
  consumable by all screens.
- Responsive behavior (mobile + desktop) and the standard loading / empty /
  error state patterns baked in.
- A tiny render harness / storybook-style page to preview each primitive.
- Wire the Playwright E2E harness (phase 1a) to assert screens use the shell.

## Modularization (first-class here)

This phase **is** a reusable artifact by design: the component library and design
tokens are built to be **portable to other projects** — a standalone package
with no Penny-specific coupling. It is the first and clearest instance of the
epic-wide modularization principle (extract reusable, portable modules wherever
they arise). See the modularization notes added across the other phase plans.

## Open questions (for brainstorming)

- Package boundary/name and where it lives (workspace package vs. `frontend/src`
  folder promoted later).
- Token format (CSS variables vs. a TS token module vs. Tailwind config).
- How much of the app shell (nav, routing chrome) belongs here vs. in the app.

## Depends on

- The user's HTML templates (forthcoming). No code dependency on other phases;
  can be built in parallel with 1a/1b, and must land before 2.
