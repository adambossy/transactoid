from pathlib import Path

import pytest

from penny.db import get_db
from penny.workspace_store.blobs import InMemoryBlobStore
from penny.workspace_store.sync import materialize, run_with_workspace
from tests.workspace_store.test_sync import _seed_with_content  # reuse seed


async def test_run_with_workspace_materializes_runs_and_flushes(isolated_db, tmp_path):
    db = get_db()
    db.create_schema()
    blobs = InMemoryBlobStore()
    ctx = _seed_with_content(db, blobs)
    seen: dict = {}

    async def fake_run(root: Path):
        seen["had_rules"] = (root / "memory" / "merchant-rules.md").exists()
        (root / "memory" / "learned.md").write_bytes(b"lesson\n")
        return "ok"

    result = await run_with_workspace(ctx, fake_run, blob_store=blobs)
    assert result == "ok" and seen["had_rules"]
    # flushed: a fresh materialize sees the new file
    with get_db().session() as s:
        again = materialize(s, ctx, blob_store=blobs, root=tmp_path / "check")
    assert (again.root / "memory" / "learned.md").exists()


async def test_aborted_run_commits_nothing(isolated_db, tmp_path):
    db = get_db()
    db.create_schema()
    blobs = InMemoryBlobStore()
    ctx = _seed_with_content(db, blobs)

    async def crashing_run(root: Path):
        (root / "memory" / "half-done.md").write_bytes(b"partial\n")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await run_with_workspace(ctx, crashing_run, blob_store=blobs)
    with get_db().session() as s:
        again = materialize(s, ctx, blob_store=blobs, root=tmp_path / "check")
    assert not (again.root / "memory" / "half-done.md").exists()
