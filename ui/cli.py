from __future__ import annotations

from typing import List, Optional


def ingest(mode: str, data_dir: Optional[str] = None, batch_size: int = 25) -> None:
    return None


def ask(question: str) -> None:
    return None


def recat(merchant_id: int, to: str) -> None:
    return None


def tag(rows: List[int], tags: List[str]) -> None:
    return None


def init_db(url: Optional[str] = None) -> None:
    return None


def seed_taxonomy(yaml_path: str = "configs/taxonomy.yaml") -> None:
    return None


def clear_cache(namespace: str = "default") -> None:
    return None


def main() -> None:
    # Minimal stub entrypoint
    return None
