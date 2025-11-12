## Taxonomy Generator

Build and store a versioned Personal Finance taxonomy using a merged prompt template and Promptorium-backed storage.

### Prerequisites
- Python 3.12+
- `OPENAI_API_KEY` environment variable set
- Promptorium integration wired to `services.taxonomy_generator.load_prompt_text`, `store_generated`, and `load_latest_generated_text`

Note: In this repository, Promptorium integration is left as stubs. Provide concrete implementations or mocks in your environment.

### Input YAML
Default path: `config/taxonomy.yaml`. You can supply your own via `--yaml`.

### Usage

```bash
python -m scripts.build_taxonomy --yaml config/taxonomy.yaml --model gpt-4o
```

Behavior:
- Loads merged template from Promptorium key `taxonomy-generator` (falls back to an internal default if unavailable)
- Computes `input_yaml_sha256` and `prompt_sha256`
- Skips regeneration if the latest stored document’s front matter matches both hashes
- Otherwise, calls OpenAI to generate Markdown and stores the result under Promptorium key `taxonomy-personal-finance`

### Development
- Linting: Ruff (see `ruff.toml` and `docs/ruff-guide.md`)
- Types: mypy strict (see `mypy.ini` and `docs/mypy-guide.md`)
- Dead code: see `docs/deadcode-guide.md` and `[tool.deadcode]` in `pyproject.toml`


