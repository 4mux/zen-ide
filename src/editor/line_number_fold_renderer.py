"""
Gutter renderers for breakpoints, line numbers, and code folding.

Three separate GtkSource.GutterRenderers inserted left-to-right:

  1. BreakpointGutterRenderer — red dots for breakpoints (click to toggle)
  2. LineNumberRenderer       — centered line numbers
  3. FoldChevronRenderer       — fold chevrons (click to toggle fold)
"""

from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk, GtkSource, Pango

from icons import get_icon_font_name
from shared.utils import hex_to_gdk_rgba
from themes import get_theme

_CHEVRON_EXPANDED = "\U000f0140"  # nf-md-chevron_down (󰅀)
_CHEVRON_COLLAPSED = "\U000f0142"  # nf-md-chevron_right (󰅂)

_BP_DIAMETER = 7
_ZONE_WIDTH = 20  # Width for breakpoint and chevron renderers
_BP_LEFT_PAD = 6  # Left padding to avoid paned separator grab zone
_NUM_PAD = 4  # Right padding for line numbers
_MIN_DIGITS = 2  # Minimum digit slots
_GIT_MARKER_WIDTH = 3  # Width of git diff marker bar


# ---------------------------------------------------------------------------
# 1. Breakpoint gutter renderer (left column)
# ---------------------------------------------------------------------------


class BreakpointGutterRenderer(GtkSource.GutterRenderer):
    __gtype_name__ = "BreakpointGutterRenderer"

    def __init__(self, view):
        super().__init__()
        self._view = view
        self._breakpoint_mgr = None
        self._file_path = ""
        self._hover_line = -1
        self.set_xpad(0)
        self.set_ypad(0)

        self.connect("query-activatable", self._on_query_activatable)
        self.connect("activate", self._on_activate)

        self._pointer_cursor = Gdk.Cursor.new_from_name("pointer")
        self._default_cursor = Gdk.Cursor.new_from_name("default")

        motion = Gtk.EventControllerMotion.new()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

    def set_breakpoint_source(self, breakpoint_mgr, file_path=""):
        self._breakpoint_mgr = breakpoint_mgr
        self._file_path = file_path

    def set_file_path(self, file_path):
        self._file_path = file_path

    def do_measure(self, _orientation, _for_size):
        return _ZONE_WIDTH, _ZONE_WIDTH, -1, -1

    def do_query_data(self, lines, line):
        pass

    def do_snapshot_line(self, snapshot, lines, line):
        # Paint gutter background per-line (so it doesn't extend past last line)
        theme = get_theme()
        line_y, line_h = lines.get_line_yrange(line, Gtk.TextWindowType.WIDGET)
        snapshot.append_color(
            hex_to_gdk_rgba(theme.line_number_bg, 1.0), Graphene.Rect().init(0, line_y, _ZONE_WIDTH, line_h)
        )

        if not self._breakpoint_mgr or not self._file_path:
            return

        bp = None
        for b in self._breakpoint_mgr.get_for_file(self._file_path):
            if b.line - 1 == line:
                bp = b
                break

        if bp is not None:
            if not bp.enabled:
                color = hex_to_gdk_rgba("#808080", 0.5)
            elif bp.is_conditional:
                color = hex_to_gdk_rgba("#FF8C00", 1.0)
            elif bp.is_logpoint:
                color = hex_to_gdk_rgba("#3CB371", 1.0)
            else:
                color = hex_to_gdk_rgba("#E51400", 1.0)
        elif line == self._hover_line:
            color = hex_to_gdk_rgba("#E51400", 0.25)
        else:
            return

        line_y, line_h = lines.get_line_yrange(line, Gtk.TextWindowType.WIDGET)
        cx = _BP_LEFT_PAD + (_ZONE_WIDTH - _BP_LEFT_PAD - _BP_DIAMETER) / 2
        cy = line_y + (line_h - _BP_DIAMETER) / 2
        rect = Graphene.Rect().init(cx, cy, _BP_DIAMETER, _BP_DIAMETER)
        rounded = _make_rounded_rect(cx, cy, _BP_DIAMETER, _BP_DIAMETER, _BP_DIAMETER // 2)
        snapshot.push_rounded_clip(rounded)
        snapshot.append_color(color, rect)
        snapshot.pop()

    def _on_motion(self, controller, x, y):
        # y is in renderer-local coords; translate to view widget coords
        # by adding the renderer's allocation y offset
        alloc = self.get_allocation()
        view_y = int(y) + alloc.y
        bx, by = self._view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, 0, view_y)
        _, it = self._view.get_iter_at_location(bx, by)
        new_line = it.get_line()
        if new_line != self._hover_line:
            self._hover_line = new_line
            self.set_cursor(self._pointer_cursor)
            self.queue_draw()

    def _on_leave(self, controller):
        self._hover_line = -1
        self.set_cursor(self._default_cursor)
        self.queue_draw()

    def _on_query_activatable(self, renderer, it, area):
        return True

    def _on_activate(self, renderer, it, area, button, state, n_presses):
        line = it.get_line() + 1
        print(f"[BP ACTIVATE] line={line} mgr={self._breakpoint_mgr is not None} file={self._file_path!r}")
        if self._breakpoint_mgr and self._file_path:
            result = self._breakpoint_mgr.toggle(self._file_path, line)
            print(f"[BP TOGGLE] added={result} bps={[b.line for b in self._breakpoint_mgr.get_for_file(self._file_path)]}")
            self.queue_draw()
            self._view.queue_draw()


# ---------------------------------------------------------------------------
# 2. Line number renderer (center column)
# ---------------------------------------------------------------------------


class LineNumberRenderer(GtkSource.GutterRenderer):
    __gtype_name__ = "LineNumberRenderer"

    def __init__(self, view, fold_manager):
        super().__init__()
        self._view = view
        self._fm = fold_manager
        self._layout = None
        self._char_width = 0.0
        self._cached_width = 0
        self.set_xpad(0)
        self.set_ypad(0)

        buf = view.get_buffer()
        if buf:
            buf.connect("notify::cursor-position", lambda *_: self.queue_draw())
            buf.connect("changed", lambda *_: self._update_width())

    def _ensure_char_width(self):
        if self._char_width > 0:
            return
        pc = self._view.get_pango_context()
        if pc is None:
            return
        font_desc = pc.get_font_description()
        if font_desc is None:
            return
        metrics = pc.get_metrics(font_desc)
        self._char_width = metrics.get_approximate_digit_width() / Pango.SCALE
        if self._char_width <= 0:
            self._char_width = 8.0

    def _compute_width(self):
        self._ensure_char_width()
        buf = self._view.get_buffer()
        line_count = buf.get_line_count() if buf else 1
        digits = max(_MIN_DIGITS, len(str(line_count)))
        return int(digits * self._char_width) + _NUM_PAD * 2

    def _update_width(self):
        new_w = self._compute_width()
        if new_w != self._cached_width:
            self._cached_width = new_w
            self.queue_resize()

    def do_measure(self, _orientation, _for_size):
        w = self._compute_width()
        self._cached_width = w
        return w, w, -1, -1

    def do_query_data(self, lines, line):
        pass

    def do_snapshot_line(self, snapshot, lines, line):
        if any(sl < line <= el for sl, el in self._fm._collapsed.items()):
            return

        # Paint gutter background per-line
        theme = get_theme()
        line_y_bg, line_h_bg = lines.get_line_yrange(line, Gtk.TextWindowType.WIDGET)
        snapshot.append_color(
            hex_to_gdk_rgba(theme.line_number_bg, 1.0), Graphene.Rect().init(0, line_y_bg, self._cached_width, line_h_bg)
        )
        is_current = lines.is_cursor(line)
        num_fg = hex_to_gdk_rgba(theme.fg_color if is_current else theme.line_number_fg, 1.0)

        if self._layout is None:
            self._layout = self._view.create_pango_layout("")

        self._layout.set_text(str(line + 1), -1)
        _ink, logical = self._layout.get_pixel_extents()
        line_y, line_h = lines.get_line_yrange(line, Gtk.TextWindowType.WIDGET)
        x = self._cached_width - logical.width - _NUM_PAD
        y = line_y + (line_h - logical.height) / 2

        snapshot.save()
        snapshot.translate(Graphene.Point().init(x, y))
        snapshot.append_layout(self._layout, num_fg)
        snapshot.restore()


# ---------------------------------------------------------------------------
# 3. Git diff marker renderer (between line numbers and chevrons)
# ---------------------------------------------------------------------------


class GitDiffGutterRenderer(GtkSource.GutterRenderer):
    __gtype_name__ = "GitDiffGutterRenderer"

    def __init__(self, fold_manager):
        super().__init__()
        self._fm = fold_manager
        self._diff_lines = {}  # line_num (0-based) -> "add" | "change" | "del"
        self.set_xpad(0)
        self.set_ypad(0)

    def set_diff_lines(self, diff_lines):
        """Update diff data (called from GutterDiffRenderer after recompute)."""
        self._diff_lines = diff_lines
        self.queue_draw()

    def do_measure(self, _orientation, _for_size):
        return _GIT_MARKER_WIDTH, _GIT_MARKER_WIDTH, -1, -1

    def do_query_data(self, lines, line):
        pass

    def do_snapshot_line(self, snapshot, lines, line):
        if any(sl < line <= el for sl, el in self._fm._collapsed.items()):
            return

        # Paint gutter background per-line
        theme = get_theme()
        line_y, line_h = lines.get_line_yrange(line, Gtk.TextWindowType.WIDGET)
        snapshot.append_color(
            hex_to_gdk_rgba(theme.line_number_bg, 1.0),
            Graphene.Rect().init(0, line_y, _GIT_MARKER_WIDTH, line_h),
        )

        dtype = self._diff_lines.get(line)
        if not dtype:
            return

        if dtype == "add":
            color = hex_to_gdk_rgba(theme.git_added, 0.9)
        elif dtype == "change":
            color = hex_to_gdk_rgba(theme.git_modified, 0.9)
        elif dtype == "del":
            color = hex_to_gdk_rgba(theme.git_deleted, 0.9)
        else:
            return

        if dtype == "del":
            snapshot.append_color(color, Graphene.Rect().init(0, line_y, _GIT_MARKER_WIDTH, min(line_h, 4)))
        else:
            snapshot.append_color(color, Graphene.Rect().init(0, line_y, _GIT_MARKER_WIDTH, line_h))


# ---------------------------------------------------------------------------
# 4. Fold chevron renderer (right column)
# ---------------------------------------------------------------------------


class FoldChevronRenderer(GtkSource.GutterRenderer):
    __gtype_name__ = "FoldChevronRenderer"

    def __init__(self, view, fold_manager):
        super().__init__()
        self._view = view
        self._fm = fold_manager
        self._hover = False
        self._chevron_opacity = 0.0
        self._fade_tick_id = None
        self._fade_target = 0.0
        self._layout = None
        self._icon_font_desc = None
        self.set_xpad(0)
        self.set_ypad(0)

        self.connect("query-activatable", self._on_query_activatable)
        self.connect("activate", self._on_activate)

        motion = Gtk.EventControllerMotion.new()
        motion.connect("enter", self._on_hover_enter)
        motion.connect("leave", self._on_hover_leave)
        self.add_controller(motion)

    def do_measure(self, _orientation, _for_size):
        return _ZONE_WIDTH, _ZONE_WIDTH, -1, -1

    def do_query_data(self, lines, line):
        pass

    def _ensure_layout(self):
        if self._layout is not None:
            return
        self._layout = self._view.create_pango_layout("")
        icon_font = get_icon_font_name()
        if icon_font:
            self._icon_font_desc = Pango.FontDescription.from_string(f"{icon_font} 14")
        else:
            pc = self._view.get_pango_context()
            if pc:
                self._icon_font_desc = pc.get_font_description().copy()
                self._icon_font_desc.set_size(14 * Pango.SCALE)

    def do_snapshot_line(self, snapshot, lines, line):
        if any(sl < line <= el for sl, el in self._fm._collapsed.items()):
            return

        # Paint editor background so chevron zone blends with the editor, not the gutter
        theme = get_theme()
        line_y, line_h = lines.get_line_yrange(line, Gtk.TextWindowType.WIDGET)
        snapshot.append_color(hex_to_gdk_rgba(theme.main_bg, 1.0), Graphene.Rect().init(0, line_y, _ZONE_WIDTH, line_h))

        fm = self._fm
        if line not in fm._fold_regions:
            return
        collapsed = line in fm._collapsed
        opacity = 1.0 if collapsed else self._chevron_opacity
        if opacity <= 0.01:
            return

        self._ensure_layout()
        theme = get_theme()
        chevron_fg = hex_to_gdk_rgba(theme.line_number_fg, 0.7 * opacity)

        icon = _CHEVRON_COLLAPSED if collapsed else _CHEVRON_EXPANDED
        self._layout.set_text(icon, -1)
        if self._icon_font_desc:
            self._layout.set_font_description(self._icon_font_desc)
        _ink, logical = self._layout.get_pixel_extents()

        line_y, line_h = lines.get_line_yrange(line, Gtk.TextWindowType.WIDGET)
        x = (_ZONE_WIDTH - logical.width) / 2
        y = line_y + (line_h - logical.height) / 2

        snapshot.save()
        snapshot.translate(Graphene.Point().init(x, y))
        snapshot.append_layout(self._layout, chevron_fg)
        snapshot.restore()

    # -- hover handling ---------------------------------------------------

    _FADE_STEP = 0.08

    def _on_hover_enter(self, controller, x, y):
        self._hover = True
        self._fade_target = 1.0
        self._start_fade()

    def _on_hover_leave(self, controller):
        self._hover = False
        self._fade_target = 0.0
        self._start_fade()

    def _start_fade(self):
        if self._fade_tick_id is not None:
            return
        self._fade_tick_id = GLib.timeout_add(16, self._fade_tick)

    def _fade_tick(self):
        if self._chevron_opacity < self._fade_target:
            self._chevron_opacity = min(self._chevron_opacity + self._FADE_STEP, 1.0)
        elif self._chevron_opacity > self._fade_target:
            self._chevron_opacity = max(self._chevron_opacity - self._FADE_STEP, 0.0)

        self.queue_draw()

        if abs(self._chevron_opacity - self._fade_target) < 0.01:
            self._chevron_opacity = self._fade_target
            self._fade_tick_id = None
            return False
        return True

    # -- click handling ---------------------------------------------------

    def _on_query_activatable(self, renderer, it, area):
        return it.get_line() in self._fm._fold_regions

    def _on_activate(self, renderer, it, area, button, state, n_presses):
        line = it.get_line()
        fm = self._fm
        if fm._toggle_pending:
            return
        fm._toggle_pending = True

        def _do_toggle():
            fm.toggle_fold(line)
            GLib.timeout_add(150, fm._clear_toggle_pending)
            return False

        GLib.timeout_add(30, _do_toggle)


def _make_rounded_rect(x, y, w, h, radius):
    rect = Graphene.Rect().init(x, y, w, h)
    size = Graphene.Size().init(radius, radius)
    rounded = Gsk.RoundedRect()
    rounded.init(rect, size, size, size, size)
    return rounded
