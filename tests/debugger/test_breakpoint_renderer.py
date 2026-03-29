"""Tests for debugger/breakpoint_renderer.py — gutter rendering logic."""

from unittest.mock import MagicMock

from debugger.breakpoint_manager import Breakpoint, BreakpointManager
from debugger.breakpoint_renderer import BreakpointRenderer


def _make_renderer():
    view = MagicMock()
    mgr = MagicMock(spec=BreakpointManager)
    mgr.has_breakpoints.return_value = False
    mgr.get_for_file.return_value = []
    renderer = BreakpointRenderer(view, mgr)
    return renderer, view, mgr


class TestInit:
    """Test renderer initialization."""

    def test_default_state(self):
        renderer, view, mgr = _make_renderer()
        assert renderer._file_path == ""
        assert renderer._current_line is None
        assert renderer._enabled is True

    def test_set_file_path(self):
        renderer, view, mgr = _make_renderer()
        renderer.set_file_path("/test.py")
        assert renderer._file_path == "/test.py"


class TestCurrentLine:
    """Test execution pointer management."""

    def test_set_current_line(self):
        renderer, view, mgr = _make_renderer()
        renderer.set_current_line(42)
        assert renderer._current_line == 42
        view.queue_draw.assert_called_once()

    def test_clear_current_line(self):
        renderer, view, mgr = _make_renderer()
        renderer.set_current_line(42)
        renderer.set_current_line(None)
        assert renderer._current_line is None


class TestHasContent:
    """Test has_content property."""

    def test_no_content_by_default(self):
        renderer, view, mgr = _make_renderer()
        assert renderer.has_content is False

    def test_has_content_with_current_line(self):
        renderer, view, mgr = _make_renderer()
        renderer.set_current_line(10)
        assert renderer.has_content is True

    def test_no_content_with_only_breakpoints(self):
        # Breakpoint dots are now drawn by LineNumberFoldRenderer,
        # so BreakpointRenderer only has content for execution pointer.
        renderer, view, mgr = _make_renderer()
        renderer.set_file_path("/test.py")
        mgr.has_breakpoints.return_value = True
        assert renderer.has_content is False

    def test_no_content_without_file_path(self):
        renderer, view, mgr = _make_renderer()
        mgr.has_breakpoints.return_value = True
        assert renderer.has_content is False


class TestDraw:
    """Test draw method behavior."""

    def test_draw_skips_when_disabled(self):
        renderer, view, mgr = _make_renderer()
        renderer._enabled = False
        snapshot = MagicMock()
        renderer.draw(snapshot, (0, 10))
        snapshot.append_color.assert_not_called()

    def test_draw_skips_when_no_content(self):
        renderer, view, mgr = _make_renderer()
        snapshot = MagicMock()
        renderer.draw(snapshot, (0, 10))
        snapshot.append_color.assert_not_called()

    def test_draw_skips_fold_unsafe_lines(self):
        renderer, view, mgr = _make_renderer()
        renderer.set_file_path("/test.py")
        mgr.get_for_file.return_value = [Breakpoint(file_path="/test.py", line=5)]
        mgr.has_breakpoints.return_value = True

        # Set up view mock to handle buffer operations
        buf = MagicMock()
        view.get_buffer.return_value = buf
        view.buffer_to_window_coords.return_value = (50, 0)

        snapshot = MagicMock()
        # Line 4 (0-based) is in fold_unsafe — should skip
        renderer.draw(snapshot, (0, 10), fold_unsafe={4})
        # Should not render the breakpoint at line 5 (0-based: 4)
        snapshot.push_rounded_clip.assert_not_called()
