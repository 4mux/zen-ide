"""Breakpoint Renderer — gutter overlay for breakpoint markers and execution pointer.

Draws into the ZenSourceView.do_snapshot() pipeline alongside diff bars,
color previews, and diagnostics. Follows the GutterDiffRenderer pattern.
"""

from gi.repository import Gdk, Graphene, Gtk, GtkSource

from .breakpoint_manager import BreakpointManager

# Current line highlight alpha
_CURRENT_LINE_ALPHA = 0.15


class BreakpointRenderer:
    """Draws breakpoint markers and current-line highlight in the editor gutter."""

    def __init__(self, view: GtkSource.View, breakpoint_mgr: BreakpointManager):
        self._view = view
        self._breakpoint_mgr = breakpoint_mgr
        self._file_path: str = ""
        self._current_line: int | None = None  # 1-based execution pointer line
        self._enabled = True

    def set_file_path(self, file_path: str) -> None:
        """Set the file path for this view."""
        self._file_path = file_path

    def set_current_line(self, line: int | None) -> None:
        """Set/clear the current execution pointer (1-based line number)."""
        self._current_line = line
        self._view.queue_draw()
        # Propagate to the gutter renderer so the yellow dot is drawn/cleared
        fm = getattr(self._view, "_fold_manager", None)
        if fm and hasattr(fm, "_bp_renderer"):
            fm._bp_renderer.set_current_line(line)

    @property
    def has_content(self) -> bool:
        """True if there's anything to draw (current execution line)."""
        return self._current_line is not None

    def draw(self, snapshot, vis_range, fold_unsafe=None):
        """Draw current-line highlight and execution arrow.

        Breakpoint dots are now drawn by LineNumberFoldRenderer in the gutter.
        Called from ZenSourceView._do_custom_snapshot().
        vis_range: (start_ln, end_ln) tuple (0-based line numbers).
        """
        if not self._enabled:
            return
        if self._current_line is None:
            return

        view = self._view
        buf = view.get_buffer()
        if not buf:
            return

        line_num = self._current_line - 1
        start_ln, end_ln = vis_range
        if line_num < start_ln or line_num > end_ln:
            return
        if fold_unsafe is None:
            fold_unsafe = getattr(view, "_fold_unsafe_lines", set())
        if line_num in fold_unsafe:
            return

        # Get line position
        it = buf.get_iter_at_line(line_num)
        if it is None:
            return
        try:
            it = it[1]
        except (TypeError, IndexError):
            pass
        y, lh = view.get_line_yrange(it)
        _, wy = view.buffer_to_window_coords(Gtk.TextWindowType.WIDGET, 0, y)
        text_x, _ = view.buffer_to_window_coords(Gtk.TextWindowType.WIDGET, 0, 0)

        # Current line highlight (full width, yellow tint)
        current_line_bg = Gdk.RGBA()
        current_line_bg.parse("#FFCC00")
        current_line_bg.alpha = _CURRENT_LINE_ALPHA

        rect = Graphene.Rect()
        visible = view.get_visible_rect()
        rect.init(0, wy, visible.width + text_x, lh)
        snapshot.append_color(current_line_bg, rect)
