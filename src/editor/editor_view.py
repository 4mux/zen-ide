"""
Editor View for Zen IDE.
Uses GtkSourceView for code editing with syntax highlighting.
"""

import os
import time
from typing import Callable

from gi.repository import Gdk, GLib, Graphene, Gtk, GtkSource, Pango

from constants import (
    BRACKET_SCOPE_LANGS,
    DEFAULT_INDENT_WIDTH,
    EDITOR_LEFT_PADDING,
    IMAGE_EXTENSIONS,
    LANG_INDENT_WIDTH,
    MINIMAP_WIDTH,
    NO_INDENT_GUIDE_LANGS,
)
from fonts import get_font_settings, subscribe_font_change
from icons import ICON_FONT_FAMILY, Icons
from shared.focus_border_mixin import FocusBorderMixin
from shared.focus_manager import get_component_focus_manager
from shared.settings import get_setting
from shared.ui import ZenButton
from shared.ui.zen_entry import ZenEntry, ZenSearchEntry
from themes import get_theme, subscribe_theme_change

from .color_preview_renderer import ColorPreviewRenderer
from .semantic_highlight import setup_semantic_highlight, update_semantic_colors

MD_EXTENSIONS = {".md", ".markdown"}
OPENAPI_EXTENSIONS = {".yaml", ".yml", ".json"}
SKETCH_EXTENSION = ".zen_sketch"

# Directory for generated GtkSourceView style scheme files
_SCHEME_DIR = os.path.join(os.environ.get("TMPDIR") or os.environ.get("TEMP") or "/tmp", "zen-ide-schemes")


def _parse_rgba(hex_color: str, alpha: float = 1.0):
    """Parse a hex color string into a Gdk.RGBA with optional alpha."""
    from gi.repository import Gdk

    rgba = Gdk.RGBA()
    rgba.parse(hex_color)
    rgba.alpha = alpha
    return rgba


def _cursor_scheme_fg(editor_bg: str) -> str:
    """Return cursor foreground for the style scheme.

    When ``wide_cursor`` is active the native GtkSourceView caret must be
    invisible so only the custom block cursor shows.
    """
    if get_setting("wide_cursor", False):
        return editor_bg  # same as background → invisible
    return "fg"


def _generate_style_scheme(theme) -> str:
    """Generate a GtkSourceView style scheme XML from theme syntax colors.

    Returns the scheme id string (e.g. 'zen-dracula').
    """
    from shared.utils import contrast_color

    os.makedirs(_SCHEME_DIR, exist_ok=True)
    scheme_id = f"zen-{theme.name}"

    editor_bg = theme.main_bg
    line_bg = theme.line_number_bg
    sel_fg = contrast_color(theme.selection_bg)
    ws_color = get_setting("editor.whitespace_color", "") or theme.fg_dim
    ws_alpha = get_setting("editor.whitespace_alpha", -1)
    if 0.0 <= ws_alpha <= 1.0:
        ws_color = ws_color.lstrip("#")[:6] + f"{int(ws_alpha * 255):02x}"
        ws_color = f"#{ws_color}"

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<style-scheme id="{scheme_id}" name="Zen {theme.display_name}" version="1.0">
  <color name="bg" value="{editor_bg}"/>
  <color name="fg" value="{theme.fg_color}"/>
  <color name="dim" value="{theme.fg_dim}"/>
  <color name="sel" value="{theme.selection_bg}"/>
  <color name="line_bg" value="{line_bg}"/>
  <color name="line_fg" value="{theme.line_number_fg}"/>

  <!-- Editor chrome -->
  <style name="text" foreground="fg" background="bg"/>
  <style name="selection" foreground="{sel_fg}" background="sel"/>
  <style name="cursor" foreground="{_cursor_scheme_fg(editor_bg)}"/>
  <style name="current-line" background="{theme.hover_bg}"/>
  <style name="line-numbers" foreground="line_fg" background="line_bg"/>
  <style name="right-margin" foreground="dim"/>
  <style name="bracket-match" foreground="fg" background="sel" bold="true"/>
  <style name="bracket-mismatch" foreground="{theme.get_syntax_color("syntax_string")}" background="bg" underline="true"/>
  <style name="search-match" background="{theme.search_match_bg or theme.selection_bg}"/>
  <style name="draw-spaces" foreground="{ws_color}"/>

  <!-- Syntax highlighting -->
  <style name="def:keyword" foreground="{theme.syntax_keyword}" bold="false"/>
  <style name="def:type" foreground="{theme.syntax_class}" bold="false"/>
  <style name="def:function" foreground="{theme.syntax_function}"/>
  <style name="def:string" foreground="{theme.syntax_string}"/>
  <style name="def:comment" foreground="{theme.syntax_comment}" italic="true"/>
  <style name="def:doc-comment" foreground="{theme.get_syntax_color("syntax_doc_comment")}" italic="true"/>
  <style name="def:doc-comment-element" foreground="{theme.get_syntax_color("syntax_doc_comment")}" bold="true"/>
  <style name="def:number" foreground="{theme.syntax_number}"/>
  <style name="def:floating-point" foreground="{theme.syntax_number}"/>
  <style name="def:decimal" foreground="{theme.syntax_number}"/>
  <style name="def:base-n-integer" foreground="{theme.syntax_number}"/>
  <style name="def:boolean" foreground="{theme.get_syntax_color("syntax_boolean")}"/>
  <style name="def:constant" foreground="{theme.get_syntax_color("syntax_constant")}"/>
  <style name="def:operator" foreground="{theme.syntax_operator}"/>
  <style name="def:special-char" foreground="{theme.get_syntax_color("syntax_string_escape")}"/>
  <style name="def:special-constant" foreground="{theme.get_syntax_color("syntax_constant")}"/>
  <style name="def:identifier" foreground="{theme.get_syntax_color("syntax_variable")}"/>
  <style name="def:preprocessor" foreground="{theme.syntax_keyword}"/>
  <style name="def:builtin" foreground="{theme.syntax_function}"/>
  <style name="def:statement" foreground="{theme.get_syntax_color("syntax_keyword_control")}"/>
  <style name="def:note" foreground="{theme.accent_color}" bold="true"/>
  <style name="def:error" foreground="{theme.get_syntax_color("syntax_string")}" underline="true"/>
  <style name="def:warning" foreground="{theme.syntax_number}" underline="true"/>
  <style name="def:net-address" foreground="{theme.syntax_function}" underline="true"/>
  <style name="def:regex" foreground="{theme.get_syntax_color("syntax_regex")}"/>

  <!-- JavaScript / TypeScript / JSX overrides (many styles lack def:* fallback) -->
  <style name="js:keyword" foreground="{theme.syntax_keyword}"/>
  <style name="js:built-in-constructor" foreground="{theme.syntax_class}"/>
  <style name="js:built-in-function" foreground="{theme.syntax_function}"/>
  <style name="js:built-in-method" foreground="{theme.syntax_function}"/>
  <style name="js:built-in-object" foreground="{theme.syntax_function}"/>
  <style name="js:identifier" foreground="{theme.fg_color}"/>
  <style name="js:template-placeholder" foreground="{theme.get_syntax_color("syntax_variable")}"/>
  <style name="jsx:element" foreground="{theme.syntax_keyword}"/>
  <style name="jsx:attribute-expression" foreground="{theme.get_syntax_color("syntax_variable")}"/>
  <style name="jsx:child-expression" foreground="{theme.get_syntax_color("syntax_variable")}"/>
  <style name="jsx:spread-attribute" foreground="{theme.syntax_operator}"/>
  <style name="typescript:decorator" foreground="{theme.syntax_keyword}" italic="true"/>
  <style name="typescript:decorator-operator" foreground="{theme.syntax_keyword}" italic="true"/>
  <style name="typescript:type-expression" foreground="{theme.syntax_class}"/>
  <style name="typescript:type-annotation" foreground="{theme.syntax_class}"/>
  <style name="typescript:interface-declaration" foreground="{theme.syntax_class}"/>
  <style name="typescript:enum-declaration" foreground="{theme.syntax_class}"/>
  <style name="typescript:type-alias-declaration" foreground="{theme.syntax_class}"/>
  <style name="typescript:optional-modifier" foreground="{theme.syntax_operator}"/>
  <style name="typescript:non-null-assertion-operator" foreground="{theme.syntax_operator}"/>
  <style name="typescript:union-intersection-type-operator" foreground="{theme.syntax_operator}"/>
  <style name="typescript:mapped-type-modifier-prefix" foreground="{theme.syntax_keyword}"/>
  <style name="typescript:ambient-declaration" foreground="{theme.syntax_keyword}"/>
  <style name="typescript:module-declaration" foreground="{theme.syntax_keyword}"/>
  <style name="typescript:namespace-declaration" foreground="{theme.syntax_keyword}"/>
  <style name="typescript:type-keyword" foreground="{theme.syntax_keyword}"/>
  <style name="typescript:basic-type" foreground="{theme.syntax_class}"/>
  <style name="typescript:built-in-library-type" foreground="{theme.syntax_class}"/>
  <style name="typescript:bracket-type-operator" foreground="{theme.syntax_operator}"/>
  <style name="typescript:conditional-type-operator" foreground="{theme.syntax_operator}"/>
  <style name="typescript:definite-assignment-assertion" foreground="{theme.syntax_operator}"/>
  <style name="typescript:object-type-literal" foreground="{theme.syntax_class}"/>
  <style name="typescript:tuple-type-literal" foreground="{theme.syntax_class}"/>
  <style name="typescript:type-arguments-list" foreground="{theme.syntax_class}"/>
  <style name="typescript:type-parameters-list" foreground="{theme.syntax_class}"/>
  <style name="typescript:global-augmentation" foreground="{theme.syntax_keyword}"/>

  <!-- Python-specific overrides (class-name maps to def:function by default) -->
  <style name="python:special-variable" foreground="{theme.syntax_keyword}" italic="true"/>
  <style name="python3:special-variable" foreground="{theme.syntax_keyword}" italic="true"/>
  <style name="python:class-name" foreground="{theme.syntax_class}"/>
  <style name="python3:class-name" foreground="{theme.syntax_class}"/>
  <style name="python:function-name" foreground="{theme.syntax_function}"/>
  <style name="python3:function-name" foreground="{theme.syntax_function}"/>
  <style name="python:decorator" foreground="{theme.syntax_keyword}" italic="true"/>
  <style name="python3:decorator" foreground="{theme.syntax_keyword}" italic="true"/>
  <style name="python:builtin-object" foreground="{theme.syntax_class}"/>
  <style name="python3:builtin-object" foreground="{theme.syntax_class}"/>
  <style name="python:builtin-function" foreground="{theme.syntax_function}"/>
  <style name="python3:builtin-function" foreground="{theme.syntax_function}"/>
</style-scheme>
"""
    path = os.path.join(_SCHEME_DIR, f"{scheme_id}.xml")
    with open(path, "w") as f:
        f.write(xml)

    # Register scheme directory with GtkSourceView
    scheme_manager = GtkSource.StyleSchemeManager.get_default()
    search_path = scheme_manager.get_search_path()
    if _SCHEME_DIR not in search_path:
        scheme_manager.prepend_search_path(_SCHEME_DIR)
    else:
        # Force reload by resetting search path
        scheme_manager.set_search_path(search_path)

    return scheme_id


def _iter_at_line(buf, line):
    """Get a valid TextIter at a line number, handling GTK4 tuple returns safely."""
    try:
        line_count = max(1, buf.get_line_count())
        safe_line = min(max(0, int(line)), line_count - 1)
    except Exception:
        safe_line = 0

    result = buf.get_iter_at_line(safe_line)
    if isinstance(result, (tuple, list)):
        if len(result) >= 2:
            if isinstance(result[0], bool) and not result[0]:
                return buf.get_start_iter()
            return result[1]
        return buf.get_start_iter()
    return result


def _iter_at_line_offset(buf, line, offset):
    """Get a valid TextIter at a line+offset, handling GTK4 tuple returns safely."""
    line_iter = _iter_at_line(buf, line)
    line_end = line_iter.copy()
    if not line_end.ends_line():
        line_end.forward_to_line_end()
    max_col = line_end.get_line_offset()
    safe_offset = min(max(0, int(offset)), max_col)
    safe_line = line_iter.get_line()

    result = buf.get_iter_at_line_offset(safe_line, safe_offset)
    if isinstance(result, (tuple, list)):
        if len(result) >= 2:
            if isinstance(result[0], bool) and not result[0]:
                return line_iter
            return result[1]
        return line_iter
    return result


def _parse_hex_color(hex_color):
    """Parse hex color to (r, g, b) floats 0–1."""
    h = hex_color.lstrip("#")
    return int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255


class ZenSourceView(GtkSource.View):
    """GtkSourceView with indent guide lines."""

    __gtype_name__ = "ZenSourceView"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._show_guides = True
        self._guide_rgba = (1.0, 1.0, 1.0, 0.08)
        self._guide_color = Gdk.RGBA()
        self._guide_color.red, self._guide_color.green, self._guide_color.blue, self._guide_color.alpha = self._guide_rgba
        self._buf_changed_id = None
        self._buf_cursor_id = None  # Track cursor-position signal for wide cursor
        self._gutter_diff_renderer = None  # Set by EditorTab
        self._color_preview_renderer = None  # Set by EditorTab
        self._ghost_text_renderer = None  # Set by GhostTextRenderer
        self._suppress_focus_effects = False  # Set by Autocomplete to prevent flicker
        self._restoring_focus_flags = False  # Re-entrancy guard for do_state_flags_changed

        self._cached_indent_step = None  # Cached indent step for stable guides
        self._cached_guide_levels = None  # Full-buffer guide levels (recomputed on buffer change only)
        self._guide_levels_dirty = True  # Flag to recompute guide levels
        # Custom wavy underline colors for diagnostics (set by EditorViewInner)
        self._diag_error_wave_rgba = (0.88, 0.42, 0.47, 1.0)
        self._diag_warning_wave_rgba = (0.90, 0.75, 0.48, 1.0)

        # -- optional block cursor -------------------------------------------
        self._wide_cursor = get_setting("wide_cursor", False)
        if self._wide_cursor:
            from constants import CURSOR_BLINK_OFF_MS, CURSOR_BLINK_ON_MS

            self._bc_visible = True
            self._bc_focused = False
            self._bc_blink_id = None
            self._bc_blink_on = CURSOR_BLINK_ON_MS
            self._bc_blink_off = CURSOR_BLINK_OFF_MS
            self._bc_blink_enabled = get_setting("cursor_blink", False)

            # Hide native caret visually via CSS (not set_cursor_visible which
            # also disables cursor movement via arrow keys in GTK4).
            css = Gtk.CssProvider()
            css.load_from_data(b"textview text { caret-color: transparent; }")
            self.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_USER + 10)

            fc = Gtk.EventControllerFocus()
            fc.connect("enter", self._bc_focus_in)
            fc.connect("leave", self._bc_focus_out)
            self.add_controller(fc)

            # Repaint on cursor movement (initial buffer + future swaps)
            # Note: _connect_buffer also connects this signal for buffer swaps;
            # the initial buffer is handled there to avoid duplicate handlers.

        # Write to system clipboard on copy/cut so content survives app exit
        self.connect("copy-clipboard", self._on_copy_to_system)
        self.connect("cut-clipboard", self._on_copy_to_system)

        # Disable built-in text drag gesture to prevent macOS crash (SIGABRT)
        # in gtk_text_view_drag_gesture_update → _gdk_macos_drag_begin
        self._disable_text_drag_gesture()

        # Redraw guides when buffer content changes
        self._connect_buffer(self.get_buffer())
        self.connect("notify::buffer", self._on_buffer_changed)

    def _disable_text_drag_gesture(self):
        """Prevent DnD of selected text (crashes on macOS) while keeping selection.

        Adds a capture-phase drag gesture that claims the sequence only when
        the click starts inside an existing selection (the case that triggers
        DnD).  For all other drags the gesture is denied, so the built-in
        GestureDrag handles normal text selection as usual.
        """
        g = Gtk.GestureDrag()
        g.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        g.connect("drag-begin", self._on_capture_drag_begin)
        self.add_controller(g)

    def _on_copy_to_system(self, textview):
        """Write selected text to the OS clipboard so it survives app exit."""
        buf = textview.get_buffer()
        bounds = buf.get_selection_bounds()
        if bounds:
            from shared.utils import copy_to_system_clipboard

            text = buf.get_text(bounds[0], bounds[1], True)
            copy_to_system_clipboard(text)

    def _on_capture_drag_begin(self, gesture, start_x, start_y):
        """Claim the drag if it starts inside a text selection (would trigger DnD)."""
        buf = self.get_buffer()
        sel = buf.get_selection_bounds()
        if sel:
            bx, by = self.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(start_x), int(start_y))
            ok, click_iter = self.get_iter_at_location(bx, by)
            if ok and sel[0].compare(click_iter) <= 0 and click_iter.compare(sel[1]) <= 0:
                gesture.set_state(Gtk.EventSequenceState.CLAIMED)
                return
        gesture.set_state(Gtk.EventSequenceState.DENIED)

    def _on_buffer_changed(self, *args):
        self._cached_indent_step = None
        self._guide_levels_dirty = True
        self._cached_guide_levels = None
        self._connect_buffer(self.get_buffer())

    def _connect_buffer(self, buf):
        if self._buf_changed_id and self._buf_changed_id[0]:
            try:
                self._buf_changed_id[0].disconnect(self._buf_changed_id[1])
            except Exception:
                pass
        if self._buf_cursor_id and self._buf_cursor_id[0]:
            try:
                self._buf_cursor_id[0].disconnect(self._buf_cursor_id[1])
            except Exception:
                pass
        if buf:
            hid = buf.connect("changed", self._on_buf_content_changed)
            self._buf_changed_id = (buf, hid)
            if self._wide_cursor:
                cid = buf.connect("notify::cursor-position", lambda *_: self.queue_draw())
                self._buf_cursor_id = (buf, cid)
            else:
                self._buf_cursor_id = None
        else:
            self._buf_changed_id = None
            self._buf_cursor_id = None

    def set_guide_color_hex(self, hex_color, alpha=0.12):
        r, g, b = _parse_hex_color(hex_color)
        self._guide_rgba = (r, g, b, alpha)
        self._guide_color.red, self._guide_color.green, self._guide_color.blue, self._guide_color.alpha = r, g, b, alpha

    def _on_buf_content_changed(self, buf):
        self._cached_indent_step = None
        self._guide_levels_dirty = True
        self.queue_draw()

    def _compute_indent_step(self, buf, tab_w):
        """Compute indent step from full file content and cache it."""
        if self._cached_indent_step is not None:
            return self._cached_indent_step

        start_it = buf.get_start_iter()
        end_it = buf.get_end_iter()
        all_text = buf.get_text(start_it, end_it, True)

        non_zero = []
        for text in all_text.split("\n"):
            if not text.strip():
                continue
            indent = 0
            for ch in text:
                if ch == " ":
                    indent += 1
                elif ch == "\t":
                    indent += tab_w
                else:
                    break
            if indent > 0:
                non_zero.append(indent)

        from editor.indent_guide_levels import compute_indent_step

        step = compute_indent_step(non_zero, tab_w)

        self._cached_indent_step = step
        return step

    # -- focus-state suppression (prevents current-line flash on popup) -------

    def do_state_flags_changed(self, previous_flags):
        """Prevent GtkSourceView from reacting to transient focus changes.

        When _suppress_focus_effects is True (e.g. autocomplete popup opening),
        immediately restore the FOCUSED/FOCUS_WITHIN state flags so that
        GtkSourceView's internal snapshot still draws the current-line highlight
        and CSS `:focus-within` styles remain unchanged.
        """
        if self._restoring_focus_flags:
            return
        if self._suppress_focus_effects:
            current = self.get_state_flags()
            focus_bits = Gtk.StateFlags.FOCUSED | Gtk.StateFlags.FOCUS_WITHIN
            lost = (previous_flags & focus_bits) & ~(current & focus_bits)
            if lost:
                self._restoring_focus_flags = True
                if lost & Gtk.StateFlags.FOCUSED:
                    self.set_state_flags(Gtk.StateFlags.FOCUSED, False)
                if lost & Gtk.StateFlags.FOCUS_WITHIN:
                    self.set_state_flags(Gtk.StateFlags.FOCUS_WITHIN, False)
                self._restoring_focus_flags = False
                return
        Gtk.Widget.do_state_flags_changed(self, previous_flags)

    # -- block cursor helpers -------------------------------------------------

    def _bc_focus_in(self, *_):
        # No suppression check here: block cursor must always restore when
        # GTK focus returns.  On window resume, EventControllerFocus.enter
        # fires while the ComponentFocusManager is still suppressed; blocking
        # this would leave _bc_focused=False permanently (cursor disappears).
        self._bc_focused = True
        self._bc_visible = True
        if self._bc_blink_enabled:
            self._bc_start_blink()
        if not self._suppress_focus_effects:
            self.queue_draw()

    def _bc_focus_out(self, *_):
        if self._suppress_focus_effects:
            return
        self._bc_focused = False
        self._bc_stop_blink()
        self._bc_visible = True
        self.queue_draw()

    def _bc_start_blink(self):
        self._bc_stop_blink()
        self._bc_blink_id = GLib.timeout_add(self._bc_blink_on, self._bc_tick)

    def _bc_stop_blink(self):
        if self._bc_blink_id is not None:
            GLib.source_remove(self._bc_blink_id)
            self._bc_blink_id = None

    def _bc_tick(self):
        self._bc_visible = not self._bc_visible
        self.queue_draw()
        ms = self._bc_blink_off if not self._bc_visible else self._bc_blink_on
        self._bc_blink_id = GLib.timeout_add(ms, self._bc_tick)
        return False

    def do_snapshot(self, snapshot):
        GtkSource.View.do_snapshot(self, snapshot)

        # All custom drawing below uses buffer iterators.  Wrap in a
        # try/except so that a stale-iterator condition (e.g. buffer
        # modified by a timer callback between frames) never crashes
        # the render pipeline — the frame is simply skipped.
        try:
            self._do_custom_snapshot(snapshot)
        except Exception:
            pass

    def _do_custom_snapshot(self, snapshot):
        """Custom overlay drawing (indent guides, diff, diagnostics, ghost text, cursor)."""
        if self._show_guides:
            self._draw_indent_guides_snapshot(snapshot)

        # Compute visible line range once, share across all snapshot renderers.
        # Convert to line numbers immediately so downstream code never
        # holds raw iterators that could become stale.
        visible = self.get_visible_rect()
        vis_start, _ = self.get_line_at_y(visible.y)
        vis_end, _ = self.get_line_at_y(visible.y + visible.height)
        vis_range = (vis_start.get_line(), vis_end.get_line())

        if self._gutter_diff_renderer and self._gutter_diff_renderer._diff_lines:
            self._gutter_diff_renderer.draw(snapshot, vis_range)

        if self._color_preview_renderer and self._color_preview_renderer._color_positions:
            self._color_preview_renderer.draw(snapshot, vis_range)

        buf = self.get_buffer()
        tt = buf.get_tag_table()
        has_diags = tt.lookup("diag_error_underline") is not None or tt.lookup("diag_warning_underline") is not None
        if has_diags:
            self._draw_diagnostic_waves(snapshot)

        # Ghost text overlay (drawn before block cursor so cursor sits on top)
        if self._ghost_text_renderer:
            self._ghost_text_renderer.draw(snapshot)

        # Block cursor (drawn last so it sits on top of everything)
        if self._wide_cursor and self._bc_focused and self._bc_visible:
            from shared.block_cursor_draw import draw_block_cursor

            draw_block_cursor(self, snapshot)

    # -- Custom wavy underlines for diagnostics --

    def _draw_diagnostic_waves(self, snapshot):
        """Draw custom wavy underlines for diagnostic-tagged text ranges."""
        buf = self.get_buffer()
        tag_table = buf.get_tag_table()
        error_tag = tag_table.lookup("diag_error_underline")
        warning_tag = tag_table.lookup("diag_warning_underline")
        if error_tag is None and warning_tag is None:
            return

        visible = self.get_visible_rect()
        vis_start, _ = self.get_line_at_y(visible.y)
        vis_end, _ = self.get_line_at_y(visible.y + visible.height)
        if not vis_end.ends_line():
            vis_end.forward_to_line_end()

        # Capture offset bounds immediately so we compare ints, not iterators.
        # This prevents stale-iterator warnings if the buffer is modified
        # between consecutive iterator operations.
        vis_end_offset = vis_end.get_offset()

        btwc = self.buffer_to_window_coords
        tags_and_colors = []
        if error_tag:
            tags_and_colors.append((error_tag, self._diag_error_wave_rgba))
        if warning_tag:
            tags_and_colors.append((warning_tag, self._diag_warning_wave_rgba))

        for tag, color in tags_and_colors:
            it = vis_start.copy()
            while it.get_offset() <= vis_end_offset:
                if not it.has_tag(tag):
                    if not it.forward_to_tag_toggle(tag):
                        break
                    if it.get_offset() > vis_end_offset:
                        break
                    if not it.has_tag(tag):
                        continue

                range_start = it.copy()
                if not it.forward_to_tag_toggle(tag):
                    it = buf.get_iter_at_offset(vis_end_offset)
                range_end = it.copy()

                # Draw line by line within the tagged range
                ls = range_start.copy()
                range_end_offset = range_end.get_offset()
                while ls.get_offset() < range_end_offset:
                    cur_line = ls.get_line()
                    le = range_end.copy()
                    if le.get_line() > cur_line:
                        le = _iter_at_line(buf, cur_line)
                        if not le.ends_line():
                            le.forward_to_line_end()

                    sr = self.get_iter_location(ls)
                    er = self.get_iter_location(le)
                    sx, sy = btwc(Gtk.TextWindowType.WIDGET, sr.x, sr.y)
                    ex, _ = btwc(Gtk.TextWindowType.WIDGET, er.x, 0)
                    wave_y = sy + sr.height + 1
                    wave_w = ex - sx

                    if wave_w > 0:
                        self._draw_wavy_line(snapshot, sx, wave_y, wave_w, color)

                    next_it = _iter_at_line(buf, cur_line + 1)
                    if next_it.get_line() == cur_line:
                        break
                    ls = next_it

    @staticmethod
    def _draw_wavy_line(snapshot, x, y, width, color):
        """Draw a smooth wavy/squiggly line using GskPathBuilder."""
        from gi.repository import Gdk, Gsk

        r, g, b, a = color
        step = 4.0  # half-wavelength in pixels
        amplitude = 2.5

        builder = Gsk.PathBuilder.new()
        builder.move_to(x, y)
        pos_x = x
        pos_y = y
        i = 0.0
        going_up = True
        while i < width:
            seg = min(step, width - i)
            dy = -amplitude if going_up else amplitude
            pos_x += seg
            pos_y += dy
            builder.line_to(pos_x, pos_y)
            going_up = not going_up
            i += seg

        path = builder.to_path()
        stroke = Gsk.Stroke.new(1.8)

        wave_color = Gdk.RGBA()
        wave_color.red, wave_color.green, wave_color.blue, wave_color.alpha = r, g, b, a
        snapshot.append_stroke(path, stroke, wave_color)

    def _draw_indent_guides_snapshot(self, snapshot):
        """Draw indent guides using GTK4 snapshot.append_color.

        Optimisations vs. the naïve per-line-per-column approach:
        1. X coordinates are pre-computed once per guide column, not per line.
        2. Consecutive visible lines at the same column are merged into a
           single tall rectangle, cutting append_color calls ~3-5×.
        3. The Gdk.RGBA colour object is cached on the instance (not
           allocated every frame).
        """
        buf = self.get_buffer()
        lang = buf.get_language() if hasattr(buf, "get_language") else None
        if lang is None or lang.get_id() in NO_INDENT_GUIDE_LANGS:
            return

        tab_w = self.get_tab_width()
        metrics = self.get_pango_context().get_metrics(None, None)
        char_w = metrics.get_approximate_char_width() / Pango.SCALE

        indent_step = self._compute_indent_step(buf, tab_w)
        indent_px = char_w * indent_step
        if indent_px <= 0:
            return

        # Recompute guide levels only when buffer content changed
        if self._guide_levels_dirty or self._cached_guide_levels is None:
            lang_id = lang.get_id() if lang else None
            start_it = buf.get_start_iter()
            end_it = buf.get_end_iter()
            all_text = buf.get_text(start_it, end_it, True)
            text_lines = all_text.split("\n")
            from editor.indent_guide_levels import compute_guide_levels

            self._cached_guide_levels = compute_guide_levels(text_lines, indent_step, tab_w, lang_id)
            self._guide_levels_dirty = False

        levels = self._cached_guide_levels

        # Visible line range
        visible = self.get_visible_rect()
        start_it, _ = self.get_line_at_y(visible.y)
        end_it, _ = self.get_line_at_y(visible.y + visible.height)
        start_ln = start_it.get_line()
        end_ln = end_it.get_line()

        if end_ln < start_ln or not levels:
            return

        btwc = self.buffer_to_window_coords
        pad_it = _iter_at_line(buf, start_ln)
        padding_x = self.get_iter_location(pad_it).x

        # Selected line range — skip guides on selected lines
        sel_start_ln = sel_end_ln = -1
        if buf.get_has_selection():
            sel_s, sel_e = buf.get_selection_bounds()
            sel_start_ln = sel_s.get_line()
            sel_end_ln = sel_e.get_line()

        # Collect per-line y/height for visible lines (one GTK call each)
        n_levels = len(levels)
        line_y = [0] * (end_ln - start_ln + 1)
        line_h = [0] * (end_ln - start_ln + 1)
        line_lvl = [0] * (end_ln - start_ln + 1)
        for i, ln in enumerate(range(start_ln, end_ln + 1)):
            if ln >= n_levels:
                break
            lvl = levels[ln]
            if lvl <= 0 or sel_start_ln <= ln <= sel_end_ln:
                line_lvl[i] = 0
                continue
            it = _iter_at_line(buf, ln)
            loc = self.get_iter_location(it)
            _, wy = btwc(Gtk.TextWindowType.WIDGET, 0, loc.y)
            line_y[i] = wy
            line_h[i] = loc.height
            line_lvl[i] = lvl

        # Determine max guide columns needed
        max_lvl = max(line_lvl) if line_lvl else 0
        if max_lvl <= 0:
            return

        # Pre-compute window X for each guide column once
        col_x = [0] * max_lvl
        for g in range(max_lvl):
            bx = padding_x + int(indent_px * g)
            col_x[g], _ = btwc(Gtk.TextWindowType.WIDGET, bx, 0)

        color = self._guide_color
        guide_rect = Graphene.Rect()
        n_lines = end_ln - start_ln + 1

        # Draw merged vertical spans per guide column
        for g in range(max_lvl):
            wx = col_x[g]
            span_start = -1
            span_y = 0
            span_bottom = 0
            for i in range(n_lines):
                if line_lvl[i] > g:
                    if span_start < 0:
                        span_start = i
                        span_y = line_y[i]
                    span_bottom = line_y[i] + line_h[i]
                else:
                    if span_start >= 0:
                        guide_rect.init(wx, span_y, 1, span_bottom - span_y)
                        snapshot.append_color(color, guide_rect)
                        span_start = -1
            if span_start >= 0:
                guide_rect.init(wx, span_y, 1, span_bottom - span_y)
                snapshot.append_color(color, guide_rect)


class EditorTab:
    """Represents a single editor tab."""

    def __init__(self, file_path: str = None, is_new: bool = False):
        self.file_path = file_path
        self.is_new = is_new
        self.modified = False
        self.original_content = ""
        self._last_internal_save_time = 0.0

        # Create source view (ZenSourceView adds indent guide lines)
        self.buffer = GtkSource.Buffer()
        self.view = ZenSourceView(buffer=self.buffer)

        # Git diff gutter renderer (vertical bars drawn in do_snapshot).
        # File path is set later in load_file() to avoid duplicate git fetches.
        from .gutter_diff_renderer import GutterDiffRenderer

        self._gutter_diff = GutterDiffRenderer(self.view)
        self.view._gutter_diff_renderer = self._gutter_diff

        # Inline color preview swatches (colored squares next to hex colors)
        self._color_preview = ColorPreviewRenderer(self.view)
        self.view._color_preview_renderer = self._color_preview

        # Diagnostic wavy underline tags
        self._setup_diagnostic_underline_tags()

        # Callback for diagnostics updates (set by EditorView)
        self.on_diagnostics_changed: Callable[[str, int, int], None] | None = None

        # Configure view
        self._configure_view()

        # Apply theme (language is set later in load_file to avoid
        # duplicate work — __init__ has no buffer content yet).
        self._apply_theme()

        # Semantic call-site highlighting (class usage + function calls)
        setup_semantic_highlight(self, get_theme())

        # Tree-sitter parse tree cache (incremental updates for semantic features)
        from .tree_sitter_buffer import setup_buffer_cache

        setup_buffer_cache(self)

        # Autocomplete (Ctrl+Space) — lazy init on first use
        self._autocomplete = None

        # Inline AI suggestions (ghost text) — lazy init on first keypress
        self._inline_completion = None

    # Bracket pairs for auto-close
    BRACKET_PAIRS = {
        "(": ")",
        "[": "]",
        "{": "}",
        '"': '"',
        "'": "'",
        "`": "`",
    }
    CLOSE_BRACKETS = set(BRACKET_PAIRS.values())

    def _ensure_inline_completion(self):
        """Lazily initialise the inline completion manager."""
        if self._inline_completion is not None:
            return self._inline_completion

        try:
            from .inline_completion import InlineCompletionManager

            self._inline_completion = InlineCompletionManager(self)
        except Exception:
            pass
        return self._inline_completion

    def _ensure_autocomplete(self):
        """Lazily initialise the autocomplete manager."""
        if self._autocomplete is not None:
            return self._autocomplete
        from .autocomplete import Autocomplete

        self._autocomplete = Autocomplete(self)
        return self._autocomplete

    def _configure_view(self):
        """Configure the source view settings."""
        view = self.view

        # Batch property changes to avoid per-setter layout invalidation
        view.freeze_notify()
        view.set_show_line_numbers(True)
        view.set_highlight_current_line(True)
        view.set_auto_indent(True)
        view.set_indent_on_tab(True)
        view.set_tab_width(DEFAULT_INDENT_WIDTH)
        view.set_insert_spaces_instead_of_tabs(True)
        view.set_smart_backspace(True)
        view.set_monospace(True)
        view.set_left_margin(EDITOR_LEFT_PADDING)
        view.set_indent_width(DEFAULT_INDENT_WIDTH)
        view.thaw_notify()

        # Bracket matching
        self.buffer.set_highlight_matching_brackets(True)

        # SpaceDrawer: dots for leading whitespace (indent visualization)
        space_drawer = view.get_space_drawer()
        show_ws = get_setting("editor.show_whitespace", False)
        if show_ws:
            space_drawer.set_types_for_locations(
                GtkSource.SpaceLocationFlags.LEADING,
                GtkSource.SpaceTypeFlags.SPACE | GtkSource.SpaceTypeFlags.TAB,
            )
            # Explicitly disable newline arrows and trailing markers
            space_drawer.set_types_for_locations(
                GtkSource.SpaceLocationFlags.TRAILING,
                GtkSource.SpaceTypeFlags.NONE,
            )
            space_drawer.set_types_for_locations(
                GtkSource.SpaceLocationFlags.INSIDE_TEXT,
                GtkSource.SpaceTypeFlags.NONE,
            )
            space_drawer.set_enable_matrix(True)
        else:
            space_drawer.set_enable_matrix(False)

        # Font - use settings from fonts.editor
        from fonts import get_font_settings

        font_settings = get_font_settings("editor")
        font_family = font_settings["family"]
        font_size = font_settings.get("size", 13)
        font_weight = font_settings.get("weight", "normal")

        # Store provider for later updates
        self.font_css_provider = Gtk.CssProvider()
        css_weight = self._css_font_weight(font_weight)
        letter_spacing = get_setting("editor.letter_spacing", 0)
        letter_spacing_css = f"letter-spacing: {letter_spacing}px;" if letter_spacing else ""
        css = f"""
            textview, textview text {{
                font-family: '{font_family}', monospace;
                font-size: {font_size}pt;
                font-weight: {css_weight};
                {letter_spacing_css}
            }}
        """
        self.font_css_provider.load_from_data(css.encode())
        # Use USER priority to override theme
        view.get_style_context().add_provider(self.font_css_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)

        # Apply font weight via Pango (CSS font-weight alone doesn't affect
        # GtkSourceView text rendering — it uses its own Pango pipeline).
        # Deferred to 'realize' because the Pango context is replaced when the
        # widget is realised, discarding any earlier set_font_description call.
        self._pending_font_weight = font_weight
        view.connect("realize", self._on_view_realize_font_weight)

        # Line spacing — adds vertical breathing room between lines
        line_spacing = get_setting("editor.line_spacing", 4)
        above = line_spacing // 2
        below = line_spacing - above
        view.set_pixels_above_lines(above)
        view.set_pixels_below_lines(below)

        # Only show native caret when wide_cursor is off — ZenSourceView
        # hides it when drawing its own block cursor.
        if not getattr(view, "_wide_cursor", False):
            view.set_cursor_visible(True)

        # Word wrap: respect user setting (default: off)
        if get_setting("editor.word_wrap", False):
            view.set_wrap_mode(Gtk.WrapMode.WORD)
        else:
            view.set_wrap_mode(Gtk.WrapMode.NONE)

        # Auto-close brackets & smart indent — must run in CAPTURE phase
        # so we intercept Enter *before* GtkSourceView inserts a newline.
        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect("key-pressed", self._on_key_pressed)
        view.add_controller(key_controller)

        # Click handler: Cmd+Click nav, double-click word, triple-click line
        click_controller = Gtk.GestureClick()
        click_controller.set_button(1)  # Left mouse button
        click_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click_controller.connect("pressed", self._on_click_pressed)
        view.add_controller(click_controller)

        # Right-click: nvim-style context menu (suppress default GtkSourceView menu)
        view.set_extra_menu(None)
        right_click = Gtk.GestureClick()
        right_click.set_button(3)
        right_click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        right_click.connect("pressed", self._on_right_click)
        view.add_controller(right_click)

        # Store reference for navigation callback
        self._cmd_click_callback = None

        # Cmd+hover underline for navigable symbols
        self._setup_hover_underline()

    def apply_font_settings(self):
        """Apply font settings from config."""
        from fonts import get_font_settings

        font_settings = get_font_settings("editor")
        font_family = font_settings["family"]
        font_size = font_settings.get("size", 13)
        font_weight = font_settings.get("weight", "normal")

        css_weight = self._css_font_weight(font_weight)
        letter_spacing = get_setting("editor.letter_spacing", 0)
        letter_spacing_css = f"letter-spacing: {letter_spacing}px;" if letter_spacing else ""
        css = f"""
            textview, textview text {{
                font-family: '{font_family}', monospace;
                font-size: {font_size}pt;
                font-weight: {css_weight};
                {letter_spacing_css}
            }}
        """
        self.font_css_provider.load_from_data(css.encode())

        # Apply font weight via Pango (update stored value for realize handler too)
        self._pending_font_weight = font_weight
        if self.view.get_realized():
            self._apply_pango_font_weight(self.view, font_weight)
            self._apply_ligatures(self.view)

        # Update line spacing
        line_spacing = get_setting("editor.line_spacing", 4)
        above = line_spacing // 2
        below = line_spacing - above
        self.view.set_pixels_above_lines(above)
        self.view.set_pixels_below_lines(below)

    def _on_view_realize_font_weight(self, view):
        """Apply deferred font weight and ligatures once the view is realized."""
        weight = getattr(self, "_pending_font_weight", "normal")
        self._apply_pango_font_weight(view, weight)
        self._apply_ligatures(view)

    # GTK4 CSS only accepts numeric font-weight (100-900) or normal/bold.
    # Use the centralized CSS_WEIGHT_MAP from font_manager.
    @staticmethod
    def _css_font_weight(weight_str: str) -> int:
        """Convert a weight name to a CSS-valid numeric font-weight."""
        from fonts import CSS_WEIGHT_MAP

        return CSS_WEIGHT_MAP.get(weight_str, 400)

    @staticmethod
    def _apply_pango_font_weight(view, weight_str: str):
        """Set font weight on the view's Pango context.

        CSS font-weight alone doesn't reach GtkSourceView's text rendering
        pipeline — Pango font description must be set directly.
        Must be called after the view is realized so the Pango context is final.
        """
        from fonts import PANGO_WEIGHT_MAP

        pango_weight = PANGO_WEIGHT_MAP.get(weight_str, Pango.Weight.NORMAL)
        ctx = view.get_pango_context()
        desc = ctx.get_font_description().copy()
        desc.set_weight(pango_weight)
        ctx.set_font_description(desc)
        view.queue_draw()

    @staticmethod
    def _apply_ligatures(view):
        """Apply font ligature settings via Pango font features.

        When ligatures are enabled, OpenType features 'liga' and 'calt' render
        combined glyphs for sequences like ==, =>, !=, etc.
        Must be called after the view is realized.
        """
        ligatures_enabled = get_setting("editor.font_ligatures", True)
        features = '"liga" 1, "calt" 1' if ligatures_enabled else '"liga" 0, "calt" 0'

        attr_list = Pango.AttrList()
        attr_list.insert(Pango.attr_font_features_new(features))
        ctx = view.get_pango_context()
        ctx.set_font_description(ctx.get_font_description())
        view._ligature_attr_list = attr_list

    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Handle key press for auto-close brackets and word navigation."""
        import platform

        from gi.repository import Gdk

        # Inline completion (ghost text): handle before everything else
        ic = self._inline_completion
        if ic is not None and ic.is_active:
            if ic.handle_key(keyval, state):
                return True

        # Lazy-init inline completion on first keypress (any key — on non-US
        # keyboards like Italian Mac, characters like # may have keyval > 127)
        if self._inline_completion is None:
            self._ensure_inline_completion()

        # Autocomplete: delegate keys when popup is visible
        ac = self._ensure_autocomplete()
        if ac.is_visible():
            if ac.handle_key(keyval, state):
                return True

        # Tab to navigate autocomplete parameter tab stops
        if keyval == Gdk.KEY_Tab and ac.has_active_tab_stops():
            return ac.advance_tab_stop()

        # Escape clears active tab stops
        if keyval == Gdk.KEY_Escape and ac.has_active_tab_stops():
            ac.clear_tab_stops()
            return True

        # Ctrl+Space or Cmd+Space triggers autocomplete
        is_ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        is_cmd = bool(state & Gdk.ModifierType.META_MASK)
        is_shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        is_alt = bool(state & Gdk.ModifierType.ALT_MASK)
        if (
            keyval == Gdk.KEY_space
            and (is_ctrl or (platform.system() == "Darwin" and is_cmd))
            and not is_shift
            and not is_alt
        ):
            self._ensure_autocomplete().show(force=True)
            return True

        # Alt+\ triggers inline AI completion manually
        if is_alt and keyval == Gdk.KEY_backslash and not is_cmd and not is_ctrl:
            ic = self._ensure_inline_completion()
            if ic:
                ic.trigger_now()
            return True

        # Handle Cmd+Backspace to delete to start of line on macOS
        if platform.system() == "Darwin":
            is_cmd = bool(state & Gdk.ModifierType.META_MASK)
            if is_cmd and keyval == Gdk.KEY_BackSpace:
                self._delete_current_line()
                return True

        # Handle Option+Left/Right for word navigation on macOS
        # GTK default behavior swaps words; override to move by word instead
        if platform.system() == "Darwin":
            is_alt = bool(state & Gdk.ModifierType.ALT_MASK)
            is_shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
            # Exclude Cmd modifier - Cmd+Option combos should pass through
            is_cmd = bool(state & Gdk.ModifierType.META_MASK)

            # Cmd+Shift+Left: select to first non-whitespace (smart home)
            if is_cmd and is_shift and keyval == Gdk.KEY_Left:
                cursor = self.buffer.get_insert()
                it = self.buffer.get_iter_at_mark(cursor)
                line_start = it.copy()
                line_start.set_line_offset(0)
                # Find first non-whitespace character on the line
                first_nonws = line_start.copy()
                while not first_nonws.ends_line() and first_nonws.get_char() in (" ", "\t"):
                    first_nonws.forward_char()
                # If cursor is already at or before first non-ws, go to column 0
                target = first_nonws if it.compare(first_nonws) > 0 else line_start
                self.buffer.move_mark(cursor, target)
                return True

            # Cmd+Left: jump to first non-whitespace (smart home)
            if is_cmd and not is_shift and keyval == Gdk.KEY_Left:
                cursor = self.buffer.get_insert()
                it = self.buffer.get_iter_at_mark(cursor)
                line_start = it.copy()
                line_start.set_line_offset(0)
                first_nonws = line_start.copy()
                while not first_nonws.ends_line() and first_nonws.get_char() in (" ", "\t"):
                    first_nonws.forward_char()
                target = first_nonws if it.compare(first_nonws) > 0 else line_start
                self.buffer.place_cursor(target)
                return True

            if is_alt and not is_cmd:
                from shared.utils import handle_word_nav_keypress

                if handle_word_nav_keypress(self.buffer, keyval, state):
                    return True

        # Smart indentation on Enter for Python
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not is_ctrl and not is_alt:
            if self._handle_smart_indent():
                return True

        char = chr(keyval) if 32 <= keyval < 127 else None
        if not char:
            return False

        cursor = self.buffer.get_insert()
        it = self.buffer.get_iter_at_mark(cursor)

        # Auto-close bracket/quote
        if get_setting("editor.auto_close_brackets", True) and char in self.BRACKET_PAIRS:
            close_char = self.BRACKET_PAIRS[char]
            # For quotes, don't auto-close if we're inside a word
            if char in ('"', "'", "`"):
                before = it.copy()
                if before.backward_char():
                    prev_char = before.get_char()
                    if prev_char.isalnum():
                        return False
            # Check if next char is already the close char (skip over it)
            next_char = it.get_char() if not it.is_end() else ""
            if char == close_char and next_char == close_char:
                # Skip over existing close char
                end = it.copy()
                end.forward_char()
                self.buffer.place_cursor(end)
                return True

            # Insert pair
            self.buffer.begin_user_action()
            self.buffer.insert_at_cursor(char + close_char)
            # Move cursor between the pair
            cursor_iter = self.buffer.get_iter_at_mark(self.buffer.get_insert())
            cursor_iter.backward_char()
            self.buffer.place_cursor(cursor_iter)
            self.buffer.end_user_action()
            return True

        # Skip over close bracket if typed
        if get_setting("editor.auto_close_brackets", True) and char in self.CLOSE_BRACKETS:
            next_char = it.get_char() if not it.is_end() else ""
            if next_char == char:
                end = it.copy()
                end.forward_char()
                self.buffer.place_cursor(end)
                return True

        return False

    # ------------------------------------------------------------------
    # Smart indentation helpers
    # ------------------------------------------------------------------

    _DEDENT_KEYWORDS = frozenset(("return", "break", "continue", "pass", "raise"))

    def _handle_smart_indent(self):
        """Add extra indent after openers or dedent after closers/keywords.

        Handles Python (``:``, openers, dedent keywords) and brace-based
        languages (``{`` / ``}``).

        Returns True if the event was consumed, False to let GtkSourceView
        handle it with its default auto-indent behaviour.
        """
        lang = self.buffer.get_language()
        if not lang:
            return False
        lang_id = lang.get_id()

        is_python = lang_id in ("python", "python3")
        is_brace_lang = lang_id in BRACKET_SCOPE_LANGS
        if not is_python and not is_brace_lang:
            return False

        cursor = self.buffer.get_insert()
        it = self.buffer.get_iter_at_mark(cursor)

        # Text from start-of-line to cursor
        line_start = it.copy()
        line_start.set_line_offset(0)
        line_text = self.buffer.get_text(line_start, it, False)

        # Current indentation
        stripped = line_text.lstrip()
        indent_len = len(line_text) - len(stripped)
        indent_str = line_text[:indent_len]
        indent_width = self.view.get_indent_width()
        if indent_width <= 0:
            indent_width = self.view.get_tab_width()
        one_level = " " * indent_width

        new_indent = None

        if is_python:
            code = self._strip_python_comment(stripped)
            if code.endswith(":") or code.endswith(("(", "[", "{")):
                new_indent = indent_str + one_level
            else:
                first_word = code.split()[0] if code else ""
                if first_word in self._DEDENT_KEYWORDS:
                    if indent_len >= indent_width:
                        new_indent = indent_str[:-indent_width]
                    else:
                        new_indent = ""
        else:
            code = self._strip_line_comment(stripped)
            if code.endswith(("{", "(", "[")):
                new_indent = indent_str + one_level
            elif code in ("}", "},", "});", ");", "]", "],", "]);"):
                if indent_len >= indent_width:
                    new_indent = indent_str[:-indent_width]
                else:
                    new_indent = ""

        if new_indent is None:
            return False

        self.buffer.begin_user_action()
        self.buffer.delete_selection(True, True)
        self.buffer.insert_at_cursor("\n" + new_indent)
        self.buffer.end_user_action()
        self.view.scroll_mark_onscreen(self.buffer.get_insert())
        return True

    @staticmethod
    def _strip_python_comment(code):
        """Return *code* with any trailing ``# …`` comment removed.

        Uses a minimal string-literal tracker so ``#`` inside quotes is kept.
        """
        in_string = None
        for i, ch in enumerate(code):
            if in_string:
                if ch == in_string:
                    in_string = None
            elif ch in ("'", '"'):
                in_string = ch
            elif ch == "#":
                return code[:i].rstrip()
        return code.rstrip()

    @staticmethod
    def _strip_line_comment(code):
        """Return *code* with any trailing ``// …`` comment removed.

        Respects string literals so ``//`` inside quotes is kept.
        """
        in_string = None
        prev = ""
        for i, ch in enumerate(code):
            if in_string:
                if ch == in_string and prev != "\\":
                    in_string = None
            elif ch in ("'", '"', "`"):
                in_string = ch
            elif ch == "/" and prev == "/" and not in_string:
                return code[: i - 1].rstrip()
            prev = ch
        return code.rstrip()

    def _delete_current_line(self):
        """Delete text from cursor to start of line (Cmd+Backspace).
        If cursor is already at column 1, act as normal backspace (join with previous line)."""
        cursor = self.buffer.get_insert()
        cursor_iter = self.buffer.get_iter_at_mark(cursor)
        line = cursor_iter.get_line()
        line_start = _iter_at_line(self.buffer, line)

        if cursor_iter.equal(line_start):
            # Cursor at col 1: act as normal backspace (join with previous line)
            if line == 0:
                return
            prev_end = cursor_iter.copy()
            prev_end.backward_char()
            self.buffer.begin_user_action()
            self.buffer.delete(prev_end, cursor_iter)
            self.buffer.end_user_action()
        else:
            # Delete from line start to cursor position
            self.buffer.begin_user_action()
            self.buffer.delete(line_start, cursor_iter)
            self.buffer.end_user_action()

    def _on_right_click(self, gesture, n_press, x, y):
        """Show nvim-style context menu on right-click."""
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        from popups.nvim_context_menu import show_context_menu

        has_selection = self.buffer.get_has_selection()
        clipboard = self.view.get_clipboard()
        can_paste = clipboard is not None

        items = [
            {"label": "Cut", "action": "cut", "icon": Icons.CUT, "enabled": has_selection},
            {"label": "Copy", "action": "copy", "icon": Icons.COPY, "enabled": has_selection},
            {"label": "Paste", "action": "paste", "icon": Icons.PASTE, "enabled": can_paste},
            {"label": "---"},
            {"label": "Select All", "action": "select_all", "icon": Icons.SELECT_ALL},
        ]

        def on_select(action):
            if action == "cut":
                self.view.emit("cut-clipboard")
            elif action == "copy":
                self.view.emit("copy-clipboard")
            elif action == "paste":
                self.view.emit("paste-clipboard")
            elif action == "select_all":
                self.buffer.select_range(self.buffer.get_start_iter(), self.buffer.get_end_iter())

        parent = self.view.get_root()
        show_context_menu(parent, items, on_select, x, y, source_widget=self.view)

    def _on_click_pressed(self, gesture, n_press, x, y):
        """Handle click events - Cmd+Click for navigation, double-click selects word, swatch click for color picker, diagnostic click."""
        import platform

        from gi.repository import Gdk

        # Dismiss inline completion ghost text on any click
        ic = self._inline_completion
        if ic is not None and ic.is_active:
            ic.dismiss()

        # Single click on diagnostic underline: show popover
        if n_press == 1 and hasattr(self, "_diag_error_tag"):
            bx, by = self.view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
            over, it = self.view.get_iter_at_location(bx, by)
            if over and (it.has_tag(self._diag_error_tag) or it.has_tag(self._diag_warning_tag)):
                line_1 = it.get_line() + 1
                # Move cursor to clicked position so click still places the caret
                self.buffer.place_cursor(it)
                self.view.grab_focus()
                loc = self.view.get_iter_location(it)
                _, wy = self.view.buffer_to_window_coords(Gtk.TextWindowType.WIDGET, loc.x, loc.y)
                gesture.set_state(Gtk.EventSequenceState.CLAIMED)
                self._show_line_diagnostics_popover(line_1, int(x), int(wy), loc.height)
                return True

        # Single click on color swatch: open color picker
        if n_press == 1 and self._color_preview:
            hit = self._color_preview.hit_test(x, y)
            if hit:
                gesture.set_state(Gtk.EventSequenceState.CLAIMED)
                self._open_color_picker(*hit)
                return True

        # Get modifier state
        state = gesture.get_current_event_state()

        # Check for Cmd (macOS) or Ctrl (other platforms) modifier
        if platform.system() == "Darwin":
            is_cmd_click = bool(state & Gdk.ModifierType.META_MASK)
        else:
            is_cmd_click = bool(state & Gdk.ModifierType.CONTROL_MASK)

        if n_press == 1 and is_cmd_click:
            # Cmd+Click: navigate to definition
            bx, by = self.view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
            over_text, it = self.view.get_iter_at_location(bx, by)
            if over_text and self._cmd_click_callback:
                gesture.set_state(Gtk.EventSequenceState.CLAIMED)
                self._cmd_click_callback(self.buffer, self.view, self.file_path, it)
                return True

        # Triple-click: select entire line
        if n_press == 3:
            bx, by = self.view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
            _over, it = self.view.get_iter_at_location(bx, by)
            start = it.copy()
            start.set_line_offset(0)
            end = it.copy()
            if not end.ends_line():
                end.forward_to_line_end()
            # Include the newline character if not at last line
            if not end.is_end():
                end.forward_char()
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.buffer.select_range(start, end)
            return

        # Double-click: let GtkSourceView handle selection rendering first,
        # then expand selection to include underscores in the next idle tick.
        # This avoids a visual shift caused by claiming the gesture in CAPTURE
        # phase before GtkSourceView has updated its internal rendering state.
        if n_press == 2:
            bx, by = self.view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
            _over_text, it = self.view.get_iter_at_location(bx, by)
            ch = it.get_char()
            if ch and (ch.isalnum() or ch == "_"):
                offset = it.get_offset()
                GLib.idle_add(self._select_word_at_offset, offset)
            return

    def _select_word_at_offset(self, offset):
        """Expand selection to include underscores (deferred from double-click).

        Called via GLib.idle_add so GtkSourceView has already rendered its own
        word selection.  We override only to include underscores in the word.
        """
        it = self.buffer.get_iter_at_offset(offset)
        ch = it.get_char()
        if not ch or not (ch.isalnum() or ch == "_"):
            return False
        start = it.copy()
        end = it.copy()
        while True:
            if start.is_start():
                break
            start.backward_char()
            if not (start.get_char().isalnum() or start.get_char() == "_"):
                start.forward_char()
                break
        while not end.is_end():
            if not (end.get_char().isalnum() or end.get_char() == "_"):
                break
            end.forward_char()
        if not start.equal(end):
            self.buffer.select_range(start, end)
        return False

    # -- Diagnostic wavy underlines --

    def _setup_diagnostic_underline_tags(self):
        """Create text tags for diagnostics (background only; wave drawn in ZenSourceView)."""
        theme = get_theme()
        err_color = theme.term_red
        warn_color = theme.term_yellow

        self._diag_error_tag = self.buffer.create_tag(
            "diag_error_underline",
            background_rgba=_parse_rgba(err_color, 0.12),
        )
        self._diag_warning_tag = self.buffer.create_tag(
            "diag_warning_underline",
            background_rgba=_parse_rgba(warn_color, 0.12),
        )
        # Store wave colors on the view for custom wavy line drawing
        self.view._diag_error_wave_rgba = _parse_hex_color(err_color) + (1.0,)
        self.view._diag_warning_wave_rgba = _parse_hex_color(warn_color) + (1.0,)

    def _update_diagnostic_underline_colors(self, theme):
        """Update diagnostic underline colors when theme changes."""
        err_hex = theme.term_red
        warn_hex = theme.term_yellow
        if hasattr(self, "_diag_error_tag"):
            self._diag_error_tag.props.background_rgba = _parse_rgba(err_hex, 0.12)
        if hasattr(self, "_diag_warning_tag"):
            self._diag_warning_tag.props.background_rgba = _parse_rgba(warn_hex, 0.12)
        # Sync wave colors on the view
        self.view._diag_error_wave_rgba = _parse_hex_color(err_hex) + (1.0,)
        self.view._diag_warning_wave_rgba = _parse_hex_color(warn_hex) + (1.0,)

    def _clear_diagnostic_underlines(self):
        """Remove all diagnostic underline tags from the buffer."""
        # Use fresh iterators for each remove_tag call — GtkSourceBuffer's
        # internal re-highlighting may invalidate iterators after tag changes.
        self.buffer.remove_tag(self._diag_error_tag, self.buffer.get_start_iter(), self.buffer.get_end_iter())
        self.buffer.remove_tag(self._diag_warning_tag, self.buffer.get_start_iter(), self.buffer.get_end_iter())

    def _apply_diagnostic_underlines(self, diagnostics):
        """Apply wavy underline tags for each diagnostic."""
        from shared.diagnostics_manager import SEVERITY_ERROR

        self._clear_diagnostic_underlines()

        line_count = self.buffer.get_line_count()
        for d in diagnostics:
            if d.line < 1 or d.line > line_count:
                continue

            tag = self._diag_error_tag if d.severity == SEVERITY_ERROR else self._diag_warning_tag

            # Start iter at (line, col) — both 1-based → 0-based
            start_line_0 = d.line - 1
            start_line_iter = _iter_at_line(self.buffer, start_line_0)
            line_chars = start_line_iter.get_chars_in_line()
            start_col = min(max(0, d.col - 1), max(0, line_chars - 1))
            start = _iter_at_line_offset(self.buffer, start_line_0, start_col)

            if d.end_line > 0 and d.end_col > 0:
                # Exact range from linter
                end_line_0 = min(d.end_line - 1, line_count - 1)
                end_iter = _iter_at_line(self.buffer, end_line_0)
                end_line_chars = end_iter.get_chars_in_line()
                end_col_0 = min(d.end_col - 1, max(0, end_line_chars - 1))
                end = _iter_at_line_offset(self.buffer, end_line_0, end_col_0)
            else:
                # No end info — underline the word at start position
                end = start.copy()
                if not end.ends_line():
                    end.forward_char()
                    while not end.ends_line():
                        ch = end.get_char()
                        if not (ch.isalnum() or ch == "_"):
                            break
                        end.forward_char()

            if start.compare(end) < 0:
                self.buffer.apply_tag(tag, start, end)

    def _show_line_diagnostics_popover(self, line_1: int, click_x: int, click_y: int, line_height: int = 20):
        """Show a popover with diagnostics for the clicked gutter line."""
        from gi.repository import Gdk

        from shared.diagnostics_manager import SEVERITY_ERROR, get_diagnostics_manager
        from themes import get_theme

        all_diags = get_diagnostics_manager().get_diagnostics(self.file_path) if self.file_path else []
        diags = [d for d in all_diags if d.line <= line_1 <= (d.end_line if d.end_line > 0 else d.line)]
        if not diags:
            return

        # Dismiss any existing diagnostics popover
        if hasattr(self, "_diag_popover") and self._diag_popover:
            self._diag_popover.unparent()
            self._diag_popover = None

        from fonts import get_font_settings

        theme = get_theme()
        err_color = theme.term_red
        warn_color = theme.term_yellow
        fg = theme.fg_color
        bg = theme.main_bg

        font_settings = get_font_settings("editor")
        font_family = font_settings["family"]
        font_size = font_settings.get("size", 16)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        content_box.set_margin_start(8)
        content_box.set_margin_end(8)
        content_box.set_margin_top(6)
        content_box.set_margin_bottom(6)

        for d in diags:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            color = err_color if d.severity == SEVERITY_ERROR else warn_color
            icon = Icons.ERROR_X if d.severity == SEVERITY_ERROR else Icons.WARNING
            icon_label = Gtk.Label()
            icon_label.set_use_markup(True)
            icon_label.set_markup(f'<span font_family="{ICON_FONT_FAMILY}" foreground="{color}">{icon}</span>')
            row.append(icon_label)

            code_part = f" <span foreground='{color}'>[{d.code}]</span>" if d.code else ""
            msg_label = Gtk.Label()
            msg_label.set_use_markup(True)
            msg_label.set_markup(f'<span foreground="{fg}">{GLib.markup_escape_text(d.message)}{code_part}</span>')
            msg_label.set_wrap(True)
            msg_label.set_max_width_chars(80)
            msg_label.set_halign(Gtk.Align.START)
            row.append(msg_label)
            content_box.append(row)

        popover = Gtk.Popover()
        popover.set_child(content_box)
        popover.set_parent(self.view)
        popover.set_autohide(True)
        popover.add_css_class("zen-diagnostics-popover")

        rect = Gdk.Rectangle()
        rect.x = click_x
        rect.y = click_y + line_height
        rect.width = 1
        rect.height = 1
        popover.set_pointing_to(rect)
        popover.set_position(Gtk.PositionType.BOTTOM)

        # Apply theme colors via inline CSS
        css = f"""
        popover.zen-diagnostics-popover > contents {{
            background-color: {bg};
            border: 1px solid {theme.accent_color};
            border-radius: 4px;
            font-family: '{font_family}';
            font-size: {font_size}pt;
        }}
        """
        provider = Gtk.CssProvider()
        provider.load_from_string(css)
        popover.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # Clean up on close
        def on_closed(_popover):
            _popover.unparent()
            if hasattr(self, "_diag_popover") and self._diag_popover is _popover:
                self._diag_popover = None

        popover.connect("closed", on_closed)
        self._diag_popover = popover
        popover.popup()

    def set_cmd_click_callback(self, callback):
        """Set the callback for Cmd+Click navigation."""
        self._cmd_click_callback = callback

    def _open_color_picker(self, line, col, hex_str):
        """Open a color picker popup for the swatch at (line, col) with current hex_str."""
        r, g, b, a = ColorPreviewRenderer._parse_color(hex_str)
        if r is None:
            return

        from popups.color_picker_popup import ColorPickerPopup

        with_alpha = len(hex_str.lstrip("#")) == 8
        window = self.view.get_root()

        def on_apply(new_hex, ln=line, c=col, old=hex_str):
            self._apply_color(new_hex, ln, c, old)

        popup = ColorPickerPopup(window, hex_str, with_alpha, on_apply)
        popup.present()

    def _apply_color(self, new_hex, line, col, old_hex):
        """Apply selected color back into the buffer."""
        buf = self.buffer
        start = ColorPreviewRenderer._iter_at_line_offset(buf, line, col)
        end = ColorPreviewRenderer._iter_at_line_offset(buf, line, col + len(old_hex))
        if start is None or end is None:
            return

        buf.begin_user_action()
        buf.delete(start, end)
        insert_iter = ColorPreviewRenderer._iter_at_line_offset(buf, line, col)
        if insert_iter:
            buf.insert(insert_iter, new_hex)
        buf.end_user_action()

    def _setup_hover_underline(self):
        """Setup Cmd+hover underline for navigable symbols."""

        # Get theme accent color for the underline
        theme = get_theme()

        # Create underline tag for hover effect with theme accent color
        self._link_tag = self.buffer.create_tag(
            "navigable_link",
            underline=Pango.Underline.SINGLE,
            foreground=theme.accent_color,
        )

        # Track hover state using marks (survive buffer modifications)
        self._hover_underline_start_mark = None
        self._hover_underline_end_mark = None
        self._cmd_held = False

        # Motion controller for hover
        motion_controller = Gtk.EventControllerMotion()
        motion_controller.connect("motion", self._on_hover_motion)
        motion_controller.connect("leave", self._on_hover_leave)
        self.view.add_controller(motion_controller)

        # Key controller to track Cmd key press/release
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_cmd_key_pressed)
        key_controller.connect("key-released", self._on_cmd_key_released)
        self.view.add_controller(key_controller)

    def _on_cmd_key_pressed(self, controller, keyval, keycode, state):
        """Track Cmd key press for hover underline."""
        import platform

        from gi.repository import Gdk

        # Check for Cmd (macOS) or Ctrl (other platforms)
        if platform.system() == "Darwin":
            if keyval in (Gdk.KEY_Meta_L, Gdk.KEY_Meta_R):
                self._cmd_held = True
        else:
            if keyval in (Gdk.KEY_Control_L, Gdk.KEY_Control_R):
                self._cmd_held = True
        return False

    def _on_cmd_key_released(self, controller, keyval, keycode, state):
        """Track Cmd key release for hover underline."""
        import platform

        from gi.repository import Gdk

        # Check for Cmd (macOS) or Ctrl (other platforms)
        if platform.system() == "Darwin":
            if keyval in (Gdk.KEY_Meta_L, Gdk.KEY_Meta_R):
                self._cmd_held = False
                self._clear_hover_underline()
        else:
            if keyval in (Gdk.KEY_Control_L, Gdk.KEY_Control_R):
                self._cmd_held = False
                self._clear_hover_underline()
        return False

    def _on_hover_motion(self, controller, x, y):
        """Handle mouse motion for Cmd+hover underline."""
        import platform

        from gi.repository import Gdk

        # Get modifier state
        state = controller.get_current_event_state()

        # Check for Cmd (macOS) or Ctrl (other platforms) modifier
        if platform.system() == "Darwin":
            is_cmd_held = bool(state & Gdk.ModifierType.META_MASK)
        else:
            is_cmd_held = bool(state & Gdk.ModifierType.CONTROL_MASK)

        self._cmd_held = is_cmd_held

        if not is_cmd_held:
            self._clear_hover_underline()
            # Show pointer cursor when hovering over diagnostic underlines
            if hasattr(self, "_diag_error_tag"):
                bx, by = self.view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
                over, it = self.view.get_iter_at_location(bx, by)
                if over and (it.has_tag(self._diag_error_tag) or it.has_tag(self._diag_warning_tag)):
                    cursor = Gdk.Cursor.new_from_name("pointer", None)
                    self.view.set_cursor(cursor)
                    return
            self.view.set_cursor(None)
            return

        # Convert to buffer coordinates
        bx, by = self.view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
        over_text, it = self.view.get_iter_at_location(bx, by)

        if not over_text:
            self._clear_hover_underline()
            self.view.set_cursor(None)
            return

        # Try file path detection first
        path_result = self._get_file_path_at_iter(it)
        if path_result:
            _path_str, s, e = path_result
            line_num = it.get_line()

            start = _iter_at_line_offset(self.buffer, line_num, s)
            end = _iter_at_line_offset(self.buffer, line_num, e)

            if (
                self._hover_underline_start_mark is not None
                and self.buffer.get_iter_at_mark(self._hover_underline_start_mark).equal(start)
                and self._hover_underline_end_mark is not None
                and self.buffer.get_iter_at_mark(self._hover_underline_end_mark).equal(end)
            ):
                return

            self._clear_hover_underline()
            # Rebuild iterators — _clear_hover_underline's remove_tag may
            # invalidate outstanding iterators on GtkSourceBuffer.
            start = _iter_at_line_offset(self.buffer, line_num, s)
            end = _iter_at_line_offset(self.buffer, line_num, e)
            self.buffer.apply_tag(self._link_tag, start, end)
            self._hover_underline_start_mark = self.buffer.create_mark(None, start, True)
            self._hover_underline_end_mark = self.buffer.create_mark(None, end, False)

            from gi.repository import Gdk

            cursor = Gdk.Cursor.new_from_name("pointer", None)
            self.view.set_cursor(cursor)
            return

        # Skip words inside strings or comments (not navigable).
        # iter_has_context_class can trigger lazy re-highlighting which
        # changes the buffer stamp and invalidates all outstanding iterators.
        # Store the offset so we can rebuild a fresh iterator afterwards.
        iter_offset = it.get_offset()
        if hasattr(self.buffer, "iter_has_context_class"):
            if self.buffer.iter_has_context_class(it, "string") or self.buffer.iter_has_context_class(
                self.buffer.get_iter_at_offset(iter_offset), "comment"
            ):
                self._clear_hover_underline()
                self.view.set_cursor(None)
                return

        # Rebuild iterator — iter_has_context_class above may have triggered
        # lazy re-highlighting that invalidated the previous iterator.
        it = self.buffer.get_iter_at_offset(iter_offset)

        # Get the word at position
        word = self._get_word_at_iter(it)
        if not word:
            self._clear_hover_underline()
            self.view.set_cursor(None)
            return

        # Check if word is navigable
        if not self._is_word_navigable(word):
            self._clear_hover_underline()
            self.view.set_cursor(None)
            return

        # Get word boundaries using identifier-aware logic (underscores included)
        line_start = it.copy()
        line_start.set_line_offset(0)
        line_end_iter = it.copy()
        if not line_end_iter.ends_line():
            line_end_iter.forward_to_line_end()
        line_content = self.buffer.get_text(line_start, line_end_iter, True)
        col = it.get_line_offset()

        s = col
        while s > 0 and (line_content[s - 1].isalnum() or line_content[s - 1] == "_"):
            s -= 1
        e = col
        while e < len(line_content) and (line_content[e].isalnum() or line_content[e] == "_"):
            e += 1

        line_num = it.get_line()
        start = _iter_at_line_offset(self.buffer, line_num, s)
        end = _iter_at_line_offset(self.buffer, line_num, e)

        # Check if we're already underlining this word
        if (
            self._hover_underline_start_mark is not None
            and self.buffer.get_iter_at_mark(self._hover_underline_start_mark).equal(start)
            and self._hover_underline_end_mark is not None
            and self.buffer.get_iter_at_mark(self._hover_underline_end_mark).equal(end)
        ):
            return

        # Clear previous underline and apply new one
        self._clear_hover_underline()
        # Rebuild iterators — _clear_hover_underline's remove_tag may
        # invalidate outstanding iterators on GtkSourceBuffer.
        start = _iter_at_line_offset(self.buffer, line_num, s)
        end = _iter_at_line_offset(self.buffer, line_num, e)
        self.buffer.apply_tag(self._link_tag, start, end)
        self._hover_underline_start_mark = self.buffer.create_mark(None, start, True)
        self._hover_underline_end_mark = self.buffer.create_mark(None, end, False)

        # Change cursor to pointing hand
        from gi.repository import Gdk

        cursor = Gdk.Cursor.new_from_name("pointer", None)
        self.view.set_cursor(cursor)

    def _on_hover_leave(self, controller):
        """Handle mouse leaving the view."""
        self._clear_hover_underline()
        self.view.set_cursor(None)

    def _clear_hover_underline(self):
        """Remove the hover underline tag."""
        if self._hover_underline_start_mark is not None and self._hover_underline_end_mark is not None:
            start = self.buffer.get_iter_at_mark(self._hover_underline_start_mark)
            end = self.buffer.get_iter_at_mark(self._hover_underline_end_mark)
            self.buffer.remove_tag(self._link_tag, start, end)
            self.buffer.delete_mark(self._hover_underline_start_mark)
            self.buffer.delete_mark(self._hover_underline_end_mark)
        self._hover_underline_start_mark = None
        self._hover_underline_end_mark = None

    # File path characters for path detection
    _FILE_PATH_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.~/#")

    def _get_file_path_at_iter(self, it: Gtk.TextIter):
        """Get file path string and its (start_col, end_col) at iterator position, or None."""
        line_start = it.copy()
        line_start.set_line_offset(0)
        line_end = it.copy()
        if not line_end.ends_line():
            line_end.forward_to_line_end()

        line_content = self.buffer.get_text(line_start, line_end, True)
        col = it.get_line_offset()

        if col >= len(line_content) or line_content[col] not in self._FILE_PATH_CHARS:
            return None

        s = col
        e = col
        while s > 0 and line_content[s - 1] in self._FILE_PATH_CHARS:
            s -= 1
        while e < len(line_content) and line_content[e] in self._FILE_PATH_CHARS:
            e += 1

        path_str = line_content[s:e].rstrip(".")
        if not path_str or "/" not in path_str:
            return None

        return path_str, s, e

    def _get_word_at_iter(self, it: Gtk.TextIter) -> str:
        """Get the word at the given iterator position."""
        # Get line content
        line_start = it.copy()
        line_start.set_line_offset(0)
        line_end = it.copy()
        if not line_end.ends_line():
            line_end.forward_to_line_end()

        line_content = self.buffer.get_text(line_start, line_end, True)
        col = it.get_line_offset()

        if col >= len(line_content):
            return ""

        # Find word boundaries (identifier characters)
        start = col
        end = col

        while start > 0 and (line_content[start - 1].isalnum() or line_content[start - 1] == "_"):
            start -= 1

        while end < len(line_content) and (line_content[end].isalnum() or line_content[end] == "_"):
            end += 1

        if start < end:
            return line_content[start:end]
        return ""

    def _is_word_navigable(self, word: str) -> bool:
        """Check if a word is navigable (not a Python builtin, is an identifier)."""
        if not word or not word[0].isalpha() and word[0] != "_":
            return False

        # Python builtins that can't be navigated to
        UNNAVIGABLE_BUILTINS = {
            "str",
            "int",
            "float",
            "bool",
            "bytes",
            "list",
            "dict",
            "set",
            "tuple",
            "object",
            "type",
            "None",
            "True",
            "False",
            "super",
            "property",
            "staticmethod",
            "classmethod",
            "isinstance",
            "issubclass",
            "hasattr",
            "getattr",
            "setattr",
            "delattr",
            "len",
            "range",
            "enumerate",
            "zip",
            "map",
            "filter",
            "sorted",
            "reversed",
            "print",
            "open",
            "input",
            "format",
            "repr",
            "id",
            "hash",
            "callable",
            "iter",
            "next",
            "all",
            "any",
            "min",
            "max",
            "sum",
            "abs",
            "round",
            "pow",
            "divmod",
            "ord",
            "chr",
            "bin",
            "hex",
            "oct",
            "ascii",
            "eval",
            "exec",
            "compile",
            "globals",
            "locals",
            "vars",
            "dir",
            "help",
            "exit",
            "quit",
            "slice",
            "Exception",
            "BaseException",
            "ValueError",
            "TypeError",
            "KeyError",
            "IndexError",
            "AttributeError",
            "ImportError",
            "FileNotFoundError",
            "OSError",
            "RuntimeError",
            "StopIteration",
            "NotImplementedError",
            "self",
            "cls",
            "if",
            "else",
            "elif",
            "for",
            "while",
            "try",
            "except",
            "finally",
            "with",
            "as",
            "import",
            "from",
            "class",
            "def",
            "return",
            "yield",
            "raise",
            "pass",
            "break",
            "continue",
            "and",
            "or",
            "not",
            "in",
            "is",
            "lambda",
            "assert",
            "global",
            "nonlocal",
            "del",
            "async",
            "await",
        }

        return word not in UNNAVIGABLE_BUILTINS

    def _apply_theme(self):
        """Apply the current theme to the source view."""
        theme = get_theme()

        # Generate custom style scheme from theme's syntax colors
        scheme_id = _generate_style_scheme(theme)
        scheme_manager = GtkSource.StyleSchemeManager.get_default()
        scheme = scheme_manager.get_scheme(scheme_id)
        if scheme:
            self.buffer.set_style_scheme(scheme)

        # Apply background color via CSS (remove old provider to avoid accumulation)
        if hasattr(self, "_theme_css_provider"):
            self.view.get_style_context().remove_provider(self._theme_css_provider)
        css_provider = Gtk.CssProvider()
        self._theme_css_provider = css_provider
        css = f"""
            textview text {{
                background-color: {theme.main_bg};
                color: {theme.fg_color};
            }}
            textview.view {{
                background-color: {theme.main_bg};
            }}
        """
        css_provider.load_from_data(css.encode())
        self.view.get_style_context().add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)

        # Set indent guide color from theme (user settings can override)
        from constants import INDENT_GUIDE_ALPHA

        if hasattr(self.view, "set_guide_color_hex"):
            guide_color = get_setting("editor.indent_guide_color", "") or theme.indent_guide
            guide_alpha = get_setting("editor.indent_guide_alpha", -1)
            if guide_alpha < 0:
                guide_alpha = INDENT_GUIDE_ALPHA
            self.view.set_guide_color_hex(guide_color, alpha=guide_alpha)

        # Update semantic highlight tag colors
        update_semantic_colors(self, theme)

        # Update diagnostic underline colors
        self._update_diagnostic_underline_colors(theme)

        # Update inline completion ghost text colors
        if getattr(self, "_inline_completion", None) is not None:
            self._inline_completion.update_theme()

    def _set_language_from_file(self, file_path: str):
        """Set the source language and per-language indent width based on file."""
        from editor.langs.language_detect import detect_language

        language = detect_language(file_path)
        if language:
            self.buffer.set_language(language)

        # Apply per-language indent width and tab mode
        from constants import TAB_ONLY_LANGS

        ext = os.path.splitext(file_path)[1].lower()
        lang_id = language.get_id() if language else None
        use_tabs = lang_id in TAB_ONLY_LANGS
        indent = LANG_INDENT_WIDTH.get(lang_id) or LANG_INDENT_WIDTH.get(ext) or DEFAULT_INDENT_WIDTH

        # Auto-detect indent width from file content when available
        if not use_tabs:
            text = self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), True)
            if text.strip():
                from editor.indent_guide_levels import detect_indent_width

                indent = detect_indent_width(text, indent)

        self.view.set_tab_width(indent)
        self.view.set_indent_width(indent)
        self.view.set_insert_spaces_instead_of_tabs(not use_tabs)

    def load_file(self, file_path: str) -> bool:
        """Load content from a file."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            # Auto-format JSON files for readability
            if file_path.lower().endswith(".json"):
                import json

                try:
                    parsed = json.loads(content)
                    content = json.dumps(parsed, indent=2, ensure_ascii=False) + "\n"
                except (json.JSONDecodeError, ValueError):
                    pass  # Keep original content if JSON is invalid

            # Set language BEFORE content so GtkSourceView applies regex
            # highlighting as the buffer text is set (avoids white flash).
            from editor.langs.language_detect import detect_language

            lang = detect_language(file_path)
            if lang:
                self.buffer.set_language(lang)

            self.buffer.set_text(content)
            self.original_content = content
            self.file_path = file_path
            self.modified = False
            self.is_new = False

            # Configure indent from file content (set_language is a no-op
            # since the same language is already set above).
            self._set_language_from_file(file_path)

            # Update gutter diff renderer with file path
            self._gutter_diff.set_file_path(file_path)

            # Apply cached diagnostics (from workspace scan) or run fresh
            self._apply_or_run_diagnostics()

            # Move cursor to beginning
            self.buffer.place_cursor(self.buffer.get_start_iter())

            # Force GtkSourceView to synchronously finish regex tokenisation
            # for the entire buffer so the first paint never shows un-styled
            # text.  Without this, the regex engine runs in idle handlers and
            # the view may render before highlighting is complete.
            self.buffer.ensure_highlight(
                self.buffer.get_start_iter(),
                self.buffer.get_end_iter(),
            )

            return True
        except Exception as e:
            import traceback

            print(f"\033[31m[ZEN] load_file failed for {file_path}: {e}\033[0m")
            traceback.print_exc()
            return False

    def reload_file(self) -> bool:
        """Reload content from file, preserving cursor position.

        Used when the file is modified externally.
        Returns True if reload succeeded, False otherwise.
        """
        if not self.file_path or not os.path.isfile(self.file_path):
            return False

        try:
            with open(self.file_path, "r", encoding="utf-8", errors="replace") as f:
                new_content = f.read()

            # Auto-format JSON files for readability
            if self.file_path.lower().endswith(".json"):
                import json

                try:
                    parsed = json.loads(new_content)
                    new_content = json.dumps(parsed, indent=2, ensure_ascii=False) + "\n"
                except (json.JSONDecodeError, ValueError):
                    pass

            # Skip reload if content hasn't actually changed
            start_iter = self.buffer.get_start_iter()
            end_iter = self.buffer.get_end_iter()
            current_content = self.buffer.get_text(start_iter, end_iter, True)
            if new_content == current_content:
                return True

            # Save cursor position (line and column) and scroll position
            cursor_mark = self.buffer.get_insert()
            cursor_iter = self.buffer.get_iter_at_mark(cursor_mark)
            cursor_line = cursor_iter.get_line()
            cursor_col = cursor_iter.get_line_offset()
            vadj = self.view.get_vadjustment()
            saved_scroll = vadj.get_value() if vadj else 0.0

            # Update original_content BEFORE set_text so the buffer-changed
            # handler sees matching content and doesn't mark tab as modified
            self.original_content = new_content
            self.modified = False
            self.buffer.set_text(new_content)

            # Restore cursor position (clamped to valid range)
            line_count = self.buffer.get_line_count()
            target_line = min(cursor_line, line_count - 1)
            new_iter = _iter_at_line(self.buffer, target_line)
            if new_iter:
                # Clamp column to line length
                line_end = new_iter.copy()
                if not line_end.ends_line():
                    line_end.forward_to_line_end()
                max_col = line_end.get_line_offset()
                target_col = min(cursor_col, max_col)
                new_iter.forward_chars(target_col)
                self.buffer.place_cursor(new_iter)

            # Restore scroll position after set_text reset it
            if vadj:
                GLib.idle_add(lambda: vadj.set_value(saved_scroll) or False)

            # Refresh gutter diff for external changes
            self._gutter_diff.refresh_head()

            # Force synchronous highlighting so the reload doesn't flash
            self.buffer.ensure_highlight(
                self.buffer.get_start_iter(),
                self.buffer.get_end_iter(),
            )

            return True
        except Exception as e:
            import traceback

            print(f"\033[31m[ZEN] reload_file failed: {e}\033[0m")
            traceback.print_exc()
            return False

    def save_file(self, file_path: str = None) -> bool:
        """Save content to a file."""
        if getattr(self, "_is_image", False):
            return False
        path = file_path or self.file_path
        if not path:
            return False

        try:
            start = self.buffer.get_start_iter()
            end = self.buffer.get_end_iter()
            content = self.buffer.get_text(start, end, True)

            # Auto-format on save
            formatted = self._format_on_save(path, content)
            if formatted is not None and formatted != content:
                content = formatted
                # Apply formatting using incremental edits to preserve scroll/cursor
                self._apply_incremental_edit(content)

            # Mark as internally saved BEFORE file write so file watcher
            # (which runs in background thread) won't race and reload
            self._last_internal_save_time = time.monotonic()

            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

            self.original_content = content
            self.file_path = path
            self.modified = False
            self.is_new = False

            # Refresh gutter diff (HEAD now matches saved content)
            self._gutter_diff.refresh_head()

            # Run diagnostics (linting) on save — deferred to avoid blocking
            self._run_diagnostics_deferred()

            return True
        except Exception as e:
            import traceback

            print(f"\033[31m[ZEN] save_file failed for {path}: {e}\033[0m")
            traceback.print_exc()
            return False

    def _format_on_save(self, path: str, content: str) -> str | None:
        """Run configured formatter on content before saving."""
        try:
            from editor.format_manager import format_content

            return format_content(path, content)
        except Exception:
            return None

    def _apply_incremental_edit(self, new_content: str):
        """Apply text changes incrementally to preserve scroll and cursor.

        Uses difflib to find minimal changes.
        This avoids the scroll jump caused by buffer.set_text().
        """
        import difflib

        old_lines = self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), True).splitlines(
            keepends=True
        )
        new_lines = new_content.splitlines(keepends=True)

        # Ensure last line has newline for consistent comparison
        if old_lines and not old_lines[-1].endswith("\n"):
            old_lines[-1] += "\n"
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"

        # Get opcodes describing how to transform old -> new
        matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
        opcodes = matcher.get_opcodes()

        # If no changes, nothing to do
        if all(op[0] == "equal" for op in opcodes):
            return

        self.buffer.begin_user_action()
        try:
            # Apply changes in reverse order to preserve line numbers
            for tag, i1, i2, j1, j2 in reversed(opcodes):
                if tag == "equal":
                    continue

                # Calculate character offsets for the range [i1, i2)
                start_iter = self.buffer.get_start_iter()
                for _ in range(i1):
                    if not start_iter.forward_line():
                        break

                end_iter = self.buffer.get_start_iter()
                for _ in range(i2):
                    if not end_iter.forward_line():
                        # i2 might be past end, go to buffer end
                        end_iter = self.buffer.get_end_iter()
                        break

                # Get new text for this region
                new_text = "".join(new_lines[j1:j2])
                # Strip trailing newline if we're at end of buffer
                if end_iter.is_end() and new_text.endswith("\n"):
                    new_text = new_text[:-1]

                # Use a mark to preserve position across the delete
                mark = self.buffer.create_mark(None, start_iter, True)
                self.buffer.delete(start_iter, end_iter)
                ins_iter = self.buffer.get_iter_at_mark(mark)
                self.buffer.delete_mark(mark)
                self.buffer.insert(ins_iter, new_text)

        finally:
            self.buffer.end_user_action()

    def _apply_or_run_diagnostics(self):
        """Apply cached diagnostics if available, otherwise run fresh."""
        if not self.file_path:
            return

        from shared.diagnostics_manager import get_diagnostics_manager

        mgr = get_diagnostics_manager()
        if mgr.has_diagnostics_data(self.file_path):
            # Workspace scan already produced results — apply them directly
            cached = mgr.get_diagnostics(self.file_path)
            self._apply_diagnostic_underlines(cached)
            cb = self.on_diagnostics_changed
            if cb:
                errors = sum(1 for d in cached if d.severity == "error")
                warnings = sum(1 for d in cached if d.severity != "error")
                cb(self.file_path, errors, warnings)
            return
        # No cached results — run fresh diagnostics
        self._run_diagnostics()

    def _run_diagnostics(self):
        """Run linter diagnostics for this file."""
        if not self.file_path:
            return

        from shared.diagnostics_manager import get_diagnostics_manager

        mgr = get_diagnostics_manager()

        def on_results(file_path, diagnostics):
            if file_path == self.file_path:
                self._apply_diagnostic_underlines(diagnostics)
                # Resolve callback at result time (not capture time) so it
                # works even when diagnostics are kicked off before
                # _add_tab_common wires the callback.
                cb = self.on_diagnostics_changed
                if cb:
                    errors = sum(1 for d in diagnostics if d.severity == "error")
                    warnings = sum(1 for d in diagnostics if d.severity != "error")
                    cb(file_path, errors, warnings)

        mgr.run_diagnostics(self.file_path, callback=on_results)

    def _run_diagnostics_deferred(self):
        """Run linter diagnostics after a short delay (debounced)."""
        if not self.file_path:
            return

        from shared.diagnostics_manager import get_diagnostics_manager

        mgr = get_diagnostics_manager()

        def on_results(file_path, diagnostics):
            if file_path == self.file_path:
                self._apply_diagnostic_underlines(diagnostics)
                cb = self.on_diagnostics_changed
                if cb:
                    errors = sum(1 for d in diagnostics if d.severity == "error")
                    warnings = sum(1 for d in diagnostics if d.severity != "error")
                    cb(file_path, errors, warnings)

        mgr.run_diagnostics_deferred(self.file_path, callback=on_results)

    def get_title(self) -> str:
        """Get the tab title (without modified indicator)."""
        if self.file_path:
            name = os.path.basename(self.file_path)
            from constants import WORKSPACE_EXTENSIONS

            for ext in WORKSPACE_EXTENSIONS:
                if name.endswith(ext):
                    name = name[: -len(ext)]
                    break
            return name
        else:
            return "Untitled"


class EditorView(FocusBorderMixin, Gtk.Box):
    """Editor view with tabbed interface."""

    COMPONENT_ID = "editor"

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        # Initialize focus border
        self._init_focus_border()

        # Register with focus manager
        focus_mgr = get_component_focus_manager()
        focus_mgr.register(
            self.COMPONENT_ID,
            on_focus_in=self._on_focus_in,
            on_focus_out=self._on_focus_out,
        )

        # Use tab_id (unique, never changes) as key, NOT page_num (position, changes on close)
        self.tabs: dict[int, EditorTab] = {}  # tab_id -> EditorTab
        self._next_tab_id = 1

        # Callback for when a file is opened (for tree view sync)
        self.on_file_opened: Callable[[str], None] | None = None
        # Callback for when a tab is switched (for tree view sync)
        self.on_tab_switched: Callable[[str], None] | None = None
        # Callback for cursor position changes (for status bar)
        self.on_cursor_position_changed: Callable[[int, int, int], None] | None = None
        # Callback for diagnostics updates (for status bar)
        self.on_diagnostics_changed: Callable[[int, int], None] | None = None
        # Callback for gutter diagnostic click (for diagnostics popup)
        self.on_gutter_diagnostic_clicked: Callable | None = None
        # Callback for when all tabs are closed (no files open)
        self.on_tabs_empty: Callable[[], None] | None = None
        # Callback for when any tab is closed (for persisting open files)
        self.on_tab_closed: Callable[[], None] | None = None

        # Create notebook for tabs
        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.notebook.set_show_border(False)
        self.notebook.set_vexpand(True)
        self.notebook.connect("switch-page", self._on_tab_changed)
        self.append(self.notebook)

        # Track active/previous tab for close-button restoration
        self._active_tab_id = -1
        self._previous_active_tab_id = -1

        # Find bar created lazily on first Cmd+F (saves ~2-3ms at startup)
        self._find_bar_created = False

        # Track modifications by tab_id
        self._modification_handler_ids = {}

        # Search context (persisted so match count updates work)
        self._search_context = None
        self._search_settings = None

        # Add click controller to gain focus
        click_ctrl = Gtk.GestureClick.new()
        click_ctrl.connect("pressed", self._on_panel_click)
        self.add_controller(click_ctrl)

        # Code navigation system
        self._code_navigation = None

        # Callback for getting workspace folders (set by main app)
        self.get_workspace_folders: Callable[[], list] | None = None

        # Subscribe to theme changes so all editor tabs update
        subscribe_theme_change(self._on_theme_change)

    def _on_theme_change(self, theme):
        """Re-apply theme to all open editor tabs, preserving scroll position."""
        for tab in self.tabs.values():
            vadj = tab.view.get_vadjustment()
            scroll_pos = vadj.get_value() if vadj else 0
            tab._apply_theme()
            if vadj and scroll_pos > 0:
                GLib.idle_add(lambda v=vadj, p=scroll_pos: v.set_value(p) or False)

    def _create_find_bar(self):
        """Create the find & replace bar."""
        self.find_bar = Gtk.SearchBar()
        self.find_bar.set_show_close_button(True)

        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        # Find row
        find_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        self.find_entry = ZenSearchEntry(placeholder="Find...")
        self.find_entry.set_hexpand(True)
        self.find_entry.connect("search-changed", self._on_find_changed)
        self.find_entry.connect("activate", self._on_find_next)

        # Add Escape key handler to close find bar
        find_key_controller = Gtk.EventControllerKey()
        find_key_controller.connect("key-pressed", self._on_find_entry_key)
        self.find_entry.add_controller(find_key_controller)

        find_row.append(self.find_entry)

        self.find_count_label = Gtk.Label(label="")
        self.find_count_label.add_css_class("dim-label")
        find_row.append(self.find_count_label)

        prev_btn = ZenButton(icon=Icons.ARROW_UP, tooltip="Previous (Shift+Enter)")
        prev_btn.connect("clicked", lambda b: self._on_find_prev())
        find_row.append(prev_btn)

        next_btn = ZenButton(icon=Icons.ARROW_DOWN, tooltip="Next (Enter)")
        next_btn.connect("clicked", lambda b: self._on_find_next())
        find_row.append(next_btn)

        # Toggle replace row button
        self._replace_toggle = ZenButton(icon=Icons.CHEVRON_DOWN, tooltip="Toggle Replace", toggle=True)
        self._replace_toggle.connect("toggled", self._on_replace_toggled)
        find_row.append(self._replace_toggle)

        container.append(find_row)

        # Replace row (hidden by default)
        self._replace_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._replace_row.set_visible(False)

        self.replace_entry = ZenEntry(placeholder="Replace...")
        self.replace_entry.set_hexpand(True)
        replace_key_controller = Gtk.EventControllerKey()
        replace_key_controller.connect("key-pressed", self._on_replace_entry_key)
        self.replace_entry.add_controller(replace_key_controller)
        self._replace_row.append(self.replace_entry)

        replace_btn = ZenButton(label="Replace")
        replace_btn.connect("clicked", lambda b: self._on_replace())
        self._replace_row.append(replace_btn)

        replace_all_btn = ZenButton(label="All")
        replace_all_btn.connect("clicked", lambda b: self._on_replace_all())
        self._replace_row.append(replace_all_btn)

        container.append(self._replace_row)

        self.find_bar.set_child(container)
        self.find_bar.connect_entry(self.find_entry)
        self.prepend(self.find_bar)

        # Apply editor font to labels that aren't covered by ZenSearchEntry/ZenEntry
        self._find_bar_font_widgets = [
            self.find_count_label,
            replace_btn,
            replace_all_btn,
        ]
        self._find_bar_css = Gtk.CssProvider()
        for w in self._find_bar_font_widgets:
            w.get_style_context().add_provider(self._find_bar_css, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
        self._apply_find_bar_font()
        subscribe_font_change(lambda comp, _s: self._apply_find_bar_font() if comp == "editor" else None)
        subscribe_theme_change(lambda _t: self._apply_find_bar_font())

    def _apply_find_bar_font(self):
        """Refresh editor font CSS on find-bar labels/buttons."""
        theme = get_theme()
        settings = get_font_settings("editor")
        css = f'label {{ font-family: "{settings["family"]}"; font-size: {settings["size"]}pt; color: {theme.fg_dim}; }}'
        self._find_bar_css.load_from_data(css.encode())

    def new_file(self):
        """Create a new empty file tab."""
        tab = EditorTab(is_new=True)
        tab_id = self._add_tab(tab, "Untitled")
        tab.view.grab_focus()
        # Trigger file-opened callback to expand collapsed editor
        if self.on_file_opened:
            self.on_file_opened(None)
        return tab_id

    def open_or_create_file(self, file_path: str) -> bool:
        """Open a file if it exists, or create a temporary unsaved tab with that name.

        The tab gets the intended file_path and syntax highlighting from the
        extension, but is marked ``is_new=True`` so it's not written to disk
        until the user explicitly saves (Cmd+S).
        """
        if os.path.isfile(file_path):
            return self.open_file(file_path)

        # Create a new tab pre-configured for this file path
        self._close_welcome_tab()
        tab = EditorTab(file_path=file_path, is_new=True)
        # Set language/indent from the file extension
        tab._set_language_from_file(file_path)
        title = os.path.basename(file_path)
        tab_id = self._add_tab(tab, title)
        tab.view.grab_focus()
        # Trigger file-opened callback to expand collapsed editor
        if self.on_file_opened:
            self.on_file_opened(file_path)
        return True

    def new_sketch_file(self):
        """Create a new untitled sketch pad tab."""
        self._close_welcome_tab()

        from .sketch_tab import SketchTab

        sketch_tab = SketchTab(None)
        sketch_tab.original_content = sketch_tab.widget.get_content()

        tab_id = self._next_tab_id
        self._next_tab_id += 1

        sketch_tab.widget._zen_tab_id = tab_id

        from shared.ui.tab_button import FileTabButton

        tab_btn = FileTabButton(tab_id, sketch_tab.get_title(), on_close=lambda tid: self._close_tab_by_id(tid))
        page_num = self.notebook.append_page(sketch_tab.widget, tab_btn)

        sketch_tab._tab_button = tab_btn
        sketch_tab._tab_id = tab_id
        self.tabs[tab_id] = sketch_tab

        self.notebook.set_current_page(page_num)

        if self.on_file_opened:
            self.on_file_opened(None)

    def _close_welcome_tab(self):
        """Close the Welcome tab if present."""
        for i in range(self.notebook.get_n_pages()):
            page = self.notebook.get_nth_page(i)
            if page.__class__.__name__ == "WelcomeScreen":
                if i < self.notebook.get_n_pages():
                    self.notebook.remove_page(i)
                return

    def toggle_dev_pad(self, dev_pad):
        """Toggle the Dev Pad as an editor tab."""
        # If already open, focus or close it
        for i in range(self.notebook.get_n_pages()):
            page = self.notebook.get_nth_page(i)
            if page.__class__.__name__ == "DevPad":
                if self.notebook.get_current_page() == i:
                    self.notebook.remove_page(i)
                    if self.notebook.get_n_pages() == 0 and self.on_tabs_empty:
                        self.on_tabs_empty()
                else:
                    self.notebook.set_current_page(i)
                return

        # Expand editor if it was collapsed
        window = self.get_root()
        if window and getattr(window, "_editor_collapsed", False):
            window._expand_editor()

        from shared.ui.tab_button import TabButton

        dev_pad.set_visible(True)
        dev_pad.show_panel()
        dev_pad.set_hexpand(True)
        dev_pad.set_vexpand(True)

        tab_btn = TabButton(-2, "Dev Pad", on_close=lambda tid: self._close_dev_pad_tab())
        page_num = self.notebook.append_page(dev_pad, tab_btn)
        self.notebook.set_current_page(page_num)

    def _close_dev_pad_tab(self):
        """Close the Dev Pad tab if present."""
        for i in range(self.notebook.get_n_pages()):
            page = self.notebook.get_nth_page(i)
            if page.__class__.__name__ == "DevPad":
                self.notebook.remove_page(i)
                if self.notebook.get_n_pages() == 0 and self.on_tabs_empty:
                    self.on_tabs_empty()
                return

    def _has_dev_pad_tab(self) -> bool:
        """Check if a DevPad tab is currently open."""
        for i in range(self.notebook.get_n_pages()):
            page = self.notebook.get_nth_page(i)
            if page.__class__.__name__ == "DevPad":
                return True
        return False

    def _is_dev_pad_active(self) -> bool:
        """Check if the DevPad tab is the currently active tab."""
        page_num = self.notebook.get_current_page()
        if page_num < 0:
            return False
        page = self.notebook.get_nth_page(page_num)
        return page.__class__.__name__ == "DevPad"

    def open_file(self, file_path: str, line_number: int = None, switch_to: bool = True) -> bool:
        """Open a file in a new tab or focus existing tab."""
        self._close_welcome_tab()
        # Check if file is already open (normalize for consistent matching)
        norm = os.path.normpath(file_path)
        for tab_id, tab in self.tabs.items():
            if tab.file_path and os.path.normpath(tab.file_path) == norm:
                # Convert tab_id to page_num for notebook navigation
                if switch_to:
                    page_num = self._get_page_num_for_tab_id(tab_id)
                    if page_num >= 0:
                        self.notebook.set_current_page(page_num)
                if line_number:
                    self._go_to_line(tab, line_number)
                # Notify callback even for existing tabs
                if self.on_file_opened:
                    self.on_file_opened(file_path)
                # Log activity to Dev Pad
                from dev_pad import log_file_activity

                log_file_activity(file_path, "open")
                return True

        # Route image files to image viewer
        ext = os.path.splitext(file_path)[1].lower()
        if ext in IMAGE_EXTENSIONS:
            return self.open_image(file_path, switch_to=switch_to)

        # Route .zen_sketch files to sketch tab
        if ext == SKETCH_EXTENSION:
            return self._open_sketch_file(file_path, switch_to=switch_to)

        # Create new tab
        tab = EditorTab(file_path=file_path)
        if tab.load_file(file_path):
            page_num = self._add_tab(tab, tab.get_title(), switch_to=switch_to)
            if line_number:
                # Wait for view to be mapped and laid out before scrolling
                def _scroll_when_ready(view, ln=line_number, t=tab):
                    GLib.idle_add(lambda: self._go_to_line(t, ln) or False)

                if tab.view.get_mapped():
                    GLib.idle_add(lambda: self._go_to_line(tab, line_number) or False)
                else:
                    tab.view.connect("map", lambda w: _scroll_when_ready(w))
            # Notify callback
            if self.on_file_opened:
                self.on_file_opened(file_path)
            # Log activity to Dev Pad
            from dev_pad import log_file_activity

            log_file_activity(file_path, "open")
            return True

        return False

    def on_external_file_change(self, file_path: str) -> None:
        """Handle external file modification detected by file watcher.

        If the file is open in a tab and hasn't been modified by the user,
        automatically reload it. If the user has unsaved changes, we skip
        auto-reload to avoid losing their work.

        Args:
            file_path: Absolute path to the file that changed externally
        """
        # Find the tab with this file
        norm = os.path.normpath(file_path)
        for tab_id, tab in self.tabs.items():
            if tab.file_path and os.path.normpath(tab.file_path) == norm:
                # Skip image tabs
                if getattr(tab, "_is_image", False):
                    return

                # Only auto-reload if the user hasn't made local changes
                # Skip if the file was saved internally within the last 2 seconds
                if not tab.modified:
                    if time.monotonic() - tab._last_internal_save_time < 2.0:
                        return
                    tab.reload_file()
                # If modified, we don't auto-reload to preserve user's changes
                return

    def _add_tab(self, tab: EditorTab, title: str, switch_to: bool = True) -> int:
        """Add a tab to the notebook. Returns tab_id (unique, stable)."""
        # Assign unique tab_id
        tab_id = self._next_tab_id
        self._next_tab_id += 1

        # Create scrolled window for the editor
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_kinetic_scrolling(True)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_child(tab.view)

        # Scroll-past-end: large bottom margin so content is always scrollable,
        # enabling kinetic/elastic scroll feel even for short files
        if get_setting("editor.scroll_past_end", True):

            def _update_scroll_past_end(*_args):
                h = scrolled.get_height()
                if h > 0:
                    tab.view.set_bottom_margin(max(h // 2, 200))

            vadj = scrolled.get_vadjustment()
            vadj.connect("notify::page-size", _update_scroll_past_end)

        # Horizontal box for editor (+ optional minimap)
        editor_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        editor_box.append(scrolled)

        # Create minimap (GtkSource.Map) on the right if enabled
        if get_setting("editor.show_minimap", True):
            # Hide the scrolled window's vertical scrollbar since the minimap provides scrolling
            scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.EXTERNAL)
            minimap = GtkSource.Map()
            minimap.set_view(tab.view)  # Link minimap to the source view
            minimap.set_size_request(MINIMAP_WIDTH, -1)
            editor_box.append(minimap)

            # Git diff & diagnostic indicator strip next to minimap
            from .editor_minimap import EditorMinimap

            indicator = EditorMinimap(tab.view, scrolled)
            if tab.file_path:
                indicator.set_file_path(tab.file_path)
            editor_box.append(indicator)
            tab._minimap_indicator = indicator

        # Check if this is a Markdown or OpenAPI file - add split view with preview
        is_markdown = False
        is_openapi = False
        md_preview = None
        openapi_preview = None
        if tab.file_path:
            ext = os.path.splitext(tab.file_path)[1].lower()
            if ext in MD_EXTENSIONS:
                is_markdown = True
            elif ext in OPENAPI_EXTENSIONS:
                # Content-based detection: check if this is an OpenAPI/Swagger spec
                try:
                    start_iter = tab.buffer.get_start_iter()
                    end_iter = tab.buffer.get_end_iter()
                    file_content = tab.buffer.get_text(start_iter, end_iter, True)
                    from .preview.openapi_preview import is_openapi_content

                    is_openapi = is_openapi_content(file_content)
                except ImportError:
                    pass  # yaml not available (e.g. in dist bundle)

        if is_markdown:
            # Create a horizontal paned container for markdown split view
            paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
            paned.set_vexpand(True)
            paned.set_hexpand(True)
            paned.set_shrink_start_child(False)
            paned.set_shrink_end_child(False)

            # Left side: editor
            paned.set_start_child(editor_box)

            # Right side: Markdown preview (lazy import — pulls in cmarkgfm/AppKit)
            from .preview.markdown_preview import MarkdownPreview

            md_preview = MarkdownPreview()
            md_preview.set_hexpand(True)
            paned.set_end_child(md_preview)

            # Set position to 50% once the paned has a real allocated width
            def _ensure_md_half():
                w = paned.get_allocated_width()
                if w > 10:
                    paned.set_position(w // 2)
                    return False
                return True

            GLib.timeout_add(100, _ensure_md_half)

            # Store preview reference on tab for live updates
            tab._md_preview = md_preview

            # Connect buffer changes to update preview
            tab.buffer.connect("changed", lambda b, t=tab: self._on_md_buffer_changed(t))

            # Scroll sync: when editor scrolls, sync preview by source line
            _syncing_from_preview = [False]
            _sync_guard_timer = [0]  # resettable guard timer ID

            def _sync_md_scroll(adj, preview=md_preview, view=tab.view):
                if _syncing_from_preview[0] or preview.is_syncing_scroll:
                    return
                visible = view.get_visible_rect()
                top_iter, _ = view.get_line_at_y(visible.y)
                preview.scroll_to_source_line(top_iter.get_line())

            scrolled.get_vadjustment().connect("value-changed", _sync_md_scroll)

            # Reverse scroll sync: when preview scrolls, sync editor proportionally
            def _sync_editor_from_preview(fraction, _scrolled=scrolled):
                _syncing_from_preview[0] = True
                vadj = _scrolled.get_vadjustment()
                upper = vadj.get_upper()
                page = vadj.get_page_size()
                if upper > page:
                    vadj.set_value(fraction * (upper - page))
                # Resettable guard: stays active until 200ms after LAST event
                if _sync_guard_timer[0]:
                    GLib.source_remove(_sync_guard_timer[0])
                _sync_guard_timer[0] = GLib.timeout_add(
                    200, lambda: (_syncing_from_preview.__setitem__(0, False), _sync_guard_timer.__setitem__(0, 0)) or False
                )

            md_preview.set_on_preview_scroll(_sync_editor_from_preview)

            # Store tab_id on paned container
            paned._zen_tab_id = tab_id
            page_container = paned
        elif is_openapi:
            # Create a horizontal paned container for OpenAPI split view
            paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
            paned.set_vexpand(True)
            paned.set_hexpand(True)
            paned.set_shrink_start_child(False)
            paned.set_shrink_end_child(False)

            # Left side: editor
            paned.set_start_child(editor_box)

            # Right side: OpenAPI preview (lazy import)
            from .preview.openapi_preview import OpenAPIPreview

            openapi_preview = OpenAPIPreview()
            openapi_preview.set_hexpand(True)
            paned.set_end_child(openapi_preview)

            # Set position to 50% once the paned has a real allocated width
            def _ensure_openapi_half():
                w = paned.get_allocated_width()
                if w > 10:
                    paned.set_position(w // 2)
                    return False
                return True

            GLib.timeout_add(100, _ensure_openapi_half)

            # Store preview reference on tab for live updates
            tab._openapi_preview = openapi_preview

            # Connect buffer changes to update preview
            tab.buffer.connect("changed", lambda b, t=tab: self._on_openapi_buffer_changed(t))

            # Scroll sync: when editor scrolls, sync preview by source line
            _syncing_from_preview = [False]
            _sync_guard_timer = [0]

            def _sync_openapi_scroll(adj, preview=openapi_preview, view=tab.view):
                if _syncing_from_preview[0] or preview.is_syncing_scroll:
                    return
                visible = view.get_visible_rect()
                top_iter, _ = view.get_line_at_y(visible.y)
                preview.scroll_to_source_line(top_iter.get_line())

            scrolled.get_vadjustment().connect("value-changed", _sync_openapi_scroll)

            # Reverse scroll sync: when preview scrolls, sync editor proportionally
            def _sync_editor_from_preview(fraction, _scrolled=scrolled):
                _syncing_from_preview[0] = True
                vadj = _scrolled.get_vadjustment()
                upper = vadj.get_upper()
                page = vadj.get_page_size()
                if upper > page:
                    vadj.set_value(fraction * (upper - page))
                if _sync_guard_timer[0]:
                    GLib.source_remove(_sync_guard_timer[0])
                _sync_guard_timer[0] = GLib.timeout_add(
                    200, lambda: (_syncing_from_preview.__setitem__(0, False), _sync_guard_timer.__setitem__(0, 0)) or False
                )

            openapi_preview.set_on_preview_scroll(_sync_editor_from_preview)

            # Store tab_id on paned container
            paned._zen_tab_id = tab_id
            page_container = paned
        else:
            # Store tab_id on the container widget so we can look it up later
            editor_box._zen_tab_id = tab_id
            page_container = editor_box

        # Create tab label using FileTabButton
        from shared.ui.tab_button import FileTabButton

        file_tab_btn = FileTabButton(tab_id, title, on_close=lambda tid: self._close_tab_by_id(tid))
        page_num = self.notebook.append_page(page_container, file_tab_btn)
        self.tabs[tab_id] = tab

        # Initial Markdown preview render
        if is_markdown and md_preview:
            start = tab.buffer.get_start_iter()
            end = tab.buffer.get_end_iter()
            content = tab.buffer.get_text(start, end, True)
            md_preview.update_from_editor(content, tab.file_path)
        # Initial OpenAPI preview render
        if is_openapi and openapi_preview:
            start = tab.buffer.get_start_iter()
            end = tab.buffer.get_end_iter()
            content = tab.buffer.get_text(start, end, True)
            openapi_preview.update_from_editor(content, tab.file_path)

        # Store label, close button and indicator references for updating
        # Store tab button reference for updating title/modified state
        tab._tab_button = file_tab_btn
        tab._tab_id = tab_id

        # Connect buffer modification signal - use tab_id
        handler_id = tab.buffer.connect("changed", lambda b, tid=tab_id: self._on_buffer_changed_by_id(tid))
        self._modification_handler_ids[tab_id] = handler_id

        # Connect cursor position signal for status bar updates
        tab.buffer.connect("notify::cursor-position", lambda b, p, tid=tab_id: self._on_cursor_moved(tid))

        # Wire diagnostics callback for status bar
        tab.on_diagnostics_changed = self._on_diagnostics_updated

        # Wire gutter diagnostic click callback
        tab._gutter_diagnostic_click_callback = self._on_gutter_diagnostic_clicked

        # Connect Cmd+Click navigation callback
        tab.set_cmd_click_callback(self._on_cmd_click)

        # Switch to the new tab
        if switch_to:
            self.notebook.set_current_page(page_num)

        return tab_id

    def _get_page_num_for_tab_id(self, tab_id: int) -> int:
        """Get the current notebook page number for a tab_id. Returns -1 if not found."""
        for i in range(self.notebook.get_n_pages()):
            page_widget = self.notebook.get_nth_page(i)
            if hasattr(page_widget, "_zen_tab_id") and page_widget._zen_tab_id == tab_id:
                return i
        return -1

    def _get_tab_id_for_page_num(self, page_num: int) -> int:
        """Get the tab_id for a notebook page number. Returns -1 if not found."""
        if page_num < 0:
            return -1
        page_widget = self.notebook.get_nth_page(page_num)
        if page_widget and hasattr(page_widget, "_zen_tab_id"):
            return page_widget._zen_tab_id
        return -1

    def _close_tab_by_id(self, tab_id: int):
        """Close a tab by its unique tab_id."""
        if tab_id not in self.tabs:
            return

        tab = self.tabs[tab_id]

        if tab.modified:
            self._confirm_close_tab_by_id(tab_id)
            return

        self._do_close_tab_by_id(tab_id)

    def _confirm_close_tab_by_id(self, tab_id: int):
        """Ask user about unsaved changes before closing using nvim-style popup."""
        from popups.save_confirm_popup import show_save_confirm

        tab = self.tabs[tab_id]
        name = os.path.basename(tab.file_path) if tab.file_path else "Untitled"

        def on_save():
            if tab_id not in self.tabs:
                return
            tab = self.tabs[tab_id]
            if tab.is_new and not tab.file_path:
                self._show_save_dialog_by_id(tab_id)
            else:
                if tab.is_new and tab.file_path:
                    parent_dir = os.path.dirname(tab.file_path)
                    if parent_dir:
                        os.makedirs(parent_dir, exist_ok=True)
                tab.save_file()
                self._do_close_tab_by_id(tab_id)

        def on_discard():
            self._do_close_tab_by_id(tab_id)

        show_save_confirm(
            self.get_root(),
            filename=name,
            on_save=on_save,
            on_discard=on_discard,
            on_cancel=None,  # Cancel just closes the popup
        )

    def _do_close_tab_by_id(self, tab_id: int):
        """Actually remove a tab by tab_id."""
        if tab_id not in self.tabs:
            return

        # Find the page number for this tab
        page_num = self._get_page_num_for_tab_id(tab_id)
        if page_num < 0 or page_num >= self.notebook.get_n_pages():
            # Page already removed from notebook - just clean up tracking
            if tab_id in self._modification_handler_ids:
                del self._modification_handler_ids[tab_id]
            del self.tabs[tab_id]
            return

        # Save current page so closing a background tab doesn't flash it
        current_page = self.notebook.get_current_page()

        # Check if we should restore a previous tab after closing.
        # When clicking X on a non-active tab, GTK auto-switches to it before
        # the close handler fires, making it appear as the "current" page.
        # Detect this by checking if _previous_active_tab_id is a different,
        # still-valid tab — if so, restore it after removal.
        restore_tab_id = -1
        if page_num == current_page:
            prev_id = self._previous_active_tab_id
            if prev_id >= 0 and prev_id != tab_id and prev_id in self.tabs:
                restore_tab_id = prev_id

        # Remove notebook page
        self.notebook.remove_page(page_num)

        # Restore correct tab
        if restore_tab_id >= 0 and self.notebook.get_n_pages() > 0:
            restore_page = self._get_page_num_for_tab_id(restore_tab_id)
            if restore_page >= 0:
                self.notebook.set_current_page(restore_page)
        elif page_num != current_page and self.notebook.get_n_pages() > 0:
            new_current = current_page if page_num > current_page else current_page - 1
            self.notebook.set_current_page(max(0, new_current))

        # Clean up
        if tab_id in self._modification_handler_ids:
            del self._modification_handler_ids[tab_id]
        del self.tabs[tab_id]

        # Notify that a tab was closed (persist open files)
        if self.on_tab_closed:
            self.on_tab_closed()

        # Notify if all tabs are now closed
        if self.notebook.get_n_pages() == 0 and self.on_tabs_empty:
            self.on_tabs_empty()

        # No renumbering needed! tab_ids are stable.

    def _on_buffer_changed_by_id(self, tab_id: int):
        """Handle buffer content change by tab_id."""
        if tab_id not in self.tabs:
            return
        tab = self.tabs[tab_id]

        # Compare current content with original to determine modified state
        start = tab.buffer.get_start_iter()
        end = tab.buffer.get_end_iter()
        current_content = tab.buffer.get_text(start, end, True)

        was_modified = tab.modified
        tab.modified = current_content != tab.original_content

        # Only update title if modified state changed
        if tab.modified != was_modified:
            self._update_tab_title_by_id(tab_id)

    def _on_md_buffer_changed(self, tab: EditorTab):
        """Handle Markdown buffer change - update preview with debouncing."""
        if not hasattr(tab, "_md_preview") or not tab._md_preview:
            return

        # Cancel any pending update
        if hasattr(tab, "_md_update_timeout") and tab._md_update_timeout:
            GLib.source_remove(tab._md_update_timeout)

        # Debounce: update preview after 300ms of no typing
        def do_update():
            if hasattr(tab, "_md_preview") and tab._md_preview:
                start = tab.buffer.get_start_iter()
                end = tab.buffer.get_end_iter()
                content = tab.buffer.get_text(start, end, True)
                tab._md_preview.update_from_editor(content, tab.file_path)
            tab._md_update_timeout = None
            return False

        tab._md_update_timeout = GLib.timeout_add(300, do_update)

    def _on_openapi_buffer_changed(self, tab: EditorTab):
        """Handle OpenAPI buffer change - update preview with debouncing."""
        if not hasattr(tab, "_openapi_preview") or not tab._openapi_preview:
            return

        # Cancel any pending update
        if hasattr(tab, "_openapi_update_timeout") and tab._openapi_update_timeout:
            GLib.source_remove(tab._openapi_update_timeout)

        # Debounce: update preview after 500ms of no typing (longer than markdown since parsing is heavier)
        def do_update():
            if hasattr(tab, "_openapi_preview") and tab._openapi_preview:
                start = tab.buffer.get_start_iter()
                end = tab.buffer.get_end_iter()
                content = tab.buffer.get_text(start, end, True)
                tab._openapi_preview.update_from_editor(content, tab.file_path)
            tab._openapi_update_timeout = None
            return False

        tab._openapi_update_timeout = GLib.timeout_add(500, do_update)

    def _on_cursor_moved(self, tab_id: int):
        """Handle cursor movement - notify callback for status bar."""
        # Only notify if this is the current tab
        current_tab_id = self._get_tab_id_for_page_num(self.notebook.get_current_page())
        if tab_id != current_tab_id:
            return

        if self.on_cursor_position_changed and tab_id in self.tabs:
            tab = self.tabs[tab_id]
            insert = tab.buffer.get_insert()
            iter_at_cursor = tab.buffer.get_iter_at_mark(insert)
            line = iter_at_cursor.get_line() + 1
            col = iter_at_cursor.get_line_offset() + 1
            total_lines = tab.buffer.get_line_count()
            self.on_cursor_position_changed(line, col, total_lines)

    def _on_diagnostics_updated(self, file_path: str, errors: int, warnings: int):
        """Handle diagnostics update - notify callback for status bar."""
        # Only notify if this is the current tab's file
        tab = self._get_current_tab()
        if tab and tab.file_path == file_path and self.on_diagnostics_changed:
            self.on_diagnostics_changed(errors, warnings)

    def _on_gutter_diagnostic_clicked(self, file_path: str):
        """Handle click on gutter diagnostic dot — open diagnostics popup."""
        if self.on_gutter_diagnostic_clicked:
            self.on_gutter_diagnostic_clicked()

    def get_current_tab(self) -> EditorTab | None:
        """Get the current tab, or None if no tabs are open."""
        return self._get_current_tab()

    def get_tab_by_path(self, file_path: str) -> EditorTab | None:
        """Get tab for a given file path, or None if not open."""
        norm = os.path.normpath(file_path)
        for tab in self.tabs.values():
            if tab.file_path and os.path.normpath(tab.file_path) == norm:
                return tab
        return None

    def close_current_tab(self):
        """Close the current tab."""
        page_num = self.notebook.get_current_page()
        if page_num >= 0:
            tab_id = self._get_tab_id_for_page_num(page_num)
            if tab_id >= 0:
                self._close_tab_by_id(tab_id)
            elif page_num < self.notebook.get_n_pages():
                # Page not tracked (e.g., welcome screen) - close directly
                self.notebook.remove_page(page_num)
                # Check if all tabs are now empty (trigger collapse)
                if self.notebook.get_n_pages() == 0 and self.on_tabs_empty:
                    self.on_tabs_empty()

    def save_current(self) -> bool:
        """Save the current file."""
        page_num = self.notebook.get_current_page()
        tab_id = self._get_tab_id_for_page_num(page_num)
        if tab_id < 0 or tab_id not in self.tabs:
            return False

        tab = self.tabs[tab_id]

        # Image tabs are read-only previews — never overwrite binary content
        if getattr(tab, "_is_image", False):
            return False

        if tab.is_new and not tab.file_path:
            self._show_save_dialog_by_id(tab_id)
            return False

        if tab.is_new and tab.file_path:
            # New file with a pre-set path (e.g. from `zen newfile.py`) —
            # create parent directories and save directly without a dialog.
            parent_dir = os.path.dirname(tab.file_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

        if tab.save_file():
            self._update_tab_title_by_id(tab_id)
            # Refresh minimap indicator after save (HEAD content may change)
            if hasattr(tab, "_minimap_indicator") and tab._minimap_indicator:
                tab._minimap_indicator.refresh_head()
            return True

        return False

    def _show_save_dialog_by_id(self, tab_id: int):
        """Show a save file dialog for untitled files."""
        dialog = Gtk.FileDialog()
        dialog.set_title("Save File")

        dialog.save(self.get_root(), None, lambda d, r, tid=tab_id: self._on_save_response_by_id(d, r, tid))

    def _on_save_response_by_id(self, dialog, result, tab_id: int):
        """Handle save dialog response."""
        try:
            file = dialog.save_finish(result)
            if file and tab_id in self.tabs:
                path = file.get_path()
                tab = self.tabs[tab_id]
                # Auto-append .zen_sketch for sketch pad files
                if getattr(tab, "_is_sketch", False) and not path.endswith(SKETCH_EXTENSION):
                    path += SKETCH_EXTENSION
                if tab.save_file(path):
                    if hasattr(tab, "_set_language_from_file"):
                        tab._set_language_from_file(path)
                    self._update_tab_title_by_id(tab_id)
                    # Refresh minimap indicator for new file path
                    if hasattr(tab, "_minimap_indicator") and tab._minimap_indicator:
                        tab._minimap_indicator.set_file_path(path)
                    # Log dev pad activity for newly saved files
                    if getattr(tab, "_is_sketch", False):
                        from dev_pad import log_sketch_activity

                        content = tab.widget.get_content() if hasattr(tab.widget, "get_content") else ""
                        log_sketch_activity(content=content, file_path=path)
                    else:
                        from dev_pad import log_file_activity

                        log_file_activity(path, "open")
        except GLib.Error:
            pass  # Cancelled

    def _update_tab_title_by_id(self, tab_id: int):
        """Update the tab title and modified indicator."""
        if tab_id not in self.tabs:
            return

        tab = self.tabs[tab_id]
        if hasattr(tab, "_tab_button"):
            tab._tab_button.set_title(tab.get_title())
            tab._tab_button.set_modified(tab.modified)
        elif hasattr(tab, "_tab_label"):
            tab._tab_label.set_label(tab.get_title())

    def _on_tab_changed(self, notebook, page, page_num):
        """Handle tab change - notify callback with file path."""
        new_tab_id = self._get_tab_id_for_page_num(page_num)
        if self._active_tab_id >= 0 and self._active_tab_id != new_tab_id:
            self._previous_active_tab_id = self._active_tab_id
        self._active_tab_id = new_tab_id

        self._sync_tab_selection(page_num)
        tab_id = new_tab_id
        if tab_id >= 0 and tab_id in self.tabs:
            tab = self.tabs[tab_id]
            if tab.file_path and self.on_tab_switched:
                self.on_tab_switched(tab.file_path)

    def _sync_tab_selection(self, active_page_num):
        """Update TabButton selection state for all notebook tabs."""
        from shared.ui.tab_button import TabButton

        for i in range(self.notebook.get_n_pages()):
            child = self.notebook.get_nth_page(i)
            tab_label = self.notebook.get_tab_label(child)
            if isinstance(tab_label, TabButton):
                tab_label.set_selected(i == active_page_num)

    def _go_to_line(self, tab: EditorTab, line_number: int):
        """Go to a specific line in the editor."""
        line_iter = _iter_at_line(tab.buffer, line_number - 1)
        tab.buffer.place_cursor(line_iter)
        tab.view.scroll_to_iter(line_iter, 0.2, False, 0.0, 0.5)

    def go_to_line_smooth(self, line_number: int, duration_ms: int = 300):
        """Scroll the current tab to a line with smooth animation."""
        tab = self._get_current_tab()
        if not tab:
            return
        target_iter = _iter_at_line(tab.buffer, line_number - 1)
        tab.buffer.place_cursor(target_iter)
        vadj = tab.view.get_vadjustment()
        if not vadj:
            self._go_to_line(tab, line_number)
            return
        start_val = vadj.get_value()
        # Compute target scroll position from iter Y coordinate
        iter_loc = tab.view.get_iter_location(target_iter)
        page_size = vadj.get_page_size()
        # Center the target line in viewport
        end_val = iter_loc.y - page_size / 2 + iter_loc.height / 2
        end_val = max(0, min(end_val, vadj.get_upper() - page_size))
        if abs(end_val - start_val) < 1:
            return
        self._animate_editor_scroll(vadj, start_val, end_val, duration_ms)

    def _animate_editor_scroll(self, vadj, start_val: float, end_val: float, duration_ms: int):
        """Animate scroll from start_val to end_val."""
        import time

        start_time = time.monotonic()

        def step():
            elapsed = (time.monotonic() - start_time) * 1000
            t = min(elapsed / duration_ms, 1.0)
            # Ease-out cubic
            t = 1 - (1 - t) ** 3
            vadj.set_value(start_val + (end_val - start_val) * t)
            if t < 1.0:
                return True
            vadj.set_value(end_val)
            return False

        GLib.timeout_add(16, step)
        return False

    def _get_current_tab(self) -> EditorTab | None:
        """Get the current tab, or None if no tabs are open."""
        page_num = self.notebook.get_current_page()
        tab_id = self._get_tab_id_for_page_num(page_num)
        if tab_id >= 0 and tab_id in self.tabs:
            return self.tabs[tab_id]
        return None

    def undo(self):
        """Undo in the current editor."""
        tab = self._get_current_tab()
        if not tab:
            return
        if getattr(tab, "_is_sketch", False):
            tab.undo()
            return
        # Dismiss visible ghost text before undoing
        ic = getattr(tab, "_inline_completion", None)
        if ic is not None and ic.is_active:
            ic.dismiss()
        if tab.buffer.get_can_undo():
            tab.buffer.undo()

    def redo(self):
        """Redo in the current editor."""
        tab = self._get_current_tab()
        if not tab:
            return
        if getattr(tab, "_is_sketch", False):
            tab.redo()
        elif tab.buffer.get_can_redo():
            tab.buffer.redo()

    def show_find_bar(self, replace: bool = False):
        """Show the find bar."""
        if not self._find_bar_created:
            self._create_find_bar()
            self._find_bar_created = True
        self.find_bar.set_search_mode(True)
        self.find_entry.grab_focus()
        # Select all text so re-pressing Cmd+F highlights existing query
        pos = len(self.find_entry.get_text())
        if pos > 0:
            self.find_entry.select_region(0, pos)
        if replace:
            self._replace_toggle.set_active(True)

    def _on_replace_toggled(self, button):
        """Toggle replace row visibility."""
        self._replace_row.set_visible(button.get_active())

    def _on_find_entry_key(self, controller, keyval, keycode, state):
        """Handle key press in find entry - Escape closes the find bar."""
        from gi.repository import Gdk

        if keyval == Gdk.KEY_Escape:
            self.find_bar.set_search_mode(False)
            # Return focus to editor
            tab = self._get_current_tab()
            if tab:
                tab.view.grab_focus()
            return True

        # Cmd+Backspace: clear the entire search entry
        meta = Gdk.ModifierType.META_MASK
        if keyval == Gdk.KEY_BackSpace and (state & meta):
            self.find_entry.set_text("")
            return True

        return False

    def _on_replace_entry_key(self, controller, keyval, keycode, state):
        """Handle key press in replace entry - Cmd+Backspace clears text."""
        from gi.repository import Gdk

        meta = Gdk.ModifierType.META_MASK
        if keyval == Gdk.KEY_BackSpace and (state & meta):
            self.replace_entry.set_text("")
            return True
        return False

    def _on_find_changed(self, entry):
        """Handle find text change."""
        text = entry.get_text()
        self._ensure_search_context(text)
        if text:
            self._find_text(text, forward=True)
        else:
            self.find_count_label.set_label("")

    def _on_find_next(self, *args):
        """Find next occurrence."""
        text = self.find_entry.get_text()
        if text:
            self._find_text(text, forward=True)

    def _on_find_prev(self, *args):
        """Find previous occurrence."""
        text = self.find_entry.get_text()
        if text:
            self._find_text(text, forward=False)

    def _ensure_search_context(self, text: str):
        """Create or update the search context for the current buffer."""
        tab = self._get_current_tab()
        if not tab:
            self._search_context = None
            return

        if self._search_settings is None:
            self._search_settings = GtkSource.SearchSettings()
            self._search_settings.set_case_sensitive(False)
            self._search_settings.set_wrap_around(True)

        self._search_settings.set_search_text(text if text else None)

        # Recreate context if buffer changed
        if self._search_context is None or self._search_context.get_buffer() != tab.buffer:
            self._search_context = GtkSource.SearchContext(buffer=tab.buffer, settings=self._search_settings)

    def _update_find_count(self):
        """Update the match count label."""
        if not self._search_context:
            self.find_count_label.set_label("")
            return

        count = self._search_context.get_occurrences_count()
        if count < 0:
            # Still computing
            self.find_count_label.set_label("...")
        elif count == 0:
            self.find_count_label.set_label("No results")
        else:
            # Find current match position
            tab = self._get_current_tab()
            if tab and tab.buffer.get_has_selection():
                sel_start, sel_end = tab.buffer.get_selection_bounds()
                pos = self._search_context.get_occurrence_position(sel_start, sel_end)
                if pos > 0:
                    self.find_count_label.set_label(f"{pos} of {count}")
                    return
            self.find_count_label.set_label(f"{count} results")

    def _find_text(self, text: str, forward: bool = True):
        """Find text in the current editor."""
        tab = self._get_current_tab()
        if not tab:
            return

        buffer = tab.buffer

        self._ensure_search_context(text)
        if not self._search_context:
            return

        # Get current cursor position
        cursor = buffer.get_insert()
        cursor_iter = buffer.get_iter_at_mark(cursor)

        if forward:
            # Start search from selection end to avoid finding same match
            if buffer.get_has_selection():
                _, cursor_iter = buffer.get_selection_bounds()
            found, start, end, wrapped = self._search_context.forward(cursor_iter)
        else:
            # Start search from selection start
            if buffer.get_has_selection():
                cursor_iter, _ = buffer.get_selection_bounds()
            found, start, end, wrapped = self._search_context.backward(cursor_iter)

        if found:
            buffer.select_range(start, end)
            tab.view.scroll_to_iter(start, 0.2, False, 0.0, 0.5)

        # Update count after a small delay to let GtkSource compute occurrences
        GLib.timeout_add(50, lambda: self._update_find_count() or False)

    def _on_replace(self):
        """Replace current match."""
        if not self._search_context:
            return

        tab = self._get_current_tab()
        if not tab:
            return

        buffer = tab.buffer
        replace_text = self.replace_entry.get_text()

        if buffer.get_has_selection():
            start, end = buffer.get_selection_bounds()
            try:
                self._search_context.replace(start, end, replace_text, -1)
            except GLib.Error:
                pass
            # Find next
            self._on_find_next()

    def _on_replace_all(self):
        """Replace all matches."""
        if not self._search_context:
            return

        replace_text = self.replace_entry.get_text()
        try:
            count = self._search_context.replace_all(replace_text, -1)
            self.find_count_label.set_label(f"Replaced {count}")
        except GLib.Error:
            pass

    def get_current_content(self) -> str:
        """Get content of the current editor."""
        tab = self._get_current_tab()
        if not tab:
            return ""
        if getattr(tab, "_is_sketch", False):
            return tab.widget.get_content()

        start = tab.buffer.get_start_iter()
        end = tab.buffer.get_end_iter()
        return tab.buffer.get_text(start, end, True)

    def get_current_file_path(self) -> str:
        """Get file path of the current editor."""
        tab = self._get_current_tab()
        if not tab:
            return ""
        return tab.file_path or ""

    def toggle_comment(self):
        """Toggle comment on current line(s)."""
        tab = self._get_current_tab()
        if not tab:
            return

        buffer = tab.buffer

        # Get selection or current line
        if buffer.get_has_selection():
            start, end = buffer.get_selection_bounds()
        else:
            cursor = buffer.get_insert()
            start = buffer.get_iter_at_mark(cursor)
            end = start.copy()

        # Expand to full lines
        start.set_line_offset(0)
        if not end.ends_line():
            end.forward_to_line_end()

        # Get language for comment style
        lang = buffer.get_language()
        comment_start = "#"  # Default to Python
        if lang:
            lang_id = lang.get_id()
            if lang_id in ("c", "cpp", "java", "javascript", "typescript", "rust", "go", "swift", "kotlin"):
                comment_start = "//"

        # Process each line
        start_line = start.get_line()
        end_line = end.get_line()

        buffer.begin_user_action()
        for line_num in range(start_line, end_line + 1):
            line_iter = _iter_at_line(buffer, line_num)
            line_end = line_iter.copy()
            line_end.forward_to_line_end()
            line_text = buffer.get_text(line_iter, line_end, True)

            # Check if line is commented
            stripped = line_text.lstrip()
            if stripped.startswith(comment_start):
                # Uncomment
                indent = len(line_text) - len(stripped)
                comment_len = len(comment_start)
                if stripped.startswith(comment_start + " "):
                    comment_len += 1
                # Delete comment
                del_start = _iter_at_line_offset(buffer, line_num, indent)
                del_end = _iter_at_line_offset(buffer, line_num, indent + comment_len)
                buffer.delete(del_start, del_end)
            else:
                # Comment
                insert_iter = _iter_at_line(buffer, line_num)
                buffer.insert(insert_iter, comment_start + " ")

        buffer.end_user_action()

    def indent(self):
        """Indent current line(s)."""
        self._indent_lines(indent=True)

    def unindent(self):
        """Unindent current line(s)."""
        self._indent_lines(indent=False)

    def _indent_lines(self, indent: bool):
        """Indent or unindent selected lines."""
        tab = self._get_current_tab()
        if not tab:
            return

        buffer = tab.buffer

        # Get selection or current line
        if buffer.get_has_selection():
            start, end = buffer.get_selection_bounds()
        else:
            cursor = buffer.get_insert()
            start = buffer.get_iter_at_mark(cursor)
            end = start.copy()

        start_line = start.get_line()
        end_line = end.get_line()

        tab_width = tab.view.get_tab_width()
        indent_str = " " * tab_width

        buffer.begin_user_action()
        for line_num in range(start_line, end_line + 1):
            line_iter = _iter_at_line(buffer, line_num)

            if indent:
                # Add indent
                buffer.insert(line_iter, indent_str)
            else:
                # Remove indent
                line_end = line_iter.copy()
                line_end.forward_to_line_end()
                line_text = buffer.get_text(line_iter, line_end, True)

                spaces_to_remove = 0
                for c in line_text[:tab_width]:
                    if c == " ":
                        spaces_to_remove += 1
                    elif c == "\t":
                        spaces_to_remove = tab_width
                        break
                    else:
                        break

                if spaces_to_remove > 0:
                    del_end = _iter_at_line_offset(buffer, line_num, spaces_to_remove)
                    buffer.delete(line_iter, del_end)

        buffer.end_user_action()

    def show_go_to_line(self):
        """Show a Go-To-Line dialog."""
        tab = self._get_current_tab()
        if not tab:
            return

        total_lines = tab.buffer.get_line_count()

        def on_submit(text):
            try:
                line = int(text)
                if 1 <= line <= total_lines:
                    self._go_to_line(tab, line)
            except ValueError:
                pass

        def validate(text):
            if not text:
                return None
            try:
                line = int(text)
                if line < 1 or line > total_lines:
                    return f"Line must be between 1 and {total_lines}"
            except ValueError:
                return "Please enter a number"
            return None

        from popups.input_dialog import show_input

        show_input(
            parent=self.get_root(),
            title="Go to Line",
            message=f"Enter line number (1–{total_lines}):",
            placeholder="Line number",
            on_submit=on_submit,
            validate=validate,
        )

    def has_unsaved_changes(self) -> bool:
        """Check if any tab has unsaved changes."""
        return any(tab.modified for tab in self.tabs.values())

    def get_unsaved_tabs(self) -> list:
        """Return list of (tab_id, tab) for modified tabs."""
        return [(tid, t) for tid, t in self.tabs.items() if t.modified]

    def open_image(self, file_path: str, switch_to: bool = True) -> bool:
        """Open an image file in a preview tab."""
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in IMAGE_EXTENSIONS:
            return False

        # Check if already open
        for tab_id, tab in self.tabs.items():
            if tab.file_path == file_path:
                if switch_to:
                    page_num = self._get_page_num_for_tab_id(tab_id)
                    if page_num >= 0:
                        self.notebook.set_current_page(page_num)
                # Trigger file opened callback to expand editor if collapsed
                if self.on_file_opened:
                    self.on_file_opened(file_path)
                return True

        # Create image preview tab
        # Assign unique tab_id
        tab_id = self._next_tab_id
        self._next_tab_id += 1

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled._zen_tab_id = tab_id  # Store tab_id for lookup

        picture = Gtk.Picture()
        picture.set_filename(file_path)
        picture.set_can_shrink(True)
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        scrolled.set_child(picture)

        # Create tab label using TabButton
        from shared.ui.tab_button import TabButton

        img_tab_btn = TabButton(tab_id, os.path.basename(file_path), on_close=lambda tid: self._do_close_tab_by_id(tid))
        page_num = self.notebook.append_page(scrolled, img_tab_btn)

        # Use a lightweight tab object for image tabs
        img_tab = EditorTab(file_path=file_path)
        img_tab._is_image = True
        img_tab._tab_button = img_tab_btn
        img_tab._tab_id = tab_id
        self.tabs[tab_id] = img_tab

        if switch_to:
            self.notebook.set_current_page(page_num)

        # Trigger file opened callback to expand editor if collapsed
        if self.on_file_opened:
            self.on_file_opened(file_path)
        from dev_pad import log_file_activity

        log_file_activity(file_path, "open")
        return True

    def _open_sketch_file(self, file_path: str, switch_to: bool = True) -> bool:
        """Open a .zen_sketch file in a SketchPad tab."""
        self._close_welcome_tab()
        norm = os.path.normpath(file_path)

        # Check if already open
        for tab_id, tab in self.tabs.items():
            if tab.file_path and os.path.normpath(tab.file_path) == norm:
                if switch_to:
                    page_num = self._get_page_num_for_tab_id(tab_id)
                    if page_num >= 0:
                        self.notebook.set_current_page(page_num)
                if self.on_file_opened:
                    self.on_file_opened(file_path)
                return True

        from .sketch_tab import SketchTab

        sketch_tab = SketchTab(file_path)
        if not os.path.isfile(file_path):
            return False
        if not sketch_tab.load_file(file_path):
            return False

        tab_id = self._next_tab_id
        self._next_tab_id += 1

        sketch_tab.widget._zen_tab_id = tab_id

        from shared.ui.tab_button import FileTabButton

        tab_btn = FileTabButton(tab_id, sketch_tab.get_title(), on_close=lambda tid: self._close_tab_by_id(tid))
        page_num = self.notebook.append_page(sketch_tab.widget, tab_btn)

        sketch_tab._tab_button = tab_btn
        sketch_tab._tab_id = tab_id
        self.tabs[tab_id] = sketch_tab

        if switch_to:
            self.notebook.set_current_page(page_num)

        if self.on_file_opened:
            self.on_file_opened(file_path)

        from dev_pad import log_sketch_activity

        content = sketch_tab.widget.get_content() if hasattr(sketch_tab.widget, "get_content") else ""
        log_sketch_activity(content=content, file_path=file_path)
        return True

    def open_binary(self, file_path: str, switch_to: bool = True) -> bool:
        """Open a binary file in a hex dump viewer tab."""
        # Check if already open
        for tab_id, tab in self.tabs.items():
            if tab.file_path == file_path:
                if switch_to:
                    page_num = self._get_page_num_for_tab_id(tab_id)
                    if page_num >= 0:
                        self.notebook.set_current_page(page_num)
                return True

        self._close_welcome_tab()

        tab_id = self._next_tab_id
        self._next_tab_id += 1

        from .preview.binary_viewer import BinaryViewer

        viewer = BinaryViewer(file_path)
        viewer._zen_tab_id = tab_id

        # Create tab label using TabButton
        from shared.ui.tab_button import TabButton

        bin_tab_btn = TabButton(tab_id, os.path.basename(file_path), on_close=lambda tid: self._do_close_tab_by_id(tid))
        page_num = self.notebook.append_page(viewer, bin_tab_btn)

        # Lightweight tab object for binary tabs
        bin_tab = EditorTab(file_path=file_path)
        bin_tab._is_binary = True
        bin_tab._tab_button = bin_tab_btn
        bin_tab._tab_id = tab_id
        self.tabs[tab_id] = bin_tab

        if switch_to:
            self.notebook.set_current_page(page_num)

        # Notify callback and log activity
        if self.on_file_opened:
            self.on_file_opened(file_path)
        from dev_pad import log_file_activity

        log_file_activity(file_path, "open")
        return True

    def _on_panel_click(self, gesture, n_press, x, y):
        """Handle click on panel to gain focus."""
        self._handle_panel_click_focus()

    def _on_focus_in(self):
        """Called when this panel gains focus."""
        self._handle_panel_focus_in()

    def _on_focus_out(self):
        """Called when this panel loses focus."""
        self._handle_panel_focus_out()

    def _on_cmd_click(self, buffer, view, file_path, click_iter):
        """Handle Cmd+Click for code navigation."""
        if not self._code_navigation:
            self._init_code_navigation()

        if self._code_navigation:
            self._code_navigation.handle_cmd_click(buffer, view, file_path, click_iter)

    def _init_code_navigation(self):
        """Initialize the code navigation system."""
        from navigation.code_navigation import CodeNavigation

        self._code_navigation = CodeNavigation(
            open_file_callback=self._navigation_open_file,
            get_workspace_folders=self.get_workspace_folders,
            get_current_buffer_view=self._get_current_buffer_view,
        )

    def _navigation_open_file(self, file_path: str, line_number: int = None) -> bool:
        """Open a file from navigation (wrapper for open_file)."""
        return self.open_file(file_path, line_number=line_number)

    def _get_current_buffer_view(self):
        """Return (buffer, view) for the current tab, or None."""
        tab = self._get_current_tab()
        if tab:
            return (tab.buffer, tab.view)
        return None
