"""Billing config — the ``PENNY_*`` seam for prices, subsidy, and platform key.

Single source of truth for the numbers the gate and metering need:

- ``PENNY_MODEL_PRICES`` — a JSON price table (``{model: {input, output,
  cache_read, cache_write}}`` in $/Mtok) turned into a harness ``PriceTable``
  the per-request ``usage_pricer`` prices completions against.
- ``PENNY_SUBSIDY_CENTS`` — the per-user grant on first Plaid link (default 200
  = $2/user; a two-spouse household that both connect gets $4).
- ``PENNY_SUBSIDY_PROVIDER_KEY`` — the platform provider key a subsidized run
  bills against (the active provider, Gemini/``google``).

Config is the only cross-domain seam (AGENTS.md): behaviour varies by
``PENNY_*`` env, never by deployment topology.
"""

from __future__ import annotations

import json
import os

from agent_harness.usage.counting import ModelPrice, PriceTable

# Penny's runtime model is Gemini-only; a subsidized run and a BYO run both use
# the Google provider (see phase-2b decision D3).
ACTIVE_PROVIDER = "google"

_DEFAULT_SUBSIDY_CENTS = 200


def load_price_table() -> PriceTable:
    """Parse ``PENNY_MODEL_PRICES`` into a ``PriceTable`` (empty if unset).

    An empty/unset table prices every model at zero — pricing is a best-effort
    observation, never a gate on the run (the harness owns that policy). Malformed
    JSON raises loudly at load, not mid-stream.
    """
    raw = os.environ.get("PENNY_MODEL_PRICES", "").strip()
    if not raw:
        return PriceTable({})
    data = json.loads(raw)
    prices: dict[str, ModelPrice] = {}
    for model, rates in data.items():
        prices[model] = ModelPrice(
            input_per_mtok=float(rates.get("input", 0.0)),
            output_per_mtok=float(rates.get("output", 0.0)),
            cache_read_per_mtok=(
                float(rates["cache_read"]) if "cache_read" in rates else None
            ),
            cache_write_per_mtok=(
                float(rates["cache_write"]) if "cache_write" in rates else None
            ),
        )
    return PriceTable(prices)


def subsidy_cents() -> int:
    """Per-user subsidy grant in cents (``PENNY_SUBSIDY_CENTS``, default 200)."""
    raw = os.environ.get("PENNY_SUBSIDY_CENTS", "").strip()
    return int(raw) if raw else _DEFAULT_SUBSIDY_CENTS


def subsidy_provider_key() -> str:
    """The platform key a subsidized run bills against (``PENNY_SUBSIDY_PROVIDER_KEY``).

    Empty string when unset — the gate treats a missing platform key as "cannot
    subsidize" and blocks rather than reaching for an ambient env key.
    """
    return os.environ.get("PENNY_SUBSIDY_PROVIDER_KEY", "").strip()
