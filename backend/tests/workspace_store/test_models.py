from pathlib import Path

from penny.adapters.db.facade import DB
from penny.adapters.db.models import (
    Household,
    User,
    WorkspaceHead,
    WorkspaceManifest,
    WorkspacePrefix,
)


def test_workspace_tables_round_trip(tmp_path: Path):
    db = DB(f"sqlite:///{tmp_path / 't.db'}")
    db.create_schema()
    with db.session() as s:
        hh = Household(name="H")
        s.add(hh)
        s.flush()
        u = User(household_id=hh.household_id, email="a@x.com")
        s.add(u)
        s.flush()
        p = WorkspacePrefix(
            prefix_token="tok1",
            household_id=hh.household_id,
            owner_user_id=u.user_id,
            visibility="shared",
            kind="shared",
        )
        s.add(p)
        s.flush()
        m = WorkspaceManifest(
            prefix_token="tok1",
            parent_manifest_id=None,
            entries=[{"path": "memory/index.md", "sha256": "0" * 64, "size": 3}],
            household_id=hh.household_id,
            owner_user_id=u.user_id,
            visibility="shared",
        )
        s.add(m)
        s.flush()
        s.add(
            WorkspaceHead(
                prefix_token="tok1",
                head_manifest_id=m.manifest_id,
                household_id=hh.household_id,
                owner_user_id=u.user_id,
                visibility="shared",
            )
        )
        s.flush()
