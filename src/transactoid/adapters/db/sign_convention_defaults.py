"""Canonical institution -> sign-convention mapping.

Empirical history: a 2026-05-09 keyword-aggregate analysis of the user's
prod data classified Bank of America and Alliant Credit Union as
expense_negative (inverted). A 2026-06-11 category-level audit during the
prod rollout disproved that: BofA/Alliant restaurant, transit, and gym
expenses arrive positive and interest income arrives negative — the
standard expense=positive convention. The keyword aggregate had been
misled by outbound "payment"-keyword descriptors, the same artifact that
was caught for Morgan Stanley by descriptor-level inspection in May.

As of the 2026-06-11 audit, ALL of the user's connected institutions
deliver the standard convention, so this mapping is currently
informational; the machinery stays in place for the first institution
that genuinely inverts (or for CSV/XLSX import sources, whose sign
semantics are user-defined and unclassified).

NOT a universal truth — these mappings reflect this user's specific
institutions. New institutions added via Plaid Link get the default
('expense_positive') and may need manual override via
`transactoid set-sign-convention`.

Institution names are matched verbatim against
`plaid_items.institution_name` (NOT `plaid_transactions.institution`,
which proved ~94% NULL in prod — see the 2026-06-11 rollout). Matching is
case-sensitive and whitespace-significant. New institutions are silently
mapped to the default; verify by querying `account_sign_conventions WHERE
provenance='seeded'` after seeding.
"""

INSTITUTION_SIGN_CONVENTIONS: dict[str, str] = {
    "American Express": "expense_positive",
    "Chase": "expense_positive",
    "Morgan Stanley Client Serv": "expense_positive",
    "Venmo - Personal": "expense_positive",
    "Bank of America": "expense_positive",
    "Alliant Credit Union": "expense_positive",
}

DEFAULT_SIGN_CONVENTION: str = "expense_positive"
