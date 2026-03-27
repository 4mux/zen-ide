"""MarkdownCanvas — Gtk.DrawingArea that renders ContentBlocks via GtkSnapshot.

Follows the ChatCanvas pattern: DrawingArea inside ScrolledWindow with
pixel-smooth scrolling. Renders structured ContentBlocks (headings, paragraphs,
code, tables, lists, blockquotes, horizontal rules, images) using Pango layouts.

Unlike ChatCanvas (fixed line heights, ANSI buffer), MarkdownCanvas handles
variable-height blocks with word-wrapping. Each block caches its Y offset and
height for viewport culling and scroll-sync mapping.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import threading

from gi.repository import Gdk, GdkPixbuf, GLib, Graphene, Gtk, Pango

from editor.preview.content_block import ContentBlock, InlineSpan
from shared.utils import hex_to_gdk_rgba

# Emoji detection for adding visual spacing in rendered text
_EMOJI_RE = re.compile(
    "(["
    "\u2600-\u27bf"  # Misc symbols & dingbats (✅, ❌, ⚠, ✨, etc.)
    "\U0001f300-\U0001f9ff"  # Emoticons, symbols, transport, supplemental
    "\U0001fa00-\U0001faff"  # Extended symbols
    "][\ufe0e\ufe0f]?)"  # Optional variation selector
)


def _add_emoji_spacing(text: str) -> str:
    """Insert a thin space after emoji characters for visual breathing room."""
    return _EMOJI_RE.sub(lambda m: m.group(0) + "\u2009", text)


def _estimate_block_lines(block: ContentBlock) -> int:
    """Estimate how many source lines a block spans."""
    if block.kind == "code":
        return max(len(block.code.split("\n")), 1) + 2  # +2 for fences
    if block.kind == "table":
        return 2 + len(block.rows)  # header + separator + rows
    return 1


class MarkdownCanvas(Gtk.DrawingArea):
    """DrawingArea that renders a list of ContentBlocks using GtkSnapshot."""

    __gtype_name__ = "MarkdownCanvas"

    PAD_LEFT = 24
    PAD_RIGHT = 24
    PAD_TOP = 16
    BLOCK_SPACING = 10
    CODE_PAD = 12
    # Extra top margin before headings (CSS-style margin-top)
    HEADING_MARGIN_TOP = {1: 28, 2: 24, 3: 20, 4: 16, 5: 14, 6: 14}
    # Extra bottom margin after headings (space between heading and next content)
    HEADING_MARGIN_BOTTOM = {1: 10, 2: 8, 3: 6, 4: 4, 5: 4, 6: 4}
    LINE_SPACING = 4  # extra pixels between wrapped lines inside a block
    QUOTE_BAR_WIDTH = 3
    QUOTE_INDENT = 16
    COLLAPSIBLE_INDENT = 20
    CHEVRON_WIDTH = 16

    # Heading sizes relative to base font size
    HEADING_SCALES = {1: 2.0, 2: 1.5, 3: 1.25, 4: 1.1, 5: 1.0, 6: 0.9}

    def __init__(self):
        super().__init__()

        self._blocks: list[ContentBlock] = []
        self._scrolled_window = None
        self._vadjustment = None
        self._vadjustment_handler_id = None
        self._page_size_handler_id = None

        # Font
        self._base_font_size = 14
        self._font_desc = Pango.FontDescription.from_string(f"sans {self._base_font_size}")
        from fonts import get_font_settings as _get_font_settings

        _editor = _get_font_settings("editor")
        self._mono_font_desc = Pango.FontDescription.from_string(f"{_editor['family']} {self._base_font_size - 1}")
        self._line_height = 0
        self._char_width = 0
        self._measured = False

        # Colors (defaults — overridden by set_theme)
        self._fg_hex = "#e0e0e0"
        self._bg_hex = "#1e1e1e"
        self._code_bg_hex = "#2d2d2d"
        self._accent_hex = "#61afef"
        self._dim_hex = "#808080"
        self._border_hex = "#3e3e3e"
        self._selection_bg_hex = "#264f78"

        self._fg_rgba = hex_to_gdk_rgba(self._fg_hex)
        self._bg_rgba = hex_to_gdk_rgba(self._bg_hex)
        self._code_bg_rgba = hex_to_gdk_rgba(self._code_bg_hex)
        self._accent_rgba = hex_to_gdk_rgba(self._accent_hex)
        self._dim_rgba = hex_to_gdk_rgba(self._dim_hex)
        self._border_rgba = hex_to_gdk_rgba(self._border_hex)
        self._selection_rgba = hex_to_gdk_rgba(self._selection_bg_hex)
        self._selection_rgba.alpha = 0.4

        # Selection state: (region_idx, byte_idx) tuples
        self._sel_anchor = None
        self._sel_cursor = None
        self._has_selection = False
        self._drag_start_x = 0.0
        self._drag_start_y = 0.0
        self._multi_click_mode = 0  # 0=normal, 2=word, 3=line

        # Text region cache for hit testing: [(layout, x, y), ...]
        self._text_regions: list[tuple] = []
        self._draw_x_offset = 0.0

        # Layout cache valid width
        self._layout_width = -1

        # State
        self._needs_layout = True
        self._redraw_scheduled = False

        # Zoom
        self._zoom_level = 1.0

        # Smooth scroll animation state
        self._smooth_target_y: float | None = None
        self._smooth_tick_id: int = 0
        self._LERP_FACTOR = 0.25  # fraction of remaining distance per frame
        self._animation_adjusting = False  # True while set_value runs inside tick

        # Image cache: url → Gdk.Texture (None means load failed)
        self._image_cache: dict[str, Gdk.Texture | None] = {}
        self._base_path: str | None = None
        self._IMAGE_MAX_HEIGHT = 600

        # Remote image download cache directory
        self._remote_cache_dir = os.path.join(tempfile.gettempdir(), ".zen_image_cache")
        os.makedirs(self._remote_cache_dir, exist_ok=True)
        # URLs currently being fetched (to avoid duplicate requests)
        self._fetching_urls: set[str] = set()

        # Setup
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_can_focus(True)
        self.set_focusable(True)
        self._setup_event_controllers()

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    @property
    def is_animation_adjusting(self) -> bool:
        """True when the canvas is programmatically adjusting scroll (animation frame)."""
        return self._animation_adjusting

    def set_blocks(self, blocks: list[ContentBlock]):
        """Set the content blocks to render."""
        self._blocks = blocks
        self._needs_layout = True
        self._schedule_redraw()

    def set_base_path(self, path: str | None):
        """Set base directory for resolving relative image paths."""
        if path != self._base_path:
            self._base_path = path
            self._image_cache.clear()

    def get_blocks(self) -> list[ContentBlock]:
        return self._blocks

    def set_theme(self, fg: str, bg: str, code_bg: str, accent: str, dim: str, border: str, selection_bg: str = ""):
        """Apply theme colors (hex strings)."""
        self._fg_hex = fg
        self._bg_hex = bg
        self._code_bg_hex = code_bg
        self._accent_hex = accent
        self._dim_hex = dim
        self._border_hex = border
        if selection_bg:
            self._selection_bg_hex = selection_bg

        self._fg_rgba = hex_to_gdk_rgba(fg)
        self._bg_rgba = hex_to_gdk_rgba(bg)
        self._code_bg_rgba = hex_to_gdk_rgba(code_bg)
        self._accent_rgba = hex_to_gdk_rgba(accent)
        self._dim_rgba = hex_to_gdk_rgba(dim)
        self._border_rgba = hex_to_gdk_rgba(border)
        if selection_bg:
            self._selection_rgba = hex_to_gdk_rgba(selection_bg)
            self._selection_rgba.alpha = 0.4

        self._schedule_redraw()

    def set_font(self, font_family: str, size: int):
        """Set the base font."""
        self._base_font_size = size
        self._font_desc = Pango.FontDescription.from_string(f"{font_family} {size}")
        from fonts import get_font_settings as _get_font_settings

        _editor = _get_font_settings("editor")
        self._mono_font_desc = Pango.FontDescription.from_string(f"{_editor['family']} {max(size - 1, 10)}")
        self._measured = False
        self._needs_layout = True
        self._schedule_redraw()

    def attach_to_scrolled_window(self, scrolled_window):
        """Bind redraws to the parent ScrolledWindow's vertical adjustment."""
        if self._scrolled_window is scrolled_window:
            return
        self._scrolled_window = scrolled_window
        scrolled_window.connect("notify::vadjustment", self._on_vadjustment_changed)
        self._connect_vadjustment(scrolled_window.get_vadjustment())

    def get_block_at_y(self, y: float) -> ContentBlock | None:
        """Return the block at the given Y coordinate (for scroll sync)."""
        for block in self._blocks:
            if block._y_offset <= y < block._y_offset + block._height:
                return block
        return self._blocks[-1] if self._blocks else None

    def get_y_for_source_line(self, source_line: int) -> float:
        """Return the Y offset for a given source line (for editor→preview sync).

        Interpolates within blocks so that scrolling through a large block
        produces proportional movement in the preview rather than snapping
        to block boundaries.
        """
        if not self._blocks:
            return 0.0

        # Find the block that contains this source line
        best_idx = 0
        for i, block in enumerate(self._blocks):
            if block.source_line <= source_line:
                best_idx = i
            else:
                break

        block = self._blocks[best_idx]

        # Calculate line span: how many source lines this block covers
        if best_idx + 1 < len(self._blocks):
            next_line = self._blocks[best_idx + 1].source_line
        else:
            # Last block — estimate span from content lines
            next_line = block.source_line + _estimate_block_lines(block)

        span = max(next_line - block.source_line, 1)
        frac = (source_line - block.source_line) / span

        return block._y_offset + frac * block._height

    def scroll_to_source_line(self, source_line: int):
        """Scroll the preview to show the block for the given editor line.

        Uses smooth exponential interpolation (lerp) so the preview glides
        to the target position instead of jumping between block boundaries.
        """
        y = self.get_y_for_source_line(source_line)
        self._smooth_scroll_to(y)

    def scroll_to_value(self, value: float):
        """Set scroll position with smooth interpolation (editor→preview sync)."""
        self._smooth_scroll_to(value)

    def _smooth_scroll_to(self, target_y: float):
        """Start or update smooth scroll animation toward target_y."""
        vadj = self._get_vadjustment()
        if not vadj:
            return
        upper = vadj.get_upper()
        page = vadj.get_page_size()
        max_val = max(0.0, upper - page)
        self._smooth_target_y = max(0.0, min(target_y, max_val))

        if not self._smooth_tick_id:
            self._smooth_tick_id = self.add_tick_callback(self._smooth_scroll_tick)

    def _smooth_scroll_tick(self, widget, frame_clock):
        """Frame-clock tick callback: lerp toward target each frame."""
        vadj = self._get_vadjustment()
        if vadj is None or self._smooth_target_y is None:
            self._smooth_tick_id = 0
            return False  # remove callback

        current = vadj.get_value()
        target = self._smooth_target_y
        diff = target - current

        if abs(diff) < 1.0:
            self._animation_adjusting = True
            vadj.set_value(target)
            self._animation_adjusting = False
            self._smooth_target_y = None
            self._smooth_tick_id = 0
            return False  # remove callback

        self._animation_adjusting = True
        vadj.set_value(current + diff * self._LERP_FACTOR)
        self._animation_adjusting = False
        return True  # keep ticking

    def _set_scroll_value(self, target_y: float):
        """Clamp and apply a scroll Y value immediately (no animation)."""
        vadj = self._get_vadjustment()
        if not vadj:
            return
        upper = vadj.get_upper()
        page = vadj.get_page_size()
        max_val = max(0.0, upper - page)
        vadj.set_value(max(0.0, min(target_y, max_val)))

    def get_source_line_at_scroll(self) -> int:
        """Return the interpolated source line at the current scroll position.

        Uses the same proportional mapping as get_y_for_source_line so the
        forward and reverse mappings are consistent.
        """
        if not self._blocks:
            return 0
        scroll_y = self._get_scroll_y() + self.PAD_TOP
        block = self.get_block_at_y(scroll_y)
        if not block:
            return 0

        # Find block index for span calculation
        idx = 0
        for i, b in enumerate(self._blocks):
            if b is block:
                idx = i
                break

        if idx + 1 < len(self._blocks):
            next_line = self._blocks[idx + 1].source_line
        else:
            next_line = block.source_line + _estimate_block_lines(block)

        span = max(next_line - block.source_line, 1)

        # Interpolate within block
        if block._height > 0:
            frac = max(0.0, min(1.0, (scroll_y - block._y_offset) / block._height))
        else:
            frac = 0.0

        return block.source_line + int(frac * span)

    def zoom_in(self):
        self._zoom_level = min(self._zoom_level + 0.1, 3.0)
        self._apply_zoom()

    def zoom_out(self):
        self._zoom_level = max(self._zoom_level - 0.1, 0.5)
        self._apply_zoom()

    def zoom_reset(self):
        self._zoom_level = 1.0
        self._apply_zoom()

    def copy_clipboard(self):
        """Copy selected text (or all text if no selection) to clipboard."""
        if self._has_selection:
            text = self._get_selected_text()
        else:
            parts = []
            for block in self._blocks:
                parts.append(self._block_to_text(block))
            text = "\n\n".join(parts)
        if text:
            clipboard = Gdk.Display.get_default().get_clipboard()
            clipboard.set(text)
            from shared.utils import copy_to_system_clipboard

            copy_to_system_clipboard(text)

    # ------------------------------------------------------------------ #
    #  Rendering (GtkSnapshot)                                             #
    # ------------------------------------------------------------------ #

    def do_snapshot(self, snapshot):
        """Render visible blocks using GtkSnapshot + Pango."""
        width = self.get_width()
        height = self.get_height()
        if width <= 0 or height <= 0:
            return

        if not self._measured:
            self._measure_font()

        content_width = width - self.PAD_LEFT - self.PAD_RIGHT
        if content_width <= 0:
            content_width = 100

        # Re-layout if width changed or layout needed
        if self._needs_layout or self._layout_width != content_width:
            self._layout_blocks(content_width)

        # Background
        rect = Graphene.Rect()
        rect.init(0, 0, width, height)
        snapshot.append_color(self._bg_rgba, rect)

        # Reset text region cache for hit testing
        self._text_regions = []
        self._draw_x_offset = 0.0

        if not self._blocks:
            return

        scroll_y = self._get_scroll_y()
        visible_height = self._get_visible_height()
        pango_ctx = self.get_pango_context()

        # Draw ALL blocks — no viewport culling.
        # On macOS GTK4, do_snapshot may not be re-invoked on every scroll
        # despite queue_draw(); rendering every block ensures the full
        # snapshot is available for the viewport to translate freely.
        # Cost is negligible (just lightweight render-node creation).
        for block in self._blocks:
            self._draw_block(snapshot, pango_ctx, block, width, scroll_y, visible_height)

        # Draw selection overlay on top
        if self._has_selection:
            self._draw_selection_overlay(snapshot)

    def _draw_block(
        self, snapshot, pango_ctx, block: ContentBlock, width: float, scroll_y: float = 0.0, visible_height: float = 1e9
    ):
        """Draw a single block, dispatching by kind."""
        if block.collapsible:
            self._draw_collapsible(snapshot, pango_ctx, block, width, scroll_y, visible_height)
        elif block.kind == "heading":
            self._draw_heading(snapshot, pango_ctx, block, width)
        elif block.kind == "paragraph":
            self._draw_paragraph(snapshot, pango_ctx, block, width)
        elif block.kind == "code":
            self._draw_code_block(snapshot, pango_ctx, block, width)
        elif block.kind == "table":
            self._draw_table(snapshot, pango_ctx, block, width)
        elif block.kind == "list":
            self._draw_list(snapshot, pango_ctx, block, width)
        elif block.kind == "blockquote":
            self._draw_blockquote(snapshot, pango_ctx, block, width)
        elif block.kind == "hr":
            self._draw_hr(snapshot, block, width)
        elif block.kind == "image":
            self._draw_image(snapshot, pango_ctx, block, width)
        elif block.kind == "image_row":
            self._draw_image_row(snapshot, pango_ctx, block, width)

    def _draw_heading(self, snapshot, pango_ctx, block: ContentBlock, width: float):
        scale = self.HEADING_SCALES.get(block.level, 1.0)
        font_size = int(self._base_font_size * scale * self._zoom_level)

        desc = self._font_desc.copy()
        desc.set_size(font_size * Pango.SCALE)
        desc.set_weight(Pango.Weight.BOLD)

        layout = Pango.Layout.new(pango_ctx)
        layout.set_font_description(desc)
        layout.set_width(int((width - self.PAD_LEFT - self.PAD_RIGHT) * Pango.SCALE))
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)

        text, attrs = self._spans_to_pango(block.spans, desc)
        layout.set_text(text, -1)
        if attrs:
            layout.set_attributes(attrs)

        point = Graphene.Point()
        point.init(self.PAD_LEFT, block._y_offset)
        snapshot.save()
        snapshot.translate(point)
        snapshot.append_layout(layout, self._fg_rgba)
        snapshot.restore()

        self._text_regions.append((layout, self.PAD_LEFT + self._draw_x_offset, block._y_offset))

        # Bottom border for h1 and h2
        if block.level <= 2:
            border_y = block._y_offset + block._height - 4
            border_rect = Graphene.Rect()
            border_rect.init(self.PAD_LEFT, border_y, width - self.PAD_LEFT - self.PAD_RIGHT, 1)
            snapshot.append_color(self._border_rgba, border_rect)

    def _draw_paragraph(self, snapshot, pango_ctx, block: ContentBlock, width: float):
        desc = self._scaled_font_desc()
        text_x = self.PAD_LEFT

        # Draw badge if present (e.g. status code on non-collapsible response)
        if block.badge_text and block.badge_color:
            badge_desc = self._scaled_font_desc()
            badge_font_size = max(int((self._base_font_size - 2) * self._zoom_level), 8)
            badge_desc.set_size(badge_font_size * Pango.SCALE)
            badge_desc.set_weight(Pango.Weight.BOLD)

            badge_layout = Pango.Layout.new(pango_ctx)
            badge_layout.set_font_description(badge_desc)
            badge_layout.set_text(block.badge_text, -1)
            _, badge_logical = badge_layout.get_pixel_extents()

            badge_pad_x = 6
            badge_pad_y = 2
            badge_w = badge_logical.width + badge_pad_x * 2
            badge_h = badge_logical.height + badge_pad_y * 2
            badge_y = block._y_offset + 1

            badge_rgba = hex_to_gdk_rgba(block.badge_color)
            badge_rect = Graphene.Rect()
            badge_rect.init(text_x, badge_y, badge_w, badge_h)
            snapshot.append_color(badge_rgba, badge_rect)

            white_rgba = hex_to_gdk_rgba("#ffffff")
            point = Graphene.Point()
            point.init(text_x + badge_pad_x, badge_y + badge_pad_y)
            snapshot.save()
            snapshot.translate(point)
            snapshot.append_layout(badge_layout, white_rgba)
            snapshot.restore()

            text_x += badge_w + 8

        layout = Pango.Layout.new(pango_ctx)
        layout.set_font_description(desc)
        layout.set_width(int((width - text_x - self.PAD_RIGHT) * Pango.SCALE))
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)
        layout.set_spacing(int(self.LINE_SPACING * Pango.SCALE))

        text, attrs = self._spans_to_pango(block.spans, desc)
        layout.set_text(text, -1)
        if attrs:
            layout.set_attributes(attrs)

        point = Graphene.Point()
        point.init(text_x, block._y_offset)
        snapshot.save()
        snapshot.translate(point)
        snapshot.append_layout(layout, self._fg_rgba)
        snapshot.restore()

        self._text_regions.append((layout, text_x + self._draw_x_offset, block._y_offset))

    def _draw_code_block(self, snapshot, pango_ctx, block: ContentBlock, width: float):
        # Background rect
        code_x = self.PAD_LEFT
        code_w = width - self.PAD_LEFT - self.PAD_RIGHT
        bg_rect = Graphene.Rect()
        bg_rect.init(code_x, block._y_offset, code_w, block._height)
        snapshot.append_color(self._code_bg_rgba, bg_rect)

        # Rounded corners via border
        border_rect = Graphene.Rect()
        border_rect.init(code_x, block._y_offset, code_w, 1)
        snapshot.append_color(self._border_rgba, border_rect)
        border_rect.init(code_x, block._y_offset + block._height - 1, code_w, 1)
        snapshot.append_color(self._border_rgba, border_rect)

        # Language label
        text_y = block._y_offset + self.CODE_PAD
        if block.language:
            lang_desc = self._mono_font_desc.copy()
            lang_size = max(int((self._base_font_size - 2) * self._zoom_level), 8)
            lang_desc.set_size(lang_size * Pango.SCALE)
            lang_layout = Pango.Layout.new(pango_ctx)
            lang_layout.set_font_description(lang_desc)
            lang_layout.set_text(block.language, -1)

            point = Graphene.Point()
            point.init(code_x + self.CODE_PAD, text_y)
            snapshot.save()
            snapshot.translate(point)
            snapshot.append_layout(lang_layout, self._dim_rgba)
            snapshot.restore()

            _, logical = lang_layout.get_pixel_extents()
            text_y += logical.height + 4

        # Code text
        desc = self._scaled_mono_desc()
        layout = Pango.Layout.new(pango_ctx)
        layout.set_font_description(desc)
        layout.set_width(int((code_w - self.CODE_PAD * 2) * Pango.SCALE))
        layout.set_wrap(Pango.WrapMode.CHAR)
        layout.set_text(block.code, -1)

        point = Graphene.Point()
        point.init(code_x + self.CODE_PAD, text_y)
        snapshot.save()
        snapshot.translate(point)
        snapshot.append_layout(layout, self._fg_rgba)
        snapshot.restore()

        self._text_regions.append((layout, code_x + self.CODE_PAD + self._draw_x_offset, text_y))

    @staticmethod
    def _table_col_widths(headers: list[str] | None, num_cols: int, avail_w: float) -> list[float]:
        """Compute per-column widths giving priority to Name and Description."""
        _WEIGHT = {"name": 3, "description": 5}
        if headers and len(headers) == num_cols:
            weights = [_WEIGHT.get(h.lower(), 1) for h in headers]
        else:
            weights = [1] * num_cols
        total = sum(weights)
        return [(w / total) * avail_w for w in weights]

    def _draw_table(self, snapshot, pango_ctx, block: ContentBlock, width: float):
        if not block.headers and not block.rows:
            return

        desc = self._scaled_font_desc()
        all_rows = [block.headers] + block.rows if block.headers else block.rows
        all_span_rows = [block.header_spans] + block.row_spans if block.header_spans else block.row_spans
        num_cols = max(len(row) for row in all_rows) if all_rows else 0
        if num_cols == 0:
            return

        avail_w = width - self.PAD_LEFT - self.PAD_RIGHT
        col_widths = self._table_col_widths(block.headers, num_cols, avail_w)
        row_heights = block._row_heights if block._row_heights else None
        if not row_heights:
            fallback_h = self._line_height * self._zoom_level + 8
            row_heights = [fallback_h] * len(all_rows)

        table_y = block._y_offset
        table_h = sum(row_heights[: len(all_rows)])
        border_r = Graphene.Rect()

        # Top border of entire table
        border_r.init(self.PAD_LEFT, table_y, avail_w, 1)
        snapshot.append_color(self._border_rgba, border_r)

        y = table_y
        for row_idx, row in enumerate(all_rows):
            row_h = row_heights[row_idx] if row_idx < len(row_heights) else (self._line_height * self._zoom_level + 8)
            x = self.PAD_LEFT
            span_row = all_span_rows[row_idx] if row_idx < len(all_span_rows) else None
            for col_idx in range(num_cols):
                cell_text = row[col_idx] if col_idx < len(row) else ""

                layout = Pango.Layout.new(pango_ctx)
                if row_idx == 0 and block.headers:
                    bold_desc = desc.copy()
                    bold_desc.set_weight(Pango.Weight.BOLD)
                    layout.set_font_description(bold_desc)
                else:
                    layout.set_font_description(desc)
                cw = col_widths[col_idx] if col_idx < len(col_widths) else col_widths[-1]
                layout.set_width(int((cw - 12) * Pango.SCALE))
                layout.set_wrap(Pango.WrapMode.WORD_CHAR)

                cell_spans = span_row[col_idx] if span_row and col_idx < len(span_row) else None
                if cell_spans:
                    text, attrs = self._spans_to_pango(cell_spans, desc)
                    layout.set_text(text, -1)
                    if attrs:
                        layout.set_attributes(attrs)
                else:
                    layout.set_text(cell_text, -1)

                point = Graphene.Point()
                point.init(x + 6, y + 4)
                snapshot.save()
                snapshot.translate(point)
                snapshot.append_layout(layout, self._fg_rgba)
                snapshot.restore()

                self._text_regions.append((layout, x + 6 + self._draw_x_offset, y + 4))

                x += cw

            # Horizontal border below every row
            border_r.init(self.PAD_LEFT, y + row_h - 1, avail_w, 1)
            snapshot.append_color(self._border_rgba, border_r)

            y += row_h

        # Vertical borders between columns (and left/right edges)
        col_x = self.PAD_LEFT
        for col_idx in range(num_cols + 1):
            border_r.init(col_x, table_y, 1, table_h)
            snapshot.append_color(self._border_rgba, border_r)
            if col_idx < num_cols:
                col_x += col_widths[col_idx] if col_idx < len(col_widths) else col_widths[-1]

    def _draw_list(self, snapshot, pango_ctx, block: ContentBlock, width: float):
        desc = self._scaled_font_desc()
        indent = 20
        y = block._y_offset

        for i, item_spans in enumerate(block.items):
            bullet = f"{i + 1}." if block.ordered else "▪"

            # Bullet
            bullet_layout = Pango.Layout.new(pango_ctx)
            bullet_layout.set_font_description(desc)
            bullet_layout.set_text(bullet, -1)

            point = Graphene.Point()
            point.init(self.PAD_LEFT, y)
            snapshot.save()
            snapshot.translate(point)
            snapshot.append_layout(bullet_layout, self._dim_rgba)
            snapshot.restore()

            # Item text
            layout = Pango.Layout.new(pango_ctx)
            layout.set_font_description(desc)
            layout.set_width(int((width - self.PAD_LEFT - self.PAD_RIGHT - indent) * Pango.SCALE))
            layout.set_wrap(Pango.WrapMode.WORD_CHAR)
            layout.set_spacing(int(self.LINE_SPACING * Pango.SCALE))

            text, attrs = self._spans_to_pango(item_spans, desc)
            layout.set_text(text, -1)
            if attrs:
                layout.set_attributes(attrs)

            point = Graphene.Point()
            point.init(self.PAD_LEFT + indent, y)
            snapshot.save()
            snapshot.translate(point)
            snapshot.append_layout(layout, self._fg_rgba)
            snapshot.restore()

            self._text_regions.append((layout, self.PAD_LEFT + indent + self._draw_x_offset, y))

            _, logical = layout.get_pixel_extents()
            y += max(logical.height, self._line_height) + 4

    def _draw_blockquote(self, snapshot, pango_ctx, block: ContentBlock, width: float):
        # Left accent bar
        bar_rect = Graphene.Rect()
        bar_rect.init(
            self.PAD_LEFT,
            block._y_offset,
            self.QUOTE_BAR_WIDTH,
            block._height,
        )
        snapshot.append_color(self._accent_rgba, bar_rect)

        # Render children with indent
        desc = self._scaled_font_desc()
        desc.set_style(Pango.Style.ITALIC)
        y = block._y_offset

        for child in block.children:
            text, attrs = self._spans_to_pango(child.spans, desc)
            if not text:
                y += self._line_height * 0.5
                continue

            layout = Pango.Layout.new(pango_ctx)
            layout.set_font_description(desc)
            layout.set_width(int((width - self.PAD_LEFT - self.PAD_RIGHT - self.QUOTE_INDENT) * Pango.SCALE))
            layout.set_wrap(Pango.WrapMode.WORD_CHAR)
            layout.set_text(text, -1)
            if attrs:
                layout.set_attributes(attrs)

            point = Graphene.Point()
            point.init(self.PAD_LEFT + self.QUOTE_INDENT, y)
            snapshot.save()
            snapshot.translate(point)
            snapshot.append_layout(layout, self._dim_rgba)
            snapshot.restore()

            self._text_regions.append((layout, self.PAD_LEFT + self.QUOTE_INDENT + self._draw_x_offset, y))

            _, logical = layout.get_pixel_extents()
            y += logical.height + self.BLOCK_SPACING

    def _draw_hr(self, snapshot, block: ContentBlock, width: float):
        hr_y = block._y_offset + block._height / 2
        hr_rect = Graphene.Rect()
        hr_rect.init(self.PAD_LEFT, hr_y, width - self.PAD_LEFT - self.PAD_RIGHT, 1)
        snapshot.append_color(self._border_rgba, hr_rect)

    def _draw_image(self, snapshot, pango_ctx, block: ContentBlock, width: float):
        texture = self._load_texture(block.image_url)
        content_width = width - self.PAD_LEFT - self.PAD_RIGHT

        # Apply percentage width constraint if specified (e.g. width="50%")
        effective_max_width = content_width
        if block.image_width_pct is not None and 0 < block.image_width_pct < 100:
            effective_max_width = content_width * (block.image_width_pct / 100.0)

        if texture is None:
            # Fallback: draw alt text placeholder
            desc = self._scaled_font_desc()
            desc.set_style(Pango.Style.ITALIC)
            layout = Pango.Layout.new(pango_ctx)
            layout.set_font_description(desc)
            layout.set_width(int(content_width * Pango.SCALE))
            layout.set_wrap(Pango.WrapMode.WORD_CHAR)
            label = f"[image: {block.image_alt}]" if block.image_alt else "[image]"
            layout.set_text(label, -1)

            point = Graphene.Point()
            point.init(self.PAD_LEFT, block._y_offset)
            snapshot.save()
            snapshot.translate(point)
            snapshot.append_layout(layout, self._dim_rgba)
            snapshot.restore()
            return

        img_w = texture.get_width()
        img_h = texture.get_height()
        display_w, display_h = self._fit_image_size(
            img_w,
            img_h,
            effective_max_width,
            explicit_w=block.image_width,
            explicit_h=block.image_height,
        )

        # Compute X offset for alignment
        img_x = float(self.PAD_LEFT)
        if block.image_align == "center" and display_w < content_width:
            img_x = self.PAD_LEFT + (content_width - display_w) / 2
        elif block.image_align == "right" and display_w < content_width:
            img_x = self.PAD_LEFT + content_width - display_w

        rect = Graphene.Rect()
        rect.init(img_x, block._y_offset, display_w, display_h)
        snapshot.append_texture(texture, rect)

        # Draw alt text caption below image if present
        if block.image_alt:
            desc = self._scaled_font_desc()
            cap_size = max(int((self._base_font_size - 2) * self._zoom_level), 8)
            desc.set_size(cap_size * Pango.SCALE)
            desc.set_style(Pango.Style.ITALIC)
            layout = Pango.Layout.new(pango_ctx)
            layout.set_font_description(desc)
            layout.set_width(int(content_width * Pango.SCALE))
            layout.set_wrap(Pango.WrapMode.WORD_CHAR)
            layout.set_text(block.image_alt, -1)

            # Center caption under image if image is centered
            cap_x = float(self.PAD_LEFT)
            if block.image_align == "center":
                _, cap_logical = layout.get_pixel_extents()
                cap_x = self.PAD_LEFT + (content_width - cap_logical.width) / 2

            point = Graphene.Point()
            point.init(cap_x, block._y_offset + display_h + 4)
            snapshot.save()
            snapshot.translate(point)
            snapshot.append_layout(layout, self._dim_rgba)
            snapshot.restore()

    def _draw_image_row(self, snapshot, pango_ctx, block: ContentBlock, width: float):
        """Draw multiple images side-by-side in a single row.

        Each image gets an equal share of the available content width (minus
        gaps). Images are scaled proportionally to fit their slot and
        vertically centred within the row height.
        """
        _IMAGE_ROW_GAP = 8
        content_width = width - self.PAD_LEFT - self.PAD_RIGHT
        images = block.images
        n = len(images)
        if n == 0:
            return

        total_gap = _IMAGE_ROW_GAP * (n - 1)
        slot_w = max((content_width - total_gap) / n, 20)

        x = float(self.PAD_LEFT)
        row_h = block._height

        for img in images:
            texture = self._load_texture(img["url"])
            if texture is None:
                # Fallback: draw placeholder text
                desc = self._scaled_font_desc()
                desc.set_style(Pango.Style.ITALIC)
                layout = Pango.Layout.new(pango_ctx)
                layout.set_font_description(desc)
                layout.set_width(int(slot_w * Pango.SCALE))
                layout.set_wrap(Pango.WrapMode.WORD_CHAR)
                label = f"[image: {img.get('alt', '')}]" if img.get("alt") else "[image]"
                layout.set_text(label, -1)

                point = Graphene.Point()
                point.init(x, block._y_offset)
                snapshot.save()
                snapshot.translate(point)
                snapshot.append_layout(layout, self._dim_rgba)
                snapshot.restore()

                x += slot_w + _IMAGE_ROW_GAP
                continue

            iw = texture.get_width()
            ih = texture.get_height()
            dw, dh = self._fit_image_size(
                iw,
                ih,
                slot_w,
                explicit_w=img.get("width"),
                explicit_h=img.get("height"),
            )

            # Vertically centre within the row
            y_off = block._y_offset + max(0, (row_h - dh) / 2)

            rect = Graphene.Rect()
            rect.init(x, y_off, dw, dh)
            snapshot.append_texture(texture, rect)

            x += slot_w + _IMAGE_ROW_GAP

    def _draw_collapsible(
        self, snapshot, pango_ctx, block: ContentBlock, width: float, scroll_y: float = 0.0, visible_height: float = 1e9
    ):
        """Draw a collapsible section: optional badge + chevron + header, then children if expanded."""
        chevron = "▶ " if block.collapsed else "▼ "
        desc = self._scaled_font_desc()
        desc.set_weight(Pango.Weight.BOLD)

        avail_w = width - self.PAD_LEFT - self.PAD_RIGHT
        text_x = self.PAD_LEFT
        badge_w = 0.0

        # Draw colored left border only when expanded (starts below header)
        if block.border_color and not block.collapsed:
            header_h = getattr(block, "_header_height", 0)
            bar_y = block._y_offset + header_h
            bar_h = block._height - header_h
            if bar_h > 0:
                border_rgba = hex_to_gdk_rgba(block.border_color)
                border_rect = Graphene.Rect()
                border_rect.init(self.PAD_LEFT, bar_y, 3, bar_h)
                snapshot.append_color(border_rgba, border_rect)

        # Draw badge (e.g. HTTP method) if present
        if block.badge_text and block.badge_color:
            badge_desc = self._scaled_font_desc()
            badge_font_size = max(int((self._base_font_size - 2) * self._zoom_level), 8)
            badge_desc.set_size(badge_font_size * Pango.SCALE)
            badge_desc.set_weight(Pango.Weight.BOLD)

            badge_layout = Pango.Layout.new(pango_ctx)
            badge_layout.set_font_description(badge_desc)
            badge_layout.set_text(block.badge_text, -1)
            _, badge_logical = badge_layout.get_pixel_extents()

            badge_pad_x = 6
            badge_pad_y = 2
            badge_w = badge_logical.width + badge_pad_x * 2
            badge_h = badge_logical.height + badge_pad_y * 2
            badge_y = block._y_offset + 1

            # Badge background
            badge_rgba = hex_to_gdk_rgba(block.badge_color)
            badge_rect = Graphene.Rect()
            badge_rect.init(text_x, badge_y, badge_w, badge_h)
            snapshot.append_color(badge_rgba, badge_rect)

            # Badge text (white)
            white_rgba = hex_to_gdk_rgba("#ffffff")
            point = Graphene.Point()
            point.init(text_x + badge_pad_x, badge_y + badge_pad_y)
            snapshot.save()
            snapshot.translate(point)
            snapshot.append_layout(badge_layout, white_rgba)
            snapshot.restore()

            text_x += badge_w + 8

        # Header text with chevron
        layout = Pango.Layout.new(pango_ctx)
        layout.set_font_description(desc)
        layout.set_width(int((avail_w - badge_w - 8) * Pango.SCALE))
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)

        text, attrs = self._spans_to_pango(block.spans, desc)
        layout.set_text(chevron + text, -1)

        # Apply attrs shifted by chevron length
        if attrs and text:
            shifted = Pango.AttrList()
            chevron_bytes = len(chevron.encode("utf-8"))
            it = attrs.get_iterator()
            while True:
                a_range = it.get_attrs()
                for a in a_range:
                    a.start_index += chevron_bytes
                    a.end_index += chevron_bytes
                    shifted.insert(a)
                if not it.next():
                    break
            # Bold the chevron
            chev_attr = Pango.attr_weight_new(Pango.Weight.BOLD)
            chev_attr.start_index = 0
            chev_attr.end_index = chevron_bytes
            shifted.insert(chev_attr)
            layout.set_attributes(shifted)

        point = Graphene.Point()
        point.init(text_x, block._y_offset)
        snapshot.save()
        snapshot.translate(point)
        snapshot.append_layout(layout, self._fg_rgba)
        snapshot.restore()

        self._text_regions.append((layout, text_x + self._draw_x_offset, block._y_offset))

        # Draw children if expanded
        if not block.collapsed and block.children:
            # Indent children past the vertical border bar
            if block.border_color:
                shift = Graphene.Point()
                shift.init(10, 0)
                snapshot.save()
                snapshot.translate(shift)
                self._draw_x_offset += 10
            for child in block.children:
                self._draw_block(
                    snapshot, pango_ctx, child, width - 10 if block.border_color else width, scroll_y, visible_height
                )
            if block.border_color:
                snapshot.restore()
                self._draw_x_offset -= 10
        # Draw inline code content for collapsible code blocks with no children
        elif not block.collapsed and block.code:
            saved_offset = block._y_offset
            saved_height = block._height
            block._y_offset = getattr(block, "_code_y_offset", saved_offset + block._header_height + self.BLOCK_SPACING)
            block._height = getattr(block, "_code_height", saved_height - block._header_height)
            self._draw_code_block(snapshot, pango_ctx, block, width)
            block._y_offset = saved_offset
            block._height = saved_height

    def _load_texture(self, url: str) -> Gdk.Texture | None:
        """Load an image URL into a Gdk.Texture, with caching.

        For remote URLs (http/https), checks a local download cache. If not
        cached, starts an async download and returns None (the canvas will
        re-render when the download completes).
        """
        if url in self._image_cache:
            return self._image_cache[url]

        resolved = self._resolve_image_path(url)
        if resolved is None:
            # Might be a remote URL — kick off async fetch
            if url.startswith(("http://", "https://")) and url not in self._fetching_urls:
                self._fetch_remote_image(url)
            return None

        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(resolved)
            texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            self._image_cache[url] = texture
            return texture
        except Exception:
            self._image_cache[url] = None
            return None

    def _resolve_image_path(self, url: str) -> str | None:
        """Resolve an image URL to a local file path."""
        # Already an absolute path
        if os.path.isabs(url) and os.path.isfile(url):
            return url

        # Remote URL — check local download cache
        if url.startswith(("http://", "https://")):
            cache_path = self._get_remote_cache_path(url)
            if cache_path and os.path.isfile(cache_path):
                return cache_path
            return None

        # Relative path — resolve from base_path
        if self._base_path and not url.startswith(("http://", "https://", "data:")):
            candidate = os.path.join(self._base_path, url)
            candidate = os.path.normpath(candidate)
            if os.path.isfile(candidate):
                return candidate

        return None

    def _get_remote_cache_path(self, url: str) -> str | None:
        """Get the local cache file path for a remote URL.

        For SVG URLs the downloaded file is converted to PNG, so this method
        returns the ``.png`` path when the URL extension is ``.svg``.
        """
        url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
        # Derive extension from URL path (strip query params)
        from urllib.parse import urlparse

        parsed = urlparse(url)
        path = parsed.path
        ext = os.path.splitext(path)[1].lower()
        if ext not in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico"):
            ext = ".png"  # default fallback
        # SVG files are converted to PNG during download — use .png extension
        if ext == ".svg":
            ext = ".png"
        return os.path.join(self._remote_cache_dir, f"{url_hash}{ext}")

    def _fetch_remote_image(self, url: str):
        """Download a remote image in a background thread, then refresh."""
        self._fetching_urls.add(url)
        cache_path = self._get_remote_cache_path(url)
        if not cache_path:
            return

        def _download():
            import urllib.request

            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Zen-IDE/1.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = resp.read()
                    content_type = resp.headers.get("Content-Type", "")

                    # SVG images need conversion to PNG for GdkPixbuf
                    # Check URL path (without query params) for .svg extension
                    from urllib.parse import urlparse as _urlparse

                    _url_path = _urlparse(url).path
                    if "svg" in content_type or _url_path.endswith(".svg"):
                        png_path = self._convert_svg_to_png(data, cache_path)
                        if png_path:
                            GLib.idle_add(self._on_remote_image_ready, url, png_path)
                        else:
                            GLib.idle_add(self._on_remote_image_failed, url)
                    else:
                        with open(cache_path, "wb") as f:
                            f.write(data)
                        GLib.idle_add(self._on_remote_image_ready, url, cache_path)
            except Exception:
                GLib.idle_add(self._on_remote_image_failed, url)

        thread = threading.Thread(target=_download, daemon=True)
        thread.start()

    def _convert_svg_to_png(self, svg_data: bytes, base_cache_path: str) -> str | None:
        """Convert SVG data to PNG using GdkPixbuf (requires librsvg).

        Falls back to writing raw SVG and hoping GdkPixbuf can handle it.
        Returns the path to the resulting image file, or None on failure.
        """
        # Try loading SVG directly via GdkPixbuf (works if librsvg is installed)
        png_path = os.path.splitext(base_cache_path)[0] + ".png"
        try:
            loader = GdkPixbuf.PixbufLoader.new()
            loader.write(svg_data)
            loader.close()
            pixbuf = loader.get_pixbuf()
            if pixbuf:
                pixbuf.savev(png_path, "png", [], [])
                return png_path
        except Exception:
            pass

        # Fallback: save raw SVG and hope GdkPixbuf can load it
        try:
            with open(base_cache_path, "wb") as f:
                f.write(svg_data)
            # Test if GdkPixbuf can load it
            GdkPixbuf.Pixbuf.new_from_file(base_cache_path)
            return base_cache_path
        except Exception:
            pass

        return None

    def _on_remote_image_ready(self, url: str, local_path: str):
        """Called on main thread when a remote image download completes."""
        self._fetching_urls.discard(url)
        # Clear the cache entry so _load_texture will re-resolve it
        self._image_cache.pop(url, None)
        # Force re-layout and redraw
        self._needs_layout = True
        self._schedule_redraw()
        return False

    def _on_remote_image_failed(self, url: str):
        """Called on main thread when a remote image download fails."""
        self._fetching_urls.discard(url)
        # Cache as None to avoid re-fetching
        self._image_cache[url] = None
        return False

    def _fit_image_size(
        self,
        img_w: int,
        img_h: int,
        max_width: float,
        explicit_w: int | None = None,
        explicit_h: int | None = None,
    ) -> tuple[float, float]:
        """Scale image to fit within max_width, maintaining aspect ratio.

        If explicit_w / explicit_h are given (from HTML attributes), use them
        as the *desired* size but still clamp to max_width and _IMAGE_MAX_HEIGHT.
        """
        if img_w <= 0 or img_h <= 0:
            return max_width, self._IMAGE_MAX_HEIGHT

        # Start from explicit or natural dimensions
        if explicit_w and explicit_h:
            display_w = float(explicit_w)
            display_h = float(explicit_h)
        elif explicit_w:
            aspect = img_w / img_h
            display_w = float(explicit_w)
            display_h = display_w / aspect
        elif explicit_h:
            aspect = img_w / img_h
            display_h = float(explicit_h)
            display_w = display_h * aspect
        else:
            display_w = float(img_w)
            display_h = float(img_h)

        # Clamp to available width
        if display_w > max_width:
            aspect = display_w / display_h
            display_w = max_width
            display_h = display_w / aspect

        # Clamp to max height
        if display_h > self._IMAGE_MAX_HEIGHT:
            aspect = display_w / display_h
            display_h = self._IMAGE_MAX_HEIGHT
            display_w = display_h * aspect

        return display_w, display_h

    # ------------------------------------------------------------------ #
    #  Pango helpers                                                       #
    # ------------------------------------------------------------------ #

    def _spans_to_pango(self, spans: list[InlineSpan], base_desc: Pango.FontDescription):
        """Convert InlineSpans to a Pango text string + AttrList."""
        if not spans:
            return "", None

        text_parts = []
        attrs = Pango.AttrList()

        for span in spans:
            text = _add_emoji_spacing(span.text)
            byte_start = len("".join(text_parts).encode("utf-8"))
            text_parts.append(text)
            byte_end = len("".join(text_parts).encode("utf-8"))

            if span.bold:
                attr = Pango.attr_weight_new(Pango.Weight.BOLD)
                attr.start_index = byte_start
                attr.end_index = byte_end
                attrs.insert(attr)

            if span.italic:
                attr = Pango.attr_style_new(Pango.Style.ITALIC)
                attr.start_index = byte_start
                attr.end_index = byte_end
                attrs.insert(attr)

            if span.code:
                from fonts import get_font_settings as _get_font_settings

                _editor = _get_font_settings("editor")
                attr = Pango.attr_family_new(_editor["family"])
                attr.start_index = byte_start
                attr.end_index = byte_end
                attrs.insert(attr)
                # Subtle background via foreground color change
                attr = Pango.attr_foreground_new(
                    int(self._accent_rgba.red * 65535),
                    int(self._accent_rgba.green * 65535),
                    int(self._accent_rgba.blue * 65535),
                )
                attr.start_index = byte_start
                attr.end_index = byte_end
                attrs.insert(attr)

            if span.strikethrough:
                attr = Pango.attr_strikethrough_new(True)
                attr.start_index = byte_start
                attr.end_index = byte_end
                attrs.insert(attr)

            if span.link_url:
                attr = Pango.attr_underline_new(Pango.Underline.SINGLE)
                attr.start_index = byte_start
                attr.end_index = byte_end
                attrs.insert(attr)
                attr = Pango.attr_foreground_new(
                    int(self._accent_rgba.red * 65535),
                    int(self._accent_rgba.green * 65535),
                    int(self._accent_rgba.blue * 65535),
                )
                attr.start_index = byte_start
                attr.end_index = byte_end
                attrs.insert(attr)

        full_text = "".join(text_parts)
        return (full_text, attrs) if full_text else (full_text, None)

    def _scaled_font_desc(self) -> Pango.FontDescription:
        """Return the base font desc scaled by zoom level."""
        desc = self._font_desc.copy()
        desc.set_size(int(self._base_font_size * self._zoom_level * Pango.SCALE))
        return desc

    def _scaled_mono_desc(self) -> Pango.FontDescription:
        """Return monospace font desc scaled by zoom level."""
        desc = self._mono_font_desc.copy()
        size = max(int((self._base_font_size - 1) * self._zoom_level), 8)
        desc.set_size(size * Pango.SCALE)
        return desc

    # ------------------------------------------------------------------ #
    #  Layout (block measurement)                                          #
    # ------------------------------------------------------------------ #

    def _layout_blocks(self, content_width: float):
        """Measure all blocks and compute cumulative Y offsets."""
        self._layout_width = content_width
        pango_ctx = self.get_pango_context()
        if pango_ctx is None:
            return

        y = float(self.PAD_TOP)
        for i, block in enumerate(self._blocks):
            # Extra top margin before headings (skip for the first block)
            if block.kind == "heading" and i > 0:
                extra_top = self.HEADING_MARGIN_TOP.get(block.level, 14)
                y += extra_top

            block._y_offset = y
            h = self._measure_block(pango_ctx, block, content_width)
            block._height = h
            y += h + self.BLOCK_SPACING

            # Extra bottom margin after headings
            if block.kind == "heading":
                y += self.HEADING_MARGIN_BOTTOM.get(block.level, 4)

        # Set total content height
        total = y + self.PAD_TOP
        self.set_size_request(-1, max(int(total), 100))
        self._needs_layout = False

    def _measure_block(self, pango_ctx, block: ContentBlock, content_width: float) -> float:
        """Return the pixel height of a single block."""
        if block.collapsible:
            return self._measure_collapsible(pango_ctx, block, content_width)
        elif block.kind == "heading":
            return self._measure_heading(pango_ctx, block, content_width)
        elif block.kind == "paragraph":
            return self._measure_paragraph(pango_ctx, block, content_width)
        elif block.kind == "code":
            return self._measure_code(pango_ctx, block, content_width)
        elif block.kind == "table":
            return self._measure_table(pango_ctx, block, content_width)
        elif block.kind == "list":
            return self._measure_list(pango_ctx, block, content_width)
        elif block.kind == "blockquote":
            return self._measure_blockquote(pango_ctx, block, content_width)
        elif block.kind == "hr":
            return 16
        elif block.kind == "image":
            return self._measure_image(pango_ctx, block, content_width)
        elif block.kind == "image_row":
            return self._measure_image_row(pango_ctx, block, content_width)
        return self._line_height

    def _measure_heading(self, pango_ctx, block: ContentBlock, content_width: float) -> float:
        scale = self.HEADING_SCALES.get(block.level, 1.0)
        font_size = int(self._base_font_size * scale * self._zoom_level)

        desc = self._font_desc.copy()
        desc.set_size(font_size * Pango.SCALE)
        desc.set_weight(Pango.Weight.BOLD)

        layout = Pango.Layout.new(pango_ctx)
        layout.set_font_description(desc)
        layout.set_width(int(content_width * Pango.SCALE))
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)

        text, attrs = self._spans_to_pango(block.spans, desc)
        layout.set_text(text, -1)
        if attrs:
            layout.set_attributes(attrs)

        _, logical = layout.get_pixel_extents()
        extra = 8 if block.level <= 2 else 4  # bottom border space for h1/h2
        return logical.height + extra

    def _measure_collapsible(self, pango_ctx, block: ContentBlock, content_width: float) -> float:
        """Measure a collapsible block: header + children if expanded."""
        desc = self._scaled_font_desc()
        desc.set_weight(Pango.Weight.BOLD)

        # Account for badge width if present
        badge_w = 0.0
        if block.badge_text and block.badge_color:
            badge_desc = self._scaled_font_desc()
            badge_font_size = max(int((self._base_font_size - 2) * self._zoom_level), 8)
            badge_desc.set_size(badge_font_size * Pango.SCALE)
            badge_desc.set_weight(Pango.Weight.BOLD)
            badge_layout = Pango.Layout.new(pango_ctx)
            badge_layout.set_font_description(badge_desc)
            badge_layout.set_text(block.badge_text, -1)
            _, badge_logical = badge_layout.get_pixel_extents()
            badge_w = badge_logical.width + 12 + 8  # pad_x*2 + gap

        layout = Pango.Layout.new(pango_ctx)
        layout.set_font_description(desc)
        layout.set_width(int((content_width - badge_w) * Pango.SCALE))
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)

        chevron = "▶ " if block.collapsed else "▼ "
        text, _ = self._spans_to_pango(block.spans, desc)
        layout.set_text(chevron + text, -1)

        _, logical = layout.get_pixel_extents()
        header_h = logical.height + 4
        # If badge is taller, use badge height
        if block.badge_text and block.badge_color:
            badge_h = max(int((self._base_font_size - 2) * self._zoom_level), 8) + 4 + 2
            header_h = max(header_h, badge_h + 4)
        block._header_height = header_h

        if block.collapsed:
            return header_h

        # Collapsible code block with no children – content lives in block.code
        if not block.children and block.code:
            code_y = block._y_offset + header_h + self.BLOCK_SPACING
            code_h = self._measure_code(pango_ctx, block, content_width)
            block._code_y_offset = code_y
            block._code_height = code_h
            return header_h + self.BLOCK_SPACING + code_h + self.BLOCK_SPACING

        if not block.children:
            return header_h

        # Layout children with absolute y positions
        child_content_w = content_width - 10 if block.border_color else content_width
        child_y = block._y_offset + header_h + self.BLOCK_SPACING
        for i, child in enumerate(block.children):
            if child.kind == "heading" and i > 0:
                extra_top = self.HEADING_MARGIN_TOP.get(child.level, 14)
                child_y += extra_top
            child._y_offset = child_y
            child_h = self._measure_block(pango_ctx, child, child_content_w)
            child._height = child_h
            child_y += child_h + self.BLOCK_SPACING

            # Extra bottom margin after headings
            if child.kind == "heading":
                child_y += self.HEADING_MARGIN_BOTTOM.get(child.level, 4)

        return child_y - block._y_offset

    def _measure_paragraph(self, pango_ctx, block: ContentBlock, content_width: float) -> float:
        desc = self._scaled_font_desc()

        badge_w = 0.0
        if block.badge_text and block.badge_color:
            badge_desc = self._scaled_font_desc()
            badge_font_size = max(int((self._base_font_size - 2) * self._zoom_level), 8)
            badge_desc.set_size(badge_font_size * Pango.SCALE)
            badge_desc.set_weight(Pango.Weight.BOLD)
            badge_layout = Pango.Layout.new(pango_ctx)
            badge_layout.set_font_description(badge_desc)
            badge_layout.set_text(block.badge_text, -1)
            _, badge_logical = badge_layout.get_pixel_extents()
            badge_w = badge_logical.width + 12 + 8

        layout = Pango.Layout.new(pango_ctx)
        layout.set_font_description(desc)
        layout.set_width(int((content_width - badge_w) * Pango.SCALE))
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)
        layout.set_spacing(int(self.LINE_SPACING * Pango.SCALE))

        text, attrs = self._spans_to_pango(block.spans, desc)
        layout.set_text(text, -1)
        if attrs:
            layout.set_attributes(attrs)

        _, logical = layout.get_pixel_extents()
        h = logical.height
        if block.badge_text and block.badge_color:
            badge_h = max(int((self._base_font_size - 2) * self._zoom_level), 8) + 4 + 2
            h = max(h, badge_h)
        return h

    def _measure_code(self, pango_ctx, block: ContentBlock, content_width: float) -> float:
        desc = self._scaled_mono_desc()
        layout = Pango.Layout.new(pango_ctx)
        layout.set_font_description(desc)
        layout.set_width(int((content_width - self.CODE_PAD * 2) * Pango.SCALE))
        layout.set_wrap(Pango.WrapMode.CHAR)
        layout.set_text(block.code, -1)

        _, logical = layout.get_pixel_extents()
        h = logical.height + self.CODE_PAD * 2

        # Add language label height
        if block.language:
            lang_desc = self._mono_font_desc.copy()
            lang_size = max(int((self._base_font_size - 2) * self._zoom_level), 8)
            lang_desc.set_size(lang_size * Pango.SCALE)
            lang_layout = Pango.Layout.new(pango_ctx)
            lang_layout.set_font_description(lang_desc)
            lang_layout.set_text(block.language, -1)
            _, lang_logical = lang_layout.get_pixel_extents()
            h += lang_logical.height + 4

        return h

    def _measure_table(self, pango_ctx, block: ContentBlock, content_width: float) -> float:
        all_rows = [block.headers] + block.rows if block.headers else block.rows
        all_span_rows = [block.header_spans] + block.row_spans if block.header_spans else block.row_spans
        if not all_rows:
            return self._line_height
        num_cols = max(len(row) for row in all_rows) if all_rows else 0
        if num_cols == 0:
            return self._line_height
        col_widths = self._table_col_widths(block.headers, num_cols, content_width)
        desc = self._scaled_font_desc()
        # Measure each row's height based on content
        row_heights = []
        for row_idx, row in enumerate(all_rows):
            max_h = self._line_height * self._zoom_level + 8
            span_row = all_span_rows[row_idx] if row_idx < len(all_span_rows) else None
            for col_idx in range(num_cols):
                cell_text = row[col_idx] if col_idx < len(row) else ""
                if cell_text:
                    cw = col_widths[col_idx] if col_idx < len(col_widths) else col_widths[-1]
                    layout = Pango.Layout.new(pango_ctx)
                    layout.set_font_description(desc)
                    layout.set_width(int((cw - 12) * Pango.SCALE))
                    layout.set_wrap(Pango.WrapMode.WORD_CHAR)

                    cell_spans = span_row[col_idx] if span_row and col_idx < len(span_row) else None
                    if cell_spans:
                        text, attrs = self._spans_to_pango(cell_spans, desc)
                        layout.set_text(text, -1)
                        if attrs:
                            layout.set_attributes(attrs)
                    else:
                        layout.set_text(cell_text, -1)

                    _, logical = layout.get_pixel_extents()
                    max_h = max(max_h, logical.height + 8)
            row_heights.append(max_h)
        block._row_heights = row_heights
        return sum(row_heights)

    def _measure_list(self, pango_ctx, block: ContentBlock, content_width: float) -> float:
        desc = self._scaled_font_desc()
        indent = 20
        total = 0.0

        for item_spans in block.items:
            layout = Pango.Layout.new(pango_ctx)
            layout.set_font_description(desc)
            layout.set_width(int((content_width - indent) * Pango.SCALE))
            layout.set_wrap(Pango.WrapMode.WORD_CHAR)
            layout.set_spacing(int(self.LINE_SPACING * Pango.SCALE))

            text, attrs = self._spans_to_pango(item_spans, desc)
            layout.set_text(text, -1)
            if attrs:
                layout.set_attributes(attrs)

            _, logical = layout.get_pixel_extents()
            total += max(logical.height, self._line_height) + 4

        return total

    def _measure_blockquote(self, pango_ctx, block: ContentBlock, content_width: float) -> float:
        desc = self._scaled_font_desc()
        desc.set_style(Pango.Style.ITALIC)
        total = 0.0

        for child in block.children:
            text, attrs = self._spans_to_pango(child.spans, desc)
            if not text:
                total += self._line_height * 0.5
                continue

            layout = Pango.Layout.new(pango_ctx)
            layout.set_font_description(desc)
            layout.set_width(int((content_width - self.QUOTE_INDENT) * Pango.SCALE))
            layout.set_wrap(Pango.WrapMode.WORD_CHAR)
            layout.set_text(text, -1)
            if attrs:
                layout.set_attributes(attrs)

            _, logical = layout.get_pixel_extents()
            total += logical.height + self.BLOCK_SPACING

        return max(total, self._line_height)

    def _measure_image(self, pango_ctx, block: ContentBlock, content_width: float) -> float:
        texture = self._load_texture(block.image_url)
        if texture is None:
            # Fallback placeholder height
            return self._line_height + 4

        # Apply percentage width constraint if specified (e.g. width="50%")
        effective_max_width = content_width
        if block.image_width_pct is not None and 0 < block.image_width_pct < 100:
            effective_max_width = content_width * (block.image_width_pct / 100.0)

        img_w = texture.get_width()
        img_h = texture.get_height()
        _, display_h = self._fit_image_size(
            img_w,
            img_h,
            effective_max_width,
            explicit_w=block.image_width,
            explicit_h=block.image_height,
        )

        # Add space for caption if alt text present
        caption_h = 0.0
        if block.image_alt:
            desc = self._scaled_font_desc()
            cap_size = max(int((self._base_font_size - 2) * self._zoom_level), 8)
            desc.set_size(cap_size * Pango.SCALE)
            layout = Pango.Layout.new(pango_ctx)
            layout.set_font_description(desc)
            layout.set_width(int(content_width * Pango.SCALE))
            layout.set_wrap(Pango.WrapMode.WORD_CHAR)
            layout.set_text(block.image_alt, -1)
            _, logical = layout.get_pixel_extents()
            caption_h = logical.height + 4

        return display_h + caption_h

    def _measure_image_row(self, pango_ctx, block: ContentBlock, content_width: float) -> float:
        """Measure a row of images laid out side-by-side.

        Images share the available width equally (minus gaps). Each image is
        scaled proportionally to fit its column, and the row height is the
        tallest image. Falls back to a vertical stack if any image texture is
        missing.
        """
        _IMAGE_ROW_GAP = 8  # horizontal gap between images

        images = block.images
        n = len(images)
        if n == 0:
            return self._line_height

        # Load all textures; if any fail we fall back to placeholder height
        textures = [self._load_texture(img["url"]) for img in images]

        max_h = 0.0
        # Compute the slot width for each image
        total_gap = _IMAGE_ROW_GAP * (n - 1)
        slot_w = max((content_width - total_gap) / n, 20)

        for i, (img, tex) in enumerate(zip(images, textures)):
            if tex is None:
                max_h = max(max_h, self._line_height + 4)
                continue
            iw = tex.get_width()
            ih = tex.get_height()
            _, dh = self._fit_image_size(iw, ih, slot_w, explicit_w=img.get("width"), explicit_h=img.get("height"))
            max_h = max(max_h, dh)

        return max_h

    # ------------------------------------------------------------------ #
    #  Text extraction                                                     #
    # ------------------------------------------------------------------ #

    def _block_to_text(self, block: ContentBlock) -> str:
        if block.kind in ("heading", "paragraph"):
            return "".join(s.text for s in block.spans)
        elif block.kind == "code":
            return block.code
        elif block.kind == "table":
            lines = []
            if block.headers:
                lines.append(" | ".join(block.headers))
            for row in block.rows:
                lines.append(" | ".join(row))
            return "\n".join(lines)
        elif block.kind == "list":
            parts = []
            for i, item in enumerate(block.items):
                prefix = f"{i + 1}." if block.ordered else "▪"
                text = "".join(s.text for s in item)
                parts.append(f"{prefix} {text}")
            return "\n".join(parts)
        elif block.kind == "blockquote":
            return "\n".join("> " + "".join(s.text for s in c.spans) for c in block.children)
        elif block.kind == "hr":
            return "---"
        elif block.kind == "image":
            return f"![{block.image_alt}]({block.image_url})"
        elif block.kind == "image_row":
            return " ".join(f"![{img.get('alt', '')}]({img['url']})" for img in block.images)
        return ""

    # ------------------------------------------------------------------ #
    #  Event controllers                                                   #
    # ------------------------------------------------------------------ #

    def _setup_event_controllers(self):
        """Setup mouse and keyboard events for text selection."""
        click = Gtk.GestureClick()
        click.set_button(1)
        click.connect("pressed", self._on_click_pressed)
        self.add_controller(click)

        drag = Gtk.GestureDrag()
        drag.set_button(1)
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key)

    def _on_click_pressed(self, gesture, n_press, x, y):
        """Handle double/triple click for word/line selection."""
        if n_press == 2:
            self._multi_click_mode = 2
            self._select_word_at(x, y)
        elif n_press >= 3:
            self._multi_click_mode = 3
            self._select_line_at(x, y)
        else:
            self._multi_click_mode = 0

    def _on_drag_begin(self, gesture, start_x, start_y):
        """Set selection anchor on mouse press."""
        self.grab_focus()
        self._drag_start_x = start_x
        self._drag_start_y = start_y
        if self._multi_click_mode:
            return
        self._clear_selection()
        pos = self._hit_test(start_x, start_y)
        if pos:
            self._sel_anchor = pos

    def _on_drag_update(self, gesture, offset_x, offset_y):
        """Extend selection during mouse drag."""
        if self._multi_click_mode:
            return
        if not self._sel_anchor:
            return
        x = self._drag_start_x + offset_x
        y = self._drag_start_y + offset_y
        pos = self._hit_test(x, y)
        if pos:
            self._sel_cursor = pos
            self._has_selection = self._sel_cursor != self._sel_anchor
            self._schedule_redraw()

    def _on_drag_end(self, gesture, offset_x, offset_y):
        """Finalize selection or handle click on drag end."""
        if self._multi_click_mode:
            self._multi_click_mode = 0
            return
        if abs(offset_x) < 3 and abs(offset_y) < 3:
            # Short click — handle collapsible toggle or link
            self._clear_selection()
            self._schedule_redraw()

            abs_y = self._drag_start_y
            toggled = self._find_and_toggle_collapsible(self._blocks, abs_y)
            if toggled:
                self._needs_layout = True
                self._schedule_redraw()
                return

            for block in self._blocks:
                if block._y_offset <= abs_y < block._y_offset + block._height:
                    if block.kind in ("heading", "paragraph"):
                        for span in block.spans:
                            if span.link_url:
                                try:
                                    Gtk.show_uri(None, span.link_url, Gdk.CURRENT_TIME)
                                except Exception:
                                    pass
                                return
                    break

    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Handle Cmd+C (copy) and Cmd+A (select all)."""
        mod = state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.META_MASK)
        if mod and keyval == Gdk.KEY_c:
            self.copy_clipboard()
            return True
        if mod and keyval == Gdk.KEY_a:
            self._select_all()
            return True
        if keyval == Gdk.KEY_Escape:
            self._clear_selection()
            self._schedule_redraw()
            return True
        return False

    def _find_and_toggle_collapsible(self, blocks: list[ContentBlock], abs_y: float) -> bool:
        """Recursively find and toggle a collapsible block header at abs_y."""
        for block in blocks:
            if block._y_offset > abs_y:
                break
            if block._y_offset + block._height < abs_y:
                continue
            if block.collapsible:
                header_bottom = block._y_offset + block._header_height
                if block._y_offset <= abs_y < header_bottom:
                    block.collapsed = not block.collapsed
                    return True
                # If expanded, check children
                if not block.collapsed and block.children:
                    if self._find_and_toggle_collapsible(block.children, abs_y):
                        return True
        return False

    # ------------------------------------------------------------------ #
    #  Text selection                                                      #
    # ------------------------------------------------------------------ #

    def _hit_test(self, x, y):
        """Find the text region and byte position at canvas coordinates (x, y)."""
        for i, (layout, lx, ly) in enumerate(self._text_regions):
            _, logical = layout.get_pixel_extents()
            if ly <= y <= ly + logical.height:
                rel_x = int((x - lx) * Pango.SCALE)
                rel_y = int((y - ly) * Pango.SCALE)
                inside, index, trailing = layout.xy_to_index(rel_x, rel_y)
                if inside or (lx <= x <= lx + logical.width):
                    byte_idx = index
                    if trailing:
                        text_bytes = layout.get_text().encode("utf-8")
                        byte_idx = index + 1
                        while byte_idx < len(text_bytes) and (text_bytes[byte_idx] & 0xC0) == 0x80:
                            byte_idx += 1
                    return (i, byte_idx)
        # No exact hit — find closest region by y
        if self._text_regions:
            best_i = 0
            best_dist = float("inf")
            for i, (layout, lx, ly) in enumerate(self._text_regions):
                _, logical = layout.get_pixel_extents()
                mid_y = ly + logical.height / 2
                dist = abs(y - mid_y)
                if dist < best_dist:
                    best_dist = dist
                    best_i = i
            _, lx, ly = self._text_regions[best_i]
            text = self._text_regions[best_i][0].get_text()
            n_bytes = len(text.encode("utf-8"))
            return (best_i, 0 if y < ly else n_bytes)
        return None

    def _draw_selection_overlay(self, snapshot):
        """Draw semi-transparent highlight rectangles over selected text."""
        if not self._sel_anchor or not self._sel_cursor:
            return

        start, end = self._sel_anchor, self._sel_cursor
        if start > end:
            start, end = end, start

        start_region, start_byte = start
        end_region, end_byte = end

        for i in range(start_region, min(end_region + 1, len(self._text_regions))):
            layout, lx, ly = self._text_regions[i]
            n_bytes = len(layout.get_text().encode("utf-8"))

            if i == start_region and i == end_region:
                sel_s, sel_e = start_byte, end_byte
            elif i == start_region:
                sel_s, sel_e = start_byte, n_bytes
            elif i == end_region:
                sel_s, sel_e = 0, end_byte
            else:
                sel_s, sel_e = 0, n_bytes

            self._draw_region_selection(snapshot, layout, lx, ly, sel_s, sel_e)

    def _draw_region_selection(self, snapshot, layout, lx, ly, sel_start, sel_end):
        """Draw selection highlight for a byte range within a single layout."""
        if sel_start >= sel_end:
            return

        layout_iter = layout.get_iter()
        while True:
            line = layout_iter.get_line_readonly()
            line_start = line.start_index
            line_end = line_start + line.length

            overlap_start = max(sel_start, line_start)
            overlap_end = min(sel_end, line_end)

            if overlap_start < overlap_end:
                start_pos = layout.index_to_pos(overlap_start)
                end_pos = layout.index_to_pos(overlap_end)

                x1 = start_pos.x / Pango.SCALE
                x2 = end_pos.x / Pango.SCALE
                if x1 > x2:
                    x1, x2 = x2, x1

                _, line_logical = layout_iter.get_line_extents()
                line_y = line_logical.y / Pango.SCALE
                line_h = line_logical.height / Pango.SCALE

                # Extend to layout width for full-line selections
                if overlap_end == line_end and sel_end > line_end:
                    _, layout_logical = layout.get_pixel_extents()
                    x2 = max(x2, float(layout_logical.width))

                rect = Graphene.Rect()
                rect.init(lx + x1, ly + line_y, max(x2 - x1, 2), line_h)
                snapshot.append_color(self._selection_rgba, rect)

            if not layout_iter.next_line():
                break

    def _get_selected_text(self) -> str:
        """Extract plain text from the current selection."""
        if not self._has_selection or not self._sel_anchor or not self._sel_cursor:
            return ""

        start, end = self._sel_anchor, self._sel_cursor
        if start > end:
            start, end = end, start

        start_region, start_byte = start
        end_region, end_byte = end

        parts = []
        for i in range(start_region, min(end_region + 1, len(self._text_regions))):
            layout = self._text_regions[i][0]
            text_bytes = layout.get_text().encode("utf-8")

            if i == start_region and i == end_region:
                selected = text_bytes[start_byte:end_byte]
            elif i == start_region:
                selected = text_bytes[start_byte:]
            elif i == end_region:
                selected = text_bytes[:end_byte]
            else:
                selected = text_bytes

            parts.append(selected.decode("utf-8", errors="replace"))

        return "\n".join(parts)

    def _select_word_at(self, x, y):
        """Select the word at the given canvas coordinates."""
        pos = self._hit_test(x, y)
        if not pos:
            return
        region_idx, byte_idx = pos
        layout = self._text_regions[region_idx][0]
        text = layout.get_text()
        text_bytes = text.encode("utf-8")

        char_idx = len(text_bytes[:byte_idx].decode("utf-8", errors="replace"))

        start = char_idx
        while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "_"):
            start -= 1
        end = char_idx
        while end < len(text) and (text[end].isalnum() or text[end] == "_"):
            end += 1

        if start == end:
            return

        start_byte = len(text[:start].encode("utf-8"))
        end_byte = len(text[:end].encode("utf-8"))

        self._sel_anchor = (region_idx, start_byte)
        self._sel_cursor = (region_idx, end_byte)
        self._has_selection = True
        self._schedule_redraw()

    def _select_line_at(self, x, y):
        """Select the entire Pango line at the given canvas coordinates."""
        pos = self._hit_test(x, y)
        if not pos:
            return
        region_idx, byte_idx = pos
        layout = self._text_regions[region_idx][0]

        layout_iter = layout.get_iter()
        while True:
            line = layout_iter.get_line_readonly()
            line_start = line.start_index
            line_end = line_start + line.length

            if line_start <= byte_idx <= line_end or not layout_iter.next_line():
                self._sel_anchor = (region_idx, line_start)
                self._sel_cursor = (region_idx, line_end)
                self._has_selection = True
                self._schedule_redraw()
                return

    def _clear_selection(self):
        """Clear the current text selection."""
        self._sel_anchor = None
        self._sel_cursor = None
        self._has_selection = False

    def _select_all(self):
        """Select all text in the canvas."""
        if self._text_regions:
            last_layout = self._text_regions[-1][0]
            last_n_bytes = len(last_layout.get_text().encode("utf-8"))
            self._sel_anchor = (0, 0)
            self._sel_cursor = (len(self._text_regions) - 1, last_n_bytes)
            self._has_selection = True
            self._schedule_redraw()

    # ------------------------------------------------------------------ #
    #  Font measurement                                                    #
    # ------------------------------------------------------------------ #

    def _measure_font(self):
        """Measure base font metrics for line height."""
        pango_ctx = self.get_pango_context()
        if pango_ctx is None:
            return
        layout = Pango.Layout.new(pango_ctx)
        layout.set_font_description(self._font_desc)
        layout.set_text("Mg", -1)
        _, logical = layout.get_extents()
        self._line_height = max(round(logical.height / Pango.SCALE) + 2, 1)
        self._char_width = max(logical.width / Pango.SCALE / 2, 1.0)
        self._measured = True

    # ------------------------------------------------------------------ #
    #  Sizing and scrolling                                                #
    # ------------------------------------------------------------------ #

    def _connect_vadjustment(self, vadjustment):
        if self._vadjustment is vadjustment:
            return
        if self._vadjustment is not None and self._vadjustment_handler_id is not None:
            self._vadjustment.disconnect(self._vadjustment_handler_id)
        if self._vadjustment is not None and self._page_size_handler_id is not None:
            self._vadjustment.disconnect(self._page_size_handler_id)
        self._vadjustment = vadjustment
        self._vadjustment_handler_id = None
        self._page_size_handler_id = None
        if vadjustment is not None:
            self._vadjustment_handler_id = vadjustment.connect("value-changed", self._on_scroll_value_changed)
            self._page_size_handler_id = vadjustment.connect("notify::page-size", self._on_page_size_changed)

    def _on_vadjustment_changed(self, scrolled_window, pspec):
        self._connect_vadjustment(scrolled_window.get_vadjustment())

    def _on_scroll_value_changed(self, adjustment):
        self.queue_draw()

    def _on_page_size_changed(self, adjustment, pspec):
        """Redraw when the viewport height changes (e.g. panel resize)."""
        self.queue_draw()

    def _get_vadjustment(self):
        parent = self.get_parent()
        while parent is not None:
            if isinstance(parent, Gtk.ScrolledWindow):
                return parent.get_vadjustment()
            parent = parent.get_parent()
        return None

    def _get_scroll_y(self) -> float:
        vadj = self._get_vadjustment()
        return vadj.get_value() if vadj else 0.0

    def _get_visible_height(self) -> float:
        vadj = self._get_vadjustment()
        if vadj:
            ps = vadj.get_page_size()
            if ps > 0:
                return ps
        # Fallback when page_size is 0 (e.g. during macOS surface transitions)
        return float(self.get_height()) or 100.0

    def _schedule_redraw(self):
        if not self._redraw_scheduled:
            self._redraw_scheduled = True
            GLib.idle_add(self._do_redraw)

    def _do_redraw(self):
        self._redraw_scheduled = False
        self.queue_draw()
        return False

    def _apply_zoom(self):
        self._needs_layout = True
        self._schedule_redraw()

    # ------------------------------------------------------------------ #
    #  Color helpers                                                       #
    # ------------------------------------------------------------------ #
