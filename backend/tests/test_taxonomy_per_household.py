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
