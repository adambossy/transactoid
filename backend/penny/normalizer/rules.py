"""Load the natural-language extraction-rule repository and build the prompt."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_RULES_PATH = Path(__file__).with_name("rules.yaml")


@dataclass(frozen=True, slots=True)
class ChannelRule:
    channel: str
    detect: str
    extract: str
    normalized_name: str
    display_name: str
    counterparty: str | None
    examples: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class RuleSet:
    version: int
    default_channel: str
    channels: tuple[ChannelRule, ...]

    @property
    def channel_names(self) -> list[str]:
        return [c.channel for c in self.channels]


@lru_cache(maxsize=1)
def load_rules() -> RuleSet:
    """Load and cache ``rules.yaml`` from the package directory."""
    data = yaml.safe_load(_RULES_PATH.read_text())
    channels = tuple(
        ChannelRule(
            channel=str(c["channel"]),
            detect=str(c["detect"]).strip(),
            extract=str(c["extract"]).strip(),
            normalized_name=str(c["normalized_name"]).strip(),
            display_name=str(c["display_name"]).strip(),
            counterparty=(
                None if c.get("counterparty") is None else str(c["counterparty"])
            ),
            examples=list(c.get("examples", [])),
        )
        for c in data["channels"]
    )
    return RuleSet(
        version=int(data["version"]),
        default_channel=str(data.get("default_channel", "direct")),
        channels=channels,
    )


def build_system_prompt(rules: RuleSet) -> str:
    """Render the rule repository into an instruction prompt for the LLM."""
    lines: list[str] = [
        "You normalize raw bank transaction descriptors into stable merchant",
        "identities. A descriptor may be a 'wrapper' (Zelle, ATM, bill pay, ACH,",
        "etc.) that hides the real counterparty behind boilerplate and",
        "per-transaction noise, or it may be an ordinary 'direct' merchant.",
        "",
        "For each descriptor decide which channel it belongs to, then extract its",
        "identity per that channel's rule. The goal: two transactions with the",
        "same real counterparty must get the SAME normalized_name, and distinct",
        "counterparties must get DIFFERENT normalized_names. Strip per-transaction",
        "noise (confirmation hashes, ids, dates, masked account numbers).",
        "",
        f"Known channels (default is '{rules.default_channel}'):",
        "",
    ]
    for c in rules.channels:
        lines.append(f"## channel: {c.channel}")
        lines.append(f"- detect: {c.detect}")
        lines.append(f"- extract: {c.extract}")
        lines.append(f"- normalized_name: {c.normalized_name}")
        lines.append(f"- display_name: {c.display_name}")
        for ex in c.examples:
            lines.append(
                f"- example: {ex.get('descriptor')!r} -> "
                f"normalized_name={ex.get('normalized_name')!r}, "
                f"counterparty={ex.get('counterparty')!r}"
            )
        lines.append("")
    lines += [
        "If a descriptor matches no wrapper channel, classify it as",
        f"'{rules.default_channel}' with counterparty=null; its normalized_name",
        "will be computed deterministically by the caller, so you may return the",
        "descriptor itself as normalized_name for direct merchants.",
        "",
        "normalized_name must be a lowercase slug (letters, digits, hyphens).",
    ]
    return "\n".join(lines)
