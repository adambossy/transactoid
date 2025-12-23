from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import tempfile
from typing import Any, TextIO

JSONType = Any

__all__ = ["FileCache", "stable_key"]

logger = logging.getLogger(__name__)


class FileCache:
    """
    Namespaced JSON file cache with atomic writes and deterministic paths.

    - Each (namespace, key) pair maps to a single JSON file on disk.
    - Writes are atomic via write-to-temp + os.replace().
    - Inputs are validated to avoid path traversal or unsafe filenames.
    """

    def __init__(self, base_dir: str = ".cache") -> None:
        self.base_dir = Path(base_dir).expanduser().resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # -------- Public API --------

    def get(self, namespace: str, key: str) -> JSONType | None:
        path = self._key_path(namespace, key)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.debug("FileCache JSON decode failed at %s", path)
            return None
        except OSError as exc:
            logger.debug("FileCache read failed at %s: %s", path, exc)
            return None

    def set(self, namespace: str, key: str, value: JSONType) -> None:
        serialized = json.dumps(value, ensure_ascii=True, sort_keys=True)
        with self._atomic_writer(namespace, key) as tmp_file:
            tmp_file.write(serialized)

    def exists(self, namespace: str, key: str) -> bool:
        return self._key_path(namespace, key).exists()

    def delete(self, namespace: str, key: str) -> bool:
        path = self._key_path(namespace, key)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            logger.debug("FileCache delete failed at %s: %s", path, exc)
            return False

    def clear_namespace(self, namespace: str) -> int:
        ns_dir = self._namespace_dir(namespace)
        removed = 0
        if not ns_dir.exists():
            return 0
        for entry in ns_dir.iterdir():
            if entry.is_file():
                try:
                    entry.unlink()
                    removed += 1
                except OSError as exc:
                    logger.debug("FileCache clear failed at %s: %s", entry, exc)
        return removed

    def list_keys(self, namespace: str) -> list[str]:
        ns_dir = self._namespace_dir(namespace)
        if not ns_dir.exists():
            return []
        keys: list[str] = []
        for entry in ns_dir.iterdir():
            if entry.is_file() and entry.suffix == ".json":
                keys.append(entry.stem)
        keys.sort()
        return keys

    def path_for(self, namespace: str, key: str) -> str:
        return str(self._key_path(namespace, key))

    # -------- Internal helpers --------

    def _namespace_dir(self, namespace: str) -> Path:
        self._validate_namespace(namespace)
        ns_dir = self.base_dir / namespace
        ns_dir.mkdir(parents=True, exist_ok=True)
        return ns_dir

    def _key_path(self, namespace: str, key: str) -> Path:
        self._validate_key(key)
        ns_dir = self._namespace_dir(namespace)
        safe_key = self._sanitize_key(key)
        return ns_dir / f"{safe_key}.json"

    @staticmethod
    def _validate_namespace(namespace: str) -> None:
        if not isinstance(namespace, str) or not namespace or namespace.strip() == "":
            raise ValueError("namespace must be a non-empty string")
        if (
            ".." in namespace
            or os.sep in namespace
            or "/" in namespace
            or "\\" in namespace
        ):
            raise ValueError("namespace contains forbidden path components")

    @staticmethod
    def _validate_key(key: str) -> None:
        if not isinstance(key, str) or not key or key.strip() == "":
            raise ValueError("key must be a non-empty string")
        if ".." in key or os.sep in key or "/" in key or "\\" in key:
            raise ValueError("key contains forbidden path components")

    @staticmethod
    def _sanitize_key(key: str) -> str:
        # Replace whitespace with underscore and remove unsafe characters
        key = re.sub(r"\s+", "_", key)
        key = re.sub(r"[^A-Za-z0-9._-]+", "_", key)
        return key

    @contextmanager
    def _atomic_writer(self, namespace: str, key: str) -> Iterator[TextIO]:
        final_path = self._key_path(namespace, key)
        ns_dir = final_path.parent
        tmp_file = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=str(ns_dir),
            prefix=".tmp",
        )
        try:
            try:
                yield tmp_file
            finally:
                try:
                    tmp_file.flush()
                    os.fsync(tmp_file.fileno())
                except Exception:  # flushing/fsync is best-effort  # noqa: S110
                    pass
                tmp_file.close()

            os.replace(tmp_file.name, final_path)
        except Exception:
            # Best-effort cleanup of temp file
            try:
                if os.path.exists(tmp_file.name):
                    os.unlink(tmp_file.name)
            except OSError:
                pass
            raise


def stable_key(payload: Any) -> str:
    """
    Deterministic SHA256 hex digest over a canonical JSON serialization.
    """
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()
