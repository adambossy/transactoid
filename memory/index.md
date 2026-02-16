# Memory Index

Generated with:

```bash
tree --noreport memory/
```

```text
memory/
|-- README.md
|-- budget.md
|-- index.md
|-- merchant-rules.md
`-- tax-returns/
    `-- 2026.md.example
```

## Annotations

- `memory/`: Root directory for persistent agent memory files.
- `memory/README.md`: Human-oriented documentation for memory purpose, conventions, and loading model.
- `memory/budget.md`: Optional budget template; copy and adapt when budget context is needed.
- `memory/index.md`: Tree-based inventory of `memory/` contents with one-line descriptions.
- `memory/merchant-rules.md`: Merchant-to-category mapping rules used for categorization guidance.
- `memory/tax-returns/`: Local-only tax return context files.
- `memory/tax-returns/2026.md.example`: Tracked template file; excluded from prompt injection.

## Tax Returns Directory

Use `memory/tax-returns/` for private tax-return context.

- `YYYY.md` is a convention, not a requirement.
- Tax-return file contents are optional and loaded on demand by the agent.
- Local tax-return file paths are surfaced in a runtime inventory block in this index.
- Files ending with `.example` are excluded from prompt assembly.
- Only `memory/tax-returns/2026.md.example` is tracked in git; other files in this directory are local-only.
