"""
Gutter renderer for code folding.

Provides a unified GutterRenderer that draws both line numbers and fold
chevrons in a single wider gutter column.  Used by FoldManager.
"""

from gi.repository import GLib, Graphene, Gsk, Gtk, GtkSource, Pango

from fonts import get_font_settings
from icons import ICON_FONT_FAMILY
from shared.utils import hex_to_gdk_rgba
from themes import get_theme

_CHEVRON_SIZE = 7
_CHEVRON_PAD = 6  # symmetric padding on each side of the chevron zone
_CHEVRON_COL_WIDTH = _CHEVRON_PAD + 14 + _CHEVRON_PAD  # pad + icon + pad
_NUM_PAD = 10  # equal padding on left and right of the number zone
_FIXED_DIGIT_COUNT = 4  # fixed digit count so the gutter never resizes


# ---------------------------------------------------------------------------
# Unified gutter renderer — line numbers + fold chevrons
# ---------------------------------------------------------------------------


class LineNumberFoldRenderer(GtkSource.GutterRenderer):
    """Replaces the built-in line number renderer.

    Draws the line number left-aligned and a fold chevron (if any)
    right-aligned, all within a single gutter column.
    """

    __gtype_name__ = "LineNumberFoldRenderer"

    def __init__(self, fold_manager, view):
        super().__init__()
        self._fm = fold_manager
        self._view = view
        self._digit_count = _FIXED_DIGIT_COUNT
        self._char_width = 0.0  # cached monospace char width
        self._layout = None  # reusable PangoLayout for number text
        self._icon_layout = None  # reusable PangoLayout for fold icon glyph
        self._hover = False  # chevrons only visible on hover
        self._chevron_opacity = 0.0  # animated opacity (0 = hidden, 1 = full)
        self._fade_tick_id = None  # GLib tick callback id
        self._fade_target = 0.0  # target opacity
        self.set_xpad(0)
        self.set_ypad(0)
        self.set_alignment_mode(GtkSource.GutterRendererAlignmentMode.CELL)

        self.connect("query-activatable", self._on_query_activatable)
        self.connect("activate", self._on_activate)

        # Show chevrons only when mouse is over the gutter
        motion = Gtk.EventControllerMotion.new()
        motion.connect("enter", self._on_hover_enter)
        motion.connect("leave", self._on_hover_leave)
        self.add_controller(motion)

    # -- width calculation ------------------------------------------------

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

    def do_measure(self, _orientation, _for_size):
        self._ensure_char_width()
        num_width = int(self._digit_count * self._char_width)
        num_zone = _NUM_PAD + num_width + _NUM_PAD
        total = num_zone + _CHEVRON_COL_WIDTH
        return total, total, -1, -1

    # -- rendering --------------------------------------------------------

    def do_query_data(self, lines, line):
        pass  # all rendering in do_snapshot_line

    def do_snapshot_line(self, snapshot, lines, line):
        fm = self._fm

        # Skip lines hidden inside a collapsed fold — they are invisible
        # in the buffer and should not be rendered in the gutter either.
        if any(sl < line <= el for sl, el in fm._collapsed.items()):
            return

        theme = get_theme()
        self._ensure_char_width()
        num_col_width = int(self._digit_count * self._char_width)
        num_zone = _NUM_PAD + num_col_width + _NUM_PAD
        line_y, line_h = lines.get_line_yrange(line, Gtk.TextWindowType.WIDGET)

        # --- line number (centered in number zone) ---
        is_current = lines.is_cursor(line)
        num_fg = hex_to_gdk_rgba(theme.fg_color if is_current else theme.line_number_fg, 1.0)

        if self._layout is None:
            self._layout = self._view.create_pango_layout("")

        self._layout.set_text(str(line + 1), -1)
        _ink, logical = self._layout.get_pixel_extents()
        total_w = num_zone + _CHEVRON_COL_WIDTH
        x = (total_w - logical.width) / 2
        y = line_y + (line_h - logical.height) / 2

        snapshot.save()
        snapshot.translate(Graphene.Point().init(x, y))
        snapshot.append_layout(self._layout, num_fg)
        snapshot.restore()

        # --- fold chevron (centered in chevron zone with symmetric padding) ---
        if line not in fm._fold_regions:
            return
        collapsed = line in fm._collapsed
        opacity = 1.0 if collapsed else self._chevron_opacity
        if opacity <= 0.01:
            return

        chevron_fg = hex_to_gdk_rgba(theme.line_number_fg, 0.7 * opacity)
        sz = _CHEVRON_SIZE
        alloc_w = self.get_allocation().width
        chevron_area = alloc_w - num_zone
        cx = num_zone + chevron_area / 2
        cy = line_y + line_h / 2

        # DEBUG: draw red rect for chevron zone, blue rect for full gutter
        dbg_red = hex_to_gdk_rgba("#ff0000", 0.3)
        dbg_blue = hex_to_gdk_rgba("#0000ff", 0.15)
        snapshot.append_color(dbg_blue, Graphene.Rect().init(0, line_y, alloc_w, line_h))
        snapshot.append_color(dbg_red, Graphene.Rect().init(num_zone, line_y, chevron_area, line_h))

        builder = Gsk.PathBuilder.new()
        if collapsed:
            # Right-pointing triangle
            builder.move_to(cx - sz / 2, cy - sz / 2)
            builder.line_to(cx + sz / 2, cy)
            builder.line_to(cx - sz / 2, cy + sz / 2)
        else:
            # Down-pointing triangle
            builder.move_to(cx - sz / 2, cy - sz / 2)
            builder.line_to(cx + sz / 2, cy - sz / 2)
            builder.line_to(cx, cy + sz / 2)
        builder.close()
        snapshot.append_fill(builder.to_path(), Gsk.FillRule.WINDING, chevron_fg)

    # -- hover handling (fade in/out) -------------------------------------

    _FADE_STEP = 0.08  # opacity change per tick (~16ms)

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
            return  # already running
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
            return False  # stop
        return True  # continue

    # -- click handling ---------------------------------------------------

    def _on_query_activatable(self, renderer, it, area):
        return it.get_line() in self._fm._fold_regions

    def _on_activate(self, renderer, it, area, button, state, n_presses):
        line = it.get_line()
        fm = self._fm
        # Debounce: ignore rapid clicks while a toggle is still pending.
        if fm._toggle_pending:
            return
        fm._toggle_pending = True

        def _do_toggle():
            fm.toggle_fold(line)
            # Re-arm after a short cooldown to absorb double-click bursts.
            GLib.timeout_add(150, fm._clear_toggle_pending)
            return False

        # Use timeout (not idle_add) so GTK finishes all click processing first.
        GLib.timeout_add(30, _do_toggle)
