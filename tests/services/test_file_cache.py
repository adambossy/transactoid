from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pytest

from services.file_cache import FileCache, stable_key


def populate_namespace(cache: FileCache, namespace: str, values: Iterable[int]) -> None:
    for idx, value in enumerate(values):
        cache.set(namespace, f"key{idx}", value)


def provoke_atomic_write_failure(cache: FileCache, namespace: str, key: str, payload: str) -> None:
    try:
        with cache._atomic_writer(namespace, key) as tmp_file:  # noqa: SLF001 (intentional private use)
            tmp_file.write(payload)
            raise RuntimeError("boom")
    except RuntimeError:
        pass


def test_set_get_round_trip(tmp_path: Path) -> None:
    cache = FileCache(base_dir=str(tmp_path))
    cache.set("ns", "key", {"foo": 1})
    result = cache.get("ns", "key")

    assert result == {"foo": 1}
    assert cache.exists("ns", "key") is True


def test_delete_semantics(tmp_path: Path) -> None:
    cache = FileCache(base_dir=str(tmp_path))
    cache.set("ns", "key", 42)

    first = cache.delete("ns", "key")
    second = cache.delete("ns", "key")
    exists = cache.exists("ns", "key")

    assert first is True
    assert second is False
    assert exists is False


def test_clear_namespace_counts_files(tmp_path: Path) -> None:
    cache = FileCache(base_dir=str(tmp_path))
    populate_namespace(cache, "ns", values=[0, 1, 2])

    cleared = cache.clear_namespace("ns")
    namespace_dir = Path(cache.path_for("ns", "placeholder")).parent
    remaining = list(namespace_dir.iterdir())

    assert cleared == 3
    assert remaining == []


def test_atomic_writer_cleans_temp_on_exception(tmp_path: Path) -> None:
    cache = FileCache(base_dir=str(tmp_path))
    namespace_dir = Path(cache.path_for("ns", "key")).parent

    provoke_atomic_write_failure(cache, "ns", "key", payload="partial")

    temp_files = list(namespace_dir.glob(".tmp*"))
    final_file_exists = Path(cache.path_for("ns", "key")).exists()

    assert temp_files == []
    assert final_file_exists is False


def test_stable_key_is_deterministic() -> None:
    payload_a = {"a": 1, "b": 2}
    payload_b = {"b": 2, "a": 1}

    key_a = stable_key(payload_a)
    key_b = stable_key(payload_b)

    assert key_a == key_b
    assert len(key_a) == 64


def test_invalid_namespace_or_key_raises(tmp_path: Path) -> None:
    cache = FileCache(base_dir=str(tmp_path))

    with pytest.raises(ValueError):
        cache.get("../evil", "key")

    with pytest.raises(ValueError):
        cache.set("ns", "bad/../key", 1)

