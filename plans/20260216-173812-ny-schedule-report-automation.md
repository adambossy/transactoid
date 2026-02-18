# NY Schedule Report Automation Plan

1. Add runtime support for scheduled report selection and artifact persistence.
- Implement a deterministic schedule selector based on America/New_York local date/time.
- Add a CLI entrypoint that computes report type precedence (annual > monthly > weekly > daily).
- Ensure `transactoid run` path uploads markdown and HTML artifacts to R2 for scheduled runs.

2. Add new daily report prompt.
- Add `prompts/report-daily.md`.
- Add mirrored versioned prompt file under `src/transactoid/prompts/report-daily/report-daily-1.md`.
- Update prompt metadata so `load_prompt("report-daily")` resolves consistently.

3. Add ops artifacts for Cron Manager.
- Add `ops/cron-manager/fly.toml` and `ops/cron-manager/schedules.json`.
- Use dual UTC schedules (09:00 and 10:00) plus an NY-time guard in command to guarantee 5:00 AM America/New_York year-round.
- Command will run `transactoid run` with selected prompt and recipients.

4. Deploy/update Fly Cron Manager.
- Sync local ops artifacts into deployed cron-manager source.
- Deploy cron-manager app and verify schedule records.
- Validate no `--schedule daily` machines remain on `transactoid`.

5. Validate and report.
- Run lint/format/type/deadcode/tests.
- Summarize deployment state, known failures/successes, and exact verification commands.
