"""Tests for the resize debounce logic in AIChatTerminalView.

Verifies that _poll_column_count debounces re-renders instead of
triggering them immediately on every column change, preventing lag
during paned maximize animations with heavy chat content.
"""

from unittest.mock import MagicMock

from ai.ai_chat_terminal import AIChatTerminalView

from ai import ai_chat_terminal as mod


def _make_view(**overrides):
    """Create a minimal AIChatTerminalView without __init__."""
    view = AIChatTerminalView.__new__(AIChatTerminalView)
    view._last_column_count = 80
    view._resize_rerender_source = None
    view._display_buffer = []
    view.messages = [{"role": "user", "content": "hello"}]

    terminal = MagicMock()
    terminal.get_column_count.return_value = 80
    view.terminal = terminal

    for k, v in overrides.items():
        setattr(view, k, v)
    return view


class TestPollColumnCountDebounce:
    """_poll_column_count schedules a debounced re-render."""

    def test_no_change_does_not_schedule(self, monkeypatch):
        """When column count hasn't changed, no timer is scheduled."""
        view = _make_view()
        timeout_calls = []
        monkeypatch.setattr(mod.GLib, "timeout_add", lambda ms, cb: timeout_calls.append((ms, cb)) or 1)

        view._poll_column_count()

        assert timeout_calls == []
        assert view._resize_rerender_source is None

    def test_change_schedules_debounced_rerender(self, monkeypatch):
        """Column change schedules a 300ms debounced re-render."""
        view = _make_view()
        view.terminal.get_column_count.return_value = 100

        timeout_calls = []
        monkeypatch.setattr(mod.GLib, "timeout_add", lambda ms, cb: timeout_calls.append((ms, cb)) or 42)

        view._poll_column_count()

        assert len(timeout_calls) == 1
        assert timeout_calls[0][0] == 300
        assert timeout_calls[0][1] == view._rerender_on_resize
        assert view._resize_rerender_source == 42
        assert view._last_column_count == 100

    def test_rapid_changes_cancel_previous_timer(self, monkeypatch):
        """Multiple rapid column changes cancel the previous timer (debounce)."""
        view = _make_view()

        source_ids = iter(range(10, 20))
        monkeypatch.setattr(mod.GLib, "timeout_add", lambda ms, cb: next(source_ids))
        removed = []
        monkeypatch.setattr(mod.GLib, "source_remove", lambda sid: removed.append(sid))

        # First change: 80 -> 90
        view.terminal.get_column_count.return_value = 90
        view._poll_column_count()
        first_source = view._resize_rerender_source

        # Second change: 90 -> 100
        view.terminal.get_column_count.return_value = 100
        view._poll_column_count()

        assert first_source in removed
        assert view._resize_rerender_source != first_source

    def test_continues_polling(self, monkeypatch):
        """_poll_column_count returns True to keep the timeout active."""
        view = _make_view()
        monkeypatch.setattr(mod.GLib, "timeout_add", lambda ms, cb: 1)

        assert view._poll_column_count() is True

    def test_stops_when_terminal_missing(self):
        """Returns False (stop polling) when terminal attr is missing."""
        view = _make_view()
        del view.terminal

        assert view._poll_column_count() is False

    def test_no_cancel_when_no_pending_timer(self, monkeypatch):
        """First column change doesn't try to cancel a non-existent timer."""
        view = _make_view()
        view.terminal.get_column_count.return_value = 120

        monkeypatch.setattr(mod.GLib, "timeout_add", lambda ms, cb: 99)
        source_remove_calls = []
        monkeypatch.setattr(mod.GLib, "source_remove", lambda sid: source_remove_calls.append(sid))

        view._poll_column_count()

        assert source_remove_calls == []
        assert view._resize_rerender_source == 99


class TestRerenderOnResize:
    """_rerender_on_resize clears its source ID and handles edge cases."""

    def test_clears_source_id(self, monkeypatch):
        """After firing, the rerender source ID is set to None."""
        view = _make_view(_resize_rerender_source=42, messages=[])

        result = view._rerender_on_resize()

        assert view._resize_rerender_source is None
        assert result is False

    def test_skips_rerender_without_messages(self, monkeypatch):
        """No re-render is attempted when messages list is empty."""
        view = _make_view(_resize_rerender_source=1, messages=[])

        result = view._rerender_on_resize()

        assert result is False
        assert view._resize_rerender_source is None


class TestResizePollingLifecycle:
    """Start/stop resize polling lifecycle."""

    def test_start_creates_poll_source(self, monkeypatch):
        view = _make_view(_resize_poll_source=None)
        monkeypatch.setattr(mod.GLib, "timeout_add", lambda ms, cb: 77)

        view._start_resize_polling(None)

        assert view._resize_poll_source == 77

    def test_start_is_idempotent(self, monkeypatch):
        """Starting polling when already active does not create a second timer."""
        view = _make_view(_resize_poll_source=77)
        calls = []
        monkeypatch.setattr(mod.GLib, "timeout_add", lambda ms, cb: calls.append(1) or 88)

        view._start_resize_polling(None)

        assert calls == []
        assert view._resize_poll_source == 77

    def test_stop_removes_source(self, monkeypatch):
        view = _make_view(_resize_poll_source=77)
        removed = []
        monkeypatch.setattr(mod.GLib, "source_remove", lambda sid: removed.append(sid))

        view._stop_resize_polling(None)

        assert 77 in removed
        assert view._resize_poll_source is None

    def test_stop_is_safe_when_not_polling(self):
        """Stopping when not polling does not raise."""
        view = _make_view(_resize_poll_source=None)

        view._stop_resize_polling(None)

        assert view._resize_poll_source is None


class TestResponseBufferPopulated:
    """_on_http_chunk must populate _response_buffer so resize can replay."""

    def test_chunk_appended_to_response_buffer(self, monkeypatch):
        """Each streaming chunk is captured in _response_buffer as bytes."""
        view = _make_view(
            _is_processing=True,
            _http_streaming=True,
            _response_buffer=[],
        )
        # Stub out settings and render path
        monkeypatch.setattr(mod, "get_setting", lambda *a, **kw: False)
        view._render_stream_chunk = MagicMock()
        view._last_data_time = 0

        view._on_http_chunk("hello ")
        view._on_http_chunk("world")

        assert len(view._response_buffer) == 2
        assert view._response_buffer[0] == b"hello "
        assert view._response_buffer[1] == b"world"
        # Verify render was still called for each chunk
        assert view._render_stream_chunk.call_count == 2

    def test_buffer_joinable_as_bytes(self, monkeypatch):
        """_response_buffer can be joined and decoded (used by _rerender_on_resize)."""
        view = _make_view(
            _is_processing=True,
            _http_streaming=True,
            _response_buffer=[],
        )
        monkeypatch.setattr(mod, "get_setting", lambda *a, **kw: False)
        view._render_stream_chunk = MagicMock()
        view._last_data_time = 0

        view._on_http_chunk("first ")
        view._on_http_chunk("second")

        raw = b"".join(view._response_buffer)
        assert raw.decode("utf-8") == "first second"

    def test_not_processing_skips_buffer(self, monkeypatch):
        """Chunks are ignored when not processing."""
        view = _make_view(
            _is_processing=False,
            _http_streaming=True,
            _response_buffer=[],
        )

        view._on_http_chunk("ignored")

        assert view._response_buffer == []


class TestDisplayBufferPopulated:
    """_display_buffer captures stream chunks and action text for resize replay."""

    def test_stream_chunk_appended_to_display_buffer(self, monkeypatch):
        """Each streaming chunk is captured in _display_buffer as a stream tuple."""
        view = _make_view(
            _is_processing=True,
            _http_streaming=True,
            _response_buffer=[],
        )
        monkeypatch.setattr(mod, "get_setting", lambda *a, **kw: False)
        view._render_stream_chunk = MagicMock()
        view._last_data_time = 0

        view._on_http_chunk("hello ")
        view._on_http_chunk("world")

        assert len(view._display_buffer) == 2
        assert view._display_buffer[0] == ("stream", b"hello ")
        assert view._display_buffer[1] == ("stream", b"world")

    def test_display_buffer_not_populated_when_not_processing(self, monkeypatch):
        """Display buffer is not populated when not processing."""
        view = _make_view(
            _is_processing=False,
            _http_streaming=True,
            _response_buffer=[],
        )

        view._on_http_chunk("ignored")

        assert view._display_buffer == []
