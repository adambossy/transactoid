"""Tests for the `transactoid taxonomy` CLI subcommand group."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from transactoid.ui.cli import app

runner = CliRunner()


def _stub_migration_tool() -> MagicMock:
    return MagicMock()


def _patch_build(tool: MagicMock) -> Any:
    return patch("transactoid.ui.cli._build_migration_tool", return_value=tool)


def _success_result(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "success": True,
        "operation": overrides.get("operation", "add"),
        "affected_transactions": 0,
        "recategorized": 0,
        "verified_retained": 0,
        "verified_demoted": 0,
        "errors": [],
        "summary": "ok",
    }
    base.update(overrides)
    return base


def test_taxonomy_add_dispatches_with_args() -> None:
    tool = _stub_migration_tool()
    captured: dict[str, Any] = {}

    def fake_run(migration_tool: Any, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return _success_result(operation="add")

    with (
        _patch_build(tool),
        patch(
            "transactoid.tools.migrate.dispatcher.run_migration",
            side_effect=fake_run,
        ),
    ):
        result = runner.invoke(
            app,
            [
                "taxonomy",
                "add",
                "child_and_baby_expenses",
                "Child & Baby Expenses",
                "--description",
                "All child/baby spend",
            ],
        )

    output = {
        "exit_code": result.exit_code,
        "operation": captured.get("operation"),
        "new_key": captured.get("new_key"),
        "name": captured.get("name"),
        "parent_key": captured.get("parent_key"),
        "description": captured.get("description"),
    }
    expected_output = {
        "exit_code": 0,
        "operation": "add",
        "new_key": "child_and_baby_expenses",
        "name": "Child & Baby Expenses",
        "parent_key": None,
        "description": "All child/baby spend",
    }
    assert output == expected_output


def test_taxonomy_merge_dispatches_with_target_and_sources() -> None:
    tool = _stub_migration_tool()
    captured: dict[str, Any] = {}

    def fake_run(migration_tool: Any, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return _success_result(operation="merge")

    with (
        _patch_build(tool),
        patch(
            "transactoid.tools.migrate.dispatcher.run_migration",
            side_effect=fake_run,
        ),
    ):
        result = runner.invoke(
            app,
            [
                "taxonomy",
                "merge",
                "childcare.classes",
                "education_and_childcare.school_activities_and_lunch",
                "--target",
                "child_and_baby_expenses.school_lunch_and_activities",
            ],
        )

    output = {
        "exit_code": result.exit_code,
        "operation": captured.get("operation"),
        "target_key": captured.get("target_key"),
        "source_keys": captured.get("source_keys"),
    }
    expected_output = {
        "exit_code": 0,
        "operation": "merge",
        "target_key": "child_and_baby_expenses.school_lunch_and_activities",
        "source_keys": [
            "childcare.classes",
            "education_and_childcare.school_activities_and_lunch",
        ],
    }
    assert output == expected_output


def test_taxonomy_split_parses_target_specs() -> None:
    tool = _stub_migration_tool()
    captured: dict[str, Any] = {}

    def fake_run(migration_tool: Any, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return _success_result(operation="split")

    with (
        _patch_build(tool),
        patch(
            "transactoid.tools.migrate.dispatcher.run_migration",
            side_effect=fake_run,
        ),
    ):
        result = runner.invoke(
            app,
            [
                "taxonomy",
                "split",
                "education_and_childcare.books_and_supplies",
                "--target",
                "child_and_baby_expenses.child_books_and_school_supplies:Child Books"
                ":Kid school supplies",
                "--target",
                "adult_education_professional_development.books_and_learning_materials"
                ":Books & Learning Materials",
            ],
        )

    output = {
        "exit_code": result.exit_code,
        "source_key": captured.get("source_key"),
        "targets": captured.get("targets"),
    }
    expected_output = {
        "exit_code": 0,
        "source_key": "education_and_childcare.books_and_supplies",
        "targets": [
            (
                "child_and_baby_expenses.child_books_and_school_supplies",
                "Child Books",
                "Kid school supplies",
            ),
            (
                "adult_education_professional_development.books_and_learning_materials",
                "Books & Learning Materials",
                None,
            ),
        ],
    }
    assert output == expected_output


def test_taxonomy_split_rejects_malformed_target_spec() -> None:
    with _patch_build(_stub_migration_tool()):
        result = runner.invoke(
            app,
            [
                "taxonomy",
                "split",
                "food.groceries",
                "--target",
                "incomplete_spec_only_one_field",
            ],
        )

    assert result.exit_code == 2
    assert "Invalid --target" in result.output


def test_taxonomy_failure_exits_nonzero() -> None:
    tool = _stub_migration_tool()
    failure: dict[str, Any] = {
        "success": False,
        "operation": "remove",
        "affected_transactions": 0,
        "recategorized": 0,
        "verified_retained": 0,
        "verified_demoted": 0,
        "errors": ["Category 'nonexistent' not found in database"],
        "summary": "Failed to remove category: not found",
    }

    with (
        _patch_build(tool),
        patch(
            "transactoid.tools.migrate.dispatcher.run_migration",
            return_value=failure,
        ),
    ):
        result = runner.invoke(app, ["taxonomy", "remove", "nonexistent"])

    assert result.exit_code == 1
    assert "not found" in result.output
