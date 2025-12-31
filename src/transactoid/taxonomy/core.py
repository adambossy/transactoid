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

    # Migration methods

    def add_category(
        self,
        key: str,
        name: str,
        parent_key: str | None,
        description: str | None = None,
    ) -> Taxonomy:
        """
        Return new Taxonomy with added category.

        Validates that:
        - Category key does not already exist
        - Parent key exists (if provided)
        - Parent is a root category (has no parent_key)
        """
        if key in self._nodes_by_key:
            msg = f"Category key '{key}' already exists"
            raise ValueError(msg)

        if parent_key is not None:
            if parent_key not in self._nodes_by_key:
                msg = f"Parent key '{parent_key}' does not exist"
                raise ValueError(msg)
            parent_node = self._nodes_by_key[parent_key]
            if parent_node.parent_key is not None:
                msg = (
                    f"Parent '{parent_key}' is not a root category "
                    f"(has parent '{parent_node.parent_key}')"
                )
                raise ValueError(msg)

        new_node = CategoryNode(
            key=key,
            name=name,
            description=description,
            parent_key=parent_key,
        )
        new_nodes = list(self._nodes_by_key.values()) + [new_node]
        return Taxonomy.from_nodes(new_nodes)

    def remove_category(self, key: str) -> Taxonomy:
        """
        Return new Taxonomy with category removed.

        Validates that:
        - Category exists
        - Category has no children
        """
        if key not in self._nodes_by_key:
            msg = f"Category key '{key}' does not exist"
            raise ValueError(msg)

        if key in self._children and len(self._children[key]) > 0:
            child_keys = [c.key for c in self._children[key]]
            msg = f"Category '{key}' has children: {child_keys}"
            raise ValueError(msg)

        new_nodes = [n for n in self._nodes_by_key.values() if n.key != key]
        return Taxonomy.from_nodes(new_nodes)

    def rename_category(self, old_key: str, new_key: str) -> Taxonomy:
        """
        Return new Taxonomy with category renamed.

        Validates that:
        - Old key exists
        - New key does not exist
        - Updates children's parent_key references
        """
        if old_key not in self._nodes_by_key:
            msg = f"Category key '{old_key}' does not exist"
            raise ValueError(msg)

        if new_key in self._nodes_by_key:
            msg = f"Category key '{new_key}' already exists"
            raise ValueError(msg)

        new_nodes: list[CategoryNode] = []

        for node in self._nodes_by_key.values():
            if node.key == old_key:
                # Update the node itself
                new_nodes.append(
                    CategoryNode(
                        key=new_key,
                        name=node.name,
                        description=node.description,
                        parent_key=node.parent_key,
                    )
                )
            elif node.parent_key == old_key:
                # Update children to point to new key
                new_nodes.append(
                    CategoryNode(
                        key=node.key,
                        name=node.name,
                        description=node.description,
                        parent_key=new_key,
                    )
                )
            else:
                new_nodes.append(node)

        return Taxonomy.from_nodes(new_nodes)

    def merge_categories(self, source_keys: list[str], target_key: str) -> Taxonomy:
        """
        Return new Taxonomy with source categories removed.

        The target category must already exist. This method only removes the
        source categories from the taxonomy - transaction reassignment must
        be handled by the caller.

        Validates that:
        - All source keys exist
        - Target key exists
        - Source keys are not the target key
        - Source categories have no children
        """
        if not source_keys:
            msg = "source_keys cannot be empty"
            raise ValueError(msg)

        if target_key not in self._nodes_by_key:
            msg = f"Target key '{target_key}' does not exist"
            raise ValueError(msg)

        for source_key in source_keys:
            if source_key not in self._nodes_by_key:
                msg = f"Source key '{source_key}' does not exist"
                raise ValueError(msg)

            if source_key == target_key:
                msg = f"Source key '{source_key}' cannot be the same as target key"
                raise ValueError(msg)

            if source_key in self._children and len(self._children[source_key]) > 0:
                child_keys = [c.key for c in self._children[source_key]]
                msg = f"Source category '{source_key}' has children: {child_keys}"
                raise ValueError(msg)

        # Remove all source categories
        source_key_set = set(source_keys)
        new_nodes = [
            n for n in self._nodes_by_key.values() if n.key not in source_key_set
        ]
        return Taxonomy.from_nodes(new_nodes)

    def split_category(
        self, source_key: str, targets: list[tuple[str, str, str | None]]
    ) -> Taxonomy:
        """
        Return new Taxonomy with source removed and targets added.

        Args:
            source_key: Key of category to split
            targets: List of (key, name, description) tuples for new categories

        The new target categories will have the same parent as the source category.
        Transaction reassignment must be handled by the caller.

        Validates that:
        - Source key exists
        - Target keys do not already exist
        - Source category has no children
        - At least one target provided
        """
        if source_key not in self._nodes_by_key:
            msg = f"Source key '{source_key}' does not exist"
            raise ValueError(msg)

        if not targets:
            msg = "Must provide at least one target category"
            raise ValueError(msg)

        source_node = self._nodes_by_key[source_key]

        if source_key in self._children and len(self._children[source_key]) > 0:
            child_keys = [c.key for c in self._children[source_key]]
            msg = f"Source category '{source_key}' has children: {child_keys}"
            raise ValueError(msg)

        # Validate target keys don't exist
        for target_key, _, _ in targets:
            if target_key in self._nodes_by_key:
                msg = f"Target key '{target_key}' already exists"
                raise ValueError(msg)

        # Remove source, add all targets with same parent_key
        new_nodes = [n for n in self._nodes_by_key.values() if n.key != source_key]

        for target_key, target_name, target_description in targets:
            new_nodes.append(
                CategoryNode(
                    key=target_key,
                    name=target_name,
                    description=target_description,
                    parent_key=source_node.parent_key,
                )
            )

        return Taxonomy.from_nodes(new_nodes)
