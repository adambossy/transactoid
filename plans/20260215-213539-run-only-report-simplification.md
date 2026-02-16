# Simplify Reporting Around `transactoid run` + Prompt Keys (No Report Command/Pipeline)

## Summary
Remove the dedicated `transactoid report` command and report pipeline code. Reporting is initiated only through `transactoid run --prompt-key ...` using three preset prompts:

- `report-weekly`
- `report-monthly`
- `report-annual`

HTML rendering is no longer done by Python renderer code. Instead, report prompts direct the agent to use a skills-file rendering guide and write HTML via `execute_shell_command`. Email sending is driven by existing `--email` behavior only.

## Public API / Interface Changes

1. CLI
- Remove `transactoid report` command from `src/transactoid/ui/cli.py`.
- Keep `transactoid run` as the only reporting entrypoint.
- Do not add `--send-email`.
- Do not add `--email-config`.
- Remove `--month` from `run`.
- Keep `--email` as the explicit CLI email trigger.

2. Prompt keys
- Add:
  - `report-weekly`
  - `report-monthly`
  - `report-annual`
- Stop using `spending-report` for reporting flows.

3. Config path
- Rename `configs/report.yaml` to `configs/email.yaml`.
- Code reads `configs/email.yaml` by default (hardcoded internal default, no CLI flag).

4. Renderer
- Delete `src/transactoid/jobs/report/html_renderer.py`.
- Move `prompts/render-report-html.md` content into a skill file under `src/transactoid/skills/.../SKILL.md`.
- Report prompts explicitly instruct agent to consult that skill and generate/write HTML.

## Implementation Details

1. Remove report command and helpers
- Delete `report_cmd`, `_report_impl`, and report-only config helper paths in `src/transactoid/ui/cli.py`.
- Update CLI help/examples to show report flows via `run --prompt-key report-*`.

2. Remove pipeline abstraction
- Delete `src/transactoid/services/agent_run/pipeline.py`.
- Remove `OutputPipeline` exports/imports/usages.
- Remove tests tied to pipeline behavior and replace with run/report flow tests.

3. Remove report job modules
- Remove `src/transactoid/jobs/report/runner.py`.
- Remove `src/transactoid/jobs/report/__init__.py` exports tied to runner/renderer.
- Keep/move email service into non-report-specific location (recommended: `src/transactoid/services/email_service.py` or `src/transactoid/services/agent_run/email_service.py`) and update imports.

4. Prompt migration
- Create prompt sources:
  - `prompts/report-weekly.md`
  - `prompts/report-monthly.md`
  - `prompts/report-annual.md`
- Add corresponding versioned prompt files under `src/transactoid/prompts/<key>/<key>-1.md`.
- Each prompt mirrors existing `spending-report` structure but timeframe-specific.
- Each prompt includes explicit instruction:
  - produce markdown report in final response,
  - generate HTML using the report-html skill instructions,
  - write HTML to a deterministic file path using `execute_shell_command`.

5. Skill migration for HTML guidance
- Add new built-in skill, e.g. `src/transactoid/skills/render-report-html/SKILL.md`.
- Move/adapt `prompts/render-report-html.md` guidance into this skill.
- Update wording so it is tool- and workflow-oriented for agent execution.
- Remove `prompts/render-report-html.md` and corresponding `src/transactoid/prompts/render-report-html/*` usage.

6. Email behavior in `run`
- When `--email` recipients are provided:
  - send email after run completion using markdown output as text body,
  - load default sender/subject/error-notification settings from `configs/email.yaml`,
  - if HTML file path is standardized by prompt, read that file and use as HTML body when present.
- If `--email` is not provided:
  - no forced CLI email send.
- Agent may still send email during run if prompted and tooling permits (separate from CLI post-run send).

7. Config migration
- Rename `configs/report.yaml` to `configs/email.yaml`.
- Keep only email-related schema and values.
- Update all references/docs/tests accordingly.

8. Documentation updates
- Update `README.md` examples from `transactoid report` / `spending-report` to `transactoid run --prompt-key report-*`.
- Document expected HTML output location convention used by prompts/agent.

## Deterministic Output Convention

1. HTML file path (for all report prompts)
- Standardize to one path pattern, e.g. `.transactoid/reports/<prompt-key>-latest.html`.
- Prompt instructions must require writing exactly this path.
- CLI email send path checks this path to attach HTML body when emailing.

2. Markdown output
- Final agent text remains markdown report content and is used for terminal output and text email body.

## Tests and Scenarios

1. CLI command surface
- `transactoid report` is absent.
- `run` no longer exposes `--month`.
- `run --prompt-key report-monthly` works.

2. Prompt loading
- `load_prompt("report-weekly")`, `load_prompt("report-monthly")`, `load_prompt("report-annual")` resolve.
- No reporting codepath depends on `spending-report` or `render-report-html` prompt keys.

3. HTML renderer removal
- No imports reference `html_renderer.py`.
- No tests reference removed renderer/pipeline modules.

4. Email flow via `--email`
- With `--email`, CLI sends email using defaults from `configs/email.yaml`.
- If standardized HTML file exists, email uses it as HTML body.
- If missing, fallback behavior is explicit and tested (text-only or markdown-as-html fallback, chosen in implementation spec comments).

5. Skill-guided HTML generation
- Prompt content asserts skill usage + file write instruction.
- Integration test verifies agent/tool output contract path handling logic (mocked tool execution).

6. Full verification gates
- `uv run ruff check .`
- `uv run ruff format .`
- `uv run mypy --config-file mypy.ini .`
- `uv run deadcode .`
- `uv run pytest -q`

## Assumptions and Defaults

- Default email config path is `configs/email.yaml`.
- No new email/config CLI flags are introduced.
- `--email` is the only CLI-level explicit trigger for post-run email.
- HTML is agent-generated and file-written through tool use, not Python post-processing.
- Reporting is prompt-driven with three explicit timeframe prompt keys.
