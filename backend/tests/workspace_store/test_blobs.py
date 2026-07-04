from penny.workspace_store.blobs import InMemoryBlobStore, content_key


def test_content_key_is_prefix_plus_sha256():
    key = content_key("tokABC", b"hello")
    assert key.startswith("tokABC/")
    assert len(key.split("/", 1)[1]) == 64


def test_inmemory_roundtrip():
    store = InMemoryBlobStore()
    key = content_key("tok", b"data")
    assert not store.exists(key)
    store.put(key, b"data")
    assert store.exists(key)
    assert store.get(key) == b"data"
