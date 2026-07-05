"""Metered BYOK — website-owned credential vault, usage ledger, and gate.

A portable "metered BYOK" module for a hosted multi-tenant agent product:

- ``vault`` — an encrypted, per-user provider-credential store (BYO API keys /
  OAuth tokens), owner-scoped and out of the agent ``run_sql`` blast radius.
- ``metering`` — a usage ledger (one row per model completion) + a per-user
  subsidy/spend record; the remaining-runway calculation.
- ``gate`` — the pre-dispatch budget gate: BYO credential → use it; else
  subsidy remaining → platform key; else Blocked.
- ``prices`` — the model price table + subsidy config (the ``PENNY_*`` seam).
- ``oauth`` — sanctioned server-side Authorization-Code + PKCE for providers
  where we register our own client.

All data lives on the website ``WebBase`` / ``web`` schema (see
``penny.api.persistence``) — never the finance ``penny.adapters.db`` façade, so
the agent's ``run_sql`` can never reach a credential (AGENTS.local.md
agent/website segregation). This package is website-domain code: it may be
invoked by the API/chat path, and it never imports agent tools or the agent
factory.
"""
