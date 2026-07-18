# Issue tracker: Beads

Issues for this repo live in Beads. The data is checked into the repo under
`.beads/` — `issues.jsonl` is the git-synced source of truth, `beads.db` the
local SQLite working copy. Use the `bd` CLI for all operations (`bd --help`
lists commands). The issue prefix is `fly-`. Never hand-edit `.beads/` files;
sync to git happens automatically via the daemon + JSONL export.

## Conventions

- **Create an issue**: `bd create "Title" -t bug|feature|task|epic|chore -p 0-4 -d "..."`.
  Use `--body-file -` with a heredoc for long bodies; `-l label1,label2` for labels.
- **Read an issue**: `bd show fly-<n>`; comments via `bd comments fly-<n>`.
- **List issues**: `bd list` with `--label`, `-a/--assignee`, `-p`, `--all`
  (include closed), `--json` for machine-readable output.
- **Search**: `bd search "query"`.
- **Comment**: `bd comments add fly-<n> "..."` (or `-f file`).
- **Apply / remove labels**: `bd update fly-<n> --add-label x --remove-label y`.
- **Update fields**: `bd update fly-<n> -s <status> -a <assignee> --title "..."`.
- **Close / reopen**: `bd close fly-<n>` / `bd reopen fly-<n>`.
- **Dependencies are first-class**: `bd dep add <blocked> <blocker>`,
  `bd dep tree fly-<n>`; `bd ready` lists open issues with no blockers.

## Pull requests as a triage surface

**PRs as a request surface: no.** (Beads is the tracker; GitHub PRs are not
read into the triage queue.)

## When a skill says "publish to the issue tracker"

Create a beads issue with `bd create`.

## When a skill says "fetch the relevant ticket"

Run `bd show <id>` (and `bd comments <id>` for the conversation).

## Wayfinding operations

Used by `/wayfinder`. The **map** is an epic with **child** issues as tickets.

- **Map**: `bd create "<effort>" -t epic -l wayfinder:map`, holding the
  Notes / Decisions-so-far / Fog body in its description.
- **Child ticket**: `bd create "<question>" --parent <map-id> -l wayfinder:<type>`
  (`research`/`prototype`/`grilling`/`task`).
- **Blocking**: beads-native dependencies — `bd dep add <child> <blocker>`.
  A ticket is unblocked when every blocker is closed.
- **Frontier query**: `bd ready` intersected with the map's children
  (`bd list --parent <map-id>`); drop assigned tickets; highest priority wins.
- **Claim**: `bd update <n> --claim` (atomic: sets assignee + in_progress,
  fails if already claimed) — the session's first write.
- **Resolve**: `bd comments add <n> "<answer>"`, then `bd close <n>`, then
  append a context pointer to the map's Decisions-so-far.
