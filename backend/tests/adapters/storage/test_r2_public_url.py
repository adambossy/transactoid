"""public_url_for_key: the R2_PUBLIC_BASE_URL branch (no network)."""

from __future__ import annotations

from penny.adapters.storage.r2 import public_url_for_key


def test_public_base_url_builds_permanent_link(monkeypatch) -> None:
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://files.example.com/")
    url = public_url_for_key("eval-runs/eval-x/report.html")
    assert url == "https://files.example.com/eval-runs/eval-x/report.html"


def test_public_base_url_trailing_slash_normalized(monkeypatch) -> None:
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://files.example.com")
    assert public_url_for_key("a/b.html") == "https://files.example.com/a/b.html"
