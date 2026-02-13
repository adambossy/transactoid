# Agent Memory Foundation + Merchant Rules (Fresh Branch Plan)

## Summary
Implement a new memory foundation for the agent, with merchant rules as the first memory-backed feature.

Key outcomes:
- Create a persistent `memory/` directory for agent knowledge.
- Store merchant categorization rules in `memory/merchant-rules.md`.
- Inject memory into the system prompt so the agent can use accumulated context.
- Keep categorizer support for merchant-rule outcomes (`rule_matched`, `rule_name`) and auto-verify on rule match.
- Add a built-in skill that teaches the agent how to edit merchant rules via shell commands (read/append/insert/replace).

## Goals
1. Establish `memory/` as durable agent memory across sessions.
2. Enable simple, human-editable merchant rule authoring.
3. Ensure rules are concise enough for prompt injection.
4. Support iterative rule maintenance using shell-based file edits.

## Scope
- In scope:
  - `memory/` structure and initial files
  - Merchant rule format and examples
  - System prompt memory injection
  - Categorizer integration with `memory/merchant-rules.md`
  - Built-in skill for merchant-rule editing
  - Tests covering memory injection and rule behavior
- Out of scope:
  - Memory token-budgeting/capping
  - Automatic taxonomy-driven rewrites of rules
  - Additional memory domains beyond merchant rules

## Architecture

### Memory Storage
Create repository-level memory files:
- `memory/index.md`: memory manifest and conventions
- `memory/merchant-rules.md`: merchant descriptor → taxonomy category rules

### Prompt Integration
- System prompt includes assembled memory via `{{AGENT_MEMORY}}`.
- Categorizer prompt includes merchant rules via `{{MERCHANT_RULES}}` sourced from `memory/merchant-rules.md`.

### Rule Matching Semantics
When a rule is applied by the model:
- include `rule_matched`
- include `rule_name`
- set `is_verified=True`

## Rule Format (V1)
Use concise markdown blocks:

```md
## Rule: <short_name>
- category: `<taxonomy.key>`
- patterns: `<pattern_1>`, `<pattern_2>`, `<pattern_3>`
- description: <one short disambiguating sentence>
```

Constraints:
- One category per rule.
- `patterns` are fuzzy clues for `merchant_descriptor`, not exact-only.
- Keep each rule compact and high-signal.

## File Plan

### New files
1. `memory/index.md`
- Purpose of memory
- File map
- Editing conventions

2. `memory/merchant-rules.md`
- Rule format instructions
- 2-3 seed example rules

3. `src/transactoid/skills/edit-merchant-rules-memory/SKILL.md`
- Skill purpose
- Required inputs (`rule_name`, `category_key`, `patterns`, `description`)
- Shell editing workflow (append/insert/replace)
- Validation checklist (taxonomy key validity, concise output, confirm edit)

### Modified files
1. `prompts/agent-loop.md`
- Add memory section and `{{AGENT_MEMORY}}` placeholder.

2. `src/transactoid/orchestrators/transactoid.py`
- Extend prompt rendering to inject assembled memory content into `{{AGENT_MEMORY}}`.
- Memory assembly behavior:
  - read `memory/index.md` first if present
  - then read other `memory/*.md` files in deterministic sorted order
  - inject empty string when files are absent

3. `prompts/categorize-transactions.md` (or active prompt version file)
- Ensure `{{MERCHANT_RULES}}` placeholder and concise instructions for rule precedence and output fields.

4. `src/transactoid/tools/categorize/categorizer_tool.py`
- Read merchant rules from `memory/merchant-rules.md`.
- Inject rules into categorization prompt.
- Ensure parsed response fields map to:
  - `rule_matched`
  - `rule_name`
  - `is_verified = (rule_matched is True)`

## Implementation Steps
1. Create `memory/` and seed markdown files.
2. Add system prompt placeholder and renderer injection path.
3. Wire categorizer merchant-rules source to `memory/merchant-rules.md`.
4. Add built-in skill for shell-based merchant-rule editing.
5. Add/update tests.
6. Run full verification suite.

## Tests and Scenarios

### Unit tests
1. Memory assembly:
- With both files present, assembled text contains `index` then sorted section files.
- With missing files, returns empty string safely.

2. System prompt rendering:
- `{{AGENT_MEMORY}}` replaced correctly.
- No crash when memory files are absent.

3. Categorizer prompt rendering:
- `{{MERCHANT_RULES}}` replaced with `memory/merchant-rules.md` content.
- Missing rules file yields empty replacement.

4. Rule behavior mapping:
- Response with `rule_matched=true` and `rule_name` sets `is_verified=True`.
- Response without rule match keeps `is_verified=False`.

5. Skill artifact:
- `src/transactoid/skills/edit-merchant-rules-memory/SKILL.md` exists and documents edit operations + validation.

### Integration scenario
- Add a rule in `memory/merchant-rules.md`.
- Run categorization on matching descriptor sample.
- Confirm `rule_matched`, `rule_name`, and verified persistence behavior.

## Acceptance Criteria
- `memory/` exists with index + merchant rules file.
- System prompt receives injected memory content.
- Categorizer reads merchant rules from memory and injects them into prompt.
- Rule match metadata and auto-verify behavior works end-to-end.
- Built-in skill exists and instructs shell-based arbitrary file edits.
- Lint/type/test/deadcode checks run and pass project standards (aside from unrelated known failures if any).

## Assumptions
- Memory is repo-backed and intended to persist through agent lifecycle.
- V1 has no prompt-size cap for injected memory.
- Shell-based memory edits are allowed operationally.
- Taxonomy key validation is required before adding or updating rules.
