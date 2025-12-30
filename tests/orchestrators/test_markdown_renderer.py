from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from transactoid.orchestrators.markdown_renderer import MarkdownStreamRenderer
from transactoid.orchestrators.stream_renderer import StreamRenderer


def test_markdown_renderer_accumulates_deltas() -> None:
    """Renderer should accumulate text deltas in buffer."""
    # Input
    delta1 = "Hello "
    delta2 = "**world**"

    # Setup
    with patch("transactoid.orchestrators.markdown_renderer.Console"):
        renderer = MarkdownStreamRenderer()
        renderer._use_rich = True  # Force Rich mode for testing

    # Act
    renderer.on_output_text(delta1)
    renderer.on_output_text(delta2)

    # Expected
    expected_buffer = ["Hello ", "**world**"]

    # Assert
    assert renderer._markdown_buffer == expected_buffer


def test_markdown_renderer_enters_mode_on_first_delta() -> None:
    """Renderer should initialize Live context on first delta."""
    # Input
    delta = "text"

    # Setup
    with patch("transactoid.orchestrators.markdown_renderer.Console"):
        renderer = MarkdownStreamRenderer()
        renderer._use_rich = True  # Force Rich mode

    # Act - before first delta
    assert not renderer._in_markdown_mode

    # Act - after first delta
    renderer.on_output_text(delta)

    # Expected
    expected_mode = True
    expected_live_exists = True

    # Assert
    assert renderer._in_markdown_mode == expected_mode
    assert (renderer._live is not None) == expected_live_exists


def test_markdown_renderer_exits_mode_on_tool_call() -> None:
    """Renderer should exit markdown mode when tool call starts."""
    # Input
    text = "Some text"
    call_id = "call_1"
    tool_name = "run_sql"

    # Setup
    with patch("transactoid.orchestrators.markdown_renderer.Console"):
        renderer = MarkdownStreamRenderer()
        renderer._use_rich = True  # Force Rich mode

    # Act - enter markdown mode
    renderer.on_output_text(text)
    assert renderer._in_markdown_mode

    # Act - start tool call
    renderer.on_tool_call_started(call_id, tool_name)

    # Expected
    expected_mode = False
    expected_live = None

    # Assert
    assert renderer._in_markdown_mode == expected_mode
    assert renderer._live == expected_live


def test_markdown_renderer_handles_incomplete_markdown() -> None:
    """Renderer should not crash on incomplete markdown syntax."""
    # Input
    incomplete_samples = ["**bold", "```python\n", "def foo("]

    # Setup
    with patch("transactoid.orchestrators.markdown_renderer.Console"):
        renderer = MarkdownStreamRenderer()
        renderer._use_rich = True  # Force Rich mode

    # Act & Assert - these should not raise exceptions
    for sample in incomplete_samples:
        renderer._markdown_buffer = []
        renderer._in_markdown_mode = False
        renderer.on_output_text(sample)


def test_markdown_renderer_fallback_when_no_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Renderer should fallback to plain text when not TTY."""
    # Input
    monkeypatch.setenv("NO_COLOR", "1")

    # Setup
    with patch("transactoid.orchestrators.markdown_renderer.Console") as mock_console:
        mock_console.return_value.is_terminal = True

        # Act
        renderer = MarkdownStreamRenderer()

        # Expected
        expected_use_rich = False

        # Assert
        assert renderer._use_rich == expected_use_rich


def test_markdown_renderer_updates_live_context() -> None:
    """Renderer should update Live context with markdown content."""
    # Input
    delta1 = "# Header\n"
    delta2 = "Some text"

    # Setup
    with patch("transactoid.orchestrators.markdown_renderer.Console"):
        renderer = MarkdownStreamRenderer()
        renderer._use_rich = True  # Force Rich mode

        # Mock the Live context
        mock_live = Mock()
        renderer._live = mock_live

        # Act
        renderer._markdown_buffer = [delta1]
        renderer._last_render_time = 0.0  # Force render
        renderer._update_markdown_display()

        renderer._markdown_buffer.append(delta2)
        renderer._last_render_time = 0.0  # Force render again
        renderer._update_markdown_display()

    # Expected - Live.update should be called
    expected_calls = 2

    # Assert
    assert mock_live.update.call_count == expected_calls


def test_markdown_renderer_cleans_up_on_turn_end() -> None:
    """Renderer should exit markdown mode and cleanup at turn end."""
    # Input
    text = "Some markdown text"

    # Setup
    with patch("transactoid.orchestrators.markdown_renderer.Console"):
        renderer = MarkdownStreamRenderer()
        renderer._use_rich = True  # Force Rich mode

    # Act - enter markdown mode
    renderer.on_output_text(text)
    assert renderer._in_markdown_mode

    # Act - end turn
    renderer.end_turn(None)

    # Expected
    expected_mode = False
    expected_live = None
    expected_buffer = []

    # Assert
    assert renderer._in_markdown_mode == expected_mode
    assert renderer._live == expected_live
    assert renderer._markdown_buffer == expected_buffer


def test_markdown_renderer_rate_limits_updates() -> None:
    """Renderer should rate limit markdown re-rendering."""
    # Input
    delta1 = "Hello"
    delta2 = " world"

    # Setup
    with patch("transactoid.orchestrators.markdown_renderer.Console"):
        with patch("transactoid.orchestrators.markdown_renderer.time") as mock_time:
            # Mock time to always return the same value for both calls
            mock_time.time.return_value = 1000.0

            renderer = MarkdownStreamRenderer()
            renderer._use_rich = True  # Force Rich mode
            mock_live = Mock()
            renderer._live = mock_live
            renderer._last_render_time = 1000.0  # Set to current mocked time

            # Act - try to update twice
            renderer._markdown_buffer = [delta1]
            renderer._update_markdown_display()  # Should skip due to rate limit

            renderer._markdown_buffer.append(delta2)
            renderer._update_markdown_display()  # Should also skip

    # Expected - Live.update should not be called due to rate limiting
    expected_calls = 0

    # Assert
    assert mock_live.update.call_count == expected_calls


def test_markdown_renderer_uses_plain_text_when_disabled() -> None:
    """Renderer should use plain text rendering when Rich is disabled."""
    # Input
    delta = "Some text"

    # Setup
    with patch("transactoid.orchestrators.markdown_renderer.Console"):
        with patch.object(StreamRenderer, "on_output_text") as mock_parent:
            renderer = MarkdownStreamRenderer()
            renderer._use_rich = False  # Disable Rich

            # Act
            renderer.on_output_text(delta)

            # Expected - should call parent's plain text renderer
            expected_calls = 1

            # Assert
            assert mock_parent.call_count == expected_calls
            mock_parent.assert_called_once_with(delta)
