"""Tests for editor/gutter_diff_renderer.py — git diff computation logic.

Tests the diff computation, HEAD content handling, and gutter renderer wiring.
GTK drawing is not tested here.
"""

from unittest.mock import MagicMock, patch

from editor.gutter_diff_renderer import _NO_REPO, GutterDiffRenderer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_renderer(buffer_text="line1\nline2\nline3\n"):
    """Create a GutterDiffRenderer with a mock view and buffer."""
    buf = MagicMock()
    start_iter = MagicMock()
    end_iter = MagicMock()
    buf.get_start_iter.return_value = start_iter
    buf.get_end_iter.return_value = end_iter
    buf.get_text.return_value = buffer_text

    view = MagicMock()
    view.get_buffer.return_value = buf

    with patch("editor.gutter_diff_renderer.GLib"):
        renderer = GutterDiffRenderer(view)
    return renderer, view, buf


# ---------------------------------------------------------------------------
# Diff computation
# ---------------------------------------------------------------------------


class TestComputeDiff:
    """Test _compute_diff logic against HEAD content."""

    def test_no_head_content_no_repo(self):
        """File outside any git repo — no diff indicators."""
        renderer, view, buf = _make_renderer("hello\n")
        renderer._head_content = _NO_REPO
        renderer._compute_diff()
        assert renderer._diff_lines == {}

    def test_no_head_new_file(self):
        """New file in repo (HEAD is None) — all lines are added."""
        renderer, view, buf = _make_renderer("line1\nline2\nline3\n")
        renderer._file_path = "/some/file.py"
        renderer._head_content = None
        renderer._compute_diff()
        assert renderer._diff_lines == {0: "add", 1: "add", 2: "add"}

    def test_no_head_no_file_path(self):
        """No file path set — no diff even with None head."""
        renderer, view, buf = _make_renderer("line1\n")
        renderer._file_path = None
        renderer._head_content = None
        renderer._compute_diff()
        assert renderer._diff_lines == {}

    def test_identical_content(self):
        """No changes — empty diff."""
        text = "line1\nline2\nline3\n"
        renderer, view, buf = _make_renderer(text)
        renderer._head_content = text
        renderer._compute_diff()
        assert renderer._diff_lines == {}

    def test_added_lines(self):
        """Lines inserted in the middle."""
        renderer, view, buf = _make_renderer("line1\nnew_line\nline2\n")
        renderer._head_content = "line1\nline2\n"
        renderer._compute_diff()
        assert renderer._diff_lines.get(1) == "add"

    def test_changed_lines(self):
        """Lines modified (replace)."""
        renderer, view, buf = _make_renderer("line1\nmodified\nline3\n")
        renderer._head_content = "line1\nline2\nline3\n"
        renderer._compute_diff()
        assert renderer._diff_lines.get(1) == "change"

    def test_deleted_lines(self):
        """Lines removed."""
        renderer, view, buf = _make_renderer("line1\nline3\n")
        renderer._head_content = "line1\nline2\nline3\n"
        renderer._compute_diff()
        # Deleted line marker appears at the position where deletion occurred
        assert "del" in renderer._diff_lines.values()

    def test_multiple_changes(self):
        """Multiple regions changed at once."""
        renderer, view, buf = _make_renderer("new1\nline2\nnew3\n")
        renderer._head_content = "line1\nline2\nline3\n"
        renderer._compute_diff()
        assert renderer._diff_lines.get(0) == "change"
        assert renderer._diff_lines.get(2) == "change"
        assert 1 not in renderer._diff_lines

    def test_no_buffer_clears_diff(self):
        """If buffer is gone, diff should be cleared."""
        renderer, view, buf = _make_renderer()
        renderer._diff_lines = {0: "add"}
        view.get_buffer.return_value = None
        renderer._compute_diff()
        assert renderer._diff_lines == {}


# ---------------------------------------------------------------------------
# Gutter renderer wiring
# ---------------------------------------------------------------------------


class TestGutterRendererWiring:
    """Test that diff data is pushed to the gutter renderer."""

    def test_gutter_renderer_updated_on_diff_change(self):
        renderer, view, buf = _make_renderer("line1\nnew\nline2\n")
        gutter = MagicMock()
        renderer._gutter_renderer = gutter
        renderer._head_content = "line1\nline2\n"
        renderer._compute_diff()
        gutter.set_diff_lines.assert_called_once_with(renderer._diff_lines)

    def test_gutter_renderer_not_called_if_none(self):
        """No crash when gutter renderer is not set."""
        renderer, view, buf = _make_renderer("new\n")
        renderer._gutter_renderer = None
        renderer._file_path = "/test.py"
        renderer._head_content = None
        renderer._compute_diff()
        # Should not raise

    def test_gutter_renderer_not_called_when_diff_unchanged(self):
        renderer, view, buf = _make_renderer("same\n")
        renderer._head_content = "same\n"
        gutter = MagicMock()
        renderer._gutter_renderer = gutter
        # First compute — sets diff to {}
        renderer._compute_diff()
        gutter.set_diff_lines.assert_not_called()  # diff_lines was already {}


# ---------------------------------------------------------------------------
# HEAD content management
# ---------------------------------------------------------------------------


class TestHeadContent:
    """Test _set_head_content and sentinel handling."""

    def test_set_head_content_triggers_diff(self):
        renderer, view, buf = _make_renderer("line1\n")
        renderer._file_path = "/test.py"
        with patch.object(renderer, "_compute_diff") as mock_diff:
            renderer._set_head_content("line1\n")
            mock_diff.assert_called_once()
        assert renderer._head_content == "line1\n"

    def test_no_repo_sentinel(self):
        renderer, view, buf = _make_renderer()
        renderer._set_head_content(_NO_REPO)
        assert renderer._head_content is _NO_REPO

    def test_refresh_head_calls_fetch(self):
        renderer, view, buf = _make_renderer()
        with patch.object(renderer, "_fetch_head_content") as mock_fetch:
            renderer.refresh_head()
            mock_fetch.assert_called_once()


# ---------------------------------------------------------------------------
# Debounced buffer change
# ---------------------------------------------------------------------------


class TestBufferChanged:
    """Test debounced buffer change handling."""

    def test_buffer_change_schedules_timeout(self):
        with patch("editor.gutter_diff_renderer.GLib") as mock_glib:
            renderer, view, buf = _make_renderer()
            mock_glib.timeout_add.return_value = 42
            renderer._on_buffer_changed(buf)
            mock_glib.timeout_add.assert_called_with(500, renderer._schedule_diff_update)
            assert renderer._update_timeout_id == 42

    def test_buffer_change_replaces_pending_timeout(self):
        with patch("editor.gutter_diff_renderer.GLib") as mock_glib:
            renderer, view, buf = _make_renderer()
            renderer._update_timeout_id = 10
            mock_glib.timeout_add.return_value = 20
            renderer._on_buffer_changed(buf)
            mock_glib.source_remove.assert_called_with(10)

    def test_schedule_diff_update_clears_timeout(self):
        renderer, view, buf = _make_renderer()
        renderer._update_timeout_id = 99
        with patch.object(renderer, "_compute_diff"):
            result = renderer._schedule_diff_update()
        assert renderer._update_timeout_id is None
        assert result is False  # one-shot
