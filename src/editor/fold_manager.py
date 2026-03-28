"""
Code folding manager for the editor.

Uses tree-sitter AST to detect foldable regions and GTK4 invisible
text tags to hide/show lines.  A custom GutterRenderer replaces the
built-in line numbers to draw both numbers and fold chevrons in a
single wider gutter column.
"""

from gi.repository import GLib, Gtk

from shared.settings import get_setting
from themes import subscribe_settings_change

from .line_number_fold_renderer import (
    BreakpointGutterRenderer,
    FoldChevronRenderer,
    GitDiffGutterRenderer,
    LineNumberRenderer,
)

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

        # Insert 4 gutter renderers: breakpoints | line numbers | git markers | fold chevrons
        gutter = view.get_gutter(Gtk.TextWindowType.LEFT)
        self._bp_renderer = BreakpointGutterRenderer(view)
        self._gutter_renderer = LineNumberRenderer(view, self)
        self._git_diff_renderer = GitDiffGutterRenderer(self)
        self._chevron_renderer = FoldChevronRenderer(view, self)
        gutter.insert(self._bp_renderer, 0)
        gutter.insert(self._gutter_renderer, 1)
        gutter.insert(self._git_diff_renderer, 2)
        gutter.insert(self._chevron_renderer, 3)

        # Respect editor.show_line_numbers setting (initial + live changes)
        editor_settings = get_setting("editor", {})
        if not editor_settings.get("show_line_numbers", True):
            self._set_gutter_visible(False)
        subscribe_settings_change(self._on_settings_change)

    def _set_gutter_visible(self, show: bool):
        for r in (self._bp_renderer, self._gutter_renderer, self._git_diff_renderer, self._chevron_renderer):
            if r:
                r.set_visible(show)

    def set_show_line_numbers(self, show: bool):
        """Toggle visibility of the gutter renderers."""
        self._set_gutter_visible(show)

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

        from .tree_sitter_buffer_cache import ts_lang_for_buffer

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
