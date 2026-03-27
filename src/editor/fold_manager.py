"""
Code folding manager for the editor.

Uses tree-sitter AST to detect foldable regions and GTK4 invisible
text tags to hide/show lines.  A custom GutterRenderer replaces the
built-in line numbers to draw both numbers and fold chevrons in a
single wider gutter column.
"""

from gi.repository import GLib, Graphene, Gtk, GtkSource, Pango

from fonts import get_font_settings
from icons import ICON_FONT_FAMILY
from shared.settings import get_setting
from shared.utils import hex_to_gdk_rgba
from themes import get_theme, subscribe_settings_change

# ---------------------------------------------------------------------------
# Foldable node types per tree-sitter language
# ---------------------------------------------------------------------------
FOLD_NODE_TYPES = {
    "python": {
        "function_definition",
        "class_definition",
        "if_statement",
        "elif_clause",
        "else_clause",
        "for_statement",
        "while_statement",
        "with_statement",
        "try_statement",
        "except_clause",
        "finally_clause",
        "dictionary",
        "list",
        "decorated_definition",
    },
    "javascript": {
        "function_declaration",
        "class_declaration",
        "method_definition",
        "if_statement",
        "else_clause",
        "for_statement",
        "for_in_statement",
        "while_statement",
        "switch_statement",
        "try_statement",
        "catch_clause",
        "object",
        "array",
        "arrow_function",
    },
    "typescript": {
        "function_declaration",
        "class_declaration",
        "method_definition",
        "if_statement",
        "else_clause",
        "for_statement",
        "for_in_statement",
        "while_statement",
        "switch_statement",
        "try_statement",
        "catch_clause",
        "object",
        "array",
        "arrow_function",
        "interface_declaration",
        "type_alias_declaration",
        "enum_declaration",
    },
    "tsx": {
        "function_declaration",
        "class_declaration",
        "method_definition",
        "if_statement",
        "else_clause",
        "for_statement",
        "for_in_statement",
        "while_statement",
        "switch_statement",
        "try_statement",
        "catch_clause",
        "object",
        "array",
        "arrow_function",
        "interface_declaration",
        "type_alias_declaration",
        "enum_declaration",
    },
}

_CHEVRON_SIZE = 7
_CHEVRON_COL_WIDTH = 14  # extra pixels for the chevron area
_NUM_RIGHT_PAD = 6  # gap between number text and chevron area
_NUM_LEFT_PAD = 8  # left padding before line number


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
        self._digit_count = 1  # current max digits for width calculation
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

        buf = view.get_buffer()
        if buf:
            buf.connect("changed", self._on_line_count_changed)
            self._update_digit_count(buf)

    # -- width calculation ------------------------------------------------

    def _on_line_count_changed(self, buf):
        old = self._digit_count
        self._update_digit_count(buf)
        if self._digit_count != old:
            self.queue_resize()

    def _update_digit_count(self, buf):
        n = max(buf.get_line_count(), 1)
        self._digit_count = max(len(str(n)), 2)  # minimum 2 digits

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
        total = _NUM_LEFT_PAD + num_width + _NUM_RIGHT_PAD + _CHEVRON_COL_WIDTH
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
        total_w = _NUM_LEFT_PAD + num_col_width + _NUM_RIGHT_PAD + _CHEVRON_COL_WIDTH
        line_y, line_h = lines.get_line_yrange(line, Gtk.TextWindowType.WIDGET)

        # --- line number ---
        is_current = lines.is_cursor(line)
        num_fg = hex_to_gdk_rgba(theme.fg_color if is_current else theme.line_number_fg, 1.0)

        if self._layout is None:
            self._layout = self._view.create_pango_layout("")

        self._layout.set_text(str(line + 1), -1)
        _ink, logical = self._layout.get_pixel_extents()
        x = _NUM_LEFT_PAD + num_col_width - logical.width
        y = line_y + (line_h - logical.height) / 2

        snapshot.save()
        snapshot.translate(Graphene.Point().init(x, y))
        snapshot.append_layout(self._layout, num_fg)
        snapshot.restore()

        # --- fold chevron (icon font glyph) — visible on hover or when collapsed ---
        if line not in fm._fold_regions:
            return
        collapsed = line in fm._collapsed
        opacity = 1.0 if collapsed else self._chevron_opacity
        if opacity <= 0.01:
            return

        chevron_fg = hex_to_gdk_rgba(theme.line_number_fg, 0.7 * opacity)
        glyph = "\U000f0142" if collapsed else "\U000f0140"

        if self._icon_layout is None:
            self._icon_layout = self._view.create_pango_layout("")
            # Get size from font manager instead of hardcoding
            editor_font = get_font_settings("editor")
            sz = int(editor_font.get("size", 13) * Pango.SCALE * 1.2)
            attrs = Pango.AttrList.new()
            attrs.insert(Pango.attr_family_new(ICON_FONT_FAMILY))
            attrs.insert(Pango.attr_size_new(sz))
            attrs.insert(Pango.attr_weight_new(Pango.Weight.BOLD))
            self._icon_layout.set_attributes(attrs)

        self._icon_layout.set_text(glyph, -1)
        _ink, icon_log = self._icon_layout.get_pixel_extents()
        ix = total_w - _CHEVRON_COL_WIDTH + (_CHEVRON_COL_WIDTH - icon_log.width) / 2
        iy = line_y + (line_h - icon_log.height) / 2

        snapshot.save()
        snapshot.translate(Graphene.Point().init(ix, iy))
        snapshot.append_layout(self._icon_layout, chevron_fg)
        snapshot.restore()

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


# ---------------------------------------------------------------------------
# FoldManager
# ---------------------------------------------------------------------------


class FoldManager:
    """Central coordinator for code folding."""

    def __init__(self, view, ts_cache):
        self._view = view
        self._ts_cache = ts_cache
        self._fold_regions = {}  # {start_line: end_line}
        self._collapsed = {}  # {start_line: end_line}
        self._fold_tag = None  # Gtk.TextTag with invisible=True
        self._update_timeout_id = None
        self._toggle_pending = False  # debounce flag for gutter clicks
        self._gutter_renderer = None

        buf = view.get_buffer()
        if buf:
            self._setup_fold_tag(buf)
            buf.connect("changed", self._on_buffer_changed)
            buf.connect("mark-set", self._on_mark_set)

        # Always disable the built-in line numbers — our custom renderer
        # replaces them and is controlled by the show_line_numbers setting.
        view.set_show_line_numbers(False)

        # Schedule initial fold region computation (buffer is already loaded)
        GLib.timeout_add(200, self._recompute_regions)

        # Insert unified line-number + fold renderer into left gutter
        self._gutter_renderer = LineNumberFoldRenderer(self, view)
        gutter = view.get_gutter(Gtk.TextWindowType.LEFT)
        gutter.insert(self._gutter_renderer, 0)

        # Respect editor.show_line_numbers setting (initial + live changes)
        editor_settings = get_setting("editor", {})
        if not editor_settings.get("show_line_numbers", True):
            self._gutter_renderer.set_visible(False)
        subscribe_settings_change(self._on_settings_change)

    def set_show_line_numbers(self, show: bool):
        """Toggle visibility of the custom line-number + fold gutter."""
        if self._gutter_renderer:
            self._gutter_renderer.set_visible(show)

    def _on_settings_change(self, key, value):
        if key == "editor" and isinstance(value, dict):
            show = value.get("show_line_numbers", True)
            self.set_show_line_numbers(bool(show))

    # ------------------------------------------------------------------
    # Tag setup
    # ------------------------------------------------------------------

    def _setup_fold_tag(self, buf):
        tag_table = buf.get_tag_table()
        existing = tag_table.lookup("fold-hidden")
        if existing:
            self._fold_tag = existing
        else:
            self._fold_tag = buf.create_tag("fold-hidden", invisible=True)

    # ------------------------------------------------------------------
    # Buffer signals
    # ------------------------------------------------------------------

    def _on_buffer_changed(self, buf):
        if self._update_timeout_id:
            GLib.source_remove(self._update_timeout_id)
        self._fold_regions = {}
        self._update_timeout_id = GLib.timeout_add(500, self._recompute_regions)

    def _on_mark_set(self, buf, location, mark):
        """Auto-expand fold if the insert cursor lands inside a collapsed region."""
        if mark != buf.get_insert():
            return
        cursor_line = location.get_line()
        to_expand = [sl for sl, el in self._collapsed.items() if sl < cursor_line <= el]
        if not to_expand:
            return

        # Defer buffer modifications out of signal handler to avoid
        # Pango layout corruption during GTK's internal processing.
        def _do_expand():
            for sl in to_expand:
                if sl in self._collapsed:
                    self._expand(buf, sl, self._collapsed[sl])
                    del self._collapsed[sl]
            self._view.queue_draw()
            return False

        GLib.idle_add(_do_expand)

    # ------------------------------------------------------------------
    # Fold region detection
    # ------------------------------------------------------------------

    def _recompute_regions(self):
        self._update_timeout_id = None

        buf = self._view.get_buffer()
        if not buf:
            return False

        from .tree_sitter_buffer import ts_lang_for_buffer

        lang_id = ts_lang_for_buffer(buf)

        start_it = buf.get_start_iter()
        end_it = buf.get_end_iter()
        content = buf.get_text(start_it, end_it, True)

        new_regions = {}
        if lang_id and lang_id in FOLD_NODE_TYPES:
            tree = self._ts_cache.get_tree(content, lang_id)
            if tree:
                self._collect_fold_regions(tree.root_node, lang_id, new_regions)
        else:
            # Brace/bracket folding for JSON and other non-tree-sitter languages
            self._collect_brace_fold_regions(content, new_regions)

        if self._collapsed:
            new_collapsed = {}
            for old_start, _old_end in self._collapsed.items():
                for new_start, new_end in new_regions.items():
                    if abs(new_start - old_start) <= 2 and new_start not in new_collapsed:
                        new_collapsed[new_start] = new_end
                        break
            for sl, el in list(self._collapsed.items()):
                if sl not in new_collapsed:
                    self._expand(buf, sl, el)
            for sl, el in new_collapsed.items():
                if sl not in self._collapsed:
                    self._collapse(buf, sl, el)
            self._collapsed = new_collapsed

        self._fold_regions = new_regions
        self._view.queue_draw()
        return False

    def _collect_fold_regions(self, node, lang_id, regions):
        foldable = FOLD_NODE_TYPES.get(lang_id, set())
        if node.type in foldable:
            start_line = node.start_point[0]
            end_line = node.end_point[0]
            if end_line > start_line:
                regions[start_line] = end_line
        for child in node.children:
            self._collect_fold_regions(child, lang_id, regions)

    @staticmethod
    def _collect_brace_fold_regions(content, regions):
        """Detect fold regions from matched braces/brackets for any language."""
        stack = []  # (open_char, line_number)
        in_string = False
        escape = False
        quote_char = None

        for line_num, line in enumerate(content.splitlines()):
            for ch in line:
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = True
                    continue
                if in_string:
                    if ch == quote_char:
                        in_string = False
                    continue
                if ch in ('"', "'"):
                    in_string = True
                    quote_char = ch
                    continue
                if ch in ("{", "["):
                    stack.append((ch, line_num))
                elif ch in ("}", "]"):
                    if stack:
                        open_ch, start_line = stack.pop()
                        if line_num > start_line:
                            # Only record outermost when two opens share a line
                            if start_line not in regions:
                                regions[start_line] = line_num

    # ------------------------------------------------------------------
    # Toggle / collapse / expand
    # ------------------------------------------------------------------

    def _clear_toggle_pending(self):
        self._toggle_pending = False
        return False  # one-shot GLib timeout

    def toggle_fold(self, line):
        """Toggle fold at *line*.  Returns True if a fold was toggled."""
        if line not in self._fold_regions:
            return False
        buf = self._view.get_buffer()
        if not buf:
            return False

        if line in self._collapsed:
            self._expand(buf, line, self._collapsed[line])
            del self._collapsed[line]
        else:
            end_line = self._fold_regions[line]
            self._collapse(buf, line, end_line)
            self._collapsed[line] = end_line

        self._view.queue_draw()
        return True

    def toggle_fold_at_cursor(self):
        """Toggle the innermost fold containing the cursor."""
        buf = self._view.get_buffer()
        if not buf:
            return False
        cursor_line = buf.get_iter_at_mark(buf.get_insert()).get_line()

        if cursor_line in self._fold_regions:
            return self.toggle_fold(cursor_line)

        best = None
        for sl, el in self._fold_regions.items():
            if sl <= cursor_line <= el:
                if best is None or sl > best:
                    best = sl
        if best is not None:
            return self.toggle_fold(best)
        return False

    def collapse_all(self):
        buf = self._view.get_buffer()
        if not buf:
            return
        for sl, el in self._fold_regions.items():
            if sl not in self._collapsed:
                self._collapse(buf, sl, el)
                self._collapsed[sl] = el
        self._view.queue_draw()

    def expand_all(self):
        buf = self._view.get_buffer()
        if not buf:
            return
        for sl, el in list(self._collapsed.items()):
            self._expand(buf, sl, el)
        self._collapsed.clear()
        self._view.queue_draw()

    def _collapse(self, buf, start_line, end_line):
        """Hide lines start_line+1 … end_line (inclusive)."""
        if not self._fold_tag:
            return
        first_hidden = start_line + 1
        line_count = buf.get_line_count()
        if first_hidden >= line_count:
            return

        # Move cursor to the fold header if it would get trapped inside
        # the invisible region — GTK crashes if the cursor is on an
        # invisible line during its own internal cursor rendering.
        insert = buf.get_insert()
        cursor_line = buf.get_iter_at_mark(insert).get_line()
        if start_line < cursor_line <= end_line:
            safe_iter = _get_line_iter(buf, start_line)
            buf.place_cursor(safe_iter)

        # Tag COMPLETE lines only — from start of (start_line+1) to
        # start of (end_line+1).  The fold header line is never touched
        # by the invisible tag, which avoids the Pango byte-index crash
        # caused by a partially-invisible line layout.
        start_iter = _get_line_iter(buf, first_hidden)
        if end_line + 1 < line_count:
            end_iter = _get_line_iter(buf, end_line + 1)
        else:
            end_iter = buf.get_end_iter()
        if start_iter.compare(end_iter) >= 0:
            return
        buf.apply_tag(self._fold_tag, start_iter, end_iter)

    def _expand(self, buf, start_line, end_line):
        """Reveal previously hidden lines."""
        if not self._fold_tag:
            return
        # Remove tag from a generous range covering all possibly-tagged text.
        start_iter = _get_line_iter(buf, start_line)
        line_count = buf.get_line_count()
        if end_line + 1 < line_count:
            end_iter = _get_line_iter(buf, end_line + 1)
        else:
            end_iter = buf.get_end_iter()
        if start_iter.compare(end_iter) >= 0:
            return
        buf.remove_tag(self._fold_tag, start_iter, end_iter)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _get_line_iter(buf, line):
    """Get a TextIter at the start of a line, handling GTK4 tuple returns."""
    line_count = buf.get_line_count()
    safe_line = min(max(0, int(line)), line_count - 1)
    result = buf.get_iter_at_line(safe_line)
    if isinstance(result, (tuple, list)):
        if len(result) >= 2:
            return result[1]
        return buf.get_start_iter()
    return result
