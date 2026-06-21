"""Deterministic tests for the merchant normalizer (no LLM calls)."""

from __future__ import annotations

from penny.normalizer import (
    KNOWN_CHANNELS,
    MerchantNormalizer,
    build_system_prompt,
    load_rules,
    naive_normalize,
    slug,
)
from penny.normalizer.merchant_normalizer import _ExtractionResult, _sanitize_name


def test_naive_normalize_matches_legacy_behaviour() -> None:
    # lowercase, drop digits, collapse whitespace — same as the legacy key.
    result = naive_normalize("Sweetgreen  #1234  NYC")
    assert result.normalized_name == "sweetgreen # nyc"
    assert result.source_channel == "direct"
    assert result.counterparty is None
    assert result.display_name == "Sweetgreen  #1234  NYC"


def test_slug() -> None:
    assert slug("896 MANHATTAN AV BROOKLYN NY") == "896-manhattan-av-brooklyn-ny"
    assert slug("  Jenny  O'Leary ") == "jenny-o-leary"


def test_rules_load_and_cover_known_channels() -> None:
    rules = load_rules()
    assert rules.version >= 1
    assert rules.default_channel == "direct"
    names = set(rules.channel_names)
    # Every non-direct known channel has a rule entry.
    for channel in KNOWN_CHANNELS:
        if channel == "direct":
            continue
        assert channel in names, f"missing rule for {channel}"


def test_system_prompt_mentions_channels_and_examples() -> None:
    rules = load_rules()
    prompt = build_system_prompt(rules)
    assert "channel: zelle" in prompt
    assert "channel: atm" in prompt
    # A real example descriptor should be embedded as a few-shot.
    assert "Zelle Payment TO MARGARITA HOUSE CLE" in prompt


def test_sanitize_name_constrains_shape() -> None:
    assert _sanitize_name("Zelle: Margarita House CLE") == "zelle:-margarita-house-cle"
    assert _sanitize_name("atm:896 MANHATTAN AV") == "atm:896-manhattan-av"
    assert _sanitize_name("   ") == "unknown"


def test_to_merchant_direct_falls_back_to_naive() -> None:
    norm = MerchantNormalizer(provider="openai", model="gpt-test")
    # An LLM result classifying as 'direct' must be replaced by the naive key.
    result = _ExtractionResult(
        idx=0,
        channel="direct",
        normalized_name="whatever-the-llm-said",
        display_name="Amazon",
        counterparty=None,
    )
    merchant = norm._to_merchant("Amazon", result)
    assert merchant == naive_normalize("Amazon")


def test_to_merchant_wrapper_uses_llm_fields() -> None:
    norm = MerchantNormalizer(provider="openai", model="gpt-test")
    result = _ExtractionResult(
        idx=0,
        channel="zelle",
        normalized_name="zelle:margarita-house-cle",
        display_name="Zelle: MARGARITA HOUSE CLE",
        counterparty="MARGARITA HOUSE CLE",
    )
    merchant = norm._to_merchant("Zelle Payment TO MARGARITA HOUSE CLE", result)
    assert merchant.source_channel == "zelle"
    assert merchant.normalized_name == "zelle:margarita-house-cle"
    assert merchant.counterparty == "MARGARITA HOUSE CLE"
