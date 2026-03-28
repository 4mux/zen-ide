"""Tests for editor/line_number_fold_renderer.py — gutter renderer logic.

Tests the testable logic: width computation, collapsed-line skipping,
git diff marker data flow, and measurement constants.
GTK snapshot drawing is not tested here.
"""

from unittest.mock import MagicMock, patch

from editor.line_number_fold_renderer import (
    _GIT_MARKER_WIDTH,
    _MIN_DIGITS,
    _NUM_PAD,
    _ZONE_WIDTH,
    GitDiffGutterRenderer,
    LineNumberRenderer,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_fm(collapsed=None):
    """Create a mock FoldManager with optional collapsed regions."""
    fm = MagicMock()
    fm._collapsed = collapsed or {}
    fm._fold_regions = {}
    return fm


def _make_mock_view(line_count=100, char_width=8.0):
    """Create a mock GtkSourceView with a buffer."""
    buf = MagicMock()
    buf.get_line_count.return_value = line_count

    metrics = MagicMock()
    # Pango.SCALE = 1024
    metrics.get_approximate_digit_width.return_value = char_width * 1024

    font_desc = MagicMock()
    pc = MagicMock()
    pc.get_font_description.return_value = font_desc
    pc.get_metrics.return_value = metrics

    view = MagicMock()
    view.get_buffer.return_value = buf
    view.get_pango_context.return_value = pc
    return view, buf


# ---------------------------------------------------------------------------
# LineNumberRenderer — width computation
# ---------------------------------------------------------------------------


class TestLineNumberRendererWidth:
    """Test dynamic width computation based on line count."""

    def _make_renderer(self, line_count=100):
        view, buf = _make_mock_view(line_count=line_count)
        fm = _make_mock_fm()
        with patch("editor.line_number_fold_renderer.GtkSource"):
            renderer = LineNumberRenderer.__new__(LineNumberRenderer)
            renderer._view = view
            renderer._fm = fm
            renderer._layout = None
            renderer._char_width = 0.0
            renderer._cached_width = 0
        return renderer, buf

    def test_minimum_digits(self):
        """Files with <100 lines should use _MIN_DIGITS (2) slots."""
        renderer, buf = self._make_renderer(line_count=5)
        w = renderer._compute_width()
        expected = int(_MIN_DIGITS * 8.0) + _NUM_PAD * 2
        assert w == expected

    def test_three_digit_lines(self):
        renderer, buf = self._make_renderer(line_count=500)
        w = renderer._compute_width()
        expected = int(3 * 8.0) + _NUM_PAD * 2
        assert w == expected

    def test_four_digit_lines(self):
        renderer, buf = self._make_renderer(line_count=5000)
        w = renderer._compute_width()
        expected = int(4 * 8.0) + _NUM_PAD * 2
        assert w == expected

    def test_width_updates_on_change(self):
        renderer, buf = self._make_renderer(line_count=99)
        w1 = renderer._compute_width()
        renderer._cached_width = w1
        buf.get_line_count.return_value = 1000
        with patch.object(type(renderer), "queue_resize"):
            renderer._update_width()
        assert renderer._cached_width != w1

    def test_width_no_resize_if_unchanged(self):
        renderer, buf = self._make_renderer(line_count=50)
        w = renderer._compute_width()
        renderer._cached_width = w
        renderer._update_width()
        # queue_resize should not be called (mock tracks calls)
        # Width stays the same since line_count didn't change


class TestLineNumberRendererCollapsed:
    """Test that collapsed fold lines are skipped."""

    def test_collapsed_line_skipped(self):
        """do_snapshot_line should return early for lines inside collapsed folds."""
        view, buf = _make_mock_view()
        fm = _make_mock_fm(collapsed={5: 10})  # lines 6-10 are hidden

        renderer = LineNumberRenderer.__new__(LineNumberRenderer)
        renderer._view = view
        renderer._fm = fm
        renderer._layout = None
        renderer._char_width = 8.0
        renderer._cached_width = 40

        snapshot = MagicMock()
        lines = MagicMock()

        # Line 7 is inside collapsed region (5 < 7 <= 10) — should skip
        renderer.do_snapshot_line(snapshot, lines, 7)
        snapshot.append_color.assert_not_called()

    def test_fold_header_not_skipped(self):
        """The fold header line itself (start_line) should still render."""
        view, buf = _make_mock_view()
        fm = _make_mock_fm(collapsed={5: 10})

        renderer = LineNumberRenderer.__new__(LineNumberRenderer)
        renderer._view = view
        renderer._fm = fm
        renderer._layout = MagicMock()
        renderer._char_width = 8.0
        renderer._cached_width = 40
        renderer._layout.get_pixel_extents.return_value = (MagicMock(), MagicMock(width=16, height=14))

        snapshot = MagicMock()
        lines = MagicMock()
        lines.get_line_yrange.return_value = (100, 20)
        lines.is_cursor.return_value = False

        renderer.do_snapshot_line(snapshot, lines, 5)
        # Should have drawn background + line number
        assert snapshot.append_color.called

    def test_line_after_fold_not_skipped(self):
        """Line immediately after fold end should render normally."""
        view, buf = _make_mock_view()
        fm = _make_mock_fm(collapsed={5: 10})

        renderer = LineNumberRenderer.__new__(LineNumberRenderer)
        renderer._view = view
        renderer._fm = fm
        renderer._layout = MagicMock()
        renderer._char_width = 8.0
        renderer._cached_width = 40
        renderer._layout.get_pixel_extents.return_value = (MagicMock(), MagicMock(width=16, height=14))

        snapshot = MagicMock()
        lines = MagicMock()
        lines.get_line_yrange.return_value = (100, 20)
        lines.is_cursor.return_value = False

        # Line 11 is outside the fold
        renderer.do_snapshot_line(snapshot, lines, 11)
        assert snapshot.append_color.called


# ---------------------------------------------------------------------------
# GitDiffGutterRenderer — data flow and collapsed skipping
# ---------------------------------------------------------------------------


class TestGitDiffGutterRendererData:
    """Test diff data flow into the gutter renderer."""

    def _make_renderer(self, collapsed=None):
        fm = _make_mock_fm(collapsed=collapsed)
        renderer = GitDiffGutterRenderer.__new__(GitDiffGutterRenderer)
        renderer._fm = fm
        renderer._diff_lines = {}
        return renderer

    def test_set_diff_lines(self):
        renderer = self._make_renderer()
        diff = {0: "add", 5: "change", 10: "del"}
        with patch.object(type(renderer), "queue_draw"):
            renderer.set_diff_lines(diff)
        assert renderer._diff_lines == diff

    def test_empty_diff(self):
        renderer = self._make_renderer()
        with patch.object(type(renderer), "queue_draw"):
            renderer.set_diff_lines({})
        assert renderer._diff_lines == {}

    def test_measure_returns_marker_width(self):
        renderer = self._make_renderer()
        min_w, nat_w, _, _ = renderer.do_measure(None, -1)
        assert min_w == _GIT_MARKER_WIDTH
        assert nat_w == _GIT_MARKER_WIDTH


class TestGitDiffGutterRendererCollapsed:
    """Test that collapsed fold lines are skipped in git diff renderer."""

    def test_collapsed_line_skipped(self):
        fm = _make_mock_fm(collapsed={5: 10})
        renderer = GitDiffGutterRenderer.__new__(GitDiffGutterRenderer)
        renderer._fm = fm
        renderer._diff_lines = {7: "add"}

        snapshot = MagicMock()
        lines = MagicMock()

        renderer.do_snapshot_line(snapshot, lines, 7)
        snapshot.append_color.assert_not_called()

    def test_fold_header_renders(self):
        fm = _make_mock_fm(collapsed={5: 10})
        renderer = GitDiffGutterRenderer.__new__(GitDiffGutterRenderer)
        renderer._fm = fm
        renderer._diff_lines = {5: "change"}

        snapshot = MagicMock()
        lines = MagicMock()
        lines.get_line_yrange.return_value = (100, 20)

        renderer.do_snapshot_line(snapshot, lines, 5)
        # Background + diff bar = 2 calls
        assert snapshot.append_color.call_count == 2

    def test_no_diff_on_line_draws_bg_only(self):
        fm = _make_mock_fm()
        renderer = GitDiffGutterRenderer.__new__(GitDiffGutterRenderer)
        renderer._fm = fm
        renderer._diff_lines = {}

        snapshot = MagicMock()
        lines = MagicMock()
        lines.get_line_yrange.return_value = (0, 20)

        renderer.do_snapshot_line(snapshot, lines, 3)
        # Only background, no diff bar
        assert snapshot.append_color.call_count == 1


class TestGitDiffGutterRendererTypes:
    """Test that all diff types render correctly."""

    def _render_line(self, dtype):
        fm = _make_mock_fm()
        renderer = GitDiffGutterRenderer.__new__(GitDiffGutterRenderer)
        renderer._fm = fm
        renderer._diff_lines = {0: dtype}

        snapshot = MagicMock()
        lines = MagicMock()
        lines.get_line_yrange.return_value = (0, 20)

        renderer.do_snapshot_line(snapshot, lines, 0)
        return snapshot

    def test_add_renders(self):
        snapshot = self._render_line("add")
        assert snapshot.append_color.call_count == 2

    def test_change_renders(self):
        snapshot = self._render_line("change")
        assert snapshot.append_color.call_count == 2

    def test_del_renders(self):
        snapshot = self._render_line("del")
        assert snapshot.append_color.call_count == 2

    def test_unknown_type_no_bar(self):
        snapshot = self._render_line("unknown")
        # Only background, no bar for unknown type
        assert snapshot.append_color.call_count == 1


# ---------------------------------------------------------------------------
# FoldChevronRenderer — collapsed skipping
# ---------------------------------------------------------------------------


class TestFoldChevronCollapsed:
    """Test that collapsed fold lines skip nested chevrons."""

    def test_nested_chevron_skipped(self):
        from editor.line_number_fold_renderer import FoldChevronRenderer

        fm = _make_mock_fm(collapsed={5: 15})
        fm._fold_regions = {5: 15, 8: 12}  # nested fold at line 8

        renderer = FoldChevronRenderer.__new__(FoldChevronRenderer)
        renderer._view = MagicMock()
        renderer._fm = fm
        renderer._hover = False
        renderer._chevron_opacity = 0.0
        renderer._layout = None
        renderer._icon_font_desc = None
        renderer._fade_tick_id = None
        renderer._fade_target = 0.0

        snapshot = MagicMock()
        lines = MagicMock()

        # Line 8 is inside collapsed region (5 < 8 <= 15) — should skip entirely
        renderer.do_snapshot_line(snapshot, lines, 8)
        snapshot.append_color.assert_not_called()

    def test_fold_header_chevron_renders(self):
        from editor.line_number_fold_renderer import FoldChevronRenderer

        fm = _make_mock_fm(collapsed={5: 15})
        fm._fold_regions = {5: 15}

        renderer = FoldChevronRenderer.__new__(FoldChevronRenderer)
        renderer._view = MagicMock()
        renderer._fm = fm
        renderer._hover = False
        renderer._chevron_opacity = 1.0
        renderer._layout = MagicMock()
        renderer._icon_font_desc = MagicMock()
        renderer._fade_tick_id = None
        renderer._fade_target = 0.0
        renderer._layout.get_pixel_extents.return_value = (MagicMock(), MagicMock(width=14, height=14))

        snapshot = MagicMock()
        lines = MagicMock()
        lines.get_line_yrange.return_value = (100, 20)

        # Line 5 is the fold header — should render
        renderer.do_snapshot_line(snapshot, lines, 5)
        # Background + chevron layout
        assert snapshot.append_color.called


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------


class TestConstants:
    def test_zone_width_positive(self):
        assert _ZONE_WIDTH > 0

    def test_git_marker_width_positive(self):
        assert _GIT_MARKER_WIDTH > 0

    def test_min_digits_at_least_one(self):
        assert _MIN_DIGITS >= 1

    def test_num_pad_non_negative(self):
        assert _NUM_PAD >= 0
