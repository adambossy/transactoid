"""LLM-backed merchant normalization (Tier 2).

Turns raw Plaid descriptors into stable :class:`NormalizedMerchant` identities,
resolving wrapper descriptors (Zelle / ATM / bill-pay / ...) via an LLM driven by
the natural-language rule repository in ``rules.yaml``.
"""

from __future__ import annotations

from penny.normalizer.core import (
    KNOWN_CHANNELS,
    NormalizedMerchant,
    naive_normalize,
    slug,
)
from penny.normalizer.llm import MerchantNormalizer
from penny.normalizer.rules import RuleSet, build_system_prompt, load_rules

__all__ = [
    "KNOWN_CHANNELS",
    "MerchantNormalizer",
    "NormalizedMerchant",
    "RuleSet",
    "build_system_prompt",
    "load_rules",
    "naive_normalize",
    "slug",
]
