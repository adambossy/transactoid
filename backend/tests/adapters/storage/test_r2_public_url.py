"""public_url_for_key + store_object_in_r2: public-base + bucket-override (no network)."""

from __future__ import annotations

from penny.adapters.storage import r2
from penny.adapters.storage.r2 import (
    R2Config,
    public_url_for_key,
    store_object_in_r2,
)


def test_public_base_url_builds_permanent_link(monkeypatch) -> None:
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://files.example.com/")
    url = public_url_for_key("eval-runs/eval-x/report.html")
    assert url == "https://files.example.com/eval-runs/eval-x/report.html"


def test_public_base_url_trailing_slash_normalized(monkeypatch) -> None:
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://files.example.com")
    assert public_url_for_key("a/b.html") == "https://files.example.com/a/b.html"


class _FakeClient:
    def __init__(self) -> None:
        self.put_kwargs: dict = {}
        self.presign_params: dict = {}

    def put_object(self, **kwargs) -> None:
        self.put_kwargs = kwargs

    def generate_presigned_url(self, _op, *, Params, ExpiresIn) -> str:  # noqa: N803
        self.presign_params = {"Params": Params, "ExpiresIn": ExpiresIn}
        return f"https://presigned/{Params['Bucket']}/{Params['Key']}"


def _cfg() -> R2Config:
    return R2Config(
        account_id="acct", access_key_id="ak", secret_access_key="sk", bucket="private"
    )


def test_store_object_bucket_override(monkeypatch) -> None:
    fake = _FakeClient()
    monkeypatch.setattr(r2, "_build_client", lambda _c: fake)
    stored = store_object_in_r2(
        key="eval-runs/x/report.html",
        body=b"<html>",
        content_type="text/html",
        config=_cfg(),
        bucket="public-reports",
    )
    assert fake.put_kwargs["Bucket"] == "public-reports"
    assert stored.bucket == "public-reports"


def test_presigned_uses_bucket_override(monkeypatch) -> None:
    monkeypatch.delenv("R2_PUBLIC_BASE_URL", raising=False)
    fake = _FakeClient()
    monkeypatch.setattr(r2, "_build_client", lambda _c: fake)
    url = public_url_for_key("x/report.html", config=_cfg(), bucket="public-reports")
    assert fake.presign_params["Params"]["Bucket"] == "public-reports"
    assert url == "https://presigned/public-reports/x/report.html"
