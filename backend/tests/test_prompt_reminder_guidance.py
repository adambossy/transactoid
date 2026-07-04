"""The active system prompt carries the static reminder + onboarding guidance."""

from __future__ import annotations

from penny.prompts import load_prompt


def test_system_prompt_carries_reminder_guidance():
    text = load_prompt("penny-system-prompt")
    assert "<system-reminder>" in text
    assert "most recent" in text.lower()
    assert "resolve_onboarding_item" in text
