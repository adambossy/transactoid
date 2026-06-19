"""Core types and helpers for merchant normalization.

The normalizer turns a raw Plaid ``merchant_descriptor`` into a
:class:`NormalizedMerchant` — a stable identity ("who", not "what message Plaid
sent") plus display metadata. Wrapper descriptors (Zelle, ATM, bill-pay, …) are
resolved by an LLM driven by the natural-language rule repository
(``rules.yaml``); direct merchants fall back to :func:`naive_normalize`, the
historical lowercase/strip-digits/collapse behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

# Channels the rule repository knows about. "direct" is the default for ordinary
# merchants that aren't routed through a wrapper.
KNOWN_CHANNELS: tuple[str, ...] = (
    "direct",
    "zelle",
    "venmo",
    "atm",
    "ach",
    "billpay",
    "transfer",
    "check",
    "paypal",
)


@dataclass(frozen=True, slots=True)
class NormalizedMerchant:
    """The resolved identity of a counterparty behind a descriptor.

    Attributes:
        normalized_name: Stable identity key, unique per counterparty
            (e.g. ``"zelle:margarita-house-cle"``, ``"atm:896-manhattan-av"``,
            or a bare naive slug for direct merchants). Used as the merchants
            table lookup key.
        display_name: Human-facing label (e.g. ``"Zelle: Margarita House Cle"``).
        source_channel: One of :data:`KNOWN_CHANNELS`.
        counterparty: The human/entity behind a wrapper descriptor
            (e.g. ``"Margarita House Cle"``); ``None`` for direct merchants,
            where the merchant itself is the counterparty.
    """

    normalized_name: str
    display_name: str
    source_channel: str
    counterparty: str | None = None


def slug(value: str) -> str:
    """Lowercase, ASCII-ish slug: keep alphanumerics, collapse runs to ``-``."""
    lowered = value.strip().lower()
    slugged = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slugged


def naive_normalize(descriptor: str) -> NormalizedMerchant:
    """Direct-merchant normalization — the historical behaviour.

    Lowercase, drop digits, collapse whitespace. Mirrors
    ``penny.adapters.db.models.normalize_merchant_name`` so direct merchants get
    the exact same identity key they had before the normalizer rewrite.
    """
    lowered = descriptor.lower().strip()
    no_digits = re.sub(r"\d+", "", lowered)
    collapsed = re.sub(r"\s+", " ", no_digits).strip()
    return NormalizedMerchant(
        normalized_name=collapsed,
        display_name=descriptor.strip(),
        source_channel="direct",
        counterparty=None,
    )
