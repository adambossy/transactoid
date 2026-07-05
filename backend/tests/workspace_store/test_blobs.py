import hashlib

from penny.workspace_store.blobs import InMemoryBlobStore, content_key


def test_content_key_is_prefix_plus_sha256():
    sha = hashlib.sha256(b"hello").hexdigest()
    key = content_key("tokABC", sha)
    assert key == f"tokABC/{sha}"
    assert len(key.split("/", 1)[1]) == 64


def test_inmemory_roundtrip():
    store = InMemoryBlobStore()
    key = content_key("tok", hashlib.sha256(b"data").hexdigest())
    assert not store.exists(key)
    store.put(key, b"data")
    assert store.exists(key)
    assert store.get(key) == b"data"
