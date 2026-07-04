"""Tags are household-scoped: names collide only within a household."""

import uuid

from penny.adapters.db.facade import DB
from penny.adapters.db.models import Household, User
from penny.tenancy.context import RequestContext

H1, H2 = uuid.uuid4(), uuid.uuid4()
U1, U2 = uuid.uuid4(), uuid.uuid4()


def _db(tmp_path) -> DB:
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    with db.session() as s:
        s.add_all(
            [Household(household_id=H1, name="A"), Household(household_id=H2, name="B")]
        )
        s.flush()
        s.add_all(
            [
                User(user_id=U1, household_id=H1, email="a@x.com"),
                User(user_id=U2, household_id=H2, email="b@x.com"),
            ]
        )
    return db


def test_two_households_can_use_the_same_tag_name(tmp_path):
    db = _db(tmp_path)
    with db.session_for(RequestContext(user_id=U1, household_id=H1)):
        t1 = db.upsert_tag("groceries")
    with db.session_for(RequestContext(user_id=U2, household_id=H2)):
        t2 = db.upsert_tag("groceries")
    assert t1.tag_id != t2.tag_id
    assert t1.household_id == H1
    assert t2.household_id == H2


def test_upsert_within_a_household_still_deduplicates(tmp_path):
    db = _db(tmp_path)
    ctx = RequestContext(user_id=U1, household_id=H1)
    with db.session_for(ctx):
        t1 = db.upsert_tag("vacation")
        t2 = db.upsert_tag("vacation", description="trips")
    assert t1.tag_id == t2.tag_id
    assert t2.description == "trips"
