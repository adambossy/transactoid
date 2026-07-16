# meetpenny.app Logged-Out Home Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the public (logged-out) marketing home page from `frontend/design-reference/index.html` as the signed-out view of `/`, stitched to the Clerk sign-in/sign-up screens so every call-to-action routes there.

**Architecture:** The landing page is website-domain frontend code only (`frontend/src/home/`), composed from the existing `@penny/ui` design system plus four new primitives (`NavLink`, `AccentUnderline`, `ButtonLink`, `DemoBubble`) and two theme motifs (grain texture, rise-in animation). Signed-out routing moves from "sign-in everywhere" to: `/` → HomeScreen, `/sign-up` → Clerk `<SignUp>`, `/sign-in` → Clerk `<SignIn>`, any other path → sign-in fallback (preserves deep links). A DEV-only `/home` preview route (same pattern as `/ui`) makes the page developable and e2e-testable in dev-principal mode without Clerk.

**Tech Stack:** React 19, Tailwind v4 (`@theme` tokens in `@penny/ui`), Clerk (`@clerk/react`), Playwright e2e harness (dev-principal mode), Vite.

## Global Constraints

- **Design reference (canonical for layout):** `frontend/design-reference/index.html` + `preview.jpeg`. Copy is expected to change later — treat all copy as placeholder, carried over from the template verbatim.
- **Copy has exactly one home:** `frontend/src/home/copy.ts` (text) and `frontend/src/home/demos.tsx` (demo conversations, which contain markup/tables). No copy strings inline in section components.
- **CTA contract:** every landing CTA (`Meet Penny`, `Ask Penny`, hero chips, all six feature-section buttons, closing CTA) links to `/sign-up`; a `Sign in` nav link goes to `/sign-in`. Clerk's components cross-link the two.
- **No routing library.** The app uses `window.location.pathname` conditionals and plain `<a href>` — keep that pattern.
- **Design tokens only from `@penny/ui`** (`bg-navy`, `text-ink`, `font-serif`, …). No hex literals in app code. Light-only per REQUIREMENTS P11 — no `dark:` variants.
- **Typography divergence (deliberate):** display headlines use `font-serif font-semibold` (Cormorant Garamond 600 — the heaviest weight the design system ships). Do NOT add new font files; the template's 700 is approximated by 600.
- **Domain segregation:** frontend/website domain only. Zero backend, deploy, or agent-domain changes.
- **Verification per task** (from `frontend/`): `npm run build` must pass; the named Playwright spec(s) must pass. Playwright boots the real backend on :8100 and Vite on :5175 (`npx playwright test <spec>`); Clerk-gated specs (`auth.spec.ts`, `signup.spec.ts`) stay skipped without `PENNY_E2E_CLERK=1` — updating them compiles but they are not run in the harness.
- Backend gates (`uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest -q`) are untouched by this work but run once at the end (Task 6) per AGENTS.md.

## File Structure

```
frontend/packages/ui/src/
├── theme.css                    # MODIFY: + rise-in animation, grain utility, ::selection
├── primitives/NavLink.tsx       # CREATE: hover-underline text link
├── primitives/AccentUnderline.tsx # CREATE: gold underline under serif headlines
├── primitives/Button.tsx        # MODIFY: extract shared buttonClasses()
├── primitives/ButtonLink.tsx    # CREATE: Button-styled <a>
├── primitives/DemoBubble.tsx    # CREATE: static marketing chat bubble (w/ table styling)
├── Gallery.tsx                  # MODIFY: samples for the four new primitives
└── index.ts                     # MODIFY: exports

frontend/src/home/
├── copy.ts                      # CREATE: all landing copy (placeholder)
├── demos.tsx                    # CREATE: six demo conversations (DemoBubble JSX)
├── HomeHeader.tsx               # CREATE: sticky blur header, nav, Sign in + Meet Penny
├── Hero.tsx                     # CREATE: headline, input, chips, emblem composition
├── StatStrip.tsx                # CREATE: 4-up serif stat band
├── FeatureSection.tsx           # CREATE: alternating text/demo-panel section
├── ClosingCta.tsx               # CREATE: orange CTA band
├── HomeFooter.tsx               # CREATE: navy footer
└── HomeScreen.tsx               # CREATE: page composition

frontend/src/
├── main.tsx                     # MODIFY: DEV-only /home preview route
├── AuthGate.tsx                 # MODIFY: signed-out routing (/, /sign-in, /sign-up)
└── ../index.html                # MODIFY: title + meta description

frontend/e2e/
├── home.spec.ts                 # CREATE: landing smoke via /home (dev harness)
├── ui-gallery.spec.ts           # MODIFY: extend PRIMITIVES list
└── auth.spec.ts                 # MODIFY: signed-out `/` now = landing (Clerk-gated)

REQUIREMENTS.txt                 # MODIFY: new P13 (public logged-out home page)
```

---

### Task 1: Theme motifs + `NavLink` + `AccentUnderline`

**Files:**
- Modify: `frontend/packages/ui/src/theme.css`
- Create: `frontend/packages/ui/src/primitives/NavLink.tsx`
- Create: `frontend/packages/ui/src/primitives/AccentUnderline.tsx`
- Modify: `frontend/packages/ui/src/index.ts`
- Modify: `frontend/packages/ui/src/Gallery.tsx`
- Test: `frontend/e2e/ui-gallery.spec.ts`

**Interfaces:**
- Consumes: existing `@penny/ui` theme tokens.
- Produces: `NavLink` (`AnchorHTMLAttributes<HTMLAnchorElement>`; inherits text color via `text-current`), `AccentUnderline` (`{ children: ReactNode; className?: string }`), Tailwind utilities `grain` and `animate-rise-in` — all consumed by Tasks 3–5.

- [ ] **Step 1: Extend the gallery e2e spec (the failing test)**

In `frontend/e2e/ui-gallery.spec.ts`, add two ids to the `PRIMITIVES` array:

```ts
const PRIMITIVES = [
  "ui-header",
  "ui-footer",
  "ui-eyebrowpill",
  "ui-logo-emblem",
  "ui-logo-flat",
  "ui-button-filled",
  "ui-button-outlined",
  "ui-chip",
  "ui-input",
  "ui-card",
  "ui-navlink",
  "ui-accent-underline",
];
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd frontend && npx playwright test e2e/ui-gallery.spec.ts`
Expected: FAIL — `getByTestId('ui-navlink')` not visible.

- [ ] **Step 3: Add the theme motifs**

In `frontend/packages/ui/src/theme.css`, add inside the existing `@theme` block (after the `--font-*` lines):

```css
  /* Landing-page reveal: rise up + fade in. Pair with motion-reduce:animate-none. */
  --animate-rise-in: rise-in 0.8s cubic-bezier(0.16, 1, 0.3, 1) both;

  @keyframes rise-in {
    from {
      opacity: 0;
      transform: translateY(26px);
    }
    to {
      opacity: 1;
      transform: none;
    }
  }
```

Then append at the end of the file (after the last `@font-face`):

```css
/* Brand motifs shared by marketing surfaces. */

/* Subtle dotted-paper texture; pair with `pointer-events-none fixed inset-0`. */
@utility grain {
  background-image: radial-gradient(var(--color-navy) 0.6px, transparent 0.6px);
  background-size: 18px 18px;
  opacity: 0.05;
}

/* Brand text selection (template's ::selection treatment). */
::selection {
  background: var(--color-orange);
  color: var(--color-paper);
}
```

- [ ] **Step 4: Create `NavLink`**

`frontend/packages/ui/src/primitives/NavLink.tsx`:

```tsx
import type { AnchorHTMLAttributes } from "react";

/** Text link with the brand hover treatment: a gold underline growing in from
 *  the left. Inherits its text color (`text-current`) so light-on-navy and
 *  ink-on-paper contexts both work; renders a plain <a> — routing stays with
 *  the app. */
export function NavLink({
  className = "",
  children,
  ...rest
}: AnchorHTMLAttributes<HTMLAnchorElement>) {
  return (
    <a className={`group relative font-ui text-sm text-current no-underline ${className}`} {...rest}>
      {children}
      <span
        aria-hidden="true"
        className="absolute -bottom-1 left-0 h-0.5 w-0 bg-orange transition-all duration-300 group-hover:w-full"
      />
    </a>
  );
}
```

- [ ] **Step 5: Create `AccentUnderline`**

`frontend/packages/ui/src/primitives/AccentUnderline.tsx`:

```tsx
import type { ReactNode } from "react";

/** Inline gold underline swash under serif display text (the template's
 *  `.underline-classic`). Wrap only the emphasized fragment of a headline. */
export function AccentUnderline({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <span className={`relative inline-block ${className}`}>
      {children}
      <span
        aria-hidden="true"
        className="absolute bottom-[-0.08em] left-0 h-[3px] w-full bg-orange"
      />
    </span>
  );
}
```

- [ ] **Step 6: Export and add Gallery samples**

In `frontend/packages/ui/src/index.ts`, add after the `EyebrowPill` exports:

```ts
export { NavLink } from "./primitives/NavLink";
export { AccentUnderline } from "./primitives/AccentUnderline";
```

In `frontend/packages/ui/src/Gallery.tsx`, import them alongside the other primitives and add two samples after the `ui-input` Sample:

```tsx
      <Sample id="ui-navlink" label="NavLink">
        <span className="text-navy">
          <NavLink href="#ui-navlink">Analyze</NavLink>
        </span>
      </Sample>

      <Sample id="ui-accent-underline" label="AccentUnderline">
        <span className="font-serif text-3xl font-semibold text-navy">
          your <AccentUnderline>finance savant.</AccentUnderline>
        </span>
      </Sample>
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd frontend && npm run build && npx playwright test e2e/ui-gallery.spec.ts`
Expected: build OK; spec PASSES.

- [ ] **Step 8: Commit**

```bash
git add frontend/packages/ui/src frontend/e2e/ui-gallery.spec.ts
git commit -m "feat(ui): NavLink + AccentUnderline primitives, grain/rise-in/selection motifs"
```

---

### Task 2: `ButtonLink` + `DemoBubble`

**Files:**
- Modify: `frontend/packages/ui/src/primitives/Button.tsx`
- Create: `frontend/packages/ui/src/primitives/ButtonLink.tsx`
- Create: `frontend/packages/ui/src/primitives/DemoBubble.tsx`
- Modify: `frontend/packages/ui/src/index.ts`
- Modify: `frontend/packages/ui/src/Gallery.tsx`
- Test: `frontend/e2e/ui-gallery.spec.ts`

**Interfaces:**
- Consumes: `ButtonVariant` from `Button.tsx`.
- Produces: `buttonClasses(variant, className?): string` (exported from `Button.tsx`), `ButtonLink` (`AnchorHTMLAttributes<HTMLAnchorElement> & { variant?: ButtonVariant }`), `DemoBubble` (`{ role: "user" | "penny"; children: ReactNode }`). Tasks 3–4 consume `ButtonLink` and `DemoBubble`.

- [ ] **Step 1: Extend the gallery spec (failing test)**

In `frontend/e2e/ui-gallery.spec.ts` `PRIMITIVES`, append:

```ts
  "ui-buttonlink",
  "ui-demobubble",
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd frontend && npx playwright test e2e/ui-gallery.spec.ts`
Expected: FAIL — `ui-buttonlink` not visible.

- [ ] **Step 3: Extract `buttonClasses` and add `ButtonLink`**

Replace `frontend/packages/ui/src/primitives/Button.tsx` with:

```tsx
import type { ButtonHTMLAttributes } from "react";

export type ButtonVariant = "filled" | "outlined";

/** Shared pill styling for Button and ButtonLink. */
export function buttonClasses(variant: ButtonVariant, className = ""): string {
  const base =
    "rounded-full px-5 py-2 font-ui text-sm transition-colors cursor-pointer disabled:cursor-not-allowed disabled:opacity-50";
  const styles =
    variant === "filled"
      ? "bg-navy text-cream hover:bg-navy-700"
      : "border border-ink text-ink hover:bg-cream-soft";
  return `${base} ${styles} ${className}`;
}

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant };

export function Button({ variant = "filled", className = "", ...rest }: Props) {
  return <button className={buttonClasses(variant, className)} {...rest} />;
}
```

Create `frontend/packages/ui/src/primitives/ButtonLink.tsx`:

```tsx
import type { AnchorHTMLAttributes } from "react";
import { buttonClasses, type ButtonVariant } from "./Button";

type Props = AnchorHTMLAttributes<HTMLAnchorElement> & { variant?: ButtonVariant };

/** Button-styled <a> for pill CTAs that navigate (e.g. "Meet Penny" → /sign-up). */
export function ButtonLink({ variant = "filled", className = "", ...rest }: Props) {
  return <a className={`inline-block no-underline ${buttonClasses(variant, className)}`} {...rest} />;
}
```

- [ ] **Step 4: Create `DemoBubble`**

`frontend/packages/ui/src/primitives/DemoBubble.tsx`:

```tsx
import type { ReactNode } from "react";

export interface DemoBubbleProps {
  /** "user" = right-aligned gold bubble; "penny" = left-aligned cream bubble. */
  role: "user" | "penny";
  children: ReactNode;
}

/** Static chat bubble for marketing/demo conversation previews — NOT the live
 *  chat surface (that's agent-ui). Penny bubbles style any nested <table> to
 *  the template's bordered data-table look. */
export function DemoBubble({ role, children }: DemoBubbleProps) {
  const shape =
    role === "user"
      ? "ml-auto max-w-[80%] rounded-2xl rounded-tr-sm bg-orange text-ink"
      : "mr-auto max-w-[96%] rounded-2xl rounded-tl-sm border border-cream bg-cream-soft text-ink";
  const tables =
    "[&_table]:my-2 [&_table]:w-full [&_table]:border-collapse [&_table]:text-xs " +
    "[&_th]:border [&_th]:border-ink/15 [&_th]:bg-navy/10 [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_th]:font-semibold " +
    "[&_td]:border [&_td]:border-ink/15 [&_td]:px-2 [&_td]:py-1 " +
    "[&_td:not(:first-child)]:text-right [&_th:not(:first-child)]:text-right";
  return (
    <div className={`px-3.5 py-2.5 font-ui text-sm leading-relaxed ${shape} ${tables}`}>
      {children}
    </div>
  );
}
```

- [ ] **Step 5: Export and add Gallery samples**

In `frontend/packages/ui/src/index.ts`, extend the Button block and add DemoBubble:

```ts
export { Button, buttonClasses } from "./primitives/Button";
export type { ButtonVariant } from "./primitives/Button";
export { ButtonLink } from "./primitives/ButtonLink";
export { DemoBubble } from "./primitives/DemoBubble";
export type { DemoBubbleProps } from "./primitives/DemoBubble";
```

(Replace the existing `export { Button } from "./primitives/Button";` line.)

In `Gallery.tsx`, import `ButtonLink` and `DemoBubble` and add after the `ui-accent-underline` Sample:

```tsx
      <Sample id="ui-buttonlink" label="ButtonLink">
        <ButtonLink variant="filled" href="#ui-buttonlink">
          Ask Penny →
        </ButtonLink>
        <ButtonLink variant="outlined" href="#ui-buttonlink">
          Meet Penny
        </ButtonLink>
      </Sample>

      <Sample id="ui-demobubble" label="DemoBubble">
        <div className="flex w-full max-w-md flex-col gap-3">
          <DemoBubble role="user">Where did my spending surge last year?</DemoBubble>
          <DemoBubble role="penny">
            Three months broke your baseline:
            <table>
              <thead>
                <tr>
                  <th>Month</th>
                  <th>Spend</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Sep</td>
                  <td>$5,900</td>
                </tr>
                <tr>
                  <td>Dec</td>
                  <td>$7,200</td>
                </tr>
              </tbody>
            </table>
            All <b>one-offs</b>, not a lifestyle shift.
          </DemoBubble>
        </div>
      </Sample>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd frontend && npm run build && npx playwright test e2e/ui-gallery.spec.ts`
Expected: build OK; spec PASSES.

- [ ] **Step 7: Commit**

```bash
git add frontend/packages/ui/src frontend/e2e/ui-gallery.spec.ts
git commit -m "feat(ui): ButtonLink + DemoBubble primitives"
```

---

### Task 3: Home page skeleton — copy, header, hero, footer, DEV `/home` route

**Files:**
- Create: `frontend/src/home/copy.ts`
- Create: `frontend/src/home/HomeHeader.tsx`
- Create: `frontend/src/home/Hero.tsx`
- Create: `frontend/src/home/HomeFooter.tsx`
- Create: `frontend/src/home/HomeScreen.tsx`
- Modify: `frontend/src/main.tsx`
- Test: `frontend/e2e/home.spec.ts` (create)

**Interfaces:**
- Consumes: `NavLink`, `AccentUnderline`, `ButtonLink`, `EyebrowPill`, `Chip`, `Input`, `Logo` from `@penny/ui`; `grain` / `animate-rise-in` utilities.
- Produces: `HomeScreen` (no props) from `frontend/src/home/HomeScreen.tsx` — consumed by Task 5's `AuthGate`; `home` copy object from `copy.ts` — consumed by Task 4's sections.

- [ ] **Step 1: Write the failing e2e spec**

Create `frontend/e2e/home.spec.ts`:

```ts
import { expect, test } from "./fixtures/app";

/**
 * Guards the logged-out landing page via the dev-only /home preview route
 * (same pattern as /ui): it renders without Clerk, so the dev-principal
 * harness covers it. Clerk-mode signed-out behavior at `/` is auth.spec.ts.
 */
test("landing page renders hero with sign-up CTAs", async ({ page }) => {
  await page.goto("/home");

  await expect(page.getByRole("heading", { level: 1 })).toContainText(/Meet Penny/i);
  // Header CTAs route to the auth screens.
  await expect(page.getByRole("link", { name: "Meet Penny" })).toHaveAttribute("href", "/sign-up");
  await expect(page.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/sign-in");
  // Hero input affordance is present.
  await expect(page.getByRole("button", { name: "Ask Penny" })).toBeVisible();
});
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd frontend && npx playwright test e2e/home.spec.ts`
Expected: FAIL — /home renders the chat screen (dev-principal fallback), no level-1 "Meet Penny" heading.

- [ ] **Step 3: Create the copy module**

`frontend/src/home/copy.ts` — all placeholder copy, carried from the design template. **This is the only file (plus demos.tsx) to touch when the words change.**

```ts
/** All landing-page copy in one place. The design is stable but the words are
 *  placeholder (carried from design-reference) — edit here, never in the
 *  section components. */
export const home = {
  eyebrow: "Your finance savant",
  nav: [
    { label: "Analyze", href: "#analyze" },
    { label: "Project", href: "#project" },
    { label: "Budget", href: "#budget" },
    { label: "Forecast", href: "#forecast" },
    { label: "Trends", href: "#trends" },
  ],
  hero: {
    title1: "Meet Penny,",
    title2Pre: "your ",
    titleAccent: "finance savant.",
    body: "Penny reasons over your entire financial history — not last month's total. Ask her to trace a spending surge to its cause, model renting against buying, or contract a year of averages into a budget that actually pulls you forward.",
    inputPlaceholder: "Analyze last year and explain what caused my spending to surge…",
    chips: [
      { emoji: "📈", label: "Diagnose my spending surges" },
      { emoji: "🏠", label: "Rent vs. buy, 5-year net worth" },
      { emoji: "🎯", label: "Build a disciplined budget" },
    ],
  },
  stats: [
    { title: "Root-cause", sub: "not just totals" },
    { title: "Scenario", sub: "modeling & projections" },
    { title: "Forward", sub: "cash-flow forecasts" },
    { title: "Goal-based", sub: "optimization" },
  ],
  features: [
    {
      id: "analyze",
      eyebrow: "01 · Root-cause analysis",
      title: "Not just what you spent —",
      titleAccent: "why.",
      body: "Penny scans a full year, detects the months where your spending broke pattern, then decomposes each spike down to the merchants and one-off events behind it — separating a real behavior shift from a single anomalous charge.",
      cta: "“Find my spending surges and explain them”",
    },
    {
      id: "project",
      eyebrow: "02 · Scenario modeling",
      title: "Model the decision before you make it.",
      body: "Rent vs. buy, a job change, a big purchase — Penny projects it forward from your real balances: down payment, opportunity cost, principal paydown, appreciation, and the market return on what you didn't spend. Then she tells you where the break-even actually is.",
      cta: "“Rent vs. buy a $750k house”",
    },
    {
      id: "budget",
      eyebrow: "03 · Disciplined budgeting",
      title: "A budget with a spine.",
      body: "Not last month's spending handed back to you. Penny builds from a full 12 months of averages — smoothing out the trips and the holidays — then contracts each discretionary line by the margin you choose, holding essentials fixed, so the plan pulls you forward instead of ratifying the status quo.",
      cta: "“12-month averages, contracted 10%”",
    },
    {
      id: "forecast",
      eyebrow: "04 · Forward cash flow",
      title: "See the months you're about to run tight.",
      body: "Penny projects your balances forward from recurring income, every subscription and bill, and the seasonal shape of your own history — then flags the months you'll dip below your comfort line, early enough to actually do something about it.",
      cta: "“Forecast my cash flow to year-end”",
    },
    {
      id: "trends",
      eyebrow: "05 · Behavioral trends",
      title: "Catch lifestyle creep in the act.",
      body: "Year over year, category by category, adjusted for inflation — Penny isolates where your baseline is quietly ratcheting up from where you simply splurged once. The slow leaks, not the obvious ones.",
      cta: "“Where is lifestyle creep setting in?”",
    },
    {
      id: "optimize",
      eyebrow: "06 · Goal optimization",
      title: "Name the goal. Penny finds the cuts.",
      body: "Tell Penny the target — $40k for a down payment in 24 months — and she reverse-engineers the plan against your actual spending, ranking specific cuts from least to most painful so the math closes without a crash diet.",
      cta: "“Reverse-engineer my $40k goal”",
    },
  ],
  closing: {
    title: "Ask something hard.",
    body: "Penny is standing by. Give her a real question and watch her work.",
    cta: "Start chatting with Penny",
  },
  footer: {
    tagline: "Penny — your finance savant · © 2026",
  },
} as const;
```

- [ ] **Step 4: Create `HomeHeader`**

`frontend/src/home/HomeHeader.tsx`:

```tsx
import { ButtonLink, Logo, NavLink } from "@penny/ui";
import { home } from "./copy";

/** Sticky translucent landing header: mark + wordmark, anchor nav (md+),
 *  Sign in / Meet Penny CTAs. Marketing chrome — deliberately not the app's
 *  @penny/ui Header (sticky + blur + wordmark-link are landing-only). */
export function HomeHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-navy bg-paper/80 backdrop-blur-md">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-6 px-5 py-3 sm:px-8">
        <a href="/" className="flex items-center gap-3 no-underline">
          <Logo variant="flat" size={44} />
          <span className="font-serif text-2xl font-semibold tracking-[0.22em] text-navy">
            PENNY
          </span>
        </a>
        <nav className="hidden items-center gap-8 text-navy md:flex">
          {home.nav.map((n) => (
            <NavLink key={n.href} href={n.href}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="flex items-center gap-5 text-navy">
          <NavLink href="/sign-in">Sign in</NavLink>
          <ButtonLink variant="outlined" href="/sign-up">
            Meet Penny
          </ButtonLink>
        </div>
      </div>
    </header>
  );
}
```

- [ ] **Step 5: Create `Hero`**

`frontend/src/home/Hero.tsx`:

```tsx
import { useState } from "react";
import { AccentUnderline, Chip, EyebrowPill, Input, Logo } from "@penny/ui";
import { home } from "./copy";

/** Hero: headline + placeholder question input + suggestion chips (left),
 *  emblem on a cream oval with accent dots (right). Every affordance routes
 *  to sign-up — the landing page never talks to the agent. */
export function Hero() {
  const [question, setQuestion] = useState("");
  const goSignUp = () => window.location.assign("/sign-up");

  return (
    <section className="mx-auto max-w-7xl px-5 pt-14 pb-16 sm:px-8 sm:pt-20">
      <div className="grid items-center gap-12 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="animate-rise-in motion-reduce:animate-none">
          <EyebrowPill className="mb-6">{home.eyebrow}</EyebrowPill>
          <h1 className="font-serif text-6xl font-semibold leading-[1.02] text-navy sm:text-7xl">
            {home.hero.title1}
            <br />
            {home.hero.title2Pre}
            <AccentUnderline>{home.hero.titleAccent}</AccentUnderline>
          </h1>
          <p className="mt-6 max-w-lg font-ui text-lg text-ink">{home.hero.body}</p>
          <div className="mt-8 max-w-xl">
            <Input
              value={question}
              onChange={setQuestion}
              onSubmit={goSignUp}
              placeholder={home.hero.inputPlaceholder}
            />
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {home.hero.chips.map((c) => (
              <Chip key={c.label} emoji={c.emoji} label={c.label} onClick={goSignUp} />
            ))}
          </div>
        </div>
        <div className="relative mx-auto flex aspect-[4/3] w-full max-w-lg items-center justify-center">
          <div className="absolute inset-0 rounded-full bg-cream" />
          <div className="absolute right-3 top-3 h-16 w-16 rounded-full bg-orange/90" />
          <div className="absolute bottom-5 left-6 h-7 w-7 rounded-full bg-navy" />
          <Logo
            variant="emblem"
            size={240}
            className="relative transition-transform duration-500 hover:-translate-y-1.5 hover:-rotate-1"
          />
        </div>
      </div>
    </section>
  );
}
```

- [ ] **Step 6: Create `HomeFooter`**

`frontend/src/home/HomeFooter.tsx`:

```tsx
import { Logo, NavLink } from "@penny/ui";
import { home } from "./copy";

/** Navy footer band: mark + wordmark, tagline, anchor links. */
export function HomeFooter() {
  return (
    <footer className="bg-navy">
      <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-6 px-5 py-10 sm:flex-row sm:px-8">
        <div className="flex items-center gap-3">
          <Logo variant="flat" size={40} />
          <span className="font-serif text-2xl font-semibold tracking-[0.22em] text-cream">
            PENNY
          </span>
        </div>
        <p className="font-ui text-sm text-cream-soft/70">{home.footer.tagline}</p>
        <nav className="flex gap-6 text-cream-soft">
          {home.nav.slice(0, 3).map((n) => (
            <NavLink key={n.href} href={n.href} className="text-xs uppercase tracking-[0.22em]">
              {n.label}
            </NavLink>
          ))}
        </nav>
      </div>
    </footer>
  );
}
```

- [ ] **Step 7: Create the `HomeScreen` skeleton**

`frontend/src/home/HomeScreen.tsx` (Task 4 adds the remaining sections into `<main>`):

```tsx
import { HomeHeader } from "./HomeHeader";
import { Hero } from "./Hero";
import { HomeFooter } from "./HomeFooter";

/** The public logged-out landing page (meetpenny.app). Pure marketing chrome —
 *  no auth, no API calls; every CTA routes to /sign-up (see home.spec.ts). */
export function HomeScreen() {
  return (
    <div className="relative h-full overflow-y-auto bg-paper text-ink">
      <div className="grain pointer-events-none fixed inset-0 z-0" />
      <HomeHeader />
      <main className="relative z-10">
        <Hero />
      </main>
      <HomeFooter />
    </div>
  );
}
```

- [ ] **Step 8: Add the DEV-only `/home` preview route**

In `frontend/src/main.tsx`, import HomeScreen (after the Gallery import):

```tsx
import { HomeScreen } from "./home/HomeScreen";
```

Add below the `showGallery` declaration:

```tsx
// Dev-only landing-page preview: `/home` renders the logged-out HomeScreen
// without Clerk, mirroring the `/ui` Gallery pattern, so the marketing page is
// developable and e2e-testable in dev-principal mode. In production the page
// is the signed-out view of `/` (AuthGate).
const showHomePreview = import.meta.env.DEV && window.location.pathname.startsWith("/home");
```

And in `Root()`, add the branch right after the gallery branch:

```tsx
function Root() {
  if (showGallery) return <Gallery />;
  if (showHomePreview) return <HomeScreen />;
  if (clerkKey) {
    ...
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd frontend && npm run build && npx playwright test e2e/home.spec.ts e2e/ui-gallery.spec.ts`
Expected: build OK; both specs PASS.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/home frontend/src/main.tsx frontend/e2e/home.spec.ts
git commit -m "feat(web): logged-out home page skeleton (header, hero, footer) + dev /home preview"
```

---

### Task 4: Feature sections, stat strip, closing CTA, demo conversations

**Files:**
- Create: `frontend/src/home/StatStrip.tsx`
- Create: `frontend/src/home/FeatureSection.tsx`
- Create: `frontend/src/home/demos.tsx`
- Create: `frontend/src/home/ClosingCta.tsx`
- Modify: `frontend/src/home/HomeScreen.tsx`
- Test: `frontend/e2e/home.spec.ts`

**Interfaces:**
- Consumes: `home` from `./copy`; `DemoBubble`, `AccentUnderline`, `ButtonLink`, `Logo` from `@penny/ui`.
- Produces: `StatStrip` (no props), `FeatureSection` (`FeatureSectionProps` below), `demos: Record<string, ReactNode>` keyed by feature id, `ClosingCta` (no props). All consumed only by `HomeScreen`.

- [ ] **Step 1: Extend the e2e spec (failing test)**

Append to `frontend/e2e/home.spec.ts`:

```ts
test("landing page renders all six feature sections and the closing CTA", async ({ page }) => {
  await page.goto("/home");

  for (const id of ["analyze", "project", "budget", "forecast", "trends", "optimize"]) {
    await expect(page.locator(`section#${id}`)).toBeVisible();
  }
  // 1 header + 6 feature CTAs + 1 closing CTA link to /sign-up.
  await expect(page.locator('a[href="/sign-up"]')).toHaveCount(8);
  await expect(page.getByRole("link", { name: /start chatting with penny/i })).toBeVisible();
});
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd frontend && npx playwright test e2e/home.spec.ts`
Expected: FAIL — `section#analyze` not found.

- [ ] **Step 3: Create `StatStrip`**

`frontend/src/home/StatStrip.tsx`:

```tsx
import { home } from "./copy";

/** Four-up serif stat band under the hero. */
export function StatStrip() {
  return (
    <section className="border-y border-ink/15 bg-cream-soft">
      <div className="mx-auto grid max-w-7xl grid-cols-2 gap-6 px-5 py-8 text-center sm:grid-cols-4 sm:px-8">
        {home.stats.map((s) => (
          <div key={s.title}>
            <p className="font-serif text-4xl font-semibold text-navy">{s.title}</p>
            <p className="mt-1 font-ui text-xs uppercase tracking-[0.22em] text-navy-700">{s.sub}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Create `FeatureSection`**

`frontend/src/home/FeatureSection.tsx`:

```tsx
import type { ReactNode } from "react";
import { AccentUnderline, ButtonLink } from "@penny/ui";

export interface FeatureSectionProps {
  id: string;
  eyebrow: string;
  title: string;
  /** Trailing headline fragment rendered with the gold underline. */
  titleAccent?: string;
  body: string;
  cta: string;
  /** Demo conversation (DemoBubbles) shown in the ringed panel. */
  demo: ReactNode;
  /** Alternate row: cream band, demo panel first at lg. */
  flip?: boolean;
}

/** One feature row: eyebrow + serif headline + body + sign-up CTA on one side,
 *  a ringed demo-conversation panel on the other; `flip` alternates sides and
 *  paints the cream band (template sections 02/04/06). */
export function FeatureSection({
  id,
  eyebrow,
  title,
  titleAccent,
  body,
  cta,
  demo,
  flip = false,
}: FeatureSectionProps) {
  return (
    <section id={id} className={flip ? "bg-cream-soft py-20" : "py-20"}>
      <div className="mx-auto grid max-w-7xl items-center gap-12 px-5 sm:px-8 lg:grid-cols-2">
        <div className={flip ? "order-1 lg:order-2" : ""}>
          <span className="font-ui text-xs font-semibold uppercase tracking-[0.22em] text-orange">
            {eyebrow}
          </span>
          <h2 className="mt-3 font-serif text-5xl font-semibold text-navy">
            {title}
            {titleAccent ? <> <AccentUnderline>{titleAccent}</AccentUnderline></> : null}
          </h2>
          <p className="mt-4 max-w-md font-ui text-lg text-ink">{body}</p>
          <ButtonLink href="/sign-up" className="mt-7 px-7 py-3.5">
            {cta} →
          </ButtonLink>
        </div>
        <div
          className={`rounded-[1.8rem] bg-paper p-6 ring-2 ring-navy ${flip ? "order-2 lg:order-1" : ""}`}
        >
          <div className="flex flex-col gap-3">{demo}</div>
        </div>
      </div>
    </section>
  );
}
```

- [ ] **Step 5: Create the demo conversations**

`frontend/src/home/demos.tsx` — placeholder demo content from the template, keyed by feature id:

```tsx
import type { ReactNode } from "react";
import { DemoBubble } from "@penny/ui";

/** Placeholder demo conversations (from design-reference), keyed by feature
 *  id. Content-only — the words/numbers are expected to iterate with copy.ts. */
export const demos: Record<string, ReactNode> = {
  analyze: (
    <>
      <DemoBubble role="user">Where did my spending surge last year, and why?</DemoBubble>
      <DemoBubble role="penny">
        Three months broke your ~$4.1k baseline:
        <table>
          <thead>
            <tr><th>Month</th><th>Spend</th><th>Driver</th></tr>
          </thead>
          <tbody>
            <tr><td>Sep</td><td>$5,900</td><td>Italy trip ($1,930 flights+hotels)</td></tr>
            <tr><td>Dec</td><td>$7,200</td><td>Gifts $1,900 + holiday travel $900</td></tr>
            <tr><td>Mar</td><td>$5,400</td><td>MacBook Pro $2,000 + $620 dental</td></tr>
          </tbody>
        </table>
        All three are <b>one-offs</b>, not a lifestyle shift — your recurring baseline held steady.
        The one to watch is Dec; it repeats every year.
      </DemoBubble>
    </>
  ),
  project: (
    <>
      <DemoBubble role="user">Net worth in 5 years — keep renting vs. buy a $750k house?</DemoBubble>
      <DemoBubble role="penny">
        Modeling 20% down, 6.75% 30-yr, 4% appreciation, 7% market return:
        <table>
          <thead>
            <tr><th>Path</th><th>Net worth, yr 5</th></tr>
          </thead>
          <tbody>
            <tr><td>Rent + invest</td><td>~$600k</td></tr>
            <tr><td>Buy $750k</td><td>~$540k</td></tr>
          </tbody>
        </table>
        Counter-intuitively, <b>renting edges ahead over 5 years</b> — $169k in upfront cash and the
        higher carry compound faster than equity + appreciation. The lines cross around{" "}
        <b>year 8</b>, after which buying pulls ahead. Illustrative; not tax advice.
      </DemoBubble>
    </>
  ),
  budget: (
    <>
      <DemoBubble role="user">Budget from my 12-mo averages, tightened 10%.</DemoBubble>
      <DemoBubble role="penny">
        Discretionary lines cut 10%, essentials held:
        <table>
          <thead>
            <tr><th>Category</th><th>12-mo avg</th><th>Target</th></tr>
          </thead>
          <tbody>
            <tr><td>Travel</td><td>$720</td><td>$648</td></tr>
            <tr><td>Groceries</td><td>$625</td><td>$563</td></tr>
            <tr><td>Restaurants</td><td>$430</td><td>$387</td></tr>
            <tr><td>Shopping</td><td>$410</td><td>$369</td></tr>
            <tr><td>Delivery</td><td>$250</td><td>$225</td></tr>
          </tbody>
        </table>
        New target: <b>$4,170/mo</b>, down from $4,636. That's ~$5,600/yr redirected. Want me to go
        conservative (15%) on the discretionary lines only?
      </DemoBubble>
    </>
  ),
  forecast: (
    <>
      <DemoBubble role="user">Forecast my cash flow to year-end. Any tight months?</DemoBubble>
      <DemoBubble role="penny">
        Projecting income, every recurring bill, and seasonal patterns against your $48k liquid
        buffer:
        <table>
          <thead>
            <tr><th>Month</th><th>Proj. liquid low</th></tr>
          </thead>
          <tbody>
            <tr><td>Sep</td><td>$14.2k</td></tr>
            <tr><td>Nov</td><td>$12.1k</td></tr>
            <tr><td>Dec</td><td><b>$8.6k ⚠</b></td></tr>
          </tbody>
        </table>
        <b>December</b> is the pinch: holiday spend collides with your $1,400 annual auto-insurance
        renewal. Moving that renewal to autopay in Jan, or pre-funding $1.5k in Nov, keeps you above
        your $10k line.
      </DemoBubble>
    </>
  ),
  trends: (
    <>
      <DemoBubble role="user">Where's lifestyle creep showing up, YoY?</DemoBubble>
      <DemoBubble role="penny">
        Discretionary is up <b>11% YoY</b> vs ~3% inflation — so ~8% real creep. The recurring
        offenders:
        <table>
          <thead>
            <tr><th>Category</th><th>YoY</th></tr>
          </thead>
          <tbody>
            <tr><td>Delivery</td><td>+31%</td></tr>
            <tr><td>Subscriptions</td><td>+22%</td></tr>
            <tr><td>Restaurants</td><td>+18%</td></tr>
          </tbody>
        </table>
        These are <b>baseline shifts every month</b>, not one-time bumps — three new subscriptions
        and a steady DoorDash climb. That's where the discipline pays off.
      </DemoBubble>
    </>
  ),
  optimize: (
    <>
      <DemoBubble role="user">Get me to $40k in 24 months. What do I cut, least painful first?</DemoBubble>
      <DemoBubble role="penny">
        You need <b>$1,667/mo</b>. You already net ~$1,450 surplus — so we need ~$220 more, ranked
        by pain:
        <table>
          <thead>
            <tr><th>Cut</th><th>+ / mo</th></tr>
          </thead>
          <tbody>
            <tr><td>2 unused subscriptions</td><td>$54</td></tr>
            <tr><td>Coffee: 2 fewer shop visits/wk</td><td>$50</td></tr>
            <tr><td>Delivery −40%</td><td>$100</td></tr>
            <tr><td>Trim shopping</td><td>$60</td></tr>
          </tbody>
        </table>
        That's <b>$264/mo</b> from the four least-painful moves — target met with room to spare,
        without touching travel or restaurants.
      </DemoBubble>
    </>
  ),
};
```

- [ ] **Step 6: Create `ClosingCta`**

`frontend/src/home/ClosingCta.tsx`:

```tsx
import { ButtonLink, Logo } from "@penny/ui";
import { home } from "./copy";

/** Orange closing band: emblem, serif headline, sign-up CTA. */
export function ClosingCta() {
  return (
    <section className="mx-auto max-w-7xl px-5 py-20 sm:px-8">
      <div className="relative overflow-hidden rounded-[2.5rem] bg-orange px-8 py-16 text-center sm:px-16 sm:py-20">
        <div className="absolute -right-10 -top-10 h-44 w-44 rounded-full bg-navy/15" />
        <div className="absolute -bottom-12 -left-8 h-52 w-52 rounded-full bg-navy/10" />
        <div className="relative">
          <Logo variant="emblem" size={96} className="mx-auto mb-7" />
          <h2 className="font-serif text-5xl font-semibold text-ink sm:text-6xl">
            {home.closing.title}
          </h2>
          <p className="mx-auto mt-4 max-w-xl font-ui text-lg text-navy">{home.closing.body}</p>
          <ButtonLink href="/sign-up" className="mt-8 px-9 py-4">
            {home.closing.cta} →
          </ButtonLink>
        </div>
      </div>
    </section>
  );
}
```

- [ ] **Step 7: Wire the sections into `HomeScreen`**

Replace `frontend/src/home/HomeScreen.tsx` with:

```tsx
import { HomeHeader } from "./HomeHeader";
import { Hero } from "./Hero";
import { StatStrip } from "./StatStrip";
import { FeatureSection } from "./FeatureSection";
import { ClosingCta } from "./ClosingCta";
import { HomeFooter } from "./HomeFooter";
import { home } from "./copy";
import { demos } from "./demos";

/** The public logged-out landing page (meetpenny.app). Pure marketing chrome —
 *  no auth, no API calls; every CTA routes to /sign-up (see home.spec.ts). */
export function HomeScreen() {
  return (
    <div className="relative h-full overflow-y-auto bg-paper text-ink">
      <div className="grain pointer-events-none fixed inset-0 z-0" />
      <HomeHeader />
      <main className="relative z-10">
        <Hero />
        <StatStrip />
        {home.features.map((f, i) => (
          <FeatureSection key={f.id} {...f} flip={i % 2 === 1} demo={demos[f.id]} />
        ))}
        <ClosingCta />
      </main>
      <HomeFooter />
    </div>
  );
}
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd frontend && npm run build && npx playwright test e2e/home.spec.ts`
Expected: build OK; both home tests PASS.

- [ ] **Step 9: Visual check against the design**

With the harness's Vite server (or `npm run dev`), open `http://127.0.0.1:5175/home` in a browser (or take a Playwright screenshot) and compare against `frontend/design-reference/preview.jpeg`: sticky blur header, hero grid with cream oval + dots, alternating cream bands on sections 02/04/06, ringed demo panels with data tables, orange closing band, navy footer. Fix layout drift before committing.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/home frontend/e2e/home.spec.ts
git commit -m "feat(web): landing feature sections, stat strip, demos, closing CTA"
```

---

### Task 5: Stitch signed-out routing — `/` = home, `/sign-in` + `/sign-up` = Clerk

**Files:**
- Modify: `frontend/src/AuthGate.tsx`
- Modify: `frontend/index.html`
- Test: `frontend/e2e/auth.spec.ts` (Clerk-gated — compile-checked here, executed only under `PENNY_E2E_CLERK=1`)

**Interfaces:**
- Consumes: `HomeScreen` from `./home/HomeScreen`; `Logo` from `@penny/ui`.
- Produces: signed-out routing contract — `/` → HomeScreen; `/sign-up` → `<SignUp>`; `/sign-in` and every other path → `<SignIn>`; both Clerk components get `forceRedirectUrl="/"` so post-auth users land on chat at `/`.

- [ ] **Step 1: Update the Clerk-gated auth spec (failing under PENNY_E2E_CLERK)**

In `frontend/e2e/auth.spec.ts`, replace the first test:

```ts
test("a signed-out visitor sees the landing page and can reach sign-in", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/Meet Penny/i);
  await expect(page.getByRole("textbox", { name: /message/i })).toHaveCount(0);

  await page.getByRole("link", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();
});
```

And in the "sign in, send a message, get a response, sign out" test, replace the final expectation (after sign-out the signed-out view at `/` is now the landing page):

```ts
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/Meet Penny/i);
```

- [ ] **Step 2: Rewrite `AuthGate`**

Replace `frontend/src/AuthGate.tsx` with:

```tsx
import { Show, SignIn, SignUp, UserButton, useAuth } from "@clerk/react";
import type { ReactNode } from "react";
import { Logo } from "@penny/ui";
import { AppShell } from "./AppShell";
import { HomeScreen } from "./home/HomeScreen";

// Signed-out routing: the marketing home page owns `/`; Clerk's <SignUp> and
// <SignIn> live at /sign-up and /sign-in (cross-linked, phase 4 open signup);
// any other signed-out deep link (e.g. /settings/providers) falls back to
// sign-in so the visitor lands on the screen they asked for once authenticated.
const path = window.location.pathname;
const showSignUp = path.startsWith("/sign-up");
const showHome = !showSignUp && !path.startsWith("/sign-in") && path === "/";

/**
 * Clerk auth shell. A signed-out visitor sees the landing page at `/` and the
 * hosted <SignUp> / <SignIn> (Google) on the auth paths; a signed-in user sees
 * the household header (name + rename + invite nav + <UserButton>) above the
 * routed screen.
 *
 * Only mounted when Clerk is configured (VITE_CLERK_PUBLISHABLE_KEY set) — see
 * main.tsx. In dev-principal mode the app renders screens without this gate.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const { getToken } = useAuth();
  return (
    <>
      <Show when="signed-out">
        {showHome ? (
          <HomeScreen />
        ) : (
          <div className="auth-gate flex h-full w-full flex-col bg-background">
            <a href="/" className="flex items-center gap-3 px-6 py-4 no-underline">
              <Logo variant="flat" size={36} />
              <span className="font-serif text-xl font-semibold tracking-[0.22em] text-navy">
                PENNY
              </span>
            </a>
            <div className="flex flex-1 items-center justify-center">
              {showSignUp ? (
                <SignUp routing="hash" signInUrl="/sign-in" forceRedirectUrl="/" />
              ) : (
                <SignIn routing="hash" signUpUrl="/sign-up" forceRedirectUrl="/" />
              )}
            </div>
          </div>
        )}
      </Show>
      <Show when="signed-in">
        <AppShell getToken={getToken} actions={<UserButton />}>
          {children}
        </AppShell>
      </Show>
    </>
  );
}
```

- [ ] **Step 3: Update the document metadata**

In `frontend/index.html`, replace `<title>Penny</title>` with:

```html
    <title>Penny — Your finance savant</title>
    <meta
      name="description"
      content="Penny is an AI agent that deeply and precisely analyzes your personal finances."
    />
```

- [ ] **Step 4: Verify**

Run: `cd frontend && npm run build && npx playwright test`
Expected: build OK; full harness suite passes (auth/signup/invite/byo specs report "skipped" without `PENNY_E2E_CLERK`).

If Clerk test keys are available in the environment, also run: `PENNY_E2E_CLERK=1 npx playwright test e2e/auth.spec.ts e2e/signup.spec.ts` — expected PASS. Otherwise flag in the PR that the Clerk-gated specs were updated but not executed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/AuthGate.tsx frontend/index.html frontend/e2e/auth.spec.ts
git commit -m "feat(web): signed-out / renders the home page; Clerk auth at /sign-in + /sign-up"
```

---

### Task 6: Requirements, full gates, bead

**Files:**
- Modify: `REQUIREMENTS.txt`

**Interfaces:**
- Consumes: nothing new.
- Produces: P13 product requirement documenting the page (scope-of-record rule in AGENTS.md).

- [ ] **Step 1: Add P13 to REQUIREMENTS.txt**

Insert after the P12 block (match the file's indentation style):

```
P13. Public logged-out home page
    A signed-out visitor to `/` sees a public marketing home page in the cream
    design system — hero with sample prompts, a six-part feature tour with demo
    conversations, and a closing call-to-action — rather than a bare sign-in
    form. Every call-to-action routes to sign-up/sign-in (P10 open signup); the
    sign-in and sign-up screens live at /sign-in and /sign-up and carry the
    same design system (P11). Signed-out deep links to app screens still land
    on sign-in. Copy is expected to iterate; the page structure and CTA routing
    are the requirement (guardrail: frontend/e2e/home.spec.ts).
```

- [ ] **Step 2: Run the full verification gates**

```bash
cd frontend && npm run build && npx playwright test
cd ../backend && uv run ruff check . && uv run ruff format --check . && uv run pytest -q
```

Expected: all green (backend untouched — this confirms it).

- [ ] **Step 3: Commit and update the bead**

```bash
git add REQUIREMENTS.txt
git commit -m "docs(requirements): P13 — public logged-out home page"
bd comment fly-svi "Home page implemented behind feature/meetpenny-home: signed-out / renders the landing page, CTAs route to /sign-in + /sign-up. DNS/hosting for meetpenny.app tracked separately in this bead."
```

(The bead stays `in_progress` — it also covers DNS/domain wiring and hosting, which are not part of this plan.)

---

## Out of scope (flagged, not planned)

- **DNS / meetpenny.app cutover and hosting** — separate work in bead fly-svi (the four config seams are recorded in project memory `project_meetpenny_domain_cutover.md`).
- **Prefilling the hero question into post-signup chat** (`/sign-up?q=…`) — nice follow-up, adds auth-flow state threading; do only when asked.
- **Clerk appearance theming** of the SignIn/SignUp cards to the cream palette — the surrounding chrome is themed here; deep Clerk `appearance` styling is its own change.
- **Final marketing copy** — placeholder copy ships in `copy.ts`/`demos.tsx`; copy iteration is a words-only edit by design.
