"""The blob-store seam: a tiny put/get/exists protocol over any object store.

The rest of ``workspace_store`` depends only on the :class:`BlobStore`
protocol, never on R2 directly. :class:`R2BlobStore` wraps the existing
functional R2 adapter for production; :class:`InMemoryBlobStore` backs every
non-R2 test. Blobs are content-addressed (:func:`content_key`) and immutable,
so ``put`` is idempotent and ``exists`` is only an optimization.
"""

from __future__ import annotations

from typing import Protocol

from penny.adapters.storage.r2 import download_object_from_r2, store_object_in_r2


def content_key(prefix_token: str, sha256_hex: str) -> str:
    """The R2 key for a blob under ``prefix_token``: ``{token}/{sha256hex}``.

    The single home for the R2 key layout: both ``sync`` call sites route
    through here. ``sha256_hex`` is the blob's content hash — callers holding the
    raw bytes hash them first (``hashlib.sha256(body).hexdigest()``); callers
    reading a manifest already hold the recorded SHA. Content addressing makes
    uploads idempotent (same bytes → same key) and keys unguessable without the
    opaque prefix token.
    """
    return f"{prefix_token}/{sha256_hex}"


class BlobStore(Protocol):
    def put(self, key: str, body: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...


class InMemoryBlobStore:
    """A dict-backed BlobStore for tests — no network, no credentials."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def put(self, key: str, body: bytes) -> None:
        self._objects[key] = body

    def get(self, key: str) -> bytes:
        return self._objects[key]

    def exists(self, key: str) -> bool:
        return key in self._objects


class R2BlobStore:
    """A BlobStore backed by Cloudflare R2 via the functional adapter.

    ``exists`` probes with a ``get`` guarded by the adapter's not-found error;
    acceptable for v1 because ``put`` is idempotent (content-addressed), so a
    false negative merely re-uploads identical bytes.
    """

    def put(self, key: str, body: bytes) -> None:
        store_object_in_r2(key=key, body=body, content_type="application/octet-stream")

    def get(self, key: str) -> bytes:
        return download_object_from_r2(key=key)

    def exists(self, key: str) -> bool:
        try:
            self.get(key)
            return True
        except Exception:
            return False
