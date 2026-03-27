"""Breakpoint Renderer — gutter overlay for breakpoint markers and execution pointer.

Draws into the ZenSourceView.do_snapshot() pipeline alongside diff bars,
color previews, and diagnostics. Follows the GutterDiffRenderer pattern.
"""

from gi.repository import Gdk, Graphene, Gtk, GtkSource

from themes import get_theme

from .breakpoint_manager import BreakpointManager

# Breakpoint circle diameter (pixels)
_BP_DIAMETER = 10
# Execution pointer arrow size
_ARROW_SIZE = 8
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

    @property
    def has_content(self) -> bool:
        """True if there's anything to draw (breakpoints or current line)."""
        if self._current_line is not None:
            return True
        if self._file_path:
            return self._breakpoint_mgr.has_breakpoints(self._file_path)
        return False

    def draw(self, snapshot, vis_range, fold_unsafe=None):
        """Draw breakpoint markers and current-line highlight.

        Called from ZenSourceView._do_custom_snapshot().
        vis_range: (start_ln, end_ln) tuple (0-based line numbers).
        """
        if not self._enabled:
            return
        if not self._file_path and self._current_line is None:
            return

        view = self._view
        buf = view.get_buffer()
        if not buf:
            return

        start_ln, end_ln = vis_range
        if fold_unsafe is None:
            fold_unsafe = getattr(view, "_fold_unsafe_lines", set())

        theme = get_theme()

        # Get gutter area position (left of text area)
        text_x, _ = view.buffer_to_window_coords(Gtk.TextWindowType.WIDGET, 0, 0)

        # Get breakpoints for this file
        breakpoints = {}
        if self._file_path:
            for bp in self._breakpoint_mgr.get_for_file(self._file_path):
                breakpoints[bp.line - 1] = bp  # Convert 1-based to 0-based

        # Prepare colors
        bp_color = Gdk.RGBA()
        bp_color.parse("#E51400")  # Red for breakpoints

        bp_disabled_color = Gdk.RGBA()
        bp_disabled_color.parse(theme.fg_dim)
        bp_disabled_color.alpha = 0.5

        bp_conditional_color = Gdk.RGBA()
        bp_conditional_color.parse("#FF8C00")  # Orange for conditional

        bp_logpoint_color = Gdk.RGBA()
        bp_logpoint_color.parse("#3CB371")  # Green for logpoints

        arrow_color = Gdk.RGBA()
        arrow_color.parse("#FFCC00")  # Yellow for execution pointer

        current_line_bg = Gdk.RGBA()
        current_line_bg.parse("#FFCC00")
        current_line_bg.alpha = _CURRENT_LINE_ALPHA

        rect = Graphene.Rect()

        for line_num in range(start_ln, end_ln + 1):
            if line_num in fold_unsafe:
                continue

            has_bp = line_num in breakpoints
            is_current = self._current_line is not None and line_num == (self._current_line - 1)

            if not has_bp and not is_current:
                continue

            # Get line position
            it = buf.get_iter_at_line(line_num)
            if it is None:
                continue
            try:
                it = it[1]
            except (TypeError, IndexError):
                pass
            y, lh = view.get_line_yrange(it)
            _, wy = view.buffer_to_window_coords(Gtk.TextWindowType.WIDGET, 0, y)

            # Draw current line highlight (full width)
            if is_current:
                visible = view.get_visible_rect()
                rect.init(0, wy, visible.width + text_x, lh)
                snapshot.append_color(current_line_bg, rect)

            # Draw breakpoint circle in gutter
            if has_bp:
                bp = breakpoints[line_num]
                # Choose color based on breakpoint type
                if not bp.enabled:
                    color = bp_disabled_color
                elif bp.is_conditional:
                    color = bp_conditional_color
                elif bp.is_logpoint:
                    color = bp_logpoint_color
                else:
                    color = bp_color

                # Center the circle vertically in the line
                cx = max(text_x - _BP_DIAMETER - 6, 4)
                cy = wy + (lh - _BP_DIAMETER) // 2
                rect.init(cx, cy, _BP_DIAMETER, _BP_DIAMETER)
                # Draw as a filled rectangle (approximating a circle)
                snapshot.push_rounded_clip(self._make_rounded_rect(cx, cy, _BP_DIAMETER, _BP_DIAMETER, _BP_DIAMETER // 2))
                rect.init(cx, cy, _BP_DIAMETER, _BP_DIAMETER)
                snapshot.append_color(color, rect)
                snapshot.pop()

            # Draw execution arrow in gutter
            if is_current:
                ax = max(text_x - _ARROW_SIZE - 4, 2)
                ay = wy + (lh - _ARROW_SIZE) // 2
                # Draw arrow as a small rectangle (simplified)
                rect.init(ax, ay, _ARROW_SIZE, _ARROW_SIZE)
                snapshot.push_rounded_clip(self._make_rounded_rect(ax, ay, _ARROW_SIZE, _ARROW_SIZE, 2))
                snapshot.append_color(arrow_color, rect)
                snapshot.pop()

    @staticmethod
    def _make_rounded_rect(x, y, w, h, radius):
        """Create a Gsk.RoundedRect for clipping."""
        from gi.repository import Gsk

        rect = Graphene.Rect()
        rect.init(x, y, w, h)
        size = Graphene.Size()
        size.init(radius, radius)
        rounded = Gsk.RoundedRect()
        rounded.init(rect, size, size, size, size)
        return rounded
