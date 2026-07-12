"""Clerk adapter: payload parsing and the cached profile reader (HTTP stubbed)."""

from __future__ import annotations

import pytest

from penny.adapters import clerk
from penny.adapters.clerk import EMPTY_PROFILE, ClerkError


@pytest.fixture(autouse=True)
def _fresh_profile_cache():
    """The TTL cache is module state; isolate it per test."""
    clerk._profile_cache.clear()
    yield
    clerk._profile_cache.clear()


def _stub_user(monkeypatch: pytest.MonkeyPatch, payload: object) -> None:
    monkeypatch.setattr(clerk, "_get_user", lambda sub, *, secret_key, op: payload)


def test_fetch_user_profile_reads_image_and_name(monkeypatch):
    # input: the fields Clerk mirrors from the Google account
    _stub_user(
        monkeypatch,
        {
            "id": "c_ada",
            "image_url": "https://img.clerk.com/ada",
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email_addresses": [],
        },
    )

    # act
    output = clerk.fetch_user_profile("c_ada")

    # expected
    assert output == {
        "image_url": "https://img.clerk.com/ada",
        "first_name": "Ada",
    }


def test_fetch_user_profile_missing_fields_come_back_none(monkeypatch):
    # input: a user with no picture and no name set (empty strings count as
    # absent — Clerk sends "" for cleared fields)
    _stub_user(monkeypatch, {"id": "c_sam", "image_url": "", "first_name": None})

    # act
    output = clerk.fetch_user_profile("c_sam")

    # expected
    assert output == EMPTY_PROFILE


def test_fetch_user_identity_still_resolves_primary_email(monkeypatch):
    # input: identity payload shape (guards the _get_user refactor)
    _stub_user(
        monkeypatch,
        {
            "primary_email_address_id": "e1",
            "email_addresses": [
                {
                    "id": "e1",
                    "email_address": "ada@x.com",
                    "verification": {"status": "verified"},
                }
            ],
        },
    )

    # act
    output = clerk.fetch_user_identity("c_ada")

    # expected
    assert output == ("ada@x.com", True)


def test_cached_profile_fetches_once_per_ttl_window(monkeypatch):
    # input: two reads of the same subject within the TTL
    calls: list[str] = []

    def _counting(sub, *, secret_key, op):
        calls.append(sub)
        return {"image_url": "https://img.clerk.com/ada", "first_name": "Ada"}

    monkeypatch.setattr(clerk, "_get_user", _counting)

    # act
    first = clerk.fetch_cached_user_profile("c_ada")
    second = clerk.fetch_cached_user_profile("c_ada")

    # expected: one Clerk fetch, same profile both times
    assert calls == ["c_ada"]
    assert (
        first
        == second
        == {
            "image_url": "https://img.clerk.com/ada",
            "first_name": "Ada",
        }
    )


def test_cached_profile_absorbs_failure_and_negative_caches(monkeypatch):
    # input: Clerk unreachable (or no secret key in dev)
    calls: list[str] = []

    def _broken(sub, *, secret_key, op):
        calls.append(sub)
        raise ClerkError("CLERK_SECRET_KEY is not set")

    monkeypatch.setattr(clerk, "_get_user", _broken)

    # act: two reads within the failure-TTL window
    first = clerk.fetch_cached_user_profile("c_sam")
    second = clerk.fetch_cached_user_profile("c_sam")

    # expected: degrades to the empty profile (never raises), and the failure
    # is cached so the second read does not re-pay the timeout
    assert first == second == EMPTY_PROFILE
    assert calls == ["c_sam"]
