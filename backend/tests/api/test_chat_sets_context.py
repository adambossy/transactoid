import uuid

import pytest

from penny.tenancy.context import SessionMode
from penny.tenancy.principal import resolve_dev_principal


def test_request_headers_build_joint_context():
    # Pins the header contract the /api/chat handler relies on.
    ctx = resolve_dev_principal(
        {
            "X-Penny-User-Id": str(uuid.uuid4()),
            "X-Penny-Household-Id": str(uuid.uuid4()),
            "X-Penny-Session-Mode": "joint",
        }
    )
    assert ctx.session_mode is SessionMode.JOINT


def test_unconfigured_principal_raises_value_error(monkeypatch):
    # The handler maps this ValueError to a 400.
    monkeypatch.delenv("PENNY_DEV_USER_ID", raising=False)
    monkeypatch.delenv("PENNY_DEV_HOUSEHOLD_ID", raising=False)
    with pytest.raises(ValueError):
        resolve_dev_principal({})
