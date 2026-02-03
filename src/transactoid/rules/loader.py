from __future__ import annotations

from pathlib import Path
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from transactoid.taxonomy.core import Taxonomy


class MerchantRulesLoader:
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
        self._rules_path = rules_path
        self._taxonomy = taxonomy
        self._content: str | None = None

    @property
    def rules_path(self) -> Path:
        """Return the rules file path."""
        return self._rules_path

    def load(self) -> str:
        """
        Load rules file and return content for prompt injection.

        Content is cached after first load. Subsequent calls return the
        cached content without re-reading from disk.

        Returns:
            The raw content of the rules file, or empty string if file
            doesn't exist.

        Raises:
            ValueError: If taxonomy is set and any category key is invalid.
        """
        if self._content is not None:
            return self._content

        if not self._rules_path.exists():
            self._content = ""
            return ""

        self._content = self._rules_path.read_text()

        if self._taxonomy is not None:
            self._validate_category_keys()

        return self._content

    def _validate_category_keys(self) -> None:
        """
        Extract category keys from markdown and validate against taxonomy.

        Raises:
            ValueError: If any category key is not valid in the taxonomy.
        """
        if self._content is None or self._taxonomy is None:
            return

        keys = self.CATEGORY_KEY_PATTERN.findall(self._content)
        invalid_keys: list[str] = []

        for key in keys:
            if not self._taxonomy.is_valid_key(key):
                invalid_keys.append(key)

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
        if not self._rules_path.exists():
            return

        content = self._rules_path.read_text()

        def replace_key(match: re.Match[str]) -> str:
            old_key = match.group(1)
            new_key = key_mappings.get(old_key, old_key)
            return f"**Category:** `{new_key}`"

        updated_content = self.CATEGORY_KEY_PATTERN.sub(replace_key, content)

        if updated_content != content:
            self._rules_path.write_text(updated_content)
            self._content = updated_content
