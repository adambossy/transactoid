from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence


@dataclass(frozen=True)
class CategoryNode:
    key: str
    name: str
    description: Optional[str]
    parent_key: Optional[str]


class Taxonomy:
    def __init__(self, nodes: Sequence[CategoryNode]) -> None:
        self._nodes_by_key: Dict[str, CategoryNode] = {n.key: n for n in nodes}
        self._children: Dict[str, List[CategoryNode]] = {}
        for node in nodes:
            if node.parent_key:
                self._children.setdefault(node.parent_key, []).append(node)
        # Ensure deterministic ordering
        for key in list(self._children.keys()):
            self._children[key].sort(key=lambda n: n.key)

    @classmethod
    def from_db(cls, db: "DB") -> "Taxonomy":
        rows: List[Dict[str, object]] = db.fetch_categories()
        nodes: List[CategoryNode] = []
        for row in rows:
            nodes.append(
                CategoryNode(
                    key=str(row["key"]),
                    name=str(row["name"]),
                    description=None if row.get("description") is None else str(row["description"]),
                    parent_key=None if row.get("parent_key") is None else str(row["parent_key"]),
                )
            )
        # Sort to keep stable order
        nodes.sort(key=lambda n: n.key)
        return cls(nodes)

    @classmethod
    def from_nodes(cls, nodes: Sequence[CategoryNode]) -> "Taxonomy":
        # Sort incoming nodes to ensure deterministic behavior
        return cls(sorted(list(nodes), key=lambda n: n.key))

    def is_valid_key(self, key: str) -> bool:
        return key in self._nodes_by_key

    def get(self, key: str) -> Optional[CategoryNode]:
        return self._nodes_by_key.get(key)

    def children(self, key: str) -> List[CategoryNode]:
        return list(self._children.get(key, []))

    def parent(self, key: str) -> Optional[CategoryNode]:
        node = self._nodes_by_key.get(key)
        if node is None or node.parent_key is None:
            return None
        return self._nodes_by_key.get(node.parent_key)

    def parents(self) -> List[CategoryNode]:
        # Top-level nodes: those with parent_key is None
        roots = [n for n in self._nodes_by_key.values() if n.parent_key is None]
        roots.sort(key=lambda n: n.key)
        return roots

    def all_nodes(self) -> List[CategoryNode]:
        return [self._nodes_by_key[k] for k in sorted(self._nodes_by_key.keys())]

    def category_id_for_key(self, db: "DB", key: str) -> Optional[int]:
        return db.get_category_id_by_key(key)

    def to_prompt(
        self,
        *,
        include_keys: Optional[Iterable[str]] = None,
    ) -> Dict[str, object]:
        if include_keys is None:
            selected = self.all_nodes()
        else:
            wanted = set(include_keys)
            selected = [n for n in self.all_nodes() if n.key in wanted]
        nodes_payload: List[Dict[str, object]] = []
        for n in selected:
            nodes_payload.append(
                {
                    "key": n.key,
                    "name": n.name,
                    "description": n.description,
                    "parent_key": n.parent_key,
                }
            )
        return {"nodes": nodes_payload}

    def path_str(self, key: str, sep: str = " > ") -> Optional[str]:
        node = self._nodes_by_key.get(key)
        if node is None:
            return None
        parts: List[str] = [node.name]
        parent = self.parent(key)
        if parent is not None:
            parts.insert(0, parent.name)
        return sep.join(parts)


