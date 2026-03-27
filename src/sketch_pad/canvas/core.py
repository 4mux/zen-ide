"""
SketchCanvas class shell — setup, properties, and core methods.
"""

import platform

from gi.repository import Gdk, Gtk, Pango

from fonts.font_manager import get_font_settings
from sketch_pad.sketch_model import (
    CLOUD_MIN_HEIGHT,
    CLOUD_MIN_WIDTH,
    TOPIC_MIN_HEIGHT,
    TOPIC_MIN_WIDTH,
    AbstractShape,
    ArrowLineStyle,
    ArrowShape,
    Board,
    CloudShape,
    DatabaseShape,
    RectangleShape,
    ToolMode,
    TopicShape,
)

from .alignment import AlignmentMixin
from .interaction import InteractionMixin
from .keyboard import KeyboardMixin
from .pan_zoom import PanZoomMixin
from .rendering import RenderingMixin
from .selection import SelectionMixin
from .text_editing import TextEditingMixin
from .text_rendering import TextRenderingMixin

_MOD = Gdk.ModifierType.META_MASK if platform.system() == "Darwin" else Gdk.ModifierType.CONTROL_MASK


class SketchCanvas(
    RenderingMixin,
    TextRenderingMixin,
    InteractionMixin,
    SelectionMixin,
    KeyboardMixin,
    AlignmentMixin,
    PanZoomMixin,
    TextEditingMixin,
    Gtk.Widget,
):
    """Interactive ASCII diagram canvas using GTK4 / GtkSnapshot / Pango."""

    _SCROLL_PAN_STEP = 8.0

    def __init__(self, board: Board, on_status_change=None, on_tool_change=None, on_dark_mode_change=None):
        super().__init__()
        self._board = board
        self._on_status_change = on_status_change
        self._on_tool_change = on_tool_change
        self._on_dark_mode_change = on_dark_mode_change

        # Display — use editor font settings with platform-aware fallback
        _fs = get_font_settings("editor")
        _editor_font = _fs["family"]
        self._font_family = _editor_font
        self._font_size = _fs.get("size", 14)
        self._grid_font_family = _editor_font
        self._cell_w = 0.0
        self._cell_h = 0.0
        self._char_ink: dict[str, tuple[int, int, int, int]] = {}  # ch -> (x, y, w, h)
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._show_grid = True
        self._dark_mode = True

        # Tool
        self._tool = ToolMode.SELECT
        self._selected_ids: set[str] = set()
        self._text_only_selection = False
        self._arrow_line_style = ArrowLineStyle.SOLID

        # Drawing (rectangle / arrow creation)
        self._drawing = False
        self._draw_start: tuple[int, int] | None = None
        self._draw_end: tuple[int, int] | None = None
        self._draw_snap_start: tuple | None = None
        self._draw_snap_end: tuple | None = None
        self._drag_start_screen: tuple[float, float] | None = None

        # Move drag
        self._dragging = False
        self._drag_start_pos: dict[str, tuple] = {}

        # Rectangle resize
        self._resizing = False
        self._resize_handle: str | None = None
        self._resize_shape_id: str | None = None
        self._resize_orig: dict | None = None

        # Arrow endpoint drag
        self._arrow_ep_dragging = False
        self._arrow_ep_end: str | None = None  # "start" or "end"
        self._arrow_ep_shape_id: str | None = None

        # Alignment guides (shown while dragging shapes)
        self._alignment_guides: list[tuple[str, float]] = []  # ("h"|"v", grid_pos)

        # Marquee (drag-to-select)
        self._marquee_selecting = False
        self._marquee_start: tuple[int, int] | None = None
        self._marquee_end: tuple[int, int] | None = None

        # Pan
        self._panning = False
        self._pan_start_offset: tuple[float, float] | None = None

        # Pinch-to-zoom
        self._pinch_start_zoom = 1.0

        # Smooth scroll animation
        self._target_pan_x = 0.0
        self._target_pan_y = 0.0
        self._scroll_tick_id: int | None = None
        _SMOOTH_LERP = 0.55  # interpolation factor per frame (0..1)
        self._smooth_lerp = _SMOOTH_LERP

        # Text editing
        self._text_editing = False
        self._text_shape_id: str | None = None
        self._text_cursor_col = 0
        self._text_cursor_row = 0
        self._text_buffer: list[str] = []
        self._text_cursor_line = 0  # cursor line within _text_buffer
        self._text_cursor_char = 0  # cursor char within current line
        self._text_sel_anchor_line = 0  # selection anchor line
        self._text_sel_anchor_char = 0  # selection anchor char

        # Undo / redo
        self._history: list[str] = []
        self._hist_idx: int = -1
        self._snapshot_history()

        # Widget setup
        self.set_can_focus(True)
        self.set_focusable(True)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self._measure_font()

        # --- Event controllers ---
        # GestureClick only for double-click (text editing)
        click = Gtk.GestureClick()
        click.set_button(1)
        click.connect("pressed", self._on_click)
        self.add_controller(click)

        # GestureDrag handles all draw/select/move/resize interaction
        drag = Gtk.GestureDrag()
        drag.set_button(0)
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)

        # Group so they share the event sequence and don't compete
        click.group(drag)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        self.add_controller(motion)

        scroll = Gtk.EventControllerScroll()
        scroll.set_flags(Gtk.EventControllerScrollFlags.BOTH_AXES | Gtk.EventControllerScrollFlags.KINETIC)
        scroll.connect("scroll", self._on_scroll)
        scroll.connect("scroll-end", self._on_scroll_end)
        self.add_controller(scroll)

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)

        pinch = Gtk.GestureZoom()
        pinch.connect("begin", self._on_pinch_begin)
        pinch.connect("scale-changed", self._on_pinch_scale_changed)
        self.add_controller(pinch)

        self._double_click_pending = False

    # ─────────────────────── GObject vfunc overrides ───────────────────────
    # PyGObject only registers vfunc overrides found in the class's own
    # __dict__, not those inherited from non-GObject mixins.  Explicitly
    # delegate so GTK sees the override during class creation.

    def do_snapshot(self, snapshot):
        RenderingMixin.do_snapshot(self, snapshot)

    # ─────────────────────── Properties ───────────────────────

    @property
    def tool(self) -> ToolMode:
        return self._tool

    @tool.setter
    def tool(self, value: ToolMode):
        self._exit_text_edit()
        self._tool = value
        self._selected_ids.clear()
        self.queue_draw()
        if self._on_tool_change:
            self._on_tool_change(value)

    @property
    def selected_shapes(self) -> list[AbstractShape]:
        return [self._board.get_shape(sid) for sid in self._selected_ids if self._board.get_shape(sid)]

    # ─────────────────────── Font / Coords ───────────────────────

    def set_font_family(self, family: str):
        """Change the label font family (shapes always use monospace)."""
        self._font_family = family
        self.queue_draw()

    def _measure_font(self):
        ctx = self.get_pango_context()
        if ctx is None:
            self._cell_w = self._font_size * 0.6
            self._cell_h = self._font_size * 1.2
            return
        fd = Pango.FontDescription.new()
        fd.set_family(self._grid_font_family)
        fd.set_size(int(self._font_size * Pango.SCALE))
        m = ctx.get_metrics(fd, None)
        self._cell_w = m.get_approximate_char_width() / Pango.SCALE
        self._cell_h = (m.get_ascent() + m.get_descent()) / Pango.SCALE

        # Cache character ink extents for selection frame alignment
        layout = Pango.Layout.new(ctx)
        layout.set_font_description(fd)
        self._char_ink = {}
        for ch in ("─", "│", "_", "(", ")", "╭"):
            layout.set_text(ch, -1)
            ink, _ = layout.get_pixel_extents()
            self._char_ink[ch] = (ink.x, ink.y, ink.width, ink.height)

    def _screen_to_grid(self, sx: float, sy: float) -> tuple[int, int]:
        if self._cell_w <= 0 or self._cell_h <= 0:
            return (0, 0)
        return (int((sx / self._zoom - self._pan_x) / self._cell_w), int((sy / self._zoom - self._pan_y) / self._cell_h))

    def _grid_to_screen(self, col: int, row: int) -> tuple[float, float]:
        return ((col * self._cell_w + self._pan_x) * self._zoom, (row * self._cell_h + self._pan_y) * self._zoom)

    # Margin in grid cells around the diagram bounding box
    _PAN_MARGIN = 10

    def _clamp_pan(self):
        """Restrict panning so the viewport stays within the diagram area + margin."""
        if self._cell_w <= 0 or self._cell_h <= 0:
            return
        bb = self._board.bounding_box()
        if bb is None:
            return
        margin = self._PAN_MARGIN
        left, top, right, bottom = bb

        # Pixel extents of the content region (in logical/unzoomed coords)
        content_left = (left - margin) * self._cell_w
        content_top = (top - margin) * self._cell_h
        content_right = (right + 1 + margin) * self._cell_w
        content_bottom = (bottom + 1 + margin) * self._cell_h

        # Viewport size in logical coords
        vw = self.get_width() / self._zoom
        vh = self.get_height() / self._zoom

        # pan values are added to the translation, so -pan_x is the left edge of the viewport
        # Clamp so that viewport left >= content_left and viewport right <= content_right
        # viewport left  = -pan_x   => pan_x = -viewport_left
        # viewport right = -pan_x + vw
        max_pan_x = -content_left
        min_pan_x = -(content_right - vw)
        max_pan_y = -content_top
        min_pan_y = -(content_bottom - vh)

        # If viewport is larger than content, center it
        if min_pan_x > max_pan_x:
            self._pan_x = (min_pan_x + max_pan_x) / 2
        else:
            self._pan_x = max(min_pan_x, min(max_pan_x, self._pan_x))
        if min_pan_y > max_pan_y:
            self._pan_y = (min_pan_y + max_pan_y) / 2
        else:
            self._pan_y = max(min_pan_y, min(max_pan_y, self._pan_y))

    def _custom_font_cursor_pos(self, shape, line=None, char=None) -> tuple[float, float, float]:
        """Return (x, y, line_height) for text cursor in a custom-font shape.

        Uses the same Pango layout as _draw_custom_font_texts so cursor and
        rendered text are always pixel-aligned.
        """
        fs = shape.font_size or self._font_size
        fd = Pango.FontDescription.new()
        fd.set_family(self._font_family)
        fd.set_size(int(fs * Pango.SCALE))

        # Fallback metrics (used when pango context is unavailable)
        line_h = fs * 1.2
        char_w = fs * 0.6
        ctx = self.get_pango_context()
        if ctx:
            m = ctx.get_metrics(fd, None)
            char_w = m.get_approximate_char_width() / Pango.SCALE
            line_h = (m.get_ascent() + m.get_descent()) / Pango.SCALE

        text = "\n".join(self._text_buffer)
        lines = self._text_buffer
        num_lines = len(lines)
        cur_line = line if line is not None else self._text_cursor_line
        cur_char = char if char is not None else self._text_cursor_char

        # Compute byte index for Pango cursor positioning
        byte_index = sum(len(lines[i].encode("utf-8")) + 1 for i in range(cur_line))
        cur_line_text = lines[cur_line] if cur_line < num_lines else ""
        byte_index += len(cur_line_text[:cur_char].encode("utf-8"))

        if isinstance(shape, (RectangleShape, DatabaseShape, TopicShape, CloudShape)):
            if isinstance(shape, (TopicShape, CloudShape, DatabaseShape)):
                interior = shape.get_interior_bounds()
                if interior:
                    il, it, ir, ib = interior
                    ix = il * self._cell_w
                    iy = it * self._cell_h
                    iw = (ir - il + 1) * self._cell_w
                    ih = (ib - it + 1) * self._cell_h
                else:
                    ix = (shape.left + 1) * self._cell_w
                    iy = (shape.top + 1) * self._cell_h
                    iw = (shape.width - 2) * self._cell_w
                    ih = (shape.height - 2) * self._cell_h
            else:
                ix = (shape.left + 1) * self._cell_w
                iy = (shape.top + 1) * self._cell_h
                iw = (shape.width - 2) * self._cell_w
                ih = (shape.height - 2) * self._cell_h

            if ctx:
                layout = Pango.Layout.new(ctx)
                layout.set_font_description(fd)
                layout.set_text(text, -1)
                layout.set_alignment(Pango.Alignment.CENTER)
                layout.set_width(int(iw * Pango.SCALE))
                _, text_ext = layout.get_pixel_extents()
                ty = iy + max(0, (ih - text_ext.height) / 2)
                strong_pos, _ = layout.get_cursor_pos(byte_index)
                return (ix + strong_pos.x / Pango.SCALE, ty + strong_pos.y / Pango.SCALE, strong_pos.height / Pango.SCALE)

            # Fallback without context
            total_h = num_lines * line_h
            ty = iy + max(0, (ih - total_h) / 2)
            text_w = len(cur_line_text) * char_w
            tx = ix + max(0, (iw - text_w) / 2)
            return (tx + cur_char * char_w, ty + cur_line * line_h, line_h)

        elif isinstance(shape, ArrowShape):
            anchor = shape.get_text_anchor()
            cx = anchor[0] * self._cell_w + self._cell_w / 2
            cy = anchor[1] * self._cell_h + self._cell_h / 2

            if ctx:
                layout = Pango.Layout.new(ctx)
                layout.set_font_description(fd)
                layout.set_text(text, -1)
                layout.set_alignment(Pango.Alignment.CENTER)
                _, text_ext = layout.get_pixel_extents()
                tx = cx - text_ext.width / 2
                ty = cy - text_ext.height / 2
                strong_pos, _ = layout.get_cursor_pos(byte_index)
                return (
                    tx + strong_pos.x / Pango.SCALE,
                    ty + strong_pos.y / Pango.SCALE,
                    strong_pos.height / Pango.SCALE,
                )

            # Fallback without context
            total_h = num_lines * line_h
            text_w = len(cur_line_text) * char_w
            tx = cx - text_w / 2
            return (tx + cur_char * char_w, cy - total_h / 2 + cur_line * line_h, line_h)

        return (0, 0, line_h)

    def set_selected_font_size(self, size: float):
        """Set font_size of selected shapes to a specific value."""
        changed = False
        for shape in self.selected_shapes:
            if not isinstance(shape, (RectangleShape, DatabaseShape, ArrowShape, TopicShape, CloudShape)):
                continue
            new_size = max(6, min(72, size))
            shape.font_size = new_size
            changed = True
        if changed:
            self._snapshot_history()
            self.queue_draw()

    def get_selected_font_size(self) -> float | None:
        """Return font_size of first selected shape, or None if none selected."""
        for shape in self.selected_shapes:
            if isinstance(shape, (RectangleShape, DatabaseShape, ArrowShape, TopicShape, CloudShape)):
                return shape.font_size or self._font_size
        return None

    def set_shape_property(self, shape_id: str, **kwargs):
        """Set arbitrary properties on a shape and record undo snapshot."""
        shape = self._board.get_shape(shape_id)
        if not shape:
            return
        changed = False
        for key, value in kwargs.items():
            if hasattr(shape, key) and getattr(shape, key) != value:
                setattr(shape, key, value)
                changed = True
        if changed:
            self._snapshot_history()
            self.queue_draw()

    # ─────────────────────── Drawing Tools ───────────────────────

    def _make_preview_shape(self) -> AbstractShape | None:
        if not self._draw_start or not self._draw_end:
            return None
        sc, sr = self._draw_start
        ec, er = self._draw_end
        if self._tool == ToolMode.RECTANGLE:
            left, top = min(sc, ec), min(sr, er)
            w, h = abs(ec - sc) + 1, abs(er - sr) + 1
            if w < 2 or h < 2:
                return None
            return RectangleShape(left=left, top=top, width=w, height=h)
        elif self._tool == ToolMode.ARROW:
            a = ArrowShape(start_col=sc, start_row=sr, end_col=ec, end_row=er, line_style=self._arrow_line_style)
            if self._draw_snap_start:
                a.start_connection = self._draw_snap_start[0]
            if self._draw_snap_end:
                a.end_connection = self._draw_snap_end[0]
            return a
        elif self._tool == ToolMode.TOPIC:
            left, top = min(sc, ec), min(sr, er)
            w, h = abs(ec - sc) + 1, abs(er - sr) + 1
            w = max(w, TOPIC_MIN_WIDTH)
            h = max(h, TOPIC_MIN_HEIGHT)
            return TopicShape(left=left, top=top, width=w, height=h)
        elif self._tool == ToolMode.CLOUD:
            left, top = min(sc, ec), min(sr, er)
            w, h = abs(ec - sc) + 1, abs(er - sr) + 1
            w = max(w, CLOUD_MIN_WIDTH)
            h = max(h, CLOUD_MIN_HEIGHT)
            return CloudShape(left=left, top=top, width=w, height=h)
        return None

    def _finish_drawing(self):
        shape = self._make_preview_shape()
        if shape:
            self._board.add_shape(shape)
            self._selected_ids = {shape.id}
            self._snapshot_history()

    # ─────────────────────── Undo / Redo ───────────────────────

    def _snapshot_history(self):
        snap = self._board.snapshot()
        self._history = self._history[: self._hist_idx + 1]
        self._history.append(snap)
        self._hist_idx = len(self._history) - 1

    def undo(self):
        if self._hist_idx > 0:
            self._hist_idx -= 1
            self._board.restore(self._history[self._hist_idx])
            self._selected_ids.clear()
            self.queue_draw()

    def redo(self):
        if self._hist_idx < len(self._history) - 1:
            self._hist_idx += 1
            self._board.restore(self._history[self._hist_idx])
            self._selected_ids.clear()
            self.queue_draw()
