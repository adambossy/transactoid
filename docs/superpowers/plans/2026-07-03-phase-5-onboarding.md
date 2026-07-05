# Phase 5 — Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> Part of the [Multi-Account Epic](2026-06-27-multi-account-epic-overview.md).
> Spec: [Phase 5 design](../specs/2026-07-03-phase-5-onboarding-design.md).
> **Prev:** [Phase 4 plan](2026-07-02-phase-4-signup-ui.md) ·
> **Next:** [Phase 6 — Security audit](2026-06-27-phase-6-security-audit.md)

**Goal:** Progressive agent-embedded onboarding — a system-reminder subsystem in
agent-harness, first-class reminder hiding in agent-ui, a deterministic
onboarding engine in Penny, and Plaid Link as inline generative UI with
server-side token exchange.

**Architecture:** agent-harness gains a `ReminderQueue` that the run loop drains
into the outgoing user message as `<system-reminder>` text blocks (system prompt
stays static → cache-safe). agent-ui strips reminder content from rendered user
messages as a library guarantee. Penny provides a DB-backed queue keyed by
conversation, an `onboarding_items` state machine whose deterministic trigger
rules enqueue one consolidated reminder per turn, and a `connect_bank_account`
tool whose structured output renders `react-plaid-link` inline; the exchange
endpoint closes the loop by enqueueing a success reminder.

**Tech Stack:** Python 3.12 (agent-harness, Penny), SQLAlchemy 2.0 + Alembic,
React 19 + `react-plaid-link` + agent-ui's tool-renderer registry, Plaid Python
SDK, promptorium for the prompt version bump.

> **Reused by Phase 2b.** [Phase 2b — BYO Keys & Metered Subsidy](../specs/2026-07-03-phase-2b-byo-keys-metered-subsidy-design.md)
> consumes this phase's mechanisms rather than adding its own nudge machinery:
> it introduces a `byo_credential` reminder kind on **this** system-reminder
> subsystem and an inline "Connect a provider" card via **this** phase's
> generative-UI tool-renderer pattern (Tasks 7–8). No new reminder/onboarding
> plumbing is added there — keep both extensible to a new kind + card.

## Global Constraints

- **Three repos.** agent-harness (`~/code/agent-harness`) and agent-ui
  (`~/code/agent-ui`) are editable-path deps already wired into Penny
  (pyproject `tool.uv.sources` / vite alias). Each repo's tasks run that repo's
  own verification (check its pyproject/package.json for the test command;
  `uv run pytest -q` / the package's `test` script). Penny tasks use the
  standard gate: `uv run ruff check .` · `uv run ruff format --check .` ·
  `uv run pytest -q` from `backend/`.
- **Backend restarts:** uvicorn `--reload` does not watch `~/code/agent-harness`
  or `.prompts/` — manual restart after those change.
- **Prod version pin (three-repo coordination).** The reminder subsystem lands
  in agent-harness and agent-ui, consumed in dev via editable path / vite alias
  — but **prod cannot install `~/code/...`**. This phase must **tag** the
  agent-harness and agent-ui commits that carry the reminder subsystem and
  **pin Penny's prod dependency** to those tags/commits (replace the editable
  source with a versioned dependency for the prod build), and document the prod
  install path. A fresh prod build must resolve a harness/UI that *has* the
  reminder subsystem, or the flush path fails at runtime. The epic index owns the
  cross-repo version matrix; record the pinned versions there.
- **Reminder contract:** wrap format is
  `<system-reminder kind="{kind}">\n{content}\n</system-reminder>`; override
  replaces same-kind queued reminders; only the most recent reminder reflects
  current state (static prompt guidance says so).
- **Statuses:** `onboarding_items.status ∈ {pending, accepted, dismissed}` —
  no `active`. Activation is computed, never stored.
- **Reminder content is server-generated only** — never interpolate client
  input into reminder text.
- **Migrations (per the epic migration ledger):** these tables live in the
  **web DB** (conversation-adjacent app state, not financial data), in the **web
  migration chain** established in phase 2 — revision **`022_add_onboarding_items`**
  and **`023_add_queued_reminders`** (web chain head after phase-2 `019` and phase-2b `020`/`021`). Standard `tenant_isolation` RLS (USING + WITH CHECK) on
  both, dialect-guarded; the web store session binds `SET LOCAL` (phase-2 web
  RLS plumbing) so the policies take effect.
- **Prompts:** the system-prompt change is a promptorium version bump — new
  `<n+1>.md` under `backend/.prompts/penny-system-prompt/` AND `_meta.json`
  bump (`source_file`, `version_dir`, `last_version`,
  `last_hash = "sha256:" + sha256 hex`). Never edit historical versions.
- New env (`.env.example`): `PENNY_PLAID_LINK_MODE=hosted|localhost` (default
  `hosted`), `PLAID_REDIRECT_URI`.

## File structure

- agent-harness — Create: `agent_harness/extras/reminders.py`; Modify:
  `agent_harness/core/loop.py` (user-prompt append, ~lines 111-121),
  `agent_harness/core/agent.py` (`Agent` gains `reminders` param); Tests:
  `tests/extras/test_reminders.py`, `tests/core/test_loop_reminders.py`.
- agent-ui — Create: `packages/agent-ui/src/reminders.ts`; Modify:
  `packages/agent-ui/src/components/Message.tsx` (user branch, lines 28-40),
  `packages/agent-ui/src/index.ts` (export); Test: package test setup.
- Penny — Create: `backend/penny/reminders.py` (DB queue),
  `backend/penny/onboarding.py`, `backend/penny/tools/plaid_link.py`,
  `backend/db/migrations/023_add_queued_reminders.py`,
  `022_add_onboarding_items.py`; Modify: `backend/penny/adapters/db/models.py`,
  `backend/penny/agent_factory.py`, `backend/penny/api/main.py`,
  `backend/penny/tools/registry.py`, `backend/.prompts/…`, `.env.example`.
- Penny frontend — Create: `frontend/src/PlaidLinkCard.tsx`; Modify:
  `frontend/src/main.tsx` (register renderer), `frontend/package.json`
  (`react-plaid-link`).

---

### Task 1 (agent-harness): `ReminderQueue` subsystem

**Files:**
- Create: `~/code/agent-harness/agent_harness/extras/reminders.py`
- Test: `~/code/agent-harness/tests/extras/test_reminders.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) Reminder(kind: str, content: str)`.
  - `wrap_system_reminder(reminder: Reminder) -> str` → the wrap format above.
  - `class ReminderQueue(Protocol)`:
    `async def enqueue(self, session_id: str, kind: str, content: str, *, override: bool = True) -> None`;
    `async def drain(self, session_id: str) -> list[Reminder]`.
  - `class InMemoryReminderQueue(ReminderQueue)` — dict of lists; `override=True`
    removes queued same-kind reminders before appending; `drain` pops all in
    FIFO order.

- [ ] **Step 1: Write the failing test**

```python
# tests/extras/test_reminders.py
import pytest

from agent_harness.extras.reminders import (
    InMemoryReminderQueue, Reminder, wrap_system_reminder,
)


async def test_override_replaces_same_kind():
    q = InMemoryReminderQueue()
    await q.enqueue("s1", "onboarding", "state v1")
    await q.enqueue("s1", "onboarding", "state v2")           # override default
    await q.enqueue("s1", "plaid_link", "linked", override=True)
    drained = await q.drain("s1")
    assert [(r.kind, r.content) for r in drained] == [
        ("onboarding", "state v2"), ("plaid_link", "linked"),
    ]
    assert await q.drain("s1") == []                          # drained empty


async def test_no_override_appends():
    q = InMemoryReminderQueue()
    await q.enqueue("s1", "note", "a", override=False)
    await q.enqueue("s1", "note", "b", override=False)
    assert [r.content for r in await q.drain("s1")] == ["a", "b"]


def test_wrap_format():
    text = wrap_system_reminder(Reminder(kind="onboarding", content="hello"))
    assert text == '<system-reminder kind="onboarding">\nhello\n</system-reminder>'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/code/agent-harness && uv run pytest tests/extras/test_reminders.py -v`
Expected: FAIL — `ModuleNotFoundError` on `agent_harness.extras.reminders`.

- [ ] **Step 3: Write minimal implementation**

```python
# agent_harness/extras/reminders.py
"""System reminders: backend-enqueued state flushed into the next user message.

Hosts enqueue reminders keyed by session; the run loop drains them when the
user prompt is appended and attaches each as a ``<system-reminder>`` text
block. Only the most recent reminder of a kind reflects current state, so
``override=True`` (the default) replaces queued same-kind reminders.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class Reminder:
    kind: str
    content: str


def wrap_system_reminder(reminder: Reminder) -> str:
    return (
        f'<system-reminder kind="{reminder.kind}">\n'
        f"{reminder.content}\n</system-reminder>"
    )


@runtime_checkable
class ReminderQueue(Protocol):
    async def enqueue(
        self, session_id: str, kind: str, content: str, *, override: bool = True
    ) -> None: ...

    async def drain(self, session_id: str) -> list[Reminder]: ...


class InMemoryReminderQueue:
    def __init__(self) -> None:
        self._queues: dict[str, list[Reminder]] = {}

    async def enqueue(
        self, session_id: str, kind: str, content: str, *, override: bool = True
    ) -> None:
        queue = self._queues.setdefault(session_id, [])
        if override:
            queue[:] = [r for r in queue if r.kind != kind]
        queue.append(Reminder(kind=kind, content=content))

    async def drain(self, session_id: str) -> list[Reminder]:
        return self._queues.pop(session_id, [])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/code/agent-harness && uv run pytest tests/extras/test_reminders.py -v` → PASS (3).

- [ ] **Step 5: Commit** (in agent-harness)

```bash
cd ~/code/agent-harness
git add agent_harness/extras/reminders.py tests/extras/test_reminders.py
git commit -m "feat(reminders): ReminderQueue subsystem (enqueue/override/drain, wrap helper)"
```

---

### Task 2 (agent-harness): flush reminders into the user message

**Files:**
- Modify: `~/code/agent-harness/agent_harness/core/agent.py` (`Agent` init),
  `~/code/agent-harness/agent_harness/core/loop.py` (user-prompt append,
  ~lines 111-121)
- Test: `~/code/agent-harness/tests/core/test_loop_reminders.py`

**Interfaces:**
- Consumes: Task 1; `Message`/`TextBlock` (`core/models.py:115-149`); the
  user-prompt append site (`core/loop.py:111-121`).
- Produces: `Agent(..., reminders: ReminderQueue | None = None)`. When set and
  a session exists, the loop — immediately after building `user_msg` and before
  appending it — drains `agent.reminders` for `agent.session.session_id` and
  extends `user_msg.content` with one
  `TextBlock(text=wrap_system_reminder(r))` per reminder, recording
  `user_msg.metadata["system_reminder_kinds"] = [r.kind, ...]`. No queue / no
  session / nothing queued → message unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_loop_reminders.py
# Uses the repo's existing fake-model test harness (see neighboring loop tests
# for the fixture pattern — a scripted model that returns one final message).
import pytest

from agent_harness.extras.reminders import InMemoryReminderQueue


async def test_user_message_carries_drained_reminders(scripted_agent_factory):
    """Build an agent via the repo's existing scripted-model fixture, attach a
    queue with one reminder, run once, and assert the recorded user message."""
    reminders = InMemoryReminderQueue()
    agent, session = scripted_agent_factory(reminders=reminders)
    await reminders.enqueue(session.session_id, "onboarding", "connect plaid")

    await agent.run("hello")

    msgs = await session.get_messages()
    user = next(m for m in msgs if m.role == "user")
    texts = [b.text for b in user.content if getattr(b, "text", None)]
    assert texts[0] == "hello"
    assert texts[1] == (
        '<system-reminder kind="onboarding">\nconnect plaid\n</system-reminder>'
    )
    assert user.metadata["system_reminder_kinds"] == ["onboarding"]
    assert await reminders.drain(session.session_id) == []


async def test_no_queue_means_untouched_message(scripted_agent_factory):
    agent, session = scripted_agent_factory(reminders=None)
    await agent.run("hello")
    user = next(m for m in await session.get_messages() if m.role == "user")
    assert len(user.content) == 1
```

> If no `scripted_agent_factory` fixture exists, adapt the assertion to the
> repo's established loop-test pattern (there are existing tests that run the
> loop against a fake model — mirror one and add the two assertions above).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/code/agent-harness && uv run pytest tests/core/test_loop_reminders.py -v`
Expected: FAIL — `Agent.__init__` has no `reminders` kwarg.

- [ ] **Step 3: Write minimal implementation**

In `agent.py`: add `reminders: ReminderQueue | None = None` to `Agent`
(dataclass/init) and expose it on the run context the loop reads (same route as
`session`). In `loop.py`, extend the user-prompt append block:

```python
user_msg = Message(
    role="user",
    content=[TextBlock(text=text)],
    timestamp=datetime.now(UTC),
)
if agent.reminders is not None and agent.session is not None:
    drained = await agent.reminders.drain(agent.session.session_id)
    if drained:
        from agent_harness.extras.reminders import wrap_system_reminder

        user_msg.content.extend(
            TextBlock(text=wrap_system_reminder(r)) for r in drained
        )
        user_msg.metadata["system_reminder_kinds"] = [r.kind for r in drained]
rc.messages.append(user_msg)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/code/agent-harness && uv run pytest -q` → green (new tests + no regressions).

- [ ] **Step 5: Commit** (in agent-harness)

```bash
cd ~/code/agent-harness
git add agent_harness/core/agent.py agent_harness/core/loop.py tests/core/test_loop_reminders.py
git commit -m "feat(reminders): drain queue into the outgoing user message at run start"
```

---

### Task 3 (agent-ui): first-class reminder hiding

**Files:**
- Create: `~/code/agent-ui/packages/agent-ui/src/reminders.ts`
- Modify: `~/code/agent-ui/packages/agent-ui/src/components/Message.tsx`
  (user branch, lines 28-40), `~/code/agent-ui/packages/agent-ui/src/index.ts`
- Test: the package's test runner (check `package.json` `test` script; add a
  unit test beside existing ones, or a `reminders.test.ts` if vitest is
  configured — otherwise verify via the package's typecheck/build script).

**Interfaces:**
- Produces: exported `stripSystemReminders(text: string): string` — removes
  every `<system-reminder …>…</system-reminder>` span (tag attributes allowed,
  dotall). User-message rendering maps text parts through it and additionally
  skips any part whose `type === "data-system-reminder"`.

- [ ] **Step 1: Implement the util**

```typescript
// packages/agent-ui/src/reminders.ts
const SYSTEM_REMINDER_RE = /<system-reminder\b[^>]*>[\s\S]*?<\/system-reminder>\s*/g;

/** Remove system-reminder spans from user-visible text. First-class rule:
 * reminders are model-facing context, never rendered. */
export function stripSystemReminders(text: string): string {
  return text.replace(SYSTEM_REMINDER_RE, "").trimEnd();
}
```

- [ ] **Step 2: Apply in the user-message branch of `Message.tsx`**

```typescript
import { stripSystemReminders } from "../reminders";
// ...
const text = stripSystemReminders(
  message.parts
    .filter(
      (p): p is Extract<UIMessagePart, { type: "text" }> =>
        p.type === "text",
    )
    .map((p) => p.text)
    .join(""),
);
```

(The existing filter already drops non-text parts, which covers
`data-system-reminder`.) Export `stripSystemReminders` from `src/index.ts`.

- [ ] **Step 3: Test**

```typescript
// reminders.test.ts (if vitest configured)
import { stripSystemReminders } from "./reminders";

test("strips reminder spans, keeps user text", () => {
  const input = 'What did I spend?<system-reminder kind="onboarding">\nnudge\n</system-reminder>';
  expect(stripSystemReminders(input)).toBe("What did I spend?");
});

test("plain text untouched", () => {
  expect(stripSystemReminders("hello")).toBe("hello");
});
```

Run the package's test/build scripts; confirm Penny's frontend still renders
(`npm run dev` smoke — the vite alias picks the change up live).

- [ ] **Step 4: Commit** (in agent-ui)

```bash
cd ~/code/agent-ui
git add packages/agent-ui/src/reminders.ts packages/agent-ui/src/components/Message.tsx packages/agent-ui/src/index.ts
git commit -m "feat: first-class system-reminder hiding in user messages"
```

---

### Task 4 (Penny): DB-backed reminder queue + migration 019

**Files:**
- Modify: `backend/penny/adapters/db/models.py` (add `QueuedReminder`)
- Create: `backend/penny/reminders.py`,
  `backend/db/migrations/023_add_queued_reminders.py`
- Modify: `backend/penny/agent_factory.py` (`build_agent(..., reminders=…)`)
- Test: `backend/tests/test_reminder_queue.py`

**Interfaces:**
- Produces:
  - Model `QueuedReminder` → table `queued_reminders`: `id (Uuid PK,
    default uuid4)`, `conversation_id (String, indexed)`, `kind (String)`,
    `content (Text)`, `household_id (Uuid)`, `owner_user_id (Uuid)`,
    `created_at`; unique `(conversation_id, kind)` — override is an upsert.
  - `class DbReminderQueue` implementing the harness `ReminderQueue` protocol:
    constructed with `(ctx: RequestContext)`; `enqueue(session_id, kind,
    content, *, override=True)` upserts (override) or inserts (non-override
    appends a uuid-suffixed kind); `drain(session_id)` selects FIFO by
    `created_at`, deletes, returns `list[Reminder]`. Sync DB work wrapped in
    `asyncio.to_thread` per repo convention.
  - Migration `019` creates the table + the standard RLS policy (household +
    owner terms, USING + WITH CHECK, dialect-guarded).
  - `build_agent` passes `reminders=DbReminderQueue(ctx)` so every chat/cron
    run flushes pending reminders.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_reminder_queue.py
import uuid

from penny.adapters.db.models import Household, User
from penny.db import get_db
from penny.reminders import DbReminderQueue
from penny.tenancy.context import RequestContext


def _ctx():
    db = get_db(); db.create_schema()
    with db.session() as s:
        hh = Household(name="H"); s.add(hh); s.flush()
        u = User(household_id=hh.household_id, email="a@x.com"); s.add(u); s.flush()
        return RequestContext(user_id=u.user_id, household_id=hh.household_id)


async def test_override_upserts_and_drain_deletes(isolated_db):
    ctx = _ctx()
    q = DbReminderQueue(ctx)
    await q.enqueue("conv-1", "onboarding", "v1")
    await q.enqueue("conv-1", "onboarding", "v2")   # override -> single row
    await q.enqueue("conv-1", "plaid_link", "linked")
    drained = await q.drain("conv-1")
    assert [(r.kind, r.content) for r in drained] == [
        ("onboarding", "v2"), ("plaid_link", "linked"),
    ]
    assert await q.drain("conv-1") == []


async def test_queues_are_per_conversation(isolated_db):
    ctx = _ctx()
    q = DbReminderQueue(ctx)
    await q.enqueue("conv-a", "onboarding", "a-state")
    assert await q.drain("conv-b") == []
    assert [r.content for r in await q.drain("conv-a")] == ["a-state"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_reminder_queue.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'penny.reminders'`.

- [ ] **Step 3: Write minimal implementation**

Add the model to `models.py` (columns above). Create `penny/reminders.py`:

```python
# backend/penny/reminders.py
from __future__ import annotations

import asyncio

from agent_harness.extras.reminders import Reminder

from penny.adapters.db.models import QueuedReminder
from penny.db import get_db
from penny.tenancy.context import RequestContext


class DbReminderQueue:
    """ReminderQueue backed by queued_reminders; survives across HTTP requests."""

    def __init__(self, ctx: RequestContext) -> None:
        self._ctx = ctx

    async def enqueue(
        self, session_id: str, kind: str, content: str, *, override: bool = True
    ) -> None:
        await asyncio.to_thread(self._enqueue_sync, session_id, kind, content, override)

    def _enqueue_sync(self, session_id: str, kind: str, content: str, override: bool) -> None:
        db = get_db()
        with db.session_for(self._ctx) as s:
            if override:
                s.query(QueuedReminder).filter_by(
                    conversation_id=session_id, kind=kind
                ).delete(synchronize_session=False)
            s.add(QueuedReminder(
                conversation_id=session_id, kind=kind, content=content,
                household_id=self._ctx.household_id,
                owner_user_id=self._ctx.user_id,
            ))

    async def drain(self, session_id: str) -> list[Reminder]:
        return await asyncio.to_thread(self._drain_sync, session_id)

    def _drain_sync(self, session_id: str) -> list[Reminder]:
        db = get_db()
        with db.session_for(self._ctx) as s:
            rows = (
                s.query(QueuedReminder)
                .filter_by(conversation_id=session_id)
                .order_by(QueuedReminder.created_at, QueuedReminder.id)
                .all()
            )
            out = [Reminder(kind=r.kind, content=r.content) for r in rows]
            for r in rows:
                s.delete(r)
            return out
```

Migration `023_add_queued_reminders.py` mirrors the model (+ unique
`(conversation_id, kind)` index + RLS block, dialect-guarded). In
`agent_factory.build_agent(..., ctx, ...)` construct `DbReminderQueue(ctx)` and
pass `reminders=` to `Agent(...)`. (Non-override enqueue: insert with kind
suffixed `f"{kind}#{uuid4().hex[:8]}"` to dodge the unique index — drain strips
the suffix when building `Reminder.kind` via `kind.split("#", 1)[0]`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_reminder_queue.py -v` → PASS (2).
Migration chain check as in prior phases → ends at `019`.

- [ ] **Step 5: Commit**

```bash
git add backend/penny/adapters/db/models.py backend/penny/reminders.py \
  backend/db/migrations/023_add_queued_reminders.py backend/penny/agent_factory.py \
  backend/tests/test_reminder_queue.py
git commit -m "feat(reminders): DB-backed reminder queue wired into agent runs (migration 019)"
```

---

### Task 5 (Penny): `onboarding_items` + deterministic trigger engine + tool

**Files:**
- Modify: `backend/penny/adapters/db/models.py` (add `OnboardingItem`)
- Create: `backend/penny/onboarding.py`,
  `backend/db/migrations/022_add_onboarding_items.py`,
  `backend/penny/tools/onboarding.py` (the `@tool`)
- Modify: `backend/penny/tools/registry.py` (register the tool)
- Test: `backend/tests/test_onboarding.py`

**Interfaces:**
- Produces:
  - Model `OnboardingItem` → `onboarding_items`: `id (Uuid PK)`,
    `household_id`, `user_id`, `item_key (String)`, `status (String,
    server_default 'pending')`, `trigger_state (JSON, default {})`,
    `created_at`, `updated_at`; unique `(user_id, item_key)`;
    `CHECK (status IN ('pending','accepted','dismissed'))`; RLS.
  - `ITEM_KEYS = ("connect_plaid", "account_visibility", "custom_taxonomy",
    "merchant_rules")`.
  - `ensure_items(session, ctx) -> None` — idempotently seeds a pending row per
    key for `ctx.user_id`.
  - `@dataclass TurnSignals(has_linked_items: bool, household_member_count:
    int, response_had_categorized_rows: bool, user_corrected_category: bool)`.
  - `evaluate(session, ctx, signals) -> str | None` — deterministic: updates
    counters in `trigger_state` (`categorized_turns`, `corrections`,
    `nudged_this_session` bookkeeping), returns the consolidated reminder
    content when ≥1 pending item's rule fires, else `None`. Rules exactly as
    the spec table (connect_plaid → every turn while unlinked;
    account_visibility → linked ∧ members ≥ 2, once per session;
    custom_taxonomy → `categorized_turns >= 3`, once per session;
    merchant_rules → `corrections >= 1 or categorized_turns >= 10`, once per
    session).
  - `resolve_onboarding_item(item_key: str, action: str)` `@tool` — validates
    `action in ("accepted", "dismissed")` and `item_key in ITEM_KEYS`, updates
    the row for `require_request_context().user_id`, returns
    `{"item_key": …, "status": …}`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_onboarding.py
import uuid

from penny.adapters.db.models import Household, OnboardingItem, User
from penny.db import get_db
from penny.onboarding import TurnSignals, ensure_items, evaluate
from penny.tenancy.context import RequestContext


def _ctx():
    db = get_db(); db.create_schema()
    with db.session() as s:
        hh = Household(name="H"); s.add(hh); s.flush()
        u = User(household_id=hh.household_id, email="a@x.com"); s.add(u); s.flush()
        return RequestContext(user_id=u.user_id, household_id=hh.household_id)


def _signals(**kw):
    base = dict(has_linked_items=False, household_member_count=1,
                response_had_categorized_rows=False, user_corrected_category=False)
    base.update(kw)
    return TurnSignals(**base)


def test_connect_plaid_fires_every_turn_until_resolved(isolated_db):
    ctx = _ctx()
    db = get_db()
    with db.session_for(ctx) as s:
        ensure_items(s, ctx)
        first = evaluate(s, ctx, _signals())
        second = evaluate(s, ctx, _signals())
    assert first and "connect_plaid" in first
    assert second and "connect_plaid" in second   # every turn, deterministic
    with db.session_for(ctx) as s:                 # dismiss -> silence
        s.query(OnboardingItem).filter_by(item_key="connect_plaid").update(
            {"status": "dismissed"}
        )
        assert evaluate(s, ctx, _signals()) is None


def test_custom_taxonomy_fires_after_three_categorized_turns(isolated_db):
    ctx = _ctx()
    db = get_db()
    with db.session_for(ctx) as s:
        ensure_items(s, ctx)
        s.query(OnboardingItem).filter_by(item_key="connect_plaid").update(
            {"status": "accepted"}
        )
        sig = _signals(has_linked_items=True, response_had_categorized_rows=True)
        assert evaluate(s, ctx, sig) is None       # turn 1
        assert evaluate(s, ctx, sig) is None       # turn 2
        third = evaluate(s, ctx, sig)              # turn 3 -> fires
    assert third and "custom_taxonomy" in third


def test_same_state_same_output(isolated_db):
    ctx = _ctx()
    db = get_db()
    with db.session_for(ctx) as s:
        ensure_items(s, ctx)
        a = evaluate(s, ctx, _signals())
    with db.session_for(ctx) as s:
        b = evaluate(s, ctx, _signals())
    assert a.split("connect_plaid")[0] == b.split("connect_plaid")[0]  # deterministic template
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_onboarding.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'penny.onboarding'`.

- [ ] **Step 3: Write minimal implementation**

`penny/onboarding.py` implements the interfaces above. The consolidated content
is a fixed template listing each fired item with one-line guidance, ending with:
"Nudge naturally, at most once this turn, without repeating earlier phrasing;
call resolve_onboarding_item when the user accepts or declines." Counter
updates: `categorized_turns += 1` when `response_had_categorized_rows`;
`corrections += 1` when `user_corrected_category`; once-per-session items stamp
`trigger_state["last_nudged_conversation"]` and skip when it matches the
current conversation (pass the conversation id via `signals` — add field
`conversation_id: str`). Add the model + migration `018` (unique index, CHECK,
RLS). The `@tool` in `tools/onboarding.py` wraps a sync service call in
`asyncio.to_thread` and returns the dict (registry pattern per existing tools).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_onboarding.py -v` → PASS (3).
Migration chain → ends at `018`.

- [ ] **Step 5: Commit**

```bash
git add backend/penny/adapters/db/models.py backend/penny/onboarding.py \
  backend/penny/tools/onboarding.py backend/penny/tools/registry.py \
  backend/db/migrations/022_add_onboarding_items.py backend/tests/test_onboarding.py
git commit -m "feat(onboarding): items table, deterministic trigger engine, resolve tool (migration 018)"
```

---

### Task 6 (Penny): wire trigger evaluation into `/api/chat`

**Files:**
- Modify: `backend/penny/api/main.py` (chat handler)
- Test: `backend/tests/api/test_onboarding_wiring.py`

**Interfaces:**
- Consumes: Tasks 4–5; phase-2 turn context.
- Produces: in the chat handler, **individual conversations only**: build
  `TurnSignals` (linked items via a façade count for `ctx`; member count via
  `users` count; categorized/correction signals from the previous turn's
  bookkeeping — v1 computes `response_had_categorized_rows` /
  `user_corrected_category` from flags stashed on the conversation row's
  metadata by the bridge at the end of the prior turn, defaulting False),
  call `ensure_items` + `evaluate`, and when content is returned,
  `await DbReminderQueue(ctx).enqueue(chat_id, "onboarding", content)` —
  before `agent.run`, so the harness flush picks it up this same turn. Joint
  conversations skip entirely.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/api/test_onboarding_wiring.py
import uuid

from penny.api.main import _maybe_enqueue_onboarding  # extracted pure-ish helper
from penny.db import get_db
from penny.reminders import DbReminderQueue
from penny.tenancy.context import RequestContext, SessionMode
from tests.test_onboarding import _ctx  # reuse seeding


async def test_individual_conversation_enqueues(isolated_db):
    ctx = _ctx()
    await _maybe_enqueue_onboarding(ctx, conversation_id="conv-1")
    drained = await DbReminderQueue(ctx).drain("conv-1")
    assert len(drained) == 1 and drained[0].kind == "onboarding"


async def test_joint_conversation_skips(isolated_db):
    base = _ctx()
    joint = RequestContext(user_id=base.user_id, household_id=base.household_id,
                           session_mode=SessionMode.JOINT)
    await _maybe_enqueue_onboarding(joint, conversation_id="conv-2")
    assert await DbReminderQueue(base).drain("conv-2") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/api/test_onboarding_wiring.py -v`
Expected: FAIL — `ImportError: cannot import name '_maybe_enqueue_onboarding'`.

- [ ] **Step 3: Write minimal implementation**

Add `_maybe_enqueue_onboarding(ctx, *, conversation_id)` to `main.py`: return
immediately when `ctx.session_mode is SessionMode.JOINT`; otherwise open
`session_for(ctx)`, build `TurnSignals` (queries + defaults as above), run
`ensure_items` + `evaluate`, enqueue on content. Call it in the chat handler
after the turn context is built and before `build_agent`/`agent.run`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/api/test_onboarding_wiring.py -v` → PASS (2).

- [ ] **Step 5: Commit**

```bash
git add backend/penny/api/main.py backend/tests/api/test_onboarding_wiring.py
git commit -m "feat(onboarding): per-turn trigger evaluation enqueues the consolidated reminder"
```

---

### Task 7 (Penny): `connect_bank_account` tool + `POST /api/plaid/exchange`

**Files:**
- Create: `backend/penny/tools/plaid_link.py`, service in
  `backend/penny/tools/_services/plaid_link.py`
- Modify: `backend/penny/api/main.py` (exchange route),
  `backend/penny/tools/registry.py`, `backend/.env.example`
- Test: `backend/tests/test_plaid_link.py`

**Interfaces:**
- Consumes: the existing configured Plaid API client (reuse the client factory
  the sync service uses in `penny/adapters/clients` — the service functions
  below take the client as an injectable parameter with that factory as
  default); phase-1a `encrypt_token`; `PlaidItem`/`PlaidAccount` models;
  `DbReminderQueue`.
- Produces:
  - Service `create_link_token(*, user_id, client=None) -> dict` — hosted mode:
    Plaid `link_token_create` with `redirect_uri = PLAID_REDIRECT_URI`,
    `client_user_id = str(user_id)`; localhost mode
    (`PENNY_PLAID_LINK_MODE=localhost`): returns
    `{"mode": "localhost", "instructions": …}` pointing at the existing
    `connect_new_account` flow (kept for dev).
  - `@tool connect_bank_account()` — calls the service with
    `require_request_context().user_id`; returns
    `{"mode": "hosted", "link_token": …, "expiration": …}` (structured content
    → the frontend renderer).
  - Service `exchange_public_token(session, ctx, *, public_token,
    conversation_id, client=None, queue=None) -> dict` — exchanges → encrypts
    `access_token` → inserts `PlaidItem` (owner/household from ctx) +
    `PlaidAccount` rows from `accounts_get` (visibility `'private'`, owner =
    ctx.user) → triggers the existing sync service for the new item (thread
    pool, fire-and-forget) → enqueues `kind="plaid_link"` reminder:
    `"{institution} linked ({n} accounts; first sync started). Tell the user,
    and mention they can connect more accounts anytime just by asking."` →
    returns `{"item_id", "accounts": n}`.
  - Route `POST /api/plaid/exchange` (authed): body `{public_token,
    conversation_id}`; verifies conversation access (phase-2 store check) then
    calls the service; 200 with the dict.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_plaid_link.py
import uuid

from penny.reminders import DbReminderQueue
from penny.tools._services.plaid_link import exchange_public_token
from penny.db import get_db
from penny.adapters.db.models import PlaidAccount, PlaidItem
from penny.security.token_cipher import is_encrypted
from tests.test_onboarding import _ctx


class FakePlaidClient:
    def item_public_token_exchange(self, req):
        return {"access_token": "access-sandbox-xyz", "item_id": "item-test-1"}
    def accounts_get(self, req):
        return {"accounts": [
            {"account_id": "acct-1", "name": "Checking"},
            {"account_id": "acct-2", "name": "Savings"},
        ], "item": {"institution_name": "Test Bank"}}


async def test_exchange_creates_encrypted_item_private_accounts_and_reminder(
    isolated_db, monkeypatch
):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("PENNY_PLAID_TOKEN_KEY", Fernet.generate_key().decode())
    ctx = _ctx()
    db = get_db()
    with db.session_for(ctx) as s:
        result = await exchange_public_token(
            s, ctx, public_token="public-x", conversation_id="conv-1",
            client=FakePlaidClient(), sync=lambda item_id: None,
        )
    assert result["accounts"] == 2
    with db.session_for(ctx) as s:
        item = s.query(PlaidItem).filter_by(item_id="item-test-1").one()
        assert is_encrypted(item.access_token)
        accts = s.query(PlaidAccount).filter_by(item_id="item-test-1").all()
        assert {a.visibility for a in accts} == {"private"}
        assert {a.owner_user_id for a in accts} == {ctx.user_id}
    drained = await DbReminderQueue(ctx).drain("conv-1")
    assert drained and drained[0].kind == "plaid_link"
    assert "Test Bank" in drained[0].content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_plaid_link.py -v`
Expected: FAIL — `ModuleNotFoundError` on the service module.

- [ ] **Step 3: Write minimal implementation**

Implement the two service functions (client/queue/sync injectable; defaults
resolve the real Plaid client factory, `DbReminderQueue(ctx)`, and the existing
sync service), the `@tool`, and the route (route wraps the service in
`session_for(ctx)` + the conversation access check; map access errors → 404).
Document `PENNY_PLAID_LINK_MODE` + `PLAID_REDIRECT_URI` in `.env.example`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_plaid_link.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/penny/tools/plaid_link.py backend/penny/tools/_services/plaid_link.py \
  backend/penny/api/main.py backend/penny/tools/registry.py backend/.env.example \
  backend/tests/test_plaid_link.py
git commit -m "feat(plaid): hosted link-token tool + server-side exchange with success reminder"
```

---

### Task 8 (Penny frontend): inline `PlaidLinkCard` renderer

**Files:**
- Create: `frontend/src/PlaidLinkCard.tsx`
- Modify: `frontend/src/main.tsx` (register), `frontend/package.json`
  (`react-plaid-link`)
- Test: manual (sandbox Plaid).

**Interfaces:**
- Consumes: agent-ui `registerToolRenderer` (registry.tsx:14-44); tool part
  shape (`part.output` = the tool's structured content); phase-2 authed fetch.
- Produces: renderer registered for tool name `connect_bank_account`.

- [ ] **Step 1: Implement the card**

```tsx
// frontend/src/PlaidLinkCard.tsx
import { usePlaidLink } from "react-plaid-link";
import { useState } from "react";

type Output = { mode: string; link_token?: string };

export function PlaidLinkCard({ part }: { part: { state: string; output?: unknown } }) {
  const output = part.output as Output | undefined;
  const [done, setDone] = useState(false);
  const conversationId = new URLSearchParams(location.search).get("chat") ?? "default";

  const { open, ready } = usePlaidLink({
    token: output?.link_token ?? null,
    receivedRedirectUri: location.href.includes("oauth_state_id") ? location.href : undefined,
    onSuccess: async (public_token) => {
      await authedFetch("/api/plaid/exchange", {
        method: "POST",
        body: JSON.stringify({ public_token, conversation_id: conversationId }),
      });
      setDone(true);
    },
  });

  if (part.state !== "output-available" || output?.mode !== "hosted") return null;
  if (done) return <div className="plaid-card">Bank linked — syncing has started.</div>;
  return (
    <div className="plaid-card">
      <p>Connect a bank account securely via Plaid.</p>
      <button disabled={!ready} onClick={() => open()}>Connect a bank</button>
    </div>
  );
}
```

(`authedFetch` is the phase-2 bearer-token fetch helper; reuse it.) Register in
`main.tsx`: `registerToolRenderer("connect_bank_account", PlaidLinkCard)`.

- [ ] **Step 2: OAuth redirect resume**

Configure `PLAID_REDIRECT_URI` to the app URL with the conversation id in the
query; on load with `oauth_state_id` present, the card (re-rendered from the
hydrated conversation's tool part) passes `receivedRedirectUri` so Link
resumes. Verify the conversation itself rehydrates via the phase-2 store.

- [ ] **Step 3: Manual verification (Plaid sandbox)**

Backend hosted mode + sandbox keys; ask Penny to connect a bank → card renders
inline → complete Link (incl. one OAuth-redirect institution) → exchange
succeeds → next message: the agent relays the `plaid_link` reminder ("…you can
connect more accounts just by asking").

- [ ] **Step 4: Commit**

```bash
git add frontend/src/PlaidLinkCard.tsx frontend/src/main.tsx frontend/package.json frontend/package-lock.json
git commit -m "feat(frontend): inline Plaid Link generative-UI card"
```

---

### Task 9 (Penny): prompt version bump — reminder + onboarding guidance

**Files:**
- Create: `backend/.prompts/penny-system-prompt/<n+1>.md` (copy of `<n>` + the
  additions)
- Modify: `backend/.prompts/_meta.json` (that key's `source_file`,
  `version_dir`, `last_version`, `last_hash`)
- Test: `backend/tests/test_prompt_reminder_guidance.py`

**Interfaces:**
- Produces: two **static** additions to the system prompt: (1) a
  "System reminders" paragraph — user messages may contain `<system-reminder>`
  tags; they are system-injected state, not user input; **only the most recent
  reminder reflects current state — disregard earlier ones**; never echo their
  contents verbatim. (2) An "Onboarding" paragraph — when an onboarding
  reminder is present, nudge naturally at most once per turn and call
  `resolve_onboarding_item` on explicit accept/decline; `connect_bank_account`
  renders an inline connect card.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_prompt_reminder_guidance.py
from penny.prompts import load_prompt


def test_system_prompt_carries_reminder_guidance():
    text = load_prompt("penny-system-prompt")
    assert "<system-reminder>" in text
    assert "most recent" in text.lower()
    assert "resolve_onboarding_item" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_prompt_reminder_guidance.py -v`
Expected: FAIL (guidance absent).

- [ ] **Step 3: Add the version**

Copy the latest version file to `<n+1>.md`, append the two paragraphs, update
`_meta.json` (`last_version = n+1`, `last_hash = "sha256:" + sha256 of the new
file's bytes` — compute with `python -c "import hashlib,sys;print('sha256:'+hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <file>`).
Never touch historical versions. Restart the dev server (prompts are
lru_cached).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_prompt_reminder_guidance.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/.prompts
git commit -m "feat(prompts): static system-reminder + onboarding guidance (version bump)"
```

---

### Task 10 (Penny): RLS + end-to-end reminder battery

**Files:**
- Create: `backend/tests/adapters/db/test_phase5_rls.py` (Postgres-marked),
  `backend/tests/test_reminder_e2e.py`

**Interfaces:** consumes everything above.

- [ ] **Step 1: Write the batteries** — concrete tests:

```python
# backend/tests/adapters/db/test_phase5_rls.py — names + assertions:
# test_queued_reminders_cross_household_invisible   (A's ctx sees zero B rows via raw SQL)
# test_onboarding_items_owner_scoped                (spouse cannot read the other's items)
# test_with_check_blocks_foreign_household_reminder (INSERT with B's household_id from A's ctx rejected)
```

```python
# backend/tests/test_reminder_e2e.py — the full loop on SQLite:
# test_enqueued_reminder_reaches_the_llm_turn:
#   enqueue via DbReminderQueue -> build agent via agent_factory with a scripted
#   model -> run one turn -> assert the session's recorded user message contains
#   the <system-reminder kind="onboarding"> block and the queue is empty after.
# test_stored_conversation_never_contains_reminder_text:
#   run the /api/chat persistence path -> assert the web-store user message text
#   equals exactly what the client sent (reminders live only in the harness turn).
```

- [ ] **Step 2–3:** Run (`POSTGRES_TEST_URL` for the RLS file), implement/fix
  until green; full gate green.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/adapters/db/test_phase5_rls.py backend/tests/test_reminder_e2e.py
git commit -m "test(phase5): RLS on reminder/onboarding tables + reminder e2e battery"
```

---

## Browser E2E Validation (Playwright)

Automated headless Playwright specs under `frontend/e2e/`, reusing the shared
harness (phase 1a) and `signInAsTestUser` (phase 2). Plaid Link runs in
**sandbox**; because the Plaid-hosted popup cannot be driven headlessly, these
specs assert up to the inline card render + a **stubbed** `/api/plaid/exchange`,
and the full sandbox link-through stays a manual step (Task 8, Step 3).

### Task 11 (Penny frontend): onboarding nudge E2E

**Files:**
- Create: `frontend/e2e/onboarding-nudge.spec.ts`

**Interfaces:**
- Consumes: the phase-1a Playwright harness (base URL + fixtures) and
  `signInAsTestUser` (phase 2); a scripted/sandbox backend where the signed-in
  test user has **no linked banks**; a stub for `POST /api/plaid/exchange`
  (`page.route`) returning a success body so the follow-up turn can proceed
  without the Plaid popup.
- Produces: a spec proving the first agent turn nudges to connect a bank, the
  inline `connect_bank_account` card renders, and the nudge stops after a
  stubbed successful exchange.

- [ ] **Step 1: Write the failing spec**

Concrete flow/assertions (prose, not full code):
- `test.beforeEach`: `await signInAsTestUser(page)` (fresh user, zero linked
  items), then navigate to the chat route.
- Send a first message (e.g. "hi") via the composer input and submit.
- Assert the agent's first response contains a connect-a-bank nudge — locate the
  latest assistant message and expect its text to match `/connect .*bank/i`.
- Assert the inline card renders: the tool-renderer output for
  `connect_bank_account` is visible — expect a `[data-tool="connect_bank_account"]`
  (or the `.plaid-card` container) to be visible with its "Connect a bank" button.
- Register `await page.route("**/api/plaid/exchange", …)` to fulfill with a 200
  success JSON, then drive the stubbed success path (invoke the card's
  `onSuccess` via the exposed test hook rather than opening the real popup).
- Send a follow-up message; assert a later assistant message confirms the link
  (text matches `/linked|connected/i`) and that **no** new connect nudge or new
  `connect_bank_account` card appears after the confirmation.

- [ ] **Step 2: Run spec to verify it fails**

Run: `cd frontend && npx playwright test e2e/onboarding-nudge.spec.ts`
Expected: FAIL — spec/selectors not yet present (or nudge/card wiring absent).

- [ ] **Step 3: Make it pass**

Ensure the renderer registration (Task 8) and the nudge wiring (Tasks 5–6,9) are
in place; adjust selectors/test hooks so the assertions hold against the
sandbox/scripted backend.

- [ ] **Step 4: Run spec to verify it passes**

Run: `cd frontend && npx playwright test e2e/onboarding-nudge.spec.ts` → PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/e2e/onboarding-nudge.spec.ts
git commit -m "test(e2e): onboarding nudge renders connect card and stops after link"
```

---

### Task 12 (Penny frontend): Plaid card E2E

**Files:**
- Create: `frontend/e2e/plaid-card.spec.ts`

**Interfaces:**
- Consumes: the phase-1a Playwright harness and `signInAsTestUser` (phase 2); a
  sandbox/scripted backend whose `connect_bank_account` tool output carries a
  `mode: "hosted"` + `link_token`.
- Produces: a spec proving the inline Plaid Link card renders from the tool
  output and enables its "Connect a bank" button once the link token is present.

- [ ] **Step 1: Write the failing spec**

Concrete flow/assertions (prose, not full code):
- `test.beforeEach`: `await signInAsTestUser(page)`, navigate to chat.
- Prompt the agent to connect a bank so it emits the `connect_bank_account`
  tool part (or seed a conversation whose latest turn contains that tool part).
- Assert the card container (`.plaid-card` / `[data-tool="connect_bank_account"]`)
  is visible and shows the "Connect a bank" copy.
- Assert the button is **enabled** once the link token is present — expect
  `getByRole("button", { name: /connect a bank/i })` to be enabled (Plaid
  `ready === true` with the token). A comment notes the Plaid popup itself is a
  manual sandbox step (Task 8, Step 3), so the spec stops at button-enabled and
  does not click through the hosted Link flow.

- [ ] **Step 2: Run spec to verify it fails**

Run: `cd frontend && npx playwright test e2e/plaid-card.spec.ts`
Expected: FAIL — card/selectors not yet present.

- [ ] **Step 3: Make it pass**

Ensure `PlaidLinkCard` (Task 8) renders for `mode: "hosted"` with a token and
enables the button on `ready`; adjust selectors to match.

- [ ] **Step 4: Run spec to verify it passes**

Run: `cd frontend && npx playwright test e2e/plaid-card.spec.ts` → PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/e2e/plaid-card.spec.ts
git commit -m "test(e2e): inline Plaid Link card renders and enables connect button"
```

---

## Modularization

**Principle:** carve each unit at a clean boundary so it could be lifted into a
standalone package with no Penny-specific coupling in its core. This phase is
already largely modular *by construction* — three of the four units land in
external packages (agent-harness, agent-ui) as general-purpose subsystems.
Guard against premature abstraction: keep concrete item keys, Plaid specifics,
and DB wiring out of the reusable cores.

- **System-reminder subsystem (the exemplar).** `ReminderQueue` +
  `wrap_system_reminder` + the run-loop drain (Tasks 1–2) are built *into*
  agent-harness (`agent_harness/extras/reminders.py` + `core/loop.py`), not
  Penny. This is the model the rest of the plan follows: a product-agnostic
  subsystem that any agent-harness host inherits for free.
  - **Seam:** the `ReminderQueue` Protocol (`enqueue`/`drain`) + the frozen
    `Reminder(kind, content)` value. Hosts supply any implementation
    (`InMemoryReminderQueue` ships in-package; Penny's `DbReminderQueue` is one
    adapter behind the same Protocol).
  - **Keep OUT of the core:** persistence choices, tenancy/`RequestContext`,
    conversation-id semantics, and any notion of "onboarding." The core only
    knows sessions, kinds, and text.
  - *Portable to any project that needs backend-enqueued state flushed into the
    next model turn without mutating the (cache-stable) system prompt.*

- **agent-ui reminder-hiding.** `stripSystemReminders` (Task 3) is a first-class
  library change in agent-ui (`packages/agent-ui/src/reminders.ts`, exported
  from `index.ts`), not a Penny-side render hack.
  - **Seam:** a pure `string -> string` function plus the `Message.tsx`
    user-branch integration; exported for direct reuse.
  - **Keep OUT of the core:** any Penny-specific reminder `kind` values or
    copy — it strips the generic `<system-reminder …>` span shape only.
  - *Portable to any agent-ui host that injects system-reminder spans and must
    keep them model-facing (never rendered).*

- **Generative-UI inline-card pattern.** The Plaid Link card (Tasks 7–8) is a
  concrete instance of a reusable pattern: a `@tool` returns structured content
  → a renderer registered via agent-ui's `registerToolRenderer(toolName, …)`
  draws it inline, keyed on `part.state`/`part.output`.
  - **Seam:** tool structured-content shape ⟷ renderer registration by tool
    name. The pattern is the contract, independent of what the card does.
  - **Keep OUT of the core:** Plaid/`react-plaid-link` specifics live entirely
    inside `PlaidLinkCard`; the registry mechanism knows nothing about banking.
  - *Portable to any project that wants a tool call to render its own inline UI
    widget instead of plain text.*

- **Onboarding trigger-engine (more product-specific — split the core).** The
  engine (Task 5) is Penny-flavored, so structure it as a generic
  state-machine / trigger-evaluation core parameterized over an item set,
  kept separate from Penny's concrete `ITEM_KEYS` and rule table.
  - **Seam:** `evaluate(state, signals) -> reminder | None` over a declarative
    rule set + a `{pending, accepted, dismissed}` per-item state machine. The
    signals struct and rule predicates are injected, not baked in.
  - **Keep OUT of the core:** Penny's specific item keys (`connect_plaid`,
    `account_visibility`, …), their copy, the SQLAlchemy models, and
    `RequestContext`. Those live in a thin Penny layer that instantiates the
    engine with its own item set.
  - *Portable to any project that needs deterministic, per-turn "nudge when
    condition X holds, once/ every turn, until resolved" progressive
    onboarding — with a different item set.*

## Self-Review

**Spec coverage:** harness `ReminderQueue` + flush → Tasks 1–2; first-class
agent-ui hiding → Task 3; DB queue keyed by conversation → Task 4;
`onboarding_items` (pending/accepted/dismissed, deterministic rules,
consolidated override reminder, individual-only) → Tasks 5–6; Plaid Link
generative UI + hosted exchange + success reminder + localhost dev mode →
Tasks 7–8; static cache-safe prompt guidance → Task 9; RLS + e2e → Task 10.
Spec's "exchange validates conversation access" → Task 7 route. Manual sandbox
verification incl. OAuth redirect → Task 8.

**Placeholder scan:** Task 2's test notes an adapt-to-fixture fallback (the
harness repo's exact fixture name is unknown from here — the instruction names
the concrete pattern to mirror); Task 10 specifies batteries by exact
name + assertion (established pattern). All other steps carry complete code.

**Type consistency:** `Reminder(kind, content)`, `wrap_system_reminder`,
`ReminderQueue.enqueue(session_id, kind, content, *, override)` /
`drain(session_id)`, `DbReminderQueue(ctx)`, `TurnSignals`, `ensure_items`,
`evaluate(session, ctx, signals) -> str | None`,
`resolve_onboarding_item(item_key, action)`, `create_link_token`,
`exchange_public_token(session, ctx, *, public_token, conversation_id, client,
sync)` consistent across tasks; phase-1a/2 names match their plans.

## Execution Handoff

Execute after phases 1a/1b/2/4 (needs tenancy, token cipher, auth context,
conversation store). Order: Tasks 1–2 (harness) → 3 (agent-ui) → 4–10 (Penny).
Harness/agent-ui commits land in their own repos (editable deps pick them up;
restart uvicorn). Postgres task needs `POSTGRES_TEST_URL`; Task 8 needs Plaid
sandbox keys. Subagent-driven execution recommended.
