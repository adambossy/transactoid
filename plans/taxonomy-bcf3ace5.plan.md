<!-- bcf3ace5-f4ee-4c83-a94a-86a26496a1da b056ca1d-cd55-4a01-af08-89e4a2e04a8d -->
# Taxonomy Generation with Promptorium

### Overview

Build a small generator that:

- Merges the system and user prompts into a single template with `{input_yaml}`.
- Uses Promptorium to store: (a) the merged prompt template, and (b) the generated taxonomy as the single official versioned artifact.
- Skips regeneration if the input YAML or prompt template hasn’t changed by comparing embedded metadata in the last stored version.
- Requires no external build metadata files; all metadata lives in the stored Markdown front matter.

### Key Decisions

- Single prompt key: `taxonomy-generator` (merged template).
- Single official version number: `taxonomy-rules` (generated taxonomy). Only this key’s version is considered the taxonomy version.
- Metadata location: YAML front matter in the generated Markdown.
- Input YAML: `config/taxonomy.yaml`.
- OpenAI model: configurable via CLI flag or env; default `gpt-4o` (override as needed).
- Promptorium integration: Use library write/update APIs; if missing, fallback to invoking the CLI.

### Files to Add/Change

- `config/taxonomy.yaml` (source categories)
- `services/taxonomy_generator.py` (library: hashing, prompt load, OpenAI call, store result)
- `scripts/build_taxonomy.py` (CLI entrypoint)
- `tests/services/test_taxonomy_generator.py` (unit tests; mock OpenAI + Promptorium)

### Merged Prompt Template (stored in `taxonomy-generator`)

Use one template that embeds the previous system guidance inside the user prompt, with `{input_yaml}` placeholder:

```md
You are an expert taxonomist and information architect. You will be given:
A list of parent categories and child categories (in YAML form)
Optionally, short rules or hints for each category
Your goal is to write a comprehensive, human-readable taxonomy document that mirrors the quality, structure, and detail of the Personal Finance Transaction Taxonomy v1 shown earlier.

---

You are an expert taxonomy architect and information designer.

You will be given a YAML definition containing parent and child categories for a specific domain.
Your job is to produce a comprehensive two-level taxonomy document, modeled after the “Proposed 2-level Transaction Category Taxonomy (v1)” example.

### Input YAML
{input_yaml}

### Domain
Personal Finance Transactions

### Objectives
[... keep the remainder of the previous user prompt spec here verbatim ...]
```

### Generator Behavior

- Load merged template text from Promptorium key `taxonomy-generator`.
- Read YAML from `config/taxonomy.yaml` and compute `input_yaml_sha256` over a normalized serialization (sorted keys, trimmed whitespace).
- Compute `prompt_sha256` over the merged template.
- Load the latest `taxonomy-rules` content (if any); parse its front matter (`---` fenced YAML) for `input_yaml_sha256` and `prompt_sha256`.
- If both hashes match current values, exit with a no-op.
- Otherwise, call OpenAI with the merged prompt (substitute `{input_yaml}`), capture Markdown output, and wrap it with front matter:
  ```yaml
  ---
  taxonomy_version: <promptorium assigned version once stored>
  input_yaml_sha256: <sha256>
  prompt_sha256: <sha256>
  model: <model>
  created_at: <iso8601>
  ---
  ```


followed by the generated Markdown.

- Store via Promptorium under key `taxonomy-rules` (this increments the single official version number).

### CLI Usage

- `python -m scripts.build_taxonomy --yaml config/taxonomy.yaml --model gpt-4o`.
- Respects `OPENAI_API_KEY`.

### Promptorium Integration

- On bootstrap, ensure `taxonomy-generator` contains the merged template using Promptorium’s write/update function. If library write API is unavailable, call the CLI `prompts update taxonomy-generator --file <template.md>` programmatically.
- Use `load_prompt(key)` to retrieve latest content when generating.
- Use the write/update function to store `taxonomy-rules` output (no manual versioning—Promptorium increments automatically).

### Tests

- Mock OpenAI client to return deterministic Markdown.
- Mock Promptorium load/update interactions.
- Verify skip-when-unchanged behavior (same hashes → no write).
- Verify write-on-change behavior for both YAML and prompt changes.
- Verify front matter contains required keys and values.

### Linting & Type Safety

- Use existing project toolchain:
  - `ruff` for lint/format
  - `mypy` for typing
  - dead code detector per `docs/deadcode-guide.md`
- Add type hints and avoid unused code.

### Minimal Code Contracts

- `services/taxonomy_generator.py`
  - `load_prompt_text(key: str) -> str`
  - `read_yaml_text(path: str) -> str`
  - `compute_sha256(text: str) -> str`
  - `should_regenerate(latest_doc: str|None, input_hash: str, prompt_hash: str) -> bool`
  - `render_prompt(merged_template: str, input_yaml: str) -> str`
  - `call_openai(markdown_prompt: str, model: str) -> str`
  - `wrap_with_front_matter(body_md: str, meta: dict) -> str`
  - `store_generated(markdown: str) -> None`

- `scripts/build_taxonomy.py`
  - Parses args; orchestrates the above.

### Reference

- Promptorium repo: [adambossy/promptorium](https://github.com/adambossy/promptorium)

### To-dos

- [ ] Create merged prompt template and store under Promptorium key taxonomy-generator
- [ ] Implement library functions in services/taxonomy_generator.py
- [ ] Use Promptorium API to write taxonomy-rules output
- [ ] Implement hash-based no-op skip logic via front matter metadata
- [ ] Add scripts/build_taxonomy.py CLI to run generation
- [ ] Add unit tests for hashing, skip logic, Promptorium/OpenAI mocks
- [ ] Run ruff, mypy, dead code detector and fix issues
- [ ] Document usage in README with CLI example and environment vars