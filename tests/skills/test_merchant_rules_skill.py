"""Tests for merchant rules editing skill artifact."""

from pathlib import Path


def test_merchant_rules_skill_exists() -> None:
    """Verify that the merchant rules editing skill SKILL.md exists."""
    skill_path = Path("src/transactoid/skills/edit-merchant-rules-memory/SKILL.md")

    assert skill_path.exists(), "Merchant rules editing skill SKILL.md should exist"


def test_merchant_rules_skill_has_content() -> None:
    """Verify that the skill file has meaningful content."""
    skill_path = Path("src/transactoid/skills/edit-merchant-rules-memory/SKILL.md")
    content = skill_path.read_text()

    # Check for key sections
    assert "# Skill:" in content
    assert "Purpose" in content
    assert "Shell Editing Workflow" in content
    assert "Validation" in content


def test_merchant_rules_skill_documents_format() -> None:
    """Verify that the skill documents the rule format."""
    skill_path = Path("src/transactoid/skills/edit-merchant-rules-memory/SKILL.md")
    content = skill_path.read_text()

    # Should document required fields
    assert "rule_name" in content
    assert "category_key" in content
    assert "patterns" in content
    assert "description" in content


def test_merchant_rules_skill_documents_validation() -> None:
    """Verify that the skill emphasizes taxonomy validation."""
    skill_path = Path("src/transactoid/skills/edit-merchant-rules-memory/SKILL.md")
    content = skill_path.read_text()

    # Should mention taxonomy validation as critical
    assert "taxonomy" in content.lower()
    assert "validate" in content.lower() or "validation" in content.lower()
