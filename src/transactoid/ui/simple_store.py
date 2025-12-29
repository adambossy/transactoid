"""Simple in-memory store for ChatKit server."""

from __future__ import annotations

from typing import Any, Literal
import uuid

from chatkit.store import Store
from chatkit.types import Page, ThreadItem, ThreadMetadata


class SimpleInMemoryStore(Store[Any]):
    """Simple in-memory store implementation for ChatKit."""

    def __init__(self) -> None:
        """Initialize the in-memory store."""
        self._threads: dict[str, ThreadMetadata] = {}
        # thread_id -> item_id -> item
        self._items: dict[str, dict[str, ThreadItem]] = {}
        self._attachments: dict[str, Any] = {}

    def generate_thread_id(self, context: Any) -> str:
        """Generate a unique thread ID."""
        return str(uuid.uuid4())

    def generate_item_id(
        self,
        item_type: Literal[
            "thread",
            "message",
            "tool_call",
            "task",
            "workflow",
            "attachment",
            "sdk_hidden_context",
        ],
        thread: ThreadMetadata,
        context: Any,
    ) -> str:
        """Generate a unique item ID."""
        return f"{item_type}_{uuid.uuid4()}"

    async def save_thread(self, thread: ThreadMetadata, context: Any) -> None:
        """Save a thread."""
        self._threads[thread.id] = thread
        if thread.id not in self._items:
            self._items[thread.id] = {}

    async def load_thread(self, thread_id: str, context: Any) -> ThreadMetadata:
        """Load a thread by ID."""
        if thread_id not in self._threads:
            raise ValueError(f"Thread {thread_id} not found")
        return self._threads[thread_id]

    async def load_threads(
        self, limit: int, after: str | None, order: str, context: Any
    ) -> Page[ThreadMetadata]:
        """Load a page of threads."""
        threads = list(self._threads.values())
        # Simple pagination (not optimal but works for demo)
        if after:
            start_idx = next(
                (i for i, t in enumerate(threads) if t.id == after), 0
            ) + 1
        else:
            start_idx = 0

        page_threads = threads[start_idx : start_idx + limit]
        has_more = start_idx + limit < len(threads)

        return Page(data=page_threads, has_more=has_more)

    async def delete_thread(self, thread_id: str, context: Any) -> None:
        """Delete a thread."""
        if thread_id in self._threads:
            del self._threads[thread_id]
        if thread_id in self._items:
            del self._items[thread_id]

    async def save_item(
        self, thread_id: str, item: ThreadItem, context: Any
    ) -> None:
        """Save a thread item."""
        if thread_id not in self._items:
            self._items[thread_id] = {}
        self._items[thread_id][item.id] = item

    async def add_thread_item(
        self, thread_id: str, item: ThreadItem, context: Any
    ) -> None:
        """Add a thread item."""
        await self.save_item(thread_id, item, context)

    async def load_item(
        self, thread_id: str, item_id: str, context: Any
    ) -> ThreadItem:
        """Load a thread item by ID."""
        if thread_id not in self._items or item_id not in self._items[thread_id]:
            raise ValueError(f"Item {item_id} not found in thread {thread_id}")
        return self._items[thread_id][item_id]

    async def load_thread_items(
        self,
        thread_id: str,
        after: str | None,
        limit: int,
        order: str,
        context: Any,
    ) -> Page[ThreadItem]:
        """Load a page of thread items."""
        if thread_id not in self._items:
            return Page(data=[], has_more=False)

        items = list(self._items[thread_id].values())

        # Simple pagination
        if after:
            start_idx = (
                next((i for i, item in enumerate(items) if item.id == after), 0) + 1
            )
        else:
            start_idx = 0

        page_items = items[start_idx : start_idx + limit]
        has_more = start_idx + limit < len(items)

        return Page(data=page_items, has_more=has_more)

    async def delete_thread_item(
        self, thread_id: str, item_id: str, context: Any
    ) -> None:
        """Delete a thread item."""
        if thread_id in self._items and item_id in self._items[thread_id]:
            del self._items[thread_id][item_id]

    async def save_attachment(self, attachment: Any, context: Any) -> None:
        """Save an attachment."""
        self._attachments[attachment.id] = attachment

    async def load_attachment(self, attachment_id: str, context: Any) -> Any:
        """Load an attachment by ID."""
        if attachment_id not in self._attachments:
            raise ValueError(f"Attachment {attachment_id} not found")
        return self._attachments[attachment_id]

    async def delete_attachment(self, attachment_id: str, context: Any) -> None:
        """Delete an attachment."""
        if attachment_id in self._attachments:
            del self._attachments[attachment_id]
