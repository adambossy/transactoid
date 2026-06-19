#!/usr/bin/env python3
"""Dry-run the merchant normalizer over the sampled corpus and emit a review page.

This is the validation step that replaces the automated backfill: it runs the
LLM normalizer over real descriptors WITHOUT writing anything to the database,
groups the proposed merchant identities, and writes a human-reviewable HTML page
(checkbox per proposed identity) plus a JSON of the proposals.

Prereqs:
  - A descriptor corpus from scripts/sample_descriptors.py
    (.descriptor-corpus/descriptors.json).
  - An LLM API key (OPENAI_API_KEY or GOOGLE_API_KEY) and, optionally,
    PENNY_NORMALIZER_MODEL / PENNY_CATEGORIZER_MODEL.

Usage (from backend/):
  uv run python scripts/normalize_dryrun.py [--only-wrappers] [--limit N]

Cost control: --only-wrappers restricts the LLM pass to descriptors the sampler
flagged as a non-direct channel (zelle/atm/ach/...). Direct merchants normalize
deterministically (naive) and add no review value, so excluding them avoids
thousands of LLM calls. The exclusion is logged, never silent.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

# Ensure `penny` is importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from penny.normalizer import MerchantNormalizer  # noqa: E402
from penny.normalizer.review import (  # noqa: E402
    ProposalMember,
    ReviewProposal,
    build_review_html,
    proposals_to_json,
)


async def _run(args: argparse.Namespace) -> int:
    corpus_dir = Path(os.environ.get("DESCRIPTOR_CORPUS_DIR", ".descriptor-corpus"))
    corpus_file = corpus_dir / "descriptors.json"
    if not corpus_file.exists():
        print(
            f"ERROR: {corpus_file} not found. Run scripts/sample_descriptors.py first.",
            file=sys.stderr,
        )
        return 2

    records = json.loads(corpus_file.read_text())
    if args.only_wrappers:
        kept = [r for r in records if r.get("channel_guess") != "other"]
        print(
            f">> --only-wrappers: {len(kept)}/{len(records)} descriptors kept "
            f"(direct merchants excluded from the LLM pass; they use naive)."
        )
        records = kept
    if args.limit:
        records = records[: args.limit]
        print(f">> --limit {args.limit}: capped to {len(records)} descriptors.")

    counts = {str(r["descriptor"]): int(r["count"]) for r in records}
    descriptors = list(counts)

    normalizer = MerchantNormalizer()
    print(f">> Normalizing {len(descriptors)} descriptors via {normalizer.model} …")
    resolved = await normalizer.normalize_many(descriptors)

    # Group descriptors by their proposed normalized identity.
    groups: dict[str, ReviewProposal] = {}
    members: dict[str, list[ProposalMember]] = {}
    for descriptor, merchant in resolved.items():
        key = merchant.normalized_name
        members.setdefault(key, []).append(
            ProposalMember(descriptor=descriptor, count=counts.get(descriptor, 1))
        )
        if key not in groups:
            groups[key] = ReviewProposal(
                normalized_name=merchant.normalized_name,
                display_name=merchant.display_name,
                source_channel=merchant.source_channel,
                counterparty=merchant.counterparty,
                members=[],
            )
    proposals = [
        ReviewProposal(
            normalized_name=g.normalized_name,
            display_name=g.display_name,
            source_channel=g.source_channel,
            counterparty=g.counterparty,
            members=members[key],
        )
        for key, g in groups.items()
    ]

    html_path = corpus_dir / "review.html"
    json_path = corpus_dir / "proposals.json"
    html_path.write_text(
        build_review_html(proposals, title="Merchant normalization — review")
    )
    json_path.write_text(proposals_to_json(proposals))

    merges = sum(1 for p in proposals if len(p.members) > 1)
    print(
        f">> {len(proposals)} proposed identities ({merges} collapse 2+ descriptors)."
    )
    print(f">> Wrote {html_path} and {json_path}")
    print(f">> Open {html_path} in a browser to review.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only-wrappers",
        action="store_true",
        help="Restrict the LLM pass to non-direct channels (cost control).",
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="Cap the number of descriptors."
    )
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
