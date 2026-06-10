"""Canonical institution -> sign-convention mapping.

Derived from empirical inspection of the user's prod data on 2026-05-09.
NOT a universal truth — these mappings reflect this user's specific
institutions and their reporting conventions. New institutions added via
Plaid Link will get the default ('expense_positive') and may need
manual override via a future agent tool.

Institution names are matched verbatim. `plaid_transactions.institution`
must equal the dict key exactly (case-sensitive, whitespace-significant).
New institutions are silently mapped to the default; verify by querying
`account_sign_conventions WHERE provenance='seeded' AND notes LIKE
'Seeded from institution=...'` after seeding.
"""

INSTITUTION_SIGN_CONVENTIONS: dict[str, str] = {
    "American Express": "expense_positive",
    "Chase": "expense_positive",
    "Morgan Stanley Client Serv": "expense_positive",
    "Venmo - Personal": "expense_positive",
    "Bank of America": "expense_negative",
    "Alliant Credit Union": "expense_negative",
}

DEFAULT_SIGN_CONVENTION: str = "expense_positive"
