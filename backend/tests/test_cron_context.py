import uuid

import pytest

from penny.cli import load_cron_jobs
from penny.tenancy.context import SessionMode

H = str(uuid.uuid4())
U1, U2 = str(uuid.uuid4()), str(uuid.uuid4())


def test_jobs_cover_each_user_plus_household(monkeypatch):
    monkeypatch.setenv("PENNY_CRON_HOUSEHOLD_ID", H)
    monkeypatch.setenv("PENNY_CRON_USER_IDS", f"{U1},{U2}")
    jobs = load_cron_jobs()
    kinds = [(j.kind, j.ctx.session_mode) for j in jobs]
    assert kinds == [
        ("individual", SessionMode.INDIVIDUAL),
        ("individual", SessionMode.INDIVIDUAL),
        ("household", SessionMode.JOINT),
    ]
    assert {str(j.ctx.user_id) for j in jobs if j.kind == "individual"} == {U1, U2}


def test_missing_principal_fails_loudly(monkeypatch):
    monkeypatch.delenv("PENNY_CRON_HOUSEHOLD_ID", raising=False)
    monkeypatch.delenv("PENNY_CRON_USER_IDS", raising=False)
    with pytest.raises(RuntimeError):
        load_cron_jobs()
