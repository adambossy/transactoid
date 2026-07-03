---
id: phase-5-reminders
label: System reminders
parent: phase-5
sections: [mechanism, cache-safety, hiding]
crosslinks: [phase-5-engine]
---

# System reminders

A modular agent-harness subsystem, modeled on Claude Code's mechanism: backend-enqueued state delivered to the model inside the next user message, invisible to the person chatting.

## Requirements

- Behind-the-scenes prompts about my setup never clutter my chat — I only ever see Penny's natural replies.
- Penny always acts on my current situation, never on a stale, out-of-date nudge.
- Even when I reopen an old conversation, none of the hidden setup machinery shows up in the transcript.

## mechanism — Enqueue, override, flush

A `ReminderQueue` holds reminders keyed by session. Enqueueing a reminder of a kind **replaces** any queued reminder of the same kind by default, so only the most recent state ever flushes. When the run loop turns the user's prompt into a message, it drains the queue and appends each reminder as an extra text block wrapped in a `system-reminder` XML tag on that same message. Penny supplies a database-backed queue keyed by conversation, so an enqueue from an HTTP handler (like the Plaid exchange endpoint) survives until the next agent run. The [onboarding engine](engine.html) is the first producer.

## cache-safety — Why not the system prompt

Injecting state into the system prompt would break prompt caching and fork the prompt per user state. Instead the system prompt gains one **static** paragraph: reminders are system-injected state, not user input, and **only the most recent reminder reflects current state — earlier ones are stale by definition**. The prompt never changes per turn; the state rides in the conversation.

## hiding — First-class hiding in the UI

The agent-ui library strips `system-reminder` spans from rendered user messages as a library guarantee — an exported `stripSystemReminders` helper plus filtering in the message component — so even a conversation hydrated from storage renders clean. Only the model ever sees the reminder text.
