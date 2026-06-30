#!/usr/bin/env python3
"""Sample distinct merchant descriptors from plaid_transactions.

This is the FIRST task of Tier 2 (merchant normalization): before writing any
extraction rules, survey the *real* descriptor corpus so the rules are built
against actual bank formats rather than guesses. The pass is read-only.

It does two things:
  1. Pulls every distinct ``merchant_descriptor`` with its frequency.
  2. Buckets them by a coarse, heuristic channel guess (zelle / venmo / atm /
     paypal / ...) purely for *discovery* — the goal is to find which wrapper
     vendors actually appear (including ones we didn't anticipate), not to
     finalize a taxonomy. Everything that doesn't match a known pattern lands
     in ``other`` and is surfaced with its most common leading tokens so new
     vendors are easy to spot.

Output (gitignored — contains real merchant strings):
  .descriptor-corpus/descriptors.json   full {descriptor, count, channel_guess}
  .descriptor-corpus/report.md          human-readable summary by bucket
  .descriptor-corpus/other_tokens.txt   leading-token frequencies for `other`

Usage (from backend/, with a TEST-branch DATABASE_URL — never production):
  set -a && source .env.test && set +a
  uv run python scripts/sample_descriptors.py
"""

from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import re
import sys

from sqlalchemy import create_engine, text

# Coarse channel guessers, evaluated in order. Each entry is (channel, regex).
# Deliberately broad: this is discovery, not the final rule set.
_CHANNEL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("zelle", re.compile(r"\bzelle\b", re.I)),
    ("venmo", re.compile(r"\bvenmo\b", re.I)),
    ("cash_app", re.compile(r"\bcash\s*app\b|\bsquare\s*cash\b", re.I)),
    ("paypal", re.compile(r"\bpaypal\b|\bpp\*\b", re.I)),
    ("atm", re.compile(r"\batm\b|\bwithdrawal\b|\bcash\s+withdraw", re.I)),
    ("stripe", re.compile(r"\bstripe\b", re.I)),
    ("square", re.compile(r"\bsq\s*\*|\bsquare\b", re.I)),
    ("bambora", re.compile(r"\bbambora\b", re.I)),
    ("ach", re.compile(r"\bach\b|\bdirect\s*dep|\bdirectdep", re.I)),
    ("check", re.compile(r"\bcheck\b|\bchk\b|\be-?check\b", re.I)),
    ("wire", re.compile(r"\bwire\b", re.I)),
    ("transfer", re.compile(r"\btransfer\b|\bxfer\b", re.I)),
]


def _guess_channel(descriptor: str) -> str:
    for channel, pattern in _CHANNEL_PATTERNS:
        if pattern.search(descriptor):
            return channel
    return "other"


def _leading_tokens(descriptor: str, n: int = 2) -> str:
    """First ``n`` alphabetic-ish tokens, lowercased — a crude vendor key."""
    tokens = re.findall(r"[A-Za-z]+", descriptor)
    return " ".join(t.lower() for t in tokens[:n])


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print(
            "ERROR: DATABASE_URL is not set. Source a TEST-branch .env.test "
            "first (never production).",
            file=sys.stderr,
        )
        return 2

    engine = create_engine(database_url)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT merchant_descriptor, COUNT(*) AS n "
                "FROM plaid_transactions "
                "WHERE merchant_descriptor IS NOT NULL "
                "GROUP BY merchant_descriptor "
                "ORDER BY n DESC"
            )
        ).all()

    records = [
        {
            "descriptor": descriptor,
            "count": int(n),
            "channel_guess": _guess_channel(descriptor),
        }
        for descriptor, n in rows
    ]

    by_channel: dict[str, list[dict[str, object]]] = {}
    for rec in records:
        by_channel.setdefault(str(rec["channel_guess"]), []).append(rec)

    out_dir = Path(os.environ.get("DESCRIPTOR_CORPUS_DIR", ".descriptor-corpus"))
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "descriptors.json").write_text(json.dumps(records, indent=2))

    # Leading-token frequencies within `other` — surfaces unanticipated vendors.
    other = by_channel.get("other", [])
    token_counts: Counter[str] = Counter()
    for rec in other:
        token_counts[_leading_tokens(str(rec["descriptor"]))] += int(rec["count"])
    (out_dir / "other_tokens.txt").write_text(
        "\n".join(f"{count}\t{token}" for token, count in token_counts.most_common())
    )

    # Human-readable report.
    total_distinct = len(records)
    total_txns = sum(int(r["count"]) for r in records)
    lines: list[str] = [
        "# Descriptor corpus sample",
        "",
        f"- distinct descriptors: **{total_distinct}**",
        f"- transactions covered: **{total_txns}**",
        "",
        "## By channel guess (coarse, for discovery)",
        "",
        "| channel | distinct | txns |",
        "|---|--:|--:|",
    ]
    for channel in sorted(
        by_channel,
        key=lambda c: sum(int(r["count"]) for r in by_channel[c]),
        reverse=True,
    ):
        recs = by_channel[channel]
        lines.append(
            f"| {channel} | {len(recs)} | {sum(int(r['count']) for r in recs)} |"
        )
    lines += ["", "## Sample descriptors per channel (top 15 by frequency)", ""]
    for channel in sorted(by_channel):
        lines.append(f"### {channel}")
        lines.append("")
        for rec in sorted(by_channel[channel], key=lambda r: -int(r["count"]))[:15]:
            lines.append(f"- `{rec['descriptor']}`  ×{rec['count']}")
        lines.append("")
    (out_dir / "report.md").write_text("\n".join(lines))

    print(f">> Sampled {total_distinct} distinct descriptors ({total_txns} txns).")
    print(
        f">> Wrote corpus to {out_dir}/ (descriptors.json, report.md, other_tokens.txt)"
    )
    print(">> Channel guess breakdown:")
    for channel in sorted(
        by_channel,
        key=lambda c: sum(int(r["count"]) for r in by_channel[c]),
        reverse=True,
    ):
        recs = by_channel[channel]
        print(
            f"   {channel:>10}: {len(recs):>4} distinct, "
            f"{sum(int(r['count']) for r in recs):>5} txns"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
