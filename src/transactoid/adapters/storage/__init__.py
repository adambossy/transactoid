"""Object storage adapters."""

from __future__ import annotations

from transactoid.adapters.storage.r2 import (
    R2Config,
    R2ConfigError,
    R2StorageError,
    R2StoredObject,
    R2UploadError,
    load_r2_config_from_env,
    store_object_in_r2,
)

__all__ = [
    "R2Config",
    "R2ConfigError",
    "R2StorageError",
    "R2StoredObject",
    "R2UploadError",
    "load_r2_config_from_env",
    "store_object_in_r2",
]
