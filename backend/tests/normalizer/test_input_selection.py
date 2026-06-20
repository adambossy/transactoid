"""Tests for normalizer input selection (routing, not extraction)."""

from __future__ import annotations

from penny.normalizer import choose_normalizer_input


def test_bare_venmo_label_prefers_original_descriptor() -> None:
    # The confirmed case: merchant_descriptor "Venmo" hides the person.
    chosen = choose_normalizer_input("Venmo", 'Jonah Spear "🏠 :venmo_dollar: 🎁"')
    assert chosen == 'Jonah Spear "🏠 :venmo_dollar: 🎁"'


def test_direct_merchant_keeps_cleaned_descriptor() -> None:
    # merchant_descriptor is Plaid's cleaned name; do NOT regress to raw text.
    chosen = choose_normalizer_input(
        "Amazon", "AMZN MKTP US*2X4AB1CD0 AMZN.COM/BILL WA"
    )
    assert chosen == "Amazon"


def test_missing_original_descriptor_uses_merchant_descriptor() -> None:
    assert choose_normalizer_input("Sweetgreen", None) == "Sweetgreen"
    assert choose_normalizer_input("Sweetgreen", "") == "Sweetgreen"


def test_missing_merchant_descriptor_falls_back_to_original() -> None:
    assert choose_normalizer_input(None, "Some Raw Text") == "Some Raw Text"
    assert choose_normalizer_input("", "Some Raw Text") == "Some Raw Text"


def test_wrapper_label_match_is_case_insensitive() -> None:
    assert choose_normalizer_input("venmo", "Keela Williams") == "Keela Williams"
    assert choose_normalizer_input("VENMO", "Keela Williams") == "Keela Williams"


def test_both_empty_returns_empty_string() -> None:
    assert choose_normalizer_input(None, None) == ""
