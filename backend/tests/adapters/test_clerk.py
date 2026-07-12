"""Clerk adapter payload parsing (the HTTP fetch itself is stubbed)."""

from __future__ import annotations

import pytest

from penny.adapters import clerk


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
        "last_name": "Lovelace",
    }


def test_fetch_user_profile_missing_fields_come_back_none(monkeypatch):
    # input: a user with no picture and no name set (empty strings count as
    # absent — Clerk sends "" for cleared fields)
    _stub_user(monkeypatch, {"id": "c_sam", "image_url": "", "first_name": None})

    # act
    output = clerk.fetch_user_profile("c_sam")

    # expected
    assert output == {"image_url": None, "first_name": None, "last_name": None}


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
