"""Neon branch lifecycle for the eval run (create off prod, delete after).

A branch is cut off the Neon ``production`` branch, the agent replays on it (so
prod is never touched), and it is deleted at the end of the run. We build the
connection URL from the branch's OWN endpoint host — the create response's
``connection_uris`` already point at the new compute. We never call
``neonctl connection-string --branch-name`` (documented bug: it returns the
PARENT endpoint), which is the footgun this module exists to avoid.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

_DEFAULT_ORG_ID = "org-sweet-sky-03842625"
_DEFAULT_PROJECT_ID = "purple-poetry-32142000"
_DEFAULT_PARENT_BRANCH = "production"


class EvalBranchError(RuntimeError):
    """neonctl failed or returned something we can't use."""


def _org_id() -> str:
    return os.environ.get("PENNY_NEON_ORG_ID", _DEFAULT_ORG_ID)


def _project_id() -> str:
    return os.environ.get("PENNY_NEON_PROJECT_ID", _DEFAULT_PROJECT_ID)


def _parent_branch() -> str:
    return os.environ.get("PENNY_NEON_PROD_BRANCH", _DEFAULT_PARENT_BRANCH)


def _neonctl() -> str:
    path = shutil.which("neonctl")
    if path is None:
        raise EvalBranchError("neonctl not found on PATH (run `neonctl auth`).")
    return path


def _run(args: list[str]) -> str:
    cmd = [_neonctl(), "--org-id", _org_id(), "--project-id", _project_id(), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)  # noqa: S603
    if proc.returncode != 0:
        raise EvalBranchError(f"neonctl {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def _ensure_sslmode(url: str) -> str:
    if "sslmode=" in url:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}sslmode=require"


def create_eval_branch(name: str) -> tuple[str, str]:
    """Create ``name`` off prod (with compute); return (branch_id, database_url).

    The URL is taken from the create response's ``connection_uris`` — the new
    branch's own endpoint, with ``sslmode=require`` ensured.
    """
    raw = _run(
        [
            "branches",
            "create",
            "--name",
            name,
            "--parent",
            _parent_branch(),
            "--compute",
            "--type",
            "read_write",
            "--output",
            "json",
        ]
    )
    data = json.loads(raw)
    branch_id = (data.get("branch") or {}).get("id")
    if not branch_id:
        raise EvalBranchError(f"no branch id in create response: {raw[:300]}")
    uris = data.get("connection_uris") or []
    conn = uris[0].get("connection_uri") if uris else None
    if not conn:
        raise EvalBranchError(
            f"no connection_uri in create response for {name}: {raw[:300]}"
        )
    return branch_id, _ensure_sslmode(conn)


def delete_eval_branch(branch_id: str) -> None:
    """Delete the eval branch (best-effort; raises only on a hard neonctl error)."""
    _run(["branches", "delete", branch_id, "--output", "json"])
