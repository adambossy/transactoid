"""Deterministic tests for the eval scorer and held-out fixtures."""

from __future__ import annotations

from penny.normalizer.core import NormalizedMerchant, naive_normalize
from penny.normalizer.evals import EvalCase, load_eval_cases, score_cases


def test_score_cases_all_correct() -> None:
    cases = [
        EvalCase("Venmo", "venmo", "venmo", None),
        EvalCase("Amazon", "direct", "amazon", None),
    ]
    predictions = {
        "Venmo": NormalizedMerchant("venmo", "Venmo", "venmo", None),
        "Amazon": naive_normalize("Amazon"),
    }
    report = score_cases(cases, predictions)
    assert report.exact_accuracy == 1.0
    assert report.passed == 2


def test_score_cases_detects_field_level_misses() -> None:
    cases = [EvalCase("Zelle Payment TO DAMARIS", "zelle", "zelle:damaris", "DAMARIS")]
    # Wrong normalized_name, right channel, counterparty case-insensitive match.
    predictions = {
        "Zelle Payment TO DAMARIS": NormalizedMerchant(
            "zelle:damaris-wrong", "Zelle: Damaris", "zelle", "damaris"
        )
    }
    report = score_cases(cases, predictions)
    r = report.results[0]
    assert r.channel_ok is True
    assert r.name_ok is False
    assert r.counterparty_ok is True  # case-insensitive
    assert r.all_ok is False


def test_score_cases_missing_prediction_scores_zero() -> None:
    cases = [EvalCase("Venmo", "venmo", "venmo", None)]
    report = score_cases(cases, {})
    assert report.results[0].all_ok is False
    assert report.exact_accuracy == 0.0


def test_eval_fixtures_load_and_are_held_out() -> None:
    cases = load_eval_cases()
    assert len(cases) >= 8
    # Fixtures must not duplicate the rules.yaml few-shot descriptors.
    from penny.normalizer import load_rules

    fewshot = {ex["descriptor"] for c in load_rules().channels for ex in c.examples}
    fixture_descriptors = {c.descriptor for c in cases}
    assert fixture_descriptors.isdisjoint(fewshot), "eval fixtures leak few-shots"
