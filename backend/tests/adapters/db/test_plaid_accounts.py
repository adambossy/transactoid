from pathlib import Path

from penny.adapters.db.facade import DB
from penny.adapters.db.models import Household, PlaidAccount, PlaidItem, User


def _create_db(tmp_path: Path) -> DB:
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    return db


def test_plaid_account_links_item_owner_household(tmp_path):
    db = _create_db(tmp_path)
    with db.session() as session:
        hh = Household(name="Bossy")
        session.add(hh)
        session.flush()
        user = User(household_id=hh.household_id, email="a@example.com")
        item = PlaidItem(item_id="item-1", access_token="tok")
        session.add_all([user, item])
        session.flush()
        acct = PlaidAccount(
            account_id="acct-1",
            item_id="item-1",
            owner_user_id=user.user_id,
            household_id=hh.household_id,
            visibility="shared",
        )
        session.add(acct)
        session.flush()
        assert acct.visibility == "shared"
