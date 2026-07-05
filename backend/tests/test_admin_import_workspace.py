from pathlib import Path

from penny.adapters.db.models import Household, User
from penny.admin import import_workspace
from penny.db import get_db
from penny.tenancy.context import RequestContext
from penny.workspace_store.blobs import InMemoryBlobStore
from penny.workspace_store.sync import materialize


def test_import_lands_in_private_prefix_and_is_idempotent(isolated_db, tmp_path: Path):
    db = get_db()
    db.create_schema()
    with db.session() as s:
        hh = Household(name="H")
        s.add(hh)
        s.flush()
        u = User(household_id=hh.household_id, email="a@x.com")
        s.add(u)
        s.flush()
        ctx = RequestContext(user_id=u.user_id, household_id=hh.household_id)
    src = tmp_path / "old-workspace"
    (src / "memory").mkdir(parents=True)
    (src / "memory" / "index.md").write_text("# memory\n")
    blobs = InMemoryBlobStore()

    first = import_workspace(ctx, src, blob_store=blobs)
    second = import_workspace(ctx, src, blob_store=blobs)  # no changes
    assert first and second == {}

    with db.session() as s:
        out = materialize(s, ctx, blob_store=blobs, root=tmp_path / "check")
    assert (out.root / "memory" / "index.md").read_text() == "# memory\n"
    private = next(i for i in out.prefixes if i.visibility == "private")
    assert out.origin["memory/index.md"] == private.prefix_token
