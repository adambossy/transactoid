#!/usr/bin/env python3
"""Run the merchant-normalizer eval suite against the live LLM.

Loads the held-out fixtures (penny/normalizer/eval_fixtures.yaml), normalizes
each descriptor, scores predictions vs. expectations, and prints per-field
accuracy plus the failing cases. Use this to decide whether a rules.yaml edit
helped or regressed.

Prereqs: an LLM API key (OPENAI_API_KEY or GOOGLE_API_KEY); optionally
PENNY_NORMALIZER_MODEL / PENNY_CATEGORIZER_MODEL.

Usage (from backend/):
  uv run python scripts/normalize_eval.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from penny.normalizer import MerchantNormalizer  # noqa: E402
from penny.normalizer.evals import load_eval_cases, score_cases  # noqa: E402


async def _run() -> int:
    cases = list(load_eval_cases())
    normalizer = MerchantNormalizer()
    print(f">> Running {len(cases)} eval cases via {normalizer.model} …")
    predictions = await normalizer.normalize_many([c.descriptor for c in cases])
    report = score_cases(cases, predictions)

    print()
    print(
        f"exact:        {report.exact_accuracy:6.1%}  ({report.passed}/{report.total})"
    )
    print(f"channel:      {report.channel_accuracy:6.1%}")
    print(f"normalized:   {report.name_accuracy:6.1%}")
    print(f"counterparty: {report.counterparty_accuracy:6.1%}")

    failures = [r for r in report.results if not r.all_ok]
    if failures:
        print(f"\n{len(failures)} failing case(s):")
        for r in failures:
            flags = "".join(
                "." if ok else x
                for ok, x in (
                    (r.channel_ok, "C"),
                    (r.name_ok, "N"),
                    (r.counterparty_ok, "P"),
                )
            )
            print(f"  [{flags}] {r.case.descriptor!r}")
            print(
                f"        expected channel={r.case.expected_channel} "
                f"name={r.case.expected_normalized_name!r} "
                f"cp={r.case.expected_counterparty!r}"
            )
            print(
                f"        got      channel={r.predicted.source_channel} "
                f"name={r.predicted.normalized_name!r} "
                f"cp={r.predicted.counterparty!r}"
            )
    # Non-zero exit when not perfect, so this can gate CI later if desired.
    return 0 if report.passed == report.total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
