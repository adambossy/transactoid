"""Deterministic tests for the validation HTML builder and eval scorer."""

from __future__ import annotations

from penny.normalizer.core import NormalizedMerchant, naive_normalize
from penny.normalizer.evals import EvalCase, load_eval_cases, score_cases
from penny.normalizer.review import (
    ProposalMember,
    ReviewProposal,
    build_review_html,
    proposals_to_json,
)


def _proposals() -> list[ReviewProposal]:
    return [
        ReviewProposal(
            normalized_name="zelle:jenny-oleary",
            display_name="Zelle: JENNY OLEARY",
            source_channel="zelle",
            counterparty="JENNY OLEARY",
            members=[
                ProposalMember("Zelle Payment FROM JENNY OLEARY", 22),
                ProposalMember("Zelle Payment TO JENNY OLEARY", 3),
            ],
        ),
        ReviewProposal(
            normalized_name="amazon",
            display_name="Amazon",
            source_channel="direct",
            counterparty=None,
            members=[ProposalMember("Amazon", 589)],
        ),
    ]


def test_build_review_html_is_self_contained_and_shows_merges() -> None:
    html = build_review_html(_proposals(), title="Review")
    assert html.startswith("<!doctype html>")
    # No external resources (CSP-safe / offline).
    assert "http://" not in html and "https://" not in html
    # The merge proposal is surfaced with its member descriptors.
    assert "zelle:jenny-oleary" in html
    assert "2 descriptors → 1" in html
    assert "Zelle Payment FROM JENNY OLEARY" in html
    # Reviewer controls present.
    assert 'type="checkbox"' in html
    assert "localStorage" in html


def test_build_review_html_escapes_descriptors() -> None:
    proposals = [
        ReviewProposal(
            normalized_name="x",
            display_name="<script>",
            source_channel="direct",
            counterparty=None,
            members=[ProposalMember("<img src=x onerror=alert(1)>", 1)],
        )
    ]
    html = build_review_html(proposals, title="x")
    assert "<img src=x" not in html
    assert "&lt;img" in html


def test_proposals_to_json_round_trips_members() -> None:
    import json

    data = json.loads(proposals_to_json(_proposals()))
    by_name = {p["normalized_name"]: p for p in data}
    assert len(by_name["zelle:jenny-oleary"]["members"]) == 2


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
    from penny.normalizer.rules import load_rules

    fewshot = {ex["descriptor"] for c in load_rules().channels for ex in c.examples}
    fixture_descriptors = {c.descriptor for c in cases}
    assert fixture_descriptors.isdisjoint(fewshot), "eval fixtures leak few-shots"
