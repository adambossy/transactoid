from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryNode:
    key: str
    name: str
    description: str | None
    parent_key: str | None


class Taxonomy:
    @staticmethod
    def _node_sort_key(node: CategoryNode) -> str:
        return node.key

    def __init__(self, nodes: Sequence[CategoryNode]) -> None:
        self._nodes_by_key: dict[str, CategoryNode] = {n.key: n for n in nodes}
        self._children: dict[str, list[CategoryNode]] = {}
        for node in nodes:
            if node.parent_key:
                self._children.setdefault(node.parent_key, []).append(node)
        # Ensure deterministic ordering
        for key in list(self._children.keys()):
            self._children[key].sort(key=self._node_sort_key)

    @classmethod
    def from_nodes(cls, nodes: Sequence[CategoryNode]) -> Taxonomy:
        # Sort incoming nodes to ensure deterministic behavior
        return cls(sorted(nodes, key=cls._node_sort_key))

    def is_valid_key(self, key: str) -> bool:
        return key in self._nodes_by_key

    def get(self, key: str) -> CategoryNode | None:
        return self._nodes_by_key.get(key)

    def children(self, key: str) -> list[CategoryNode]:
        return list(self._children.get(key, []))

    def parent(self, key: str) -> CategoryNode | None:
        node = self._nodes_by_key.get(key)
        if node is None or node.parent_key is None:
            return None
        return self._nodes_by_key.get(node.parent_key)

    def parents(self) -> list[CategoryNode]:
        # Top-level nodes: those with parent_key is None
        roots = [n for n in self._nodes_by_key.values() if n.parent_key is None]
        roots.sort(key=lambda n: n.key)
        return roots

    def all_nodes(self) -> list[CategoryNode]:
        return [self._nodes_by_key[k] for k in sorted(self._nodes_by_key.keys())]

    def to_prompt(
        self,
        *,
        include_keys: Iterable[str] | None = None,
    ) -> dict[str, object]:
        if include_keys is None:
            selected = self.all_nodes()
        else:
            wanted = set(include_keys)
            selected = [n for n in self.all_nodes() if n.key in wanted]
        nodes_payload: list[dict[str, object]] = []
        for n in selected:
            nodes_payload.append(
                {
                    "key": n.key,
                    "name": n.name,
                    "description": n.description,
                    "parent_key": n.parent_key,
                }
            )
        return {
            "nodes": nodes_payload,
        }

    def path_str(self, key: str, sep: str = " > ") -> str | None:
        node = self._nodes_by_key.get(key)
        if node is None:
            return None
        parts: list[str] = [node.name]
        parent = self.parent(key)
        if parent is not None:
            parts.insert(0, parent.name)
        return sep.join(parts)
