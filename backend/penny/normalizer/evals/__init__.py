"""Eval harness for the merchant normalizer.

Because extraction is an LLM call driven by natural-language rules, correctness
is measured with evals rather than hard-coded unit assertions: a fixture set of
real descriptors with expected ``{channel, normalized_name, counterparty}``,
scored as a suite so rule-repository edits can be measured for regression or
improvement.

``score_cases`` is pure (takes precomputed predictions) so it is unit-testable
without an API key; ``scripts/normalize_eval.py`` wires it to the live LLM.

The fixtures here are HELD OUT — deliberately different descriptors from the
few-shot examples embedded in ``rules.yaml`` — so a passing eval reflects
generalization, not memorization of the prompt.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from penny.normalizer.core import NormalizedMerchant

_FIXTURES_PATH = Path(__file__).with_name("eval_fixtures.yaml")


@dataclass(frozen=True, slots=True)
class EvalCase:
    descriptor: str
    expected_channel: str
    expected_normalized_name: str
    expected_counterparty: str | None


@dataclass(frozen=True, slots=True)
class CaseResult:
    case: EvalCase
    predicted: NormalizedMerchant
    channel_ok: bool
    name_ok: bool
    counterparty_ok: bool

    @property
    def all_ok(self) -> bool:
        return self.channel_ok and self.name_ok and self.counterparty_ok


@dataclass(frozen=True, slots=True)
class EvalReport:
    results: list[CaseResult]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.all_ok)

    @property
    def channel_accuracy(self) -> float:
        return self._ratio(lambda r: r.channel_ok)

    @property
    def name_accuracy(self) -> float:
        return self._ratio(lambda r: r.name_ok)

    @property
    def counterparty_accuracy(self) -> float:
        return self._ratio(lambda r: r.counterparty_ok)

    @property
    def exact_accuracy(self) -> float:
        return self._ratio(lambda r: r.all_ok)

    def _ratio(self, pred) -> float:  # type: ignore[no-untyped-def]
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if pred(r)) / len(self.results)


@lru_cache(maxsize=1)
def load_eval_cases() -> tuple[EvalCase, ...]:
    data = yaml.safe_load(_FIXTURES_PATH.read_text())
    return tuple(
        EvalCase(
            descriptor=str(c["descriptor"]),
            expected_channel=str(c["channel"]),
            expected_normalized_name=str(c["normalized_name"]),
            expected_counterparty=(
                None if c.get("counterparty") is None else str(c["counterparty"])
            ),
        )
        for c in data["cases"]
    )


def _cp_match(expected: str | None, predicted: str | None) -> bool:
    if expected is None:
        return predicted is None
    if predicted is None:
        return False
    return expected.strip().lower() == predicted.strip().lower()


def score_cases(
    cases: list[EvalCase], predictions: dict[str, NormalizedMerchant]
) -> EvalReport:
    """Score predictions against expectations.

    normalized_name and channel are compared exactly (both are normalized
    forms); counterparty is compared case-insensitively (the LLM may echo the
    bank's casing). A missing prediction scores all-False for that case.
    """
    results: list[CaseResult] = []
    for case in cases:
        predicted = predictions.get(case.descriptor)
        if predicted is None:
            placeholder = NormalizedMerchant("", "", "", None)
            results.append(CaseResult(case, placeholder, False, False, False))
            continue
        results.append(
            CaseResult(
                case=case,
                predicted=predicted,
                channel_ok=predicted.source_channel == case.expected_channel,
                name_ok=predicted.normalized_name == case.expected_normalized_name,
                counterparty_ok=_cp_match(
                    case.expected_counterparty, predicted.counterparty
                ),
            )
        )
    return EvalReport(results=results)
