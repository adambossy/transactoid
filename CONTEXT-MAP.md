# Context Map

## Contexts

- [Agent core (`backend/`)](./backend/CONTEXT.md) — the Penny agent and the
  finance domain: sync, categorization, itemization, tenancy, workspace,
  billing
- Frontend (`frontend/`) — the chat web app (no `CONTEXT.md` yet; created
  lazily when its first term is resolved)
- Protocol lib (`lib/`) — the sandbox wire protocol shared by backend and
  sandbox (no `CONTEXT.md` yet)
- Sandbox (`sandbox/`) — the Modal runner shell that executes agent turns
  (no `CONTEXT.md` yet)

## Relationships

- **Frontend → Backend**: the chat UI drives the backend's streaming chat API
  (Vercel AI SDK UI message-stream protocol); the frontend holds no finance
  concepts of its own
- **Backend → Lib, Sandbox → Lib**: backend and sandbox share only the wire
  protocol in `lib/`; the sandbox never sees the finance stack
- **Backend → Sandbox**: the backend spawns sandbox runners to execute agent
  turns in isolation
