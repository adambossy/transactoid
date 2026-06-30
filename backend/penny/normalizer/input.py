"""Choose which descriptor string the normalizer should see.

This is *routing*, not extraction: given a transaction's ``merchant_descriptor``
(= Plaid merchant_name or name) and its raw ``original_descriptor``, decide which
string to hand the normalizer's LLM.

Why not always use original_descriptor? For ordinary merchants
``merchant_descriptor`` is Plaid's *cleaned* merchant name ("Amazon"), whereas
``original_descriptor`` is the messy raw issuer text ("AMZN MKTP US*2X4…").
Preferring the raw text there would regress direct-merchant identity. We only
swap in ``original_descriptor`` when ``merchant_descriptor`` is a bare
payment-app label that hides the real counterparty — Venmo being the confirmed
case (merchant_descriptor "Venmo", original_descriptor "Jenny O'Leary
:venmo_dollar:"). The normalizer/rules still do all extraction.
"""

from __future__ import annotations

# Bare payment-app labels whose merchant_descriptor carries no counterparty, so
# the raw original_descriptor is preferred when present. Confirmed from the
# corpus: Venmo. Cash App / Square Cash included as the same known shape; add
# others only once observed in real data.
WRAPPER_LABELS: frozenset[str] = frozenset({"venmo", "cash app", "square cash"})


def choose_normalizer_input(
    merchant_descriptor: str | None,
    original_descriptor: str | None,
) -> str:
    """Return the descriptor string to feed the normalizer.

    Prefers ``original_descriptor`` only when ``merchant_descriptor`` is a bare
    wrapper-app label (see :data:`WRAPPER_LABELS`); otherwise keeps
    ``merchant_descriptor`` (which benefits from Plaid's merchant-name cleaning),
    falling back to whichever is non-empty.
    """
    md = (merchant_descriptor or "").strip()
    od = (original_descriptor or "").strip()
    if not od:
        return md
    if md.lower() in WRAPPER_LABELS:
        return od
    return md or od
