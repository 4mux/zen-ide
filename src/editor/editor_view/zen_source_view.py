"""ZenSourceView — GtkSourceView subclass with indent guides, block cursor, diagnostics."""

from gi.repository import Gtk, GtkSource

from shared.utils import tuple_to_gdk_rgba

from .core import _parse_hex_color
from .zen_source_view_cursor_mixin import ZenSourceViewCursorMixin
from .zen_source_view_gutters_mixin import ZenSourceViewGuttersMixin


class ZenSourceView(ZenSourceViewCursorMixin, ZenSourceViewGuttersMixin, GtkSource.View):
    """GtkSourceView with indent guide lines."""

    __gtype_name__ = "ZenSourceView"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._show_guides = True
        self._guide_rgba = (1.0, 1.0, 1.0, 0.08)
        self._guide_color = tuple_to_gdk_rgba(self._guide_rgba)
        self._buf_changed_id = None
        self._buf_cursor_id = None  # Track cursor-position signal for wide cursor
        self._gutter_diff_renderer = None  # Set by EditorTab
        self._breakpoint_renderer = None  # Set by EditorTab (BreakpointRenderer)
        self._color_preview_renderer = None  # Set by EditorTab
        self._fold_manager = None  # Set by EditorTab (FoldManager)
        self._fold_unsafe_lines = set()  # Lines where get_iter_location is unsafe (fold)
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
        self._init_cursor()

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
        # Build set of lines unsafe for get_iter_location (hidden inside folds).
        # Fold header lines are now safe — the invisible tag only covers
        # complete lines (start_line+1 … end_line), never the header itself.
        fm = getattr(self, "_fold_manager", None)
        fold_unsafe = set()
        if fm and fm._collapsed:
            for sl, el in fm._collapsed.items():
                for ln in range(sl + 1, el + 1):
                    fold_unsafe.add(ln)
        self._fold_unsafe_lines = fold_unsafe

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

        if self._breakpoint_renderer and self._breakpoint_renderer.has_content:
            self._breakpoint_renderer.draw(snapshot, vis_range, fold_unsafe)

        if self._color_preview_renderer and self._color_preview_renderer._color_positions:
            self._color_preview_renderer.draw(snapshot, vis_range, fold_unsafe)

        buf = self.get_buffer()
        tt = buf.get_tag_table()
        has_diags = tt.lookup("diag_error_underline") is not None or tt.lookup("diag_warning_underline") is not None
        if has_diags:
            self._draw_diagnostic_waves(snapshot)

        # Ghost text overlay (drawn before block cursor so cursor sits on top)
        if self._ghost_text_renderer:
            # Skip ghost text if cursor is on a fold-affected line
            cursor_line = buf.get_iter_at_mark(buf.get_insert()).get_line()
            if cursor_line not in fold_unsafe:
                self._ghost_text_renderer.draw(snapshot)

        # Block cursor (drawn last so it sits on top of everything)
        if self._wide_cursor and self._bc_focused and self._bc_visible:
            cursor_line = buf.get_iter_at_mark(buf.get_insert()).get_line()
            if cursor_line not in fold_unsafe:
                from shared.block_cursor_draw import draw_block_cursor

                draw_block_cursor(self, snapshot)
