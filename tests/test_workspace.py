from __future__ import annotations

from pathlib import Path
from typing import Any

from transactoid.workspace import (
    resolve_memory_dir,
    resolve_reports_dir,
    resolve_workspace_dir,
)


def test_resolve_workspace_dir_default(monkeypatch: Any) -> None:
    monkeypatch.delenv("TRANSACTOID_WORKSPACE", raising=False)

    output = resolve_workspace_dir()

    expected_output = Path.home() / ".transactoid"
    assert output == expected_output


def test_resolve_workspace_dir_env_override(monkeypatch: Any, tmp_path: Path) -> None:
    workspace = tmp_path / "my-workspace"
    monkeypatch.setenv("TRANSACTOID_WORKSPACE", str(workspace))

    output = resolve_workspace_dir()

    assert output == workspace


def test_resolve_workspace_dir_ignores_blank(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("TRANSACTOID_WORKSPACE", "   ")

    output = resolve_workspace_dir()

    expected_output = Path.home() / ".transactoid"
    assert output == expected_output


def test_resolve_memory_dir_default(monkeypatch: Any) -> None:
    monkeypatch.delenv("TRANSACTOID_WORKSPACE", raising=False)

    output = resolve_memory_dir()

    expected_output = Path.home() / ".transactoid" / "memory"
    assert output == expected_output


def test_resolve_memory_dir_env_override(monkeypatch: Any, tmp_path: Path) -> None:
    workspace = tmp_path / "my-workspace"
    monkeypatch.setenv("TRANSACTOID_WORKSPACE", str(workspace))

    output = resolve_memory_dir()

    assert output == workspace / "memory"


def test_resolve_reports_dir_default(monkeypatch: Any) -> None:
    monkeypatch.delenv("TRANSACTOID_WORKSPACE", raising=False)

    output = resolve_reports_dir()

    expected_output = Path.home() / ".transactoid" / "reports"
    assert output == expected_output


def test_resolve_reports_dir_env_override(monkeypatch: Any, tmp_path: Path) -> None:
    workspace = tmp_path / "my-workspace"
    monkeypatch.setenv("TRANSACTOID_WORKSPACE", str(workspace))

    output = resolve_reports_dir()

    assert output == workspace / "reports"
