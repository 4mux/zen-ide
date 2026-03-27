"""
Color Preview Renderer - inline color swatches in the editor.

Draws small colored squares next to hex color strings (#RRGGBB or #RRGGBBAA)
in the editor, synchronized with scroll position and buffer changes.
"""

import re

from gi.repository import Gdk, GLib, Graphene, Gtk, GtkSource

# Match hex color patterns: #RGB, #RRGGBB, #RRGGBBAA
_HEX_COLOR_RE = re.compile(r"#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")

# Size of the color swatch square
_SWATCH_SIZE = 12
_SWATCH_MARGIN = 3
_BORDER_WIDTH = 1


class ColorPreviewRenderer:
    """Draws inline color swatches next to hex color strings in the editor."""

    def __init__(self, view: GtkSource.View):
        self._view = view
        self._color_positions = []  # [(line, col, hex_str), ...]
        self._update_timeout_id = None
        self._buffer_changed_id = None

        buf = view.get_buffer()
        if buf:
            self._buffer_changed_id = buf.connect("changed", self._on_buffer_changed)

    def _on_buffer_changed(self, buffer):
        """Debounced handler for buffer changes."""
        if self._update_timeout_id:
            GLib.source_remove(self._update_timeout_id)
        self._update_timeout_id = GLib.timeout_add(300, self._do_scan)

    def _do_scan(self):
        self._update_timeout_id = None
        self._scan_colors()
        return False

    def _scan_colors(self):
        """Scan entire buffer for hex color patterns."""
        view = self._view
        buf = view.get_buffer()
        if not buf:
            return

        total = buf.get_line_count()
        positions = []
        for ln in range(total):
            line_start = self._iter_at_line(buf, ln)
            line_end = line_start.copy()
            if not line_end.ends_line():
                line_end.forward_to_line_end()
            line_text = buf.get_text(line_start, line_end, False)

            for m in _HEX_COLOR_RE.finditer(line_text):
                hex_str = m.group(0)
                col = m.start()
                positions.append((ln, col, hex_str))

        self._color_positions = positions
        view.queue_draw()

    def draw(self, snapshot, vis_range=None, fold_unsafe=None):
        """Draw color swatches using GtkSnapshot (called from ZenSourceView.do_snapshot).

        vis_range: optional (start_ln, end_ln) tuple to avoid redundant get_visible_rect.
        fold_unsafe: optional set of line numbers where get_iter_location is unsafe.
        """
        if not self._color_positions:
            return

        view = self._view
        buf = view.get_buffer()
        if not buf:
            return

        # Use pre-computed visible range if available
        if vis_range is not None:
            vis_start_ln, vis_end_ln = vis_range
        else:
            visible = view.get_visible_rect()
            vis_start, _ = view.get_line_at_y(visible.y)
            vis_end, _ = view.get_line_at_y(visible.y + visible.height)
            vis_start_ln = vis_start.get_line()
            vis_end_ln = vis_end.get_line()

        rect = Graphene.Rect()
        border_color = Gdk.RGBA()
        border_color.red, border_color.green, border_color.blue, border_color.alpha = 0.5, 0.5, 0.5, 0.6

        for ln, col, hex_str in self._color_positions:
            if ln < vis_start_ln or ln > vis_end_ln:
                continue
            if fold_unsafe and ln in fold_unsafe:
                continue

            r, g, b, a = self._parse_color(hex_str)
            if r is None:
                continue

            # Position the swatch just after the hex string
            end_col = col + len(hex_str)
            it = self._iter_at_line_offset(buf, ln, end_col)
            if it is None:
                continue

            loc = view.get_iter_location(it)
            wx, wy = view.buffer_to_window_coords(Gtk.TextWindowType.WIDGET, loc.x, loc.y)

            # Center vertically in the line
            sy = wy + (loc.height - _SWATCH_SIZE) / 2
            sx = wx + _SWATCH_MARGIN

            # Draw checkerboard background (for transparency)
            if a < 1.0:
                self._draw_checkerboard(snapshot, sx, sy, _SWATCH_SIZE, _SWATCH_SIZE)

            # Draw the color fill
            fill_color = Gdk.RGBA()
            fill_color.red, fill_color.green, fill_color.blue, fill_color.alpha = r, g, b, a
            rect.init(sx, sy, _SWATCH_SIZE, _SWATCH_SIZE)
            snapshot.append_color(fill_color, rect)

            # Draw border using an inset trick: draw outer rect, then inner rect
            # covers the fill — simulating a 1px border
            bw = _BORDER_WIDTH
            from gi.repository import Gsk

            outline = Gsk.RoundedRect()
            outline.init_from_rect(rect, 0)
            border_widths = [bw, bw, bw, bw]
            border_colors = [border_color, border_color, border_color, border_color]
            snapshot.append_border(outline, border_widths, border_colors)

    def hit_test(self, widget_x, widget_y):
        """Test if (widget_x, widget_y) hits a color swatch. Returns (line, col, hex_str) or None."""
        if not self._color_positions:
            return None

        view = self._view
        buf = view.get_buffer()
        if not buf:
            return None

        for ln, col, hex_str in self._color_positions:
            end_col = col + len(hex_str)
            it = self._iter_at_line_offset(buf, ln, end_col)
            if it is None:
                continue

            loc = view.get_iter_location(it)
            wx, wy = view.buffer_to_window_coords(Gtk.TextWindowType.WIDGET, loc.x, loc.y)
            sy = wy + (loc.height - _SWATCH_SIZE) / 2
            sx = wx + _SWATCH_MARGIN

            if sx <= widget_x <= sx + _SWATCH_SIZE and sy <= widget_y <= sy + _SWATCH_SIZE:
                return (ln, col, hex_str)

        return None

    @staticmethod
    def _draw_checkerboard(snapshot, x, y, w, h):
        """Draw a checkerboard pattern to indicate transparency."""
        cell = 3
        rect = Graphene.Rect()
        white = Gdk.RGBA()
        white.red, white.green, white.blue, white.alpha = 1.0, 1.0, 1.0, 1.0
        gray = Gdk.RGBA()
        gray.red, gray.green, gray.blue, gray.alpha = 0.7, 0.7, 0.7, 1.0

        for row in range(int(h / cell) + 1):
            for col_i in range(int(w / cell) + 1):
                color = white if (row + col_i) % 2 == 0 else gray
                cx = x + col_i * cell
                cy = y + row * cell
                cw = min(cell, x + w - cx)
                ch = min(cell, y + h - cy)
                if cw > 0 and ch > 0:
                    rect.init(cx, cy, cw, ch)
                    snapshot.append_color(color, rect)

    @staticmethod
    def _parse_color(hex_str):
        """Parse hex color string to (r, g, b, a) floats. Returns (None,...) on failure."""
        h = hex_str.lstrip("#")
        try:
            if len(h) == 3:
                r = int(h[0] * 2, 16) / 255.0
                g = int(h[1] * 2, 16) / 255.0
                b = int(h[2] * 2, 16) / 255.0
                return r, g, b, 1.0
            elif len(h) == 6:
                r = int(h[0:2], 16) / 255.0
                g = int(h[2:4], 16) / 255.0
                b = int(h[4:6], 16) / 255.0
                return r, g, b, 1.0
            elif len(h) == 8:
                r = int(h[0:2], 16) / 255.0
                g = int(h[2:4], 16) / 255.0
                b = int(h[4:6], 16) / 255.0
                a = int(h[6:8], 16) / 255.0
                return r, g, b, a
        except ValueError:
            pass
        return None, None, None, None

    @staticmethod
    def _iter_at_line(buf, line):
        line_count = max(1, buf.get_line_count())
        safe_line = min(max(0, int(line)), line_count - 1)
        result = buf.get_iter_at_line(safe_line)
        if isinstance(result, (tuple, list)):
            if len(result) >= 2:
                if isinstance(result[0], bool) and not result[0]:
                    return buf.get_start_iter()
                return result[1]
            return buf.get_start_iter()
        return result

    @staticmethod
    def _iter_at_line_offset(buf, line, offset):
        line_iter = ColorPreviewRenderer._iter_at_line(buf, line)
        line_end = line_iter.copy()
        if not line_end.ends_line():
            line_end.forward_to_line_end()
        max_col = line_end.get_line_offset()
        safe_offset = min(max(0, int(offset)), max_col)
        safe_line = line_iter.get_line()

        result = buf.get_iter_at_line_offset(safe_line, safe_offset)
        if isinstance(result, (tuple, list)):
            if len(result) >= 2:
                return result[1] if result[0] else None
            return None
        return result
