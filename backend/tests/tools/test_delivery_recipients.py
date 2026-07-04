from penny.adapters.db.models import Household, User
from penny.db import get_db
from penny.tenancy.context import RequestContext, SessionMode
from penny.tools.delivery import resolve_report_recipients, send_email_report


def _seed():
    db = get_db()
    db.create_schema()
    with db.session() as s:
        hh = Household(name="HH")
        s.add(hh)
        s.flush()
        a = User(household_id=hh.household_id, email="a@x.com", external_auth_id="c1")
        b = User(household_id=hh.household_id, email="b@x.com", external_auth_id="c2")
        pending = User(
            household_id=hh.household_id, email="p@x.com", external_auth_id=None
        )
        s.add_all([a, b, pending])
        s.flush()
        return hh.household_id, a.user_id


def test_individual_mode_emails_only_that_user(isolated_db):
    hid, uid = _seed()
    ctx = RequestContext(user_id=uid, household_id=hid)
    with get_db().session() as s:
        assert resolve_report_recipients(s, ctx) == ["a@x.com"]


def test_joint_mode_emails_active_household_members(isolated_db):
    hid, uid = _seed()
    ctx = RequestContext(user_id=uid, household_id=hid, session_mode=SessionMode.JOINT)
    with get_db().session() as s:
        assert sorted(resolve_report_recipients(s, ctx)) == ["a@x.com", "b@x.com"]


def test_tool_has_no_recipient_parameter():
    # @tool wraps the function in a Tool; assert the agent-facing schema (the
    # actual injection surface) exposes no recipient parameter.
    assert "to" not in send_email_report.schema["properties"]
