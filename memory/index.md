# Memory Index

Generated with:
```bash
tree --noreport memory/
```

```text
memory/
|-- ops/
|   `-- 20260221-172500-cron-job-hardening.md
|-- tax-returns/
|   |-- 2018-adam.pdf
|   |-- 2019-adam.pdf
|   |-- 2020-adam.pdf
|   |-- 2021-adam.pdf
|   |-- 2022-adam.pdf
|   |-- 2023-adam.pdf
|   |-- 2024-adam.pdf
|   `-- 2025-adam-&-jenny.pdf
|-- README.md
|-- budget.md
|-- index.md
`-- merchant-rules.md
```

## Annotations

*   `ops/`: Contains operational logs, incident reports, and hardening details.
*   `tax-returns/`: Dedicated directory for storing and retrieving PDF tax documents.
*   `budget.md`: Defines budget categories, allocations, and tracking logic.
*   `merchant-rules.md`: specific regex or substring matching rules for transaction categorization.
*   `README.md`: General documentation regarding the agent's memory structure.

## Tax Returns Directory

This directory stores runtime tax return documents. The agent scans this location to load historical tax contexts or process new returns. Files typically follow the naming convention `YYYY-name.pdf`.

**Current Runtime Files:**
- `tax-returns/2018-adam.pdf`
- `tax-returns/2019-adam.pdf`
- `tax-returns/2020-adam.pdf`
- `tax-returns/2021-adam.pdf`
- `tax-returns/2022-adam.pdf`
- `tax-returns/2023-adam.pdf`
- `tax-returns/2024-adam.pdf`
- `tax-returns/2025-adam-&-jenny.pdf`
