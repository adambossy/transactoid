---
id: phase-4-ux
label: UI/UX & E2E
parent: phase-4
sections: [ui-ux, e2e]
crosslinks: [phase-4-signup]
---

# UI/UX & end-to-end validation

Phase 4 adds the self-serve signup and invite surfaces, validated end to end by driving Clerk signup with testing tokens in a real browser.

## Requirements

- I can find a signup screen inside the normal app, sign up with Google, and land directly in my own space.
- I can see my household's name in the header and rename it in place.
- I can invite a family member, review my pending invites, and cancel one — with a clear message if they already have an account.
- A brand-new space with no data yet greets me with a friendly explanation of what to do next, not a blank or broken screen.

## ui-ux — UI/UX requirements

A prospective user can reach a self-serve signup screen (Clerk `<SignUp>`) rendered inside the normal app shell, sign up with Google, and land directly in their own solo household (see [signup.html](signup.html)). A newly signed-up user sees their household's name in the header and can click it to rename the household inline, persisted via `PATCH /api/household`. A household member can open an Invite screen, enter an email, and send an invitation; the screen lists the household's pending invites, each with a revoke control. When inviting an email that already has an account, the inviter sees a clear "start fresh" message (the `409` case) rather than a generic error. A member of a brand-new household with no synced data yet sees a friendly empty state explaining what to do next instead of a blank or broken screen. New screens use the shared UI template primitives — Header, Footer, Logo, color tokens, type scale — responsive, with loading, empty, and error states.

## e2e — Browser E2E validation

Headless Playwright specs reuse the shared harness introduced in phase 1a (test server + DB-reset fixtures) and the `signInAsTestUser` helper from phase 2, driving Clerk signup/sign-in with testing tokens so the flow runs without a human solving bot checks. A signup spec uses a fresh browser context to drive the `<SignUp>` form for a brand-new test email through Clerk's test verification code, then asserts the app redirects into the authenticated shell, `GET /api/me` resolves a household, and the header's `data-testid="household-name"` shows the name derived from the email's local part. An invite spec proves an invited new email signs up into the inviter's household rather than a new one, and that inviting an already-active email surfaces the `409` "start fresh" message. Both run entirely headless against the live backend + frontend.
