import uuid

from penny.adapters.db.facade import DB
from penny.adapters.db.models import Category, Household
from penny.bootstrap import seed_taxonomy_for_household

H1 = uuid.uuid4()
H2 = uuid.uuid4()


def test_two_households_get_independent_taxonomies(tmp_path):
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    with db.session() as s:
        s.add_all(
            [Household(household_id=H1, name="A"), Household(household_id=H2, name="B")]
        )
        s.flush()
        seed_taxonomy_for_household(s, H1)
        seed_taxonomy_for_household(s, H2)
    with db.session() as s:
        n1 = s.query(Category).filter_by(household_id=H1).count()
        n2 = s.query(Category).filter_by(household_id=H2).count()
    assert n1 > 0 and n1 == n2


def _seed_two_households(tmp_path):
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    with db.session() as s:
        s.add_all(
            [Household(household_id=H1, name="A"), Household(household_id=H2, name="B")]
        )
        s.flush()
        seed_taxonomy_for_household(s, H1)
        seed_taxonomy_for_household(s, H2)
    return db


def test_category_key_lookup_scopes_to_the_context_household(tmp_path):
    from penny.tenancy.context import RequestContext

    db = _seed_two_households(tmp_path)
    with db.session() as s:
        key = s.query(Category).filter_by(household_id=H1).first().key
    with db.session_for(RequestContext(user_id=uuid.uuid4(), household_id=H1)):
        id1 = db.get_category_id_by_key(key)
        ids1 = db.get_category_ids_by_keys([key])
    with db.session_for(RequestContext(user_id=uuid.uuid4(), household_id=H2)):
        id2 = db.get_category_id_by_key(key)
    assert id1 != id2
    assert ids1 == {key: id1}
    with db.session() as s:
        assert s.get(Category, id1).household_id == H1
        assert s.get(Category, id2).household_id == H2


def test_fetch_categories_scopes_to_the_context_household(tmp_path):
    from penny.tenancy.context import RequestContext

    db = _seed_two_households(tmp_path)
    with db.session_for(RequestContext(user_id=uuid.uuid4(), household_id=H1)):
        rows = db.fetch_categories()
    with db.session() as s:
        h1_ids = {c.category_id for c in s.query(Category).filter_by(household_id=H1)}
    assert {r["category_id"] for r in rows} == h1_ids


def test_replace_categories_rows_leaves_other_household_alone(tmp_path):
    from penny.tenancy.context import RequestContext

    db = _seed_two_households(tmp_path)
    with db.session_for(RequestContext(user_id=uuid.uuid4(), household_id=H1)):
        db.replace_categories_rows([])
    with db.session() as s:
        assert s.query(Category).filter_by(household_id=H1).count() == 0
        assert s.query(Category).filter_by(household_id=H2).count() > 0


def test_taxonomy_singleton_and_id_cache_are_per_household(
    tmp_path, isolated_db, monkeypatch
):
    from penny import services
    from penny.db import get_db
    from penny.taxonomy import loader
    from penny.tenancy.context import (
        RequestContext,
        reset_request_context,
        set_request_context,
    )

    db = get_db()
    db.create_schema()
    with db.session() as s:
        s.add_all(
            [Household(household_id=H1, name="A"), Household(household_id=H2, name="B")]
        )
        s.flush()
        seed_taxonomy_for_household(s, H1)
        seed_taxonomy_for_household(s, H2)

    ctx1 = RequestContext(user_id=uuid.uuid4(), household_id=H1)
    ctx2 = RequestContext(user_id=uuid.uuid4(), household_id=H2)

    token = set_request_context(ctx1)
    try:
        t1 = services.get_taxonomy()
        key = t1.all_nodes()[0].key
        id1 = loader.get_category_id(db, t1, key)
        assert services.get_taxonomy() is t1
    finally:
        reset_request_context(token)
    token = set_request_context(ctx2)
    try:
        t2 = services.get_taxonomy()
        id2 = loader.get_category_id(db, t2, key)
    finally:
        reset_request_context(token)

    assert t1 is not t2
    assert id1 != id2


def test_seeding_same_household_twice_is_idempotent(tmp_path):
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    with db.session() as s:
        s.add(Household(household_id=H1, name="A"))
        s.flush()
        seed_taxonomy_for_household(s, H1)
    with db.session() as s:
        first = s.query(Category).filter_by(household_id=H1).count()
        seed_taxonomy_for_household(s, H1)
    with db.session() as s:
        assert s.query(Category).filter_by(household_id=H1).count() == first
