"""Tests for budget generation skill artifact."""

from __future__ import annotations

from pathlib import Path

SKILL_PATH = Path("src/transactoid/skills/generate-budget/SKILL.md")


def _load_skill_content() -> str:
    return SKILL_PATH.read_text()


def test_generate_budget_skill_exists() -> None:
    output = SKILL_PATH.exists()

    expected_output = True

    assert output == expected_output


def test_generate_budget_skill_documents_full_coverage() -> None:
    output = _load_skill_content().lower()

    expected_output = ("all categories" in output) and ("subcategories" in output)

    assert expected_output


def test_generate_budget_skill_documents_history_window_bounds() -> None:
    output = _load_skill_content()

    expected_output = "3-12" in output

    assert expected_output


def test_generate_budget_skill_documents_markdown_table_output() -> None:
    output = _load_skill_content()
    table_header = (
        "| Category | Subcategory | Avg Monthly Spend | Proposed Budget |"
        " Delta | Notes |"
    )

    expected_output = table_header in output

    assert expected_output
