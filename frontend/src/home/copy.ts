/** All landing-page copy in one place. The design is stable but the words are
 *  placeholder (carried from design-reference) — edit here, never in the
 *  section components. */
const nav = [
  { label: "Analyze", href: "#analyze" },
  { label: "Project", href: "#project" },
  { label: "Budget", href: "#budget" },
  { label: "Forecast", href: "#forecast" },
  { label: "Trends", href: "#trends" },
] as const;

export const home = {
  eyebrow: "Your finance savant",
  nav,
  header: { signIn: "Sign in", cta: "Meet Penny" },
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
    // The subset of nav anchors the footer repeats — declared beside `nav` so
    // reordering the nav is a deliberate footer decision too.
    links: nav.slice(0, 3),
  },
} as const;
