from penny.adapters.db.models import Household, User, WorkspacePrefix
from penny.db import get_db
from penny.tenancy.context import RequestContext, SessionMode
from penny.workspace_store.broker import ensure_prefixes, resolve_readable_prefixes


def _seed(db):
    with db.session() as s:
        hh = Household(name="H")
        s.add(hh)
        s.flush()
        a = User(household_id=hh.household_id, email="a@x.com")
        b = User(household_id=hh.household_id, email="b@x.com")
        s.add_all([a, b])
        s.flush()
        return hh.household_id, a.user_id, b.user_id


def test_ensure_is_idempotent_and_tokens_opaque(isolated_db):
    db = get_db()
    db.create_schema()
    hid, ua, _ = _seed(db)
    ctx = RequestContext(user_id=ua, household_id=hid)
    with db.session() as s:
        ensure_prefixes(s, ctx)
        ensure_prefixes(s, ctx)  # no duplicates
        rows = s.query(WorkspacePrefix).all()
        assert len(rows) == 2  # one shared + one private(a)
        for r in rows:
            assert str(hid) not in r.prefix_token and str(ua) not in r.prefix_token


def test_individual_resolves_private_plus_shared(isolated_db):
    db = get_db()
    db.create_schema()
    hid, ua, _ = _seed(db)
    ctx = RequestContext(user_id=ua, household_id=hid)
    with db.session() as s:
        ensure_prefixes(s, ctx)
        infos = resolve_readable_prefixes(s, ctx)
    assert sorted(i.visibility for i in infos) == ["private", "shared"]


def test_joint_resolves_shared_only(isolated_db):
    db = get_db()
    db.create_schema()
    hid, ua, ub = _seed(db)
    for u in (ua, ub):
        with db.session() as s:
            ensure_prefixes(s, RequestContext(user_id=u, household_id=hid))
    joint = RequestContext(user_id=ua, household_id=hid, session_mode=SessionMode.JOINT)
    with db.session() as s:
        infos = resolve_readable_prefixes(s, joint)
    assert [i.visibility for i in infos] == ["shared"]
