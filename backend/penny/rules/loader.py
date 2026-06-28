from __future__ import annotations

from pathlib import Path
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from penny.taxonomy.core import Taxonomy


class MarkdownFileLoader:
    """Load a markdown file (from the workspace) for prompt injection.

    Content is cached after the first load; an absent file yields ``""`` so
    callers can inject the block unconditionally. Subclasses hook ``_post_load``
    to run validation or other processing once the content is read.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._content: str | None = None

    @property
    def path(self) -> Path:
        """Return the markdown file path."""
        return self._path

    def load(self) -> str:
        """Return the file content (cached; ``""`` if the file doesn't exist)."""
        if self._content is not None:
            return self._content
        self._content = self._path.read_text() if self._path.exists() else ""
        self._post_load()
        return self._content

    def _post_load(self) -> None:
        """Hook run once after the content is first loaded (no-op by default)."""


class TaxonomyRulesLoader(MarkdownFileLoader):
    """Loads the taxonomy rules markdown (from the workspace) for prompt injection.

    Natural-language category definitions + decision rules injected as
    ``{{TAXONOMY_RULES}}``. Lives in the workspace (``memory/taxonomy-rules.md``),
    not the codebase.
    """


class MerchantRulesLoader(MarkdownFileLoader):
    """
    Loads merchant rules from a markdown file for prompt injection.

    Rules are expressed in natural language in markdown format and are
    injected directly into the categorization prompt. The LLM determines
    if a rule applies to a transaction.
    """

    # Regex pattern to extract category keys from **Category:** `key` format
    CATEGORY_KEY_PATTERN = re.compile(r"\*\*Category:\*\*\s*`([^`]+)`")

    def __init__(
        self,
        rules_path: Path,
        taxonomy: Taxonomy | None = None,
    ) -> None:
        """
        Initialize the rules loader.

        Args:
            rules_path: Path to the merchant rules markdown file
            taxonomy: Optional taxonomy for category key validation
        """
        super().__init__(rules_path)
        self._taxonomy = taxonomy

    @property
    def rules_path(self) -> Path:
        """Return the rules file path."""
        return self._path

    def _post_load(self) -> None:
        """Validate category keys against the taxonomy once the file is read."""
        if self._taxonomy is not None:
            self._validate_category_keys()

    def _validate_category_keys(self) -> None:
        """
        Extract category keys from markdown and validate against taxonomy.

        Raises:
            ValueError: If any category key is not valid in the taxonomy.
        """
        if self._content is None or self._taxonomy is None:
            return

        # Skip validation for empty taxonomies (e.g., in tests). Empty taxonomies
        # have no nodes, so we skip rather than reject every key.
        try:
            has_nodes_by_key = hasattr(self._taxonomy, "_nodes_by_key")
            if has_nodes_by_key and not self._taxonomy._nodes_by_key:
                return
        except AttributeError:
            pass

        keys = self.CATEGORY_KEY_PATTERN.findall(self._content)
        invalid_keys: list[str] = [
            key for key in keys if not self._taxonomy.is_valid_key(key)
        ]

        if invalid_keys:
            msg = f"Invalid category keys in merchant rules: {invalid_keys}"
            raise ValueError(msg)

    def extract_category_keys(self) -> list[str]:
        """
        Extract all category keys from the rules file.

        Returns:
            List of category keys found in the rules file.
        """
        if self._content is None:
            self.load()

        if self._content is None:
            return []

        return self.CATEGORY_KEY_PATTERN.findall(self._content)

    def update_category_keys(self, key_mappings: dict[str, str]) -> None:
        """
        Update category keys in the rules file.

        This is used during taxonomy migrations to keep the rules file
        in sync when categories are renamed, removed, or merged.

        Args:
            key_mappings: Dictionary mapping old keys to new keys.
                         Example: {"old_key": "new_key"}
        """
        if not self._path.exists():
            return

        content = self._path.read_text()

        def replace_key(match: re.Match[str]) -> str:
            old_key = match.group(1)
            new_key = key_mappings.get(old_key, old_key)
            return f"**Category:** `{new_key}`"

        updated_content = self.CATEGORY_KEY_PATTERN.sub(replace_key, content)

        if updated_content != content:
            self._path.write_text(updated_content)
            self._content = updated_content
