from pathlib import Path
import uuid

from penny.adapters.db.facade import DB
from penny.adapters.db.models import Household, User


def _create_db(tmp_path: Path) -> DB:
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    return db


def test_household_and_user_round_trip(tmp_path):
    db = _create_db(tmp_path)
    with db.session() as session:
        hh = Household(name="Bossy")
        session.add(hh)
        session.flush()
        user = User(household_id=hh.household_id, email="adam@example.com")
        session.add(user)
        session.flush()
        assert isinstance(hh.household_id, uuid.UUID)
        assert user.household_id == hh.household_id
