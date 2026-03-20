"""ChatCanvas — Gtk.DrawingArea that renders ANSI-styled text with GtkSnapshot.

Follows the TreeCanvas pattern: DrawingArea inside ScrolledWindow with
pixel-smooth scrolling.  Features visual soft-wrapping so content never
overflows the viewport — long lines wrap to subsequent visual rows.
"""

from gi.repository import Gdk, GLib, Graphene, Gtk, Pango

from ai.ansi_buffer import AnsiBuffer
from shared.utils import display_width


class ChatCanvas(Gtk.DrawingArea):
    """DrawingArea that renders ANSI-styled terminal text using GtkSnapshot.

    Implements visual soft-wrapping: buffer lines whose text extends
    beyond the viewport width are rendered across multiple visual rows.
    The wrap map (buffer-line → visual-row-count) is recomputed whenever
    the buffer is dirty or the viewport width changes, so content is
    always responsive to resize.
    """

    __gtype_name__ = "ChatCanvas"

    # Padding around text content
    PAD_LEFT = 8
    PAD_TOP = 2

    def __init__(self):
        super().__init__()

        self._buffer = AnsiBuffer()
        self._scrolled_window = None
        self._vadjustment = None
        self._vadjustment_handler_id = None
        self._page_size_handler_id = None

        # Font
        from fonts import get_font_settings

        _settings = get_font_settings("ai_chat")
        self._font_desc = Pango.FontDescription.from_string(f"{_settings['family']} {_settings.get('size', 13)}")
        self._font_desc_bold = self._make_bold_desc(self._font_desc)
        self._font_desc_italic = self._make_italic_desc(self._font_desc)
        self._line_height = 0
        self._char_width = 0
        self._measured = False

        # Colors
        self._fg_hex = "#e0e0e0"
        self._bg_hex = "#1e1e1e"
        self._selection_bg_hex = "#264f78"

        # Colour cache: hex string → Gdk.RGBA (avoids re-parsing every frame)
        self._rgba_cache: dict[str, Gdk.RGBA] = {}
        # Dim colour cache: maps (fg_hex, bg_hex) → dimmed Gdk.RGBA
        self._dim_cache: dict[tuple[str, str], Gdk.RGBA] = {}

        # Cached RGBA objects
        self._fg_rgba = self._hex_to_rgba(self._fg_hex)
        self._bg_rgba = self._hex_to_rgba(self._bg_hex)
        self._selection_rgba = self._hex_to_rgba(self._selection_bg_hex)
        self._dim_alpha = 0.55

        # Selection state: (line, col) tuples
        self._sel_anchor = None  # where mouse press started
        self._sel_cursor = None  # current drag position
        self._has_selection = False
        self._multi_click_active = False  # True during double/triple-click

        # Track whether content changed since last draw
        self._needs_height_update = True

        # Batch redraw scheduling
        self._redraw_scheduled = False

        # Height suppression for batch operations (resize re-renders)
        self._suppress_height = False

        # Layout cache for dirty-line rendering optimisation.
        # Maps line index → (char_cells, rows) where:
        #   char_cells = list[(char, pixel_width, span_index)]
        #   rows = list[list[(char, pixel_width, span_index)]]
        # Invalidated per-line when dirty, cleared entirely on width/font/color change.
        self._layout_cache: dict[int, tuple[list, list]] = {}
        # The content_width_px the layout cache was computed for.
        self._layout_cache_width: float = 0.0

        # Soft-wrap mapping: buffer-line-index → number of visual rows.
        # Recomputed when dirty lines change or viewport width changes.
        self._wrap_map: list[int] = []
        # Cumulative visual row offsets: _wrap_offsets[i] = sum of visual
        # rows for lines 0..i-1.  _wrap_offsets[0] = 0.
        self._wrap_offsets: list[int] = []
        # Total visual row count (sum of all wrap_map entries).
        self._total_visual_rows: int = 0
        # The viewport width (in pixels) that the current wrap map was
        # computed for.  When the widget width changes, the map is rebuilt.
        self._wrap_map_width: float = 0.0
        # Track the buffer line count the wrap map was built for.
        self._wrap_map_line_count: int = 0

        # Window is-active tracking for background/foreground refresh
        self._window_active_handler_id = None

        # Block tracking for inspector: list of (start_line, block_type, meta)
        self._block_tags: list[tuple[int, str, dict]] = []

        # Resize scroll anchoring: during continuous resize, we bypass
        # vadjustment entirely to avoid GTK's layout-driven clamping.
        # A persistent scroll anchor stores which buffer line should be
        # at the top of the viewport.  do_snapshot computes scroll_y
        # directly from this anchor, and value-changed redraws are
        # suppressed.  The anchor is reconciled with vadjustment when
        # resizing stops (detected by width stabilising or the 300ms
        # debounced rerender).
        self._resize_scroll_anchor: dict | None = None  # {anchor_line, anchor_offset, at_bottom}
        self._resize_settle_id: int | None = None  # timeout source to reconcile after resize stops

        # Setup
        self.set_hexpand(True)
        self.set_vexpand(True)
        # Clip any content that extends beyond the widget allocation.
        # Prevents long unwrapped lines from visually overflowing the chat frame.
        self.set_overflow(Gtk.Overflow.HIDDEN)
        # Non-focusable: prevents GTK4 ScrolledWindow scroll-to-focus from
        # jumping to (0,0) when clicked.  Text selection works via GestureDrag
        # (no focus needed), copy shortcut is handled at the panel level.
        self.set_can_focus(False)
        self.set_focusable(False)
        self._setup_event_controllers()

        # Force height + redraw on map so content is correct after
        # background/foreground transitions (macOS surface invalidation).
        self.connect("map", self._on_map)
        self.connect("realize", self._on_realize)

    # ------------------------------------------------------------------ #
    #  Public API (ChatCanvas subset used by AIChatTerminalView)       #
    # ------------------------------------------------------------------ #

    def feed(self, data):
        """Feed text or bytes to the buffer. Schedules a redraw."""
        if isinstance(data, bytes):
            self._buffer.feed_bytes(data)
        else:
            self._buffer.feed(data)
        self._needs_height_update = True
        self._eagerly_update_height()
        self._schedule_redraw()

    def feed_immediate(self, data):
        """Feed text/bytes and force synchronous redraw (bypass idle_add coalescing).

        Used for first-token display to minimize latency on the most
        perceptually important moment — the transition from spinner to content.
        """
        if isinstance(data, bytes):
            self._buffer.feed_bytes(data)
        else:
            self._buffer.feed(data)
        self._needs_height_update = True
        self._eagerly_update_height()
        # Synchronous redraw — skip idle_add
        self._redraw_scheduled = False
        self.queue_draw()

    def reset(self, clear_tabstops=True, clear_history=True):
        """Clear all content (ChatCanvas signature)."""
        self._buffer.clear()
        self._layout_cache.clear()
        self._block_tags.clear()
        self._clear_selection()
        self._wrap_map.clear()
        self._wrap_offsets.clear()
        self._total_visual_rows = 0
        self._wrap_map_width = 0.0
        self._wrap_map_line_count = 0
        self._resize_scroll_anchor = None
        if self._resize_settle_id is not None:
            GLib.source_remove(self._resize_settle_id)
            self._resize_settle_id = None
        self._needs_height_update = True
        self._eagerly_update_height()
        self._schedule_redraw()

    def get_column_count(self) -> int:
        """Calculate column count from pixel width ."""
        if not self._measured:
            self._measure_font()
        width = self._get_visible_width()
        if width <= 0 or self._char_width <= 0:
            return 80
        return max(20, int((width - self.PAD_LEFT * 2) / self._char_width))

    def get_text_format(self, fmt=None) -> str:
        """Get plain text content (ChatCanvas)."""
        return self._buffer.get_text()

    def get_has_selection(self) -> bool:
        return self._has_selection

    # -- Block tracking (inspector) ----------------------------------------

    def begin_block(self, block_type: str, **meta):
        """Mark the current buffer line as the start of a new content block.

        Used by AIChatTerminalView to tag user/thinking/assistant regions
        so the widget inspector can identify which content block the cursor
        is over.
        """
        start_line = self._buffer.get_line_count() - 1
        self._block_tags.append((start_line, block_type, meta))

    def get_block_at_line(self, line: int) -> tuple[str, int, int, dict] | None:
        """Return (block_type, start_line, end_line, meta) for the block at *line*.

        Returns ``None`` if no block has been registered.
        """
        if not self._block_tags:
            return None
        # Find the last tag whose start_line <= line
        best = None
        best_idx = -1
        for i, (start, btype, meta) in enumerate(self._block_tags):
            if start <= line:
                best = (start, btype, meta)
                best_idx = i
            else:
                break
        if best is None:
            return None
        start, btype, meta = best
        # End line is the start of the next block (exclusive), or buffer end
        if best_idx + 1 < len(self._block_tags):
            end = self._block_tags[best_idx + 1][0] - 1
        else:
            end = self._buffer.get_line_count() - 1
        return (btype, start, end, meta)

    def line_at_y(self, y: float) -> int:
        """Convert a Y pixel coordinate (widget-local) to a buffer line index."""
        if not self._measured:
            self._measure_font()
        if self._line_height <= 0:
            return 0
        abs_y = y - self.PAD_TOP
        visual_row = max(0, int(abs_y / self._line_height))
        # When wrap map isn't initialised, fall back to simple mapping
        if not self._wrap_offsets:
            return max(0, min(visual_row, self._buffer.get_line_count() - 1))
        return self._visual_row_to_line(visual_row)

    def get_block_content_preview(self, start_line: int, end_line: int, max_chars: int = 120) -> str:
        """Return a plain-text preview of buffer lines *start_line..end_line*."""
        parts = []
        total = 0
        for i in range(start_line, min(end_line + 1, self._buffer.get_line_count())):
            text = self._buffer.get_line_text(i).strip()
            if not text:
                continue
            if total + len(text) > max_chars:
                parts.append(text[: max_chars - total] + "…")
                break
            parts.append(text)
            total += len(text) + 1
        return " ".join(parts)

    def get_line_colors(self, line: int) -> tuple[str, str]:
        """Return (fg_hex, bg_hex) for the dominant styled span on *line*.

        'Dominant' = the span with the most text.  Falls back to the
        canvas default fg/bg if no styled spans exist.
        """
        spans = self._buffer.get_line(line)
        best_fg = self._fg_hex
        best_bg = self._bg_hex
        best_len = 0
        for span in spans:
            if len(span.text) > best_len:
                best_len = len(span.text)
                if span.fg:
                    best_fg = span.fg
                if span.bg:
                    best_bg = span.bg
        return best_fg, best_bg

    def begin_batch(self):
        """Suppress height updates until end_batch(). Prevents intermediate
        states (height dropping to 0 during reset) from being visible."""
        self._suppress_height = True

    def end_batch(self):
        """Release height suppression and do a single height+redraw pass."""
        self._suppress_height = False
        self._eagerly_update_height()
        self._schedule_redraw()

    def get_top_visible_line(self) -> int:
        """Return the buffer line index at the top of the visible viewport.

        Uses the current scroll offset and wrap map to determine which
        buffer line is at the top edge.  During active resize, uses the
        stored anchor line directly for stability.
        """
        if self._resize_scroll_anchor is not None:
            return self._resize_scroll_anchor["anchor_line"]
        if self._line_height <= 0:
            return 0
        scroll_y = self._get_scroll_y()
        visual_row = max(0, int((scroll_y - self.PAD_TOP) / self._line_height))
        if not self._wrap_offsets:
            return max(0, min(visual_row, self._buffer.get_line_count() - 1))
        return self._visual_row_to_line(visual_row)

    def get_scroll_anchor(self) -> tuple[int, float]:
        """Return ``(line_index, pixel_offset)`` for the top of the viewport.

        *line_index* is the buffer line at the top edge.
        *pixel_offset* is the number of pixels scrolled *past* the start
        of that line (accounts for multi-row wrapped lines).

        During active resize, returns the stored anchor directly for
        frame-to-frame stability.

        After a resize / re-render, call ``get_y_for_line(line_index)``
        to find where that line now lives and add back the pixel offset
        to restore the exact scroll position.
        """
        if self._resize_scroll_anchor is not None:
            return (
                self._resize_scroll_anchor["anchor_line"],
                self._resize_scroll_anchor["anchor_offset"],
            )
        if self._line_height <= 0:
            return (0, 0.0)
        scroll_y = self._get_scroll_y()
        line = self.get_top_visible_line()
        line_y = self._line_visual_y(line)
        offset = max(0.0, scroll_y - line_y)
        return (line, offset)

    def get_y_for_line(self, line_idx: int) -> float:
        """Return the Y pixel offset for buffer *line_idx* after the current wrap map.

        This is accurate after ``end_batch()`` has rebuilt the wrap map
        at the new width.  Used by resize scroll restoration to compute
        the exact scroll target for a given buffer line.
        """
        return self._line_visual_y(line_idx)

    def select_all(self):
        """Select all content."""
        line_count = self._buffer.get_line_count()
        if line_count == 0:
            return
        last_line = self._buffer.get_line_text(line_count - 1)
        self._sel_anchor = (0, 0)
        self._sel_cursor = (line_count - 1, len(last_line))
        self._has_selection = True
        self.queue_draw()

    def copy_clipboard_format(self, fmt=None):
        """Copy selected text to GTK clipboard (ChatCanvas)."""
        text = self.get_selected_text()
        if text:
            clipboard = Gdk.Display.get_default().get_clipboard()
            clipboard.set(text)
            from shared.utils import copy_to_system_clipboard

            copy_to_system_clipboard(text)

    def set_font(self, font_desc: Pango.FontDescription):
        """Set the font for rendering."""
        self._font_desc = font_desc
        self._font_desc_bold = self._make_bold_desc(font_desc)
        self._font_desc_italic = self._make_italic_desc(font_desc)
        self._measured = False
        self._invalidate_wrap_map()
        self._needs_height_update = True
        self._schedule_redraw()

    def set_colors(self, fg: Gdk.RGBA, bg: Gdk.RGBA, palette=None, selection_bg: Gdk.RGBA | None = None):
        """Set foreground/background colors (ChatCanvas signature)."""
        self._fg_hex = self._rgba_to_hex(fg)
        self._bg_hex = self._rgba_to_hex(bg)
        self._fg_rgba = fg
        self._bg_rgba = bg
        if selection_bg is not None:
            self._selection_bg_hex = self._rgba_to_hex(selection_bg)
            self._selection_rgba = selection_bg
        self._layout_cache.clear()
        self._dim_cache.clear()
        self._schedule_redraw()

    def set_editable(self, editable: bool):
        """No-op — DrawingArea is inherently read-only."""
        pass

    def set_monospace(self, monospace: bool):
        """No-op — we use monospace fonts by default."""
        pass

    def set_rewrap_on_resize(self, rewrap: bool):
        """No-op — we handle wrapping internally via soft-wrap map."""
        pass

    def set_scrollback_lines(self, lines: int):
        """No-op — buffer is unlimited."""
        pass

    def set_scroll_on_output(self, scroll: bool):
        """No-op — handled externally."""
        pass

    def set_scroll_on_keystroke(self, scroll: bool):
        """No-op — handled externally."""
        pass

    def set_allow_hyperlink(self, allow: bool):
        """No-op."""
        pass

    def set_audible_bell(self, bell: bool):
        """No-op."""
        pass

    def set_cursor_blink_mode(self, mode):
        """No-op — no cursor in chat output."""
        pass

    def set_color_cursor(self, color):
        """No-op."""
        pass

    def set_color_cursor_foreground(self, color):
        """No-op."""
        pass

    def attach_to_scrolled_window(self, scrolled_window):
        """Bind redraws to the parent ScrolledWindow's vertical adjustment."""
        if self._scrolled_window is scrolled_window:
            return
        self._scrolled_window = scrolled_window
        scrolled_window.connect("notify::vadjustment", self._on_vadjustment_changed)
        self._connect_vadjustment(scrolled_window.get_vadjustment())

    # ------------------------------------------------------------------ #
    #  Soft-wrap map                                                       #
    # ------------------------------------------------------------------ #

    def _invalidate_wrap_map(self):
        """Force a full rebuild of the wrap map on the next draw."""
        self._wrap_map.clear()
        self._wrap_offsets.clear()
        self._total_visual_rows = 0
        self._wrap_map_width = 0.0
        self._wrap_map_line_count = 0
        self._layout_cache.clear()
        self._layout_cache_width = 0.0

    def _visual_rows_for_line(self, line_idx: int, content_width_px: float) -> int:
        """Return the number of visual rows needed to display *line_idx*.

        Uses the exact same row-splitting logic as the layout cache in
        ``_draw_line`` to guarantee the wrap map is consistent with what
        is actually rendered.  A mismatch between the two would cause
        cumulative offset drift, making lines appear at wrong Y positions
        and causing some content to disappear from the viewport during
        resize.

        Fast-path: for pure-ASCII lines (common in code blocks), every
        character has display width 1, so we can compute rows with simple
        arithmetic instead of per-character iteration.
        """
        if content_width_px <= 0:
            return 1
        text = self._buffer.get_line_text(line_idx)
        if not text:
            return 1
        char_width = self._char_width
        # Fast path: if all characters are printable ASCII (0x20-0x7E),
        # each has display width 1, so total pixel width = len * char_width.
        # This avoids per-character display_width() calls for the ~90% of
        # lines that are pure ASCII (code, table content, regular text).
        try:
            encoded = text.encode("ascii")
            # All characters are ASCII.  Check they're all printable (0x20-0x7E).
            if all(0x20 <= b <= 0x7E for b in encoded):
                total_w = len(text) * char_width
                if total_w <= content_width_px + 0.5:
                    return 1
                # Integer ceil division for number of rows
                chars_per_row = max(1, int((content_width_px + 0.5) / char_width))
                return (len(text) + chars_per_row - 1) // chars_per_row
        except UnicodeEncodeError:
            pass
        # Slow path: non-ASCII content (box-drawing, CJK, emoji, etc.)
        rows = 1
        row_w = 0.0
        has_content = False
        for ch in text:
            ch_w = display_width(ch) * char_width
            if has_content and row_w + ch_w > content_width_px + 0.5:
                rows += 1
                row_w = ch_w
            else:
                row_w += ch_w
            has_content = True
        return rows

    def _rebuild_wrap_map(self, viewport_width: float):
        """(Re)build the wrap map for the current buffer at *viewport_width*.

        Called during do_snapshot when the width has changed or the buffer
        has grown.  Tries to be incremental: if only new lines were appended
        it extends the existing map rather than rebuilding from scratch.
        """
        if not self._measured:
            self._measure_font()

        content_width_px = max(viewport_width - self.PAD_LEFT * 2, self._char_width)
        line_count = self._buffer.get_line_count()

        width_changed = abs(viewport_width - self._wrap_map_width) > 0.5

        if width_changed or len(self._wrap_map) == 0:
            # Full rebuild
            self._wrap_map = [self._visual_rows_for_line(i, content_width_px) for i in range(line_count)]
            self._wrap_map_width = viewport_width
            self._wrap_map_line_count = line_count
        else:
            # Incremental: update dirty lines and append new lines
            dirty = self._buffer.dirty_lines
            for idx in dirty:
                if 0 <= idx < len(self._wrap_map):
                    self._wrap_map[idx] = self._visual_rows_for_line(idx, content_width_px)
            # Append entries for newly added lines
            for i in range(len(self._wrap_map), line_count):
                self._wrap_map.append(self._visual_rows_for_line(i, content_width_px))
            # Trim if buffer was shortened (shouldn't normally happen)
            if len(self._wrap_map) > line_count:
                self._wrap_map = self._wrap_map[:line_count]
            self._wrap_map_line_count = line_count

        # Rebuild cumulative offsets
        self._wrap_offsets = [0] * (line_count + 1)
        cumulative = 0
        for i in range(line_count):
            self._wrap_offsets[i] = cumulative
            cumulative += self._wrap_map[i]
        self._wrap_offsets[line_count] = cumulative if line_count > 0 else 0
        self._total_visual_rows = cumulative

    def _line_visual_y(self, line_idx: int) -> float:
        """Return the Y pixel offset for the start of *line_idx* (including wrap)."""
        if line_idx < len(self._wrap_offsets):
            return self._wrap_offsets[line_idx] * self._line_height + self.PAD_TOP
        # Fallback for out-of-range
        return self._total_visual_rows * self._line_height + self.PAD_TOP

    def _visual_row_to_line(self, visual_row: int) -> int:
        """Convert a visual row index to a buffer line index.

        Uses binary search on the cumulative wrap offsets.
        """
        if not self._wrap_offsets or visual_row < 0:
            return 0
        line_count = self._buffer.get_line_count()
        if line_count == 0:
            return 0
        # Binary search: find largest line_idx where _wrap_offsets[line_idx] <= visual_row
        lo, hi = 0, line_count - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if mid < len(self._wrap_offsets) and self._wrap_offsets[mid] <= visual_row:
                lo = mid
            else:
                hi = mid - 1
        return lo

    # ------------------------------------------------------------------ #
    #  Rendering (GtkSnapshot)                                             #
    # ------------------------------------------------------------------ #

    def do_snapshot(self, snapshot):
        """Render visible lines using GtkSnapshot + Pango.

        Uses dirty-line tracking: only lines marked dirty in the AnsiBuffer
        have their layout cache invalidated. Unchanged lines reuse cached
        Pango layout measurements, reducing per-frame work ~10x during streaming.

        Lines that exceed the viewport width are visually soft-wrapped
        across multiple rows.
        """
        width = self.get_width()
        height = self.get_height()
        if width <= 0 or height <= 0:
            return

        if not self._measured:
            self._measure_font()

        # Rebuild / update the soft-wrap map when needed
        line_count = self._buffer.get_line_count()
        width_changed = abs(width - self._wrap_map_width) > 0.5
        lines_changed = line_count != self._wrap_map_line_count
        has_dirty = bool(self._buffer.dirty_lines)

        # --- Resize scroll anchoring ---
        # On width change, capture which buffer line is at the top of the
        # viewport BEFORE rebuilding the wrap map.  This anchor persists
        # across all frames during continuous resize.
        #
        # We freeze set_size_request() during resize so that GTK never
        # re-layouts / clamps vadjustment.  We then shift all painted
        # content by a "paint offset" so the correct lines appear in the
        # viewport at the position determined by the (stable) vadjustment
        # value.  This eliminates ALL scroll jumping during resize —
        # for top, middle, and bottom scroll positions.
        if width_changed and self._wrap_map and not self._suppress_height:
            if self._resize_scroll_anchor is None:
                # First frame of a resize — capture the anchor
                anchor_candidate = self._capture_resize_anchor()
                if anchor_candidate is not None:
                    self._resize_scroll_anchor = anchor_candidate
            # Cancel any pending settle callback — resize is still active
            if self._resize_settle_id is not None:
                GLib.source_remove(self._resize_settle_id)
                self._resize_settle_id = None
            # Schedule a settle callback for when resize stops (150ms).
            if self._resize_scroll_anchor is not None:
                self._resize_settle_id = GLib.timeout_add(150, self._settle_resize_scroll)

        if width_changed or lines_changed or has_dirty or not self._wrap_map:
            self._rebuild_wrap_map(width)

        # Update content height if needed.
        # During active resize (anchor is set), do NOT call
        # _update_content_height() — that would change set_size_request(),
        # trigger GTK layout, and clamp vadjustment.  Height is deferred
        # until resize stops (_settle_resize_scroll).
        if self._resize_scroll_anchor is None:
            if self._needs_height_update or width_changed or lines_changed:
                self._update_content_height()
                self._needs_height_update = False

        # Evict dirty lines from the layout cache
        dirty = self._buffer.dirty_lines
        if dirty:
            for line_idx in dirty:
                self._layout_cache.pop(line_idx, None)
            dirty.clear()

        # Clip all rendering to the widget bounds so content never
        # overflows the chat frame (e.g. long unwrapped lines).
        clip_rect = Graphene.Rect()
        clip_rect.init(0, 0, width, height)
        snapshot.push_clip(clip_rect)

        # Background
        rect = Graphene.Rect()
        rect.init(0, 0, width, height)
        snapshot.append_color(self._bg_rgba, rect)

        if line_count == 0:
            snapshot.pop()
            return

        # Compute scroll_y and paint_offset for rendering.
        #
        # During active resize, vadjustment.value is stable (we froze the
        # DrawingArea height) but it no longer matches the new wrap layout.
        # We compute the *desired* scroll_y from the anchor, then derive a
        # paint_offset that shifts all rendered content so the correct lines
        # appear in the viewport at vadjustment's (stable) position.
        #
        # paint_offset = vadj_value - desired_scroll_y
        #
        # Each line is painted at  _line_visual_y(i) + paint_offset  instead
        # of  _line_visual_y(i).  The viewport shows  [vadj_value, vadj_value + page_size],
        # so a line at desired_scroll_y appears at vadj_value (top of viewport).
        paint_offset = 0.0
        anchor = self._resize_scroll_anchor
        if anchor is not None:
            # Compute content height from the (just-rebuilt) wrap map
            visual_rows = self._total_visual_rows if self._total_visual_rows > 0 else line_count
            content_height = visual_rows * self._line_height + self.PAD_TOP * 2
            visible = self._get_visible_height()
            if anchor["at_bottom"]:
                desired_scroll_y = max(0.0, float(content_height) - visible)
            else:
                line_y = self._line_visual_y(anchor["anchor_line"])
                desired_scroll_y = line_y + anchor["anchor_offset"]
                max_scroll = max(0.0, float(content_height) - visible)
                desired_scroll_y = max(0.0, min(desired_scroll_y, max_scroll))

            vadj_value = self._get_scroll_y()
            paint_offset = vadj_value - desired_scroll_y
            # For line culling, use desired_scroll_y (the content position)
            # not vadj_value (the viewport position).  Lines are painted at
            # _line_visual_y(i) + paint_offset, so a line is visible when
            # _line_visual_y(i) is near desired_scroll_y.
            scroll_y = desired_scroll_y
        else:
            scroll_y = self._get_scroll_y()

        # Visible range in visual rows.
        # Use a generous margin to account for long wrapped lines where a
        # single buffer line can span many visual rows — a tight margin
        # could exclude the beginning of such a line even though its later
        # rows fall within the viewport.
        _MARGIN = 20
        visible_height = self._get_visible_height()
        first_visual = max(0, int(scroll_y / self._line_height) - _MARGIN)
        last_visual = int((scroll_y + visible_height) / self._line_height) + 1 + _MARGIN

        # Convert visual row range to buffer line range
        first_line = self._visual_row_to_line(first_visual)
        last_line = min(line_count, self._visual_row_to_line(last_visual) + 1)

        # Content width available for text (excluding padding on both sides)
        content_width_px = max(width - self.PAD_LEFT * 2, self._char_width)

        # Invalidate layout cache if content width changed (rows depend on it)
        if abs(content_width_px - self._layout_cache_width) > 0.5:
            self._layout_cache.clear()
            self._layout_cache_width = content_width_px

        # Pango layout — reuse for all lines
        pango_ctx = self.get_pango_context()
        layout = Pango.Layout.new(pango_ctx)
        layout.set_font_description(self._font_desc)

        # Normalised selection range
        sel_start, sel_end = self._normalised_selection()

        for i in range(first_line, last_line):
            self._draw_line(snapshot, layout, i, width, content_width_px, sel_start, sel_end, paint_offset)

        # End clip region
        snapshot.pop()

    def _draw_line(self, snapshot, layout, line_idx, width, content_width_px, sel_start, sel_end, paint_offset=0.0):
        """Draw a single buffer line, soft-wrapping across multiple visual rows.

        *paint_offset* shifts all Y positions by that many pixels.  Used
        during resize to align content with the frozen vadjustment position.

        Uses a three-pass approach per visual row:
        1. Span backgrounds
        2. Selection highlight
        3. Text and underlines
        """
        base_y = self._line_visual_y(line_idx) + paint_offset
        spans = self._buffer.get_line(line_idx)
        point = Graphene.Point()

        # Use cached char_cells + rows if available (cache is evicted for
        # dirty lines in do_snapshot and cleared on width/font/color change).
        cached = self._layout_cache.get(line_idx)
        if cached is not None:
            char_cells, rows = cached
        else:
            # Pre-compute the character-level layout: list of
            # (char, char_pixel_width, span_index) so we can split across rows.
            #
            # Fast-path: when a span's text is all printable ASCII, every
            # character has display width 1, so we can batch-compute widths
            # without calling display_width() per character.
            char_cells: list[tuple[str, float, int]] = []
            cw = self._char_width
            for si, span in enumerate(spans):
                text = span.text
                if not text:
                    continue
                # Check if all chars are printable ASCII (very common for
                # code block content, table text, and regular prose)
                try:
                    encoded = text.encode("ascii")
                    if all(0x20 <= b <= 0x7E for b in encoded):
                        # All ASCII: width = 1 * char_width for each char
                        char_cells.extend((ch, cw, si) for ch in text)
                        continue
                except UnicodeEncodeError:
                    pass
                # Slow path for non-ASCII spans
                for ch in text:
                    char_cells.append((ch, display_width(ch) * cw, si))

            # Split chars into visual rows based on content_width_px
            rows: list[list[tuple[str, float, int]]] = []
            current_row: list[tuple[str, float, int]] = []
            row_w = 0.0
            for cell in char_cells:
                ch, ch_w, si = cell
                if current_row and row_w + ch_w > content_width_px + 0.5:
                    rows.append(current_row)
                    current_row = [cell]
                    row_w = ch_w
                else:
                    current_row.append(cell)
                    row_w += ch_w
            rows.append(current_row)  # last (or only) row

            self._layout_cache[line_idx] = (char_cells, rows)

        # Track the character offset into the buffer line for selection
        global_char_offset = 0

        for row_idx, row_cells in enumerate(rows):
            y = base_y + row_idx * self._line_height
            row_char_start = global_char_offset
            row_char_count = len(row_cells)

            # --- Pass 1: backgrounds (merged adjacent same-color rects) ---
            x = float(self.PAD_LEFT)
            run_bg = None  # current background hex or None
            run_x = 0.0  # start x of current run
            run_w = 0.0  # accumulated width of current run
            for ch, ch_w, si in row_cells:
                bg = spans[si].bg
                if bg == run_bg:
                    # Same background — extend the run
                    run_w += ch_w
                else:
                    # Flush previous run
                    if run_bg:
                        bg_rect = Graphene.Rect()
                        bg_rect.init(run_x, y, run_w, self._line_height)
                        snapshot.append_color(self._hex_to_rgba(run_bg), bg_rect)
                    run_bg = bg
                    run_x = x
                    run_w = ch_w
                x += ch_w
            # Flush final run
            if run_bg:
                bg_rect = Graphene.Rect()
                bg_rect.init(run_x, y, run_w, self._line_height)
                snapshot.append_color(self._hex_to_rgba(run_bg), bg_rect)

            # --- Pass 2: selection highlight ---
            if sel_start is not None and sel_end is not None:
                self._draw_selection_for_row(
                    snapshot,
                    line_idx,
                    y,
                    width,
                    row_char_start,
                    row_char_start + row_char_count,
                    row_cells,
                    sel_start,
                    sel_end,
                )

            # --- Pass 3: text and underlines ---
            # Group consecutive chars that share the same span index into
            # runs so we can render them in a single Pango layout call.
            x = float(self.PAD_LEFT)
            run_start = 0
            while run_start < len(row_cells):
                run_si = row_cells[run_start][2]
                run_end = run_start + 1
                while run_end < len(row_cells) and row_cells[run_end][2] == run_si:
                    run_end += 1

                span = spans[run_si]
                run_text = "".join(c[0] for c in row_cells[run_start:run_end])
                run_w = sum(c[1] for c in row_cells[run_start:run_end])

                # Set font variant (use pre-cached descriptors)
                if span.bold:
                    layout.set_font_description(self._font_desc_bold)
                elif span.italic:
                    layout.set_font_description(self._font_desc_italic)
                else:
                    layout.set_font_description(self._font_desc)

                fg = self._hex_to_rgba(span.fg) if span.fg else self._fg_rgba
                if span.dim:
                    fg = self._make_dim(fg)

                # Check if this run contains wide/box characters that need
                # per-character centering.  Uses pre-computed pixel widths
                # from char_cells to avoid redundant display_width() calls:
                # a char with pixel width > char_width is wide, and
                # box-drawing chars are detected by codepoint range.
                cw = self._char_width
                needs_grid = any(
                    c[1] > cw + 0.5 or 0x2500 <= ord(c[0]) <= 0x257F
                    for c in row_cells[run_start:run_end]
                )

                if needs_grid:
                    x = self._draw_wide_span_text(
                        snapshot,
                        layout,
                        run_text,
                        x,
                        y,
                        fg,
                        span.underline,
                        point,
                    )
                else:
                    layout.set_text(run_text, -1)
                    _, logical = layout.get_pixel_extents()
                    text_y = y + (self._line_height - logical.height) / 2

                    snapshot.save()
                    point.init(x, text_y)
                    snapshot.translate(point)
                    snapshot.append_layout(layout, fg)
                    snapshot.restore()

                    if span.underline:
                        underline_rect = Graphene.Rect()
                        underline_y = text_y + logical.height - 1
                        underline_rect.init(x, underline_y, logical.width, 1)
                        snapshot.append_color(fg, underline_rect)

                    x += run_w

                run_start = run_end

            global_char_offset += row_char_count

    def _draw_selection_for_row(
        self,
        snapshot,
        line_idx,
        y,
        width,
        row_char_start,
        row_char_end,
        row_cells,
        sel_start,
        sel_end,
    ):
        """Draw selection highlight for one visual row of a buffer line."""
        start_line, start_col = sel_start
        end_line, end_col = sel_end

        if line_idx < start_line or line_idx > end_line:
            return

        line_text = self._buffer.get_line_text(line_idx)
        line_len = len(line_text)

        # Determine the selected character range within this buffer line
        if line_idx == start_line and line_idx == end_line:
            sel_col_start = start_col
            sel_col_end = min(end_col, line_len)
        elif line_idx == start_line:
            sel_col_start = start_col
            sel_col_end = max(line_len, 1)
        elif line_idx == end_line:
            sel_col_start = 0
            sel_col_end = min(end_col, line_len)
        else:
            sel_col_start = 0
            sel_col_end = max(line_len, 1)

        # Intersect selection range with this visual row's character range
        vis_start = max(sel_col_start, row_char_start)
        vis_end = min(sel_col_end, row_char_end)
        if vis_end <= vis_start:
            return

        # Compute pixel x range for the selected portion within this row
        x1 = float(self.PAD_LEFT)
        x2 = float(self.PAD_LEFT)
        cumulative = 0.0
        for i, (ch, ch_w, si) in enumerate(row_cells):
            char_idx = row_char_start + i
            if char_idx < vis_start:
                cumulative += ch_w
            elif char_idx < vis_end:
                if char_idx == vis_start:
                    x1 = self.PAD_LEFT + cumulative
                cumulative += ch_w
                x2 = self.PAD_LEFT + cumulative
            else:
                break

        if x2 > x1:
            sel_rect = Graphene.Rect()
            sel_rect.init(x1, y, x2 - x1, self._line_height)
            snapshot.append_color(self._selection_rgba, sel_rect)

    def _wide_span_runs(self, text):
        """Split text into runs for grid-aligned rendering of wide/box chars."""
        runs: list[tuple[str, str]] = []
        current = ""
        for ch in text:
            ch_dw = display_width(ch)
            cp = ord(ch)
            if ch_dw > 1:
                if current:
                    runs.append((current, "normal"))
                    current = ""
                runs.append((ch, "wide"))
            elif 0x2500 <= cp <= 0x257F:
                if current:
                    runs.append((current, "normal"))
                    current = ""
                runs.append((ch, "box"))
            else:
                current += ch
        if current:
            runs.append((current, "normal"))
        return runs

    def _draw_wide_span_text(self, snapshot, layout, text, x, y, fg, underline, point):
        """Draw only text and underlines for a wide/box-drawing span."""
        cw = self._char_width
        for run_text, run_type in self._wide_span_runs(text):
            cell_w = display_width(run_text) * cw
            layout.set_text(run_text, -1)
            _, logical = layout.get_pixel_extents()
            text_y = y + (self._line_height - logical.height) / 2
            draw_x = x + (cell_w - logical.width) / 2 if run_type == "wide" else x

            snapshot.save()
            point.init(draw_x, text_y)
            snapshot.translate(point)
            snapshot.append_layout(layout, fg)
            snapshot.restore()

            if underline:
                underline_rect = Graphene.Rect()
                underline_y = text_y + logical.height - 1
                underline_rect.init(x, underline_y, cell_w, 1)
                snapshot.append_color(fg, underline_rect)

            x += cell_w
        return x

    def _char_col_to_x(self, line_idx, col):
        """Convert a character index to pixel x-position, accounting for display widths.

        With soft-wrapping, this returns the x position within the
        visual row that contains the character.
        """
        text = self._buffer.get_line_text(line_idx)
        width = self.get_width()
        content_width_px = max(width - self.PAD_LEFT * 2, self._char_width) if width > 0 else 9999

        x = float(self.PAD_LEFT)
        for i in range(min(col, len(text))):
            ch_w = display_width(text[i]) * self._char_width
            if x + ch_w - self.PAD_LEFT > content_width_px + 0.5:
                x = float(self.PAD_LEFT)
            x += ch_w
        return x

    # ------------------------------------------------------------------ #
    #  Event controllers                                                   #
    # ------------------------------------------------------------------ #

    def _setup_event_controllers(self):
        """Setup mouse events for text selection."""
        # Click gesture for double-click (word) and triple-click (line)
        click = Gtk.GestureClick()
        click.set_button(1)
        click.connect("pressed", self._on_click_pressed)
        self.add_controller(click)

        # Drag gesture for selection
        drag = Gtk.GestureDrag()
        drag.set_button(1)
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)

    def _on_drag_begin(self, gesture, start_x, start_y):
        """Start text selection."""
        if self._multi_click_active:
            return
        pos = self._pixel_to_pos(start_x, start_y)
        self._sel_anchor = pos
        self._sel_cursor = pos
        self._has_selection = False
        self.queue_draw()

    def _on_drag_update(self, gesture, offset_x, offset_y):
        """Update text selection."""
        if self._multi_click_active:
            return
        if self._sel_anchor is None:
            return
        ok, start_x, start_y = gesture.get_start_point()
        if not ok:
            return
        pos = self._pixel_to_pos(start_x + offset_x, start_y + offset_y)
        self._sel_cursor = pos
        self._has_selection = self._sel_anchor != self._sel_cursor
        self.queue_draw()

    def _on_drag_end(self, gesture, offset_x, offset_y):
        """End text selection."""
        if self._multi_click_active:
            self._multi_click_active = False
            return
        if self._sel_anchor is None:
            return
        ok, start_x, start_y = gesture.get_start_point()
        if ok:
            pos = self._pixel_to_pos(start_x + offset_x, start_y + offset_y)
            self._sel_cursor = pos
            self._has_selection = self._sel_anchor != self._sel_cursor

    def _on_click_pressed(self, gesture, n_press, x, y):
        """Handle double-click (word) and triple-click (line) selection."""
        if not self._measured or self._buffer.get_line_count() == 0:
            return
        line, col = self._pixel_to_char_index(x, y)
        if n_press == 2:
            start, end = self._word_bounds_at(line, col)
            self._sel_anchor = (line, start)
            self._sel_cursor = (line, end)
            self._has_selection = start != end
            self._multi_click_active = True
            self.queue_draw()
        elif n_press >= 3:
            line_len = len(self._buffer.get_line_text(line))
            self._sel_anchor = (line, 0)
            self._sel_cursor = (line, line_len)
            self._has_selection = line_len > 0
            self._multi_click_active = True
            self.queue_draw()

    def _word_bounds_at(self, line, col):
        """Return (start_col, end_col) of the word at position."""
        text = self._buffer.get_line_text(line)
        if not text or col >= len(text):
            return (col, col)
        ch = text[col]
        if ch.isspace():
            # Select contiguous whitespace
            start = col
            while start > 0 and text[start - 1].isspace():
                start -= 1
            end = col + 1
            while end < len(text) and text[end].isspace():
                end += 1
            return (start, end)
        # Select word characters (letters, digits, underscore)
        is_word_char = ch.isalnum() or ch == "_"
        if is_word_char:
            start = col
            while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "_"):
                start -= 1
            end = col + 1
            while end < len(text) and (text[end].isalnum() or text[end] == "_"):
                end += 1
        else:
            # Select contiguous punctuation / symbols
            start = col
            while start > 0 and not text[start - 1].isalnum() and text[start - 1] != "_" and not text[start - 1].isspace():
                start -= 1
            end = col + 1
            while end < len(text) and not text[end].isalnum() and text[end] != "_" and not text[end].isspace():
                end += 1
        return (start, end)

    # ------------------------------------------------------------------ #
    #  Selection helpers                                                   #
    # ------------------------------------------------------------------ #

    def _pixel_to_pos(self, x, y):
        """Convert pixel coordinates to (line, col) insertion point.

        Uses midpoint snapping: clicking on the right half of a character
        returns the *next* column (suitable for drag-selection / cursor placement).
        Accounts for soft-wrapped visual rows.
        """
        if self._char_width <= 0 or self._line_height <= 0:
            if not self._measured:
                self._measure_font()
        abs_y = y - self.PAD_TOP

        # When the wrap map hasn't been built (e.g. during tests that
        # set _line_height / _char_width directly), fall back to simple
        # line = row logic without sub-row wrap handling.
        if not self._wrap_offsets:
            line = max(0, min(int(abs_y / self._line_height), self._buffer.get_line_count() - 1))
            text = self._buffer.get_line_text(line)
            if not text or self._char_width <= 0:
                return (line, 0)
            target_x = x - self.PAD_LEFT
            cumulative = 0.0
            for i, ch in enumerate(text):
                ch_w = display_width(ch) * self._char_width
                if cumulative + ch_w / 2 > target_x:
                    return (line, i)
                cumulative += ch_w
            return (line, len(text))

        visual_row = max(0, int(abs_y / self._line_height))
        line = self._visual_row_to_line(visual_row)

        text = self._buffer.get_line_text(line)
        if not text or self._char_width <= 0:
            return (line, 0)

        # Determine which visual sub-row within this buffer line
        line_visual_start = self._wrap_offsets[line] if line < len(self._wrap_offsets) else 0
        sub_row = visual_row - line_visual_start

        # Walk through characters, tracking which visual row we're on
        width = self.get_width()
        content_width_px = max(width - self.PAD_LEFT * 2, self._char_width) if width > 0 else 9999

        current_sub_row = 0
        row_x = 0.0
        target_x = x - self.PAD_LEFT

        for i, ch in enumerate(text):
            ch_w = display_width(ch) * self._char_width
            # Check if adding this char would overflow the row
            if row_x > 0 and row_x + ch_w > content_width_px + 0.5:
                current_sub_row += 1
                row_x = 0.0
            if current_sub_row == sub_row:
                if row_x + ch_w / 2 > target_x:
                    return (line, i)
            elif current_sub_row > sub_row:
                return (line, i)
            row_x += ch_w

        return (line, len(text))

    def _pixel_to_char_index(self, x, y):
        """Convert pixel coordinates to (line, char_index) of the character under the cursor.

        Unlike ``_pixel_to_pos`` (which snaps to insertion points at the midpoint
        of each character cell), this returns the index of the character whose
        cell *contains* the click position.  Used for double-click word selection
        so that clicking anywhere on a character selects the correct word.
        Accounts for soft-wrapped visual rows.
        """
        if self._char_width <= 0 or self._line_height <= 0:
            if not self._measured:
                self._measure_font()
        abs_y = y - self.PAD_TOP

        # Fallback when wrap map isn't initialised
        if not self._wrap_offsets:
            line = max(0, min(int(abs_y / self._line_height), self._buffer.get_line_count() - 1))
            text = self._buffer.get_line_text(line)
            if not text or self._char_width <= 0:
                return (line, 0)
            target_x = x - self.PAD_LEFT
            cumulative = 0.0
            for i, ch in enumerate(text):
                ch_w = display_width(ch) * self._char_width
                if cumulative + ch_w > target_x:
                    return (line, i)
                cumulative += ch_w
            return (line, max(0, len(text) - 1))

        visual_row = max(0, int(abs_y / self._line_height))
        line = self._visual_row_to_line(visual_row)

        text = self._buffer.get_line_text(line)
        if not text or self._char_width <= 0:
            return (line, 0)

        line_visual_start = self._wrap_offsets[line] if line < len(self._wrap_offsets) else 0
        sub_row = visual_row - line_visual_start

        width = self.get_width()
        content_width_px = max(width - self.PAD_LEFT * 2, self._char_width) if width > 0 else 9999

        current_sub_row = 0
        row_x = 0.0
        target_x = x - self.PAD_LEFT

        for i, ch in enumerate(text):
            ch_w = display_width(ch) * self._char_width
            if row_x > 0 and row_x + ch_w > content_width_px + 0.5:
                current_sub_row += 1
                row_x = 0.0
            if current_sub_row == sub_row:
                if row_x + ch_w > target_x:
                    return (line, i)
            elif current_sub_row > sub_row:
                return (line, i)
            row_x += ch_w

        return (line, max(0, len(text) - 1))

    def _normalised_selection(self):
        """Return (start, end) with start <= end, or (None, None)."""
        if not self._has_selection or self._sel_anchor is None or self._sel_cursor is None:
            return None, None
        a, b = self._sel_anchor, self._sel_cursor
        if a > b:
            a, b = b, a
        return a, b

    def get_selected_text(self) -> str:
        """Return plain text from the current selection range."""
        sel_start, sel_end = self._normalised_selection()
        if sel_start is None:
            return ""
        start_line, start_col = sel_start
        end_line, end_col = sel_end

        if start_line == end_line:
            text = self._buffer.get_line_text(start_line)
            return text[start_col:end_col]

        parts = []
        for i in range(start_line, end_line + 1):
            text = self._buffer.get_line_text(i)
            if i == start_line:
                parts.append(text[start_col:])
            elif i == end_line:
                parts.append(text[:end_col])
            else:
                parts.append(text)
        return "\n".join(parts)

    def _clear_selection(self):
        self._sel_anchor = None
        self._sel_cursor = None
        self._has_selection = False

    # ------------------------------------------------------------------ #
    #  Font measurement                                                    #
    # ------------------------------------------------------------------ #

    def _measure_font(self):
        """Measure font metrics for line height and char width.

        Uses Pango units (not pixel extents) and averages across multiple
        characters to get a precise float width.  This eliminates accumulated
        pixel drift when advancing x across many spans.
        """
        pango_ctx = self.get_pango_context()
        if pango_ctx is None:
            return
        layout = Pango.Layout.new(pango_ctx)
        layout.set_font_description(self._font_desc)
        sample = "M" * 10
        layout.set_text(sample, -1)
        _, logical = layout.get_extents()
        self._char_width = max(logical.width / Pango.SCALE / len(sample), 1.0)
        self._line_height = max(round(logical.height / Pango.SCALE) + 2, 1)
        self._measured = True

    @staticmethod
    def _make_bold_desc(base: Pango.FontDescription) -> Pango.FontDescription:
        """Create a bold variant of *base* (cached, not per-frame)."""
        desc = base.copy()
        desc.set_weight(Pango.Weight.BOLD)
        return desc

    @staticmethod
    def _make_italic_desc(base: Pango.FontDescription) -> Pango.FontDescription:
        """Create an italic variant of *base* (cached, not per-frame)."""
        desc = base.copy()
        desc.set_style(Pango.Style.ITALIC)
        return desc

    # ------------------------------------------------------------------ #
    #  Sizing and scrolling                                                #
    # ------------------------------------------------------------------ #

    def _connect_vadjustment(self, vadjustment):
        """Reconnect redraw handling when the scrolled window swaps adjustments."""
        if self._vadjustment is vadjustment:
            return
        if self._vadjustment is not None:
            if self._vadjustment_handler_id is not None:
                self._vadjustment.disconnect(self._vadjustment_handler_id)
            if self._page_size_handler_id is not None:
                self._vadjustment.disconnect(self._page_size_handler_id)
        self._vadjustment = vadjustment
        self._vadjustment_handler_id = None
        self._page_size_handler_id = None
        if vadjustment is not None:
            self._vadjustment_handler_id = vadjustment.connect("value-changed", self._on_scroll_value_changed)
            # Redraw when viewport height changes (e.g. editor collapse/expand)
            # so newly visible lines are rendered instead of showing blank space.
            self._page_size_handler_id = vadjustment.connect("notify::page-size", self._on_page_size_changed)

    def _on_vadjustment_changed(self, scrolled_window, pspec):
        self._connect_vadjustment(scrolled_window.get_vadjustment())

    def _on_map(self, widget):
        """Re-sync content height and schedule a redraw when the widget maps.

        On macOS, background→foreground transitions can leave the vadjustment
        with stale page_size / upper values.  Forcing a height update + redraw
        ensures the full content is rendered.

        IMPORTANT: We do NOT call _invalidate_wrap_map() here.  That would
        set _total_visual_rows = 0, causing _update_content_height() to
        fall back to a line-count-based height (ignoring soft-wrapping).
        If the wrap map was recently built (e.g. by _do_restore_messages),
        invalidating it creates a transient state where the content height
        is too small, GTK clamps vadjustment.value, and the scroll position
        is lost.  Instead, we clear the layout cache (cheap Pango re-render)
        and let do_snapshot rebuild the wrap map if the width actually changed.
        """
        self._needs_height_update = True
        self._layout_cache.clear()
        self._layout_cache_width = 0.0
        self._eagerly_update_height()
        self._schedule_redraw()

    def _on_realize(self, widget):
        """Connect to the toplevel window's is-active property once realized."""
        root = self.get_root()
        if root is not None and hasattr(root, "connect"):
            self._window_active_handler_id = root.connect("notify::is-active", self._on_window_active)

    def _on_window_active(self, window, pspec):
        """Refresh rendering when the window regains focus (foreground).

        Like _on_map, avoids _invalidate_wrap_map() to prevent transient
        wrong content heights that cause scroll position clamping.  The
        layout cache is cleared so Pango re-renders at the current width,
        and do_snapshot will rebuild the wrap map if the width changed.
        """
        if window.get_property("is-active"):
            self._needs_height_update = True
            self._layout_cache.clear()
            self._layout_cache_width = 0.0
            self._eagerly_update_height()
            self._schedule_redraw()

    def _on_scroll_value_changed(self, adjustment):
        # During active resize, scroll_y is computed from the anchor,
        # not vadjustment.  Suppress GTK-clamping-driven redraws to
        # prevent visual jumps.
        if self._resize_scroll_anchor is not None:
            return
        self._schedule_redraw()

    def _on_page_size_changed(self, adjustment, pspec):
        """Redraw when the viewport height changes so all visible lines are rendered."""
        self._schedule_redraw()

    def _update_content_height(self):
        """Set DrawingArea height to match content for ScrolledWindow scrolling.

        Uses the total visual row count (which accounts for soft-wrapped
        lines) instead of the buffer line count.
        """
        visual_rows = self._total_visual_rows if self._total_visual_rows > 0 else self._buffer.get_line_count()
        total = visual_rows * self._line_height + self.PAD_TOP * 2
        self.set_size_request(-1, max(total, 100))

    def _capture_resize_anchor(self) -> dict | None:
        """Snapshot the scroll anchor before a width-triggered wrap-map rebuild.

        Returns a dict with the buffer line at the top of the viewport and
        the sub-line pixel offset, plus whether the viewport was at the
        bottom.  Returns ``None`` if no vadjustment is available.
        """
        vadj = self._vadjustment
        if vadj is None:
            return None
        max_val = max(vadj.get_upper() - vadj.get_page_size(), 0)
        value = vadj.get_value()
        at_bottom = (max_val - value) <= 2.0

        # Derive anchor from current vadjustment (no render offset involved)
        if self._line_height <= 0:
            return {"anchor_line": 0, "anchor_offset": 0.0, "at_bottom": at_bottom}

        scroll_y = value
        visual_row = max(0, int((scroll_y - self.PAD_TOP) / self._line_height))
        if self._wrap_offsets:
            line = self._visual_row_to_line(visual_row)
        else:
            line = max(0, min(visual_row, self._buffer.get_line_count() - 1))
        line_y = self._line_visual_y(line)
        offset = max(0.0, scroll_y - line_y)

        return {
            "anchor_line": line,
            "anchor_offset": offset,
            "at_bottom": at_bottom,
        }

    def _settle_resize_scroll(self) -> bool:
        """Reconcile vadjustment with the scroll anchor after resize stops.

        Called as a GLib.timeout_add(150ms) callback — fires only after
        no width-change frame has arrived for 150ms, meaning resize has
        truly stopped.  By this point GTK layout has settled, so
        vadjustment.upper and page_size are accurate.  We update the
        content height (deferred during resize to avoid GTK clamping),
        set the correct scroll value, and clear the anchor so subsequent
        frames use normal vadjustment-based scrolling.
        """
        self._resize_settle_id = None
        anchor = self._resize_scroll_anchor
        if anchor is None:
            return False

        vadj = self._vadjustment
        if vadj is None:
            self._resize_scroll_anchor = None
            return False

        # Compute the target scroll position from the anchor BEFORE
        # updating content height, because _update_content_height()
        # calls set_size_request() which can trigger GTK layout and
        # clamp vadj.value.  We need the target computed from the
        # current (accurate) wrap map state.
        visual_rows = self._total_visual_rows if self._total_visual_rows > 0 else self._buffer.get_line_count()
        new_content_height = visual_rows * self._line_height + self.PAD_TOP * 2
        new_content_height = max(new_content_height, 100)
        page_size = vadj.get_page_size()
        max_val = max(float(new_content_height) - page_size, 0)

        if anchor["at_bottom"]:
            target = max_val
        else:
            line_y = self._line_visual_y(anchor["anchor_line"])
            target = line_y + anchor["anchor_offset"]

        target = max(0.0, min(target, max_val))

        # Now update content height. This may trigger GTK layout and
        # clamp vadj.value, but we've already computed our target.
        self._update_content_height()
        self._needs_height_update = False

        # Force vadjustment.upper to match the new content height
        vadj.set_upper(float(new_content_height))

        # Re-clamp target against the (now-final) adjustment bounds
        final_max = max(vadj.get_upper() - vadj.get_page_size(), 0)
        target = max(0.0, min(target, final_max))

        # Clear the anchor BEFORE setting value so the value-changed
        # signal handler uses normal (non-anchor) scrolling.
        self._resize_scroll_anchor = None

        if abs(vadj.get_value() - target) > 0.5:
            vadj.set_value(target)
        else:
            self.queue_draw()

        return False

    def _get_scroll_y(self) -> float:
        """Get vertical scroll offset from parent ScrolledWindow."""
        parent = self.get_parent()
        while parent is not None:
            if isinstance(parent, Gtk.ScrolledWindow):
                vadj = parent.get_vadjustment()
                return vadj.get_value() if vadj else 0.0
            parent = parent.get_parent()
        return 0.0

    def _get_visible_height(self) -> float:
        """Get visible viewport height from parent ScrolledWindow."""
        parent = self.get_parent()
        while parent is not None:
            if isinstance(parent, Gtk.ScrolledWindow):
                vadj = parent.get_vadjustment()
                if vadj:
                    ps = vadj.get_page_size()
                    if ps > 0:
                        return ps
                # page_size can be 0 during background→foreground transitions
                return float(self.get_height()) or 100.0
            parent = parent.get_parent()
        return float(self.get_height()) or 100.0

    def _get_visible_width(self) -> float:
        """Get the actual rendering area width.

        Prefers the DrawingArea's own allocated width — this is the most
        accurate representation of the visible rendering area and correctly
        accounts for scrollbar space, viewport margins, and pane splits.
        Falls back to ScrolledWindow width during initial layout when the
        DrawingArea has not yet received its allocation.
        """
        # Own allocated width is the true rendering area
        own_width = float(self.get_width())
        if own_width > 0:
            return own_width

        # Fallback during initial layout before allocation
        if self._scrolled_window is not None:
            width = self._scrolled_window.get_width()
            if width > 0:
                return float(width)

        return 0.0

    def _eagerly_update_height(self):
        """Update content height immediately if font metrics are available.

        Ensures the ScrolledWindow vadjustment reflects the current content
        size before scroll restoration runs, preventing set_value() from
        silently clamping to a stale upper bound.
        """
        if self._suppress_height:
            return
        if self._line_height > 0:
            # Ensure wrap map is current before computing height
            width = self._get_visible_width()
            if width > 0 and (
                not self._wrap_map
                or abs(width - self._wrap_map_width) > 0.5
                or self._buffer.get_line_count() != self._wrap_map_line_count
            ):
                self._rebuild_wrap_map(width)
            self._update_content_height()
            self._needs_height_update = False

    def _schedule_redraw(self):
        """Batch redraws — only one queue_draw per frame."""
        if not self._redraw_scheduled:
            self._redraw_scheduled = True
            GLib.idle_add(self._do_redraw)

    def _do_redraw(self):
        self._redraw_scheduled = False
        self.queue_draw()
        return False

    # ------------------------------------------------------------------ #
    #  Color helpers                                                       #
    # ------------------------------------------------------------------ #

    def _hex_to_rgba(self, hex_color: str) -> Gdk.RGBA:
        """Convert a hex colour string to Gdk.RGBA, with caching."""
        cached = self._rgba_cache.get(hex_color)
        if cached is not None:
            return cached
        rgba = Gdk.RGBA()
        rgba.parse(hex_color)
        self._rgba_cache[hex_color] = rgba
        return rgba

    @staticmethod
    def _rgba_to_hex(rgba: Gdk.RGBA) -> str:
        r = int(rgba.red * 255)
        g = int(rgba.green * 255)
        b = int(rgba.blue * 255)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _make_dim(self, color: Gdk.RGBA) -> Gdk.RGBA:
        """Return a dimmed version of the color, with caching.

        Dim spans (e.g. table borders, code block frames) reuse the same
        few colors thousands of times.  Caching avoids creating a fresh
        Gdk.RGBA and doing the blending arithmetic on every call.
        """
        # Build a cache key from the color's RGB channels (quantised to
        # avoid float comparison issues).
        key = (
            round(color.red, 4),
            round(color.green, 4),
            round(color.blue, 4),
        )
        cached = self._dim_cache.get(key)
        if cached is not None:
            return cached
        dim = Gdk.RGBA()
        dim.red = color.red * self._dim_alpha + self._bg_rgba.red * (1 - self._dim_alpha)
        dim.green = color.green * self._dim_alpha + self._bg_rgba.green * (1 - self._dim_alpha)
        dim.blue = color.blue * self._dim_alpha + self._bg_rgba.blue * (1 - self._dim_alpha)
        dim.alpha = color.alpha
        self._dim_cache[key] = dim
        return dim
