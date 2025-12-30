from __future__ import annotations

import os
import time
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown

from transactoid.orchestrators.stream_renderer import StreamRenderer


class MarkdownStreamRenderer(StreamRenderer):
    """Renderer with incremental markdown support using Rich.

    This renderer extends StreamRenderer to provide formatted markdown rendering
    using Rich library's Live context manager. It accumulates text deltas and
    re-renders the complete markdown on each update, providing proper formatting
    for headers, code blocks, lists, tables, and other markdown elements.

    The renderer automatically falls back to plain text rendering in non-TTY
    environments or when NO_COLOR/TRANSACTOID_PLAIN_TEXT env vars are set.
    """

    def __init__(self) -> None:
        """Initialize the markdown stream renderer."""
        super().__init__()
        self._console = Console()
        self._markdown_buffer: list[str] = []
        self._live: Live | None = None
        self._in_markdown_mode = False
        self._use_rich = self._should_use_rich()
        self._last_render_time = 0.0
        self._min_render_interval = 0.05  # 50ms = 20 FPS max

    def _should_use_rich(self) -> bool:
        """Check if Rich rendering is supported/desired.

        Returns:
            False if not TTY, NO_COLOR set, or TRANSACTOID_PLAIN_TEXT set
        """
        return (
            self._console.is_terminal
            and not os.getenv("NO_COLOR")
            and not os.getenv("TRANSACTOID_PLAIN_TEXT")
        )

    def on_output_text(self, delta: str) -> None:
        """Stream output text with markdown rendering.

        Args:
            delta: The text delta to render
        """
        if not self._use_rich:
            # Fallback to parent's plain rendering
            super().on_output_text(delta)
            return

        self._clear_thinking()

        if not self._in_markdown_mode:
            self._enter_markdown_mode()

        self._markdown_buffer.append(delta)
        self._update_markdown_display()

    def _enter_markdown_mode(self) -> None:
        """Initialize Live context for markdown streaming."""
        self._in_markdown_mode = True
        self._markdown_buffer = []
        self._live = Live(
            "",
            console=self._console,
            refresh_per_second=10,  # Limit refresh rate
            vertical_overflow="visible",
        )
        self._live.start()

    def _update_markdown_display(self) -> None:
        """Re-render accumulated markdown in Live context.

        This method rate-limits rendering to avoid excessive re-rendering
        and gracefully falls back to plain text if markdown parsing fails.
        """
        if not self._live:
            return

        current_time = time.time()

        # Rate limit to avoid excessive re-rendering
        if current_time - self._last_render_time < self._min_render_interval:
            return

        self._last_render_time = current_time

        text = "".join(self._markdown_buffer)
        try:
            markdown = Markdown(text)
            self._live.update(markdown)
        except Exception:
            # Graceful fallback on parse errors
            self._live.update(text)

    def _exit_markdown_mode(self) -> None:
        """Finalize markdown rendering and cleanup."""
        if self._live:
            self._live.stop()
            self._live = None
        self._in_markdown_mode = False
        self._markdown_buffer = []

    def on_tool_call_started(self, call_id: str, name: str) -> None:
        """Exit markdown mode before tool rendering.

        Args:
            call_id: The tool call ID
            name: The tool name
        """
        if self._in_markdown_mode:
            self._exit_markdown_mode()
            print()  # Add spacing
        super().on_tool_call_started(call_id, name)

    def end_turn(self, result: Any | None) -> None:
        """Cleanup markdown mode at turn end.

        Args:
            result: The turn result (may contain token usage)
        """
        if self._in_markdown_mode:
            self._exit_markdown_mode()
        super().end_turn(result)
