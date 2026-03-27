"""
GTK4 canvas widget for ASCII diagram editing.

Renders a character grid via Pango and handles mouse/keyboard interaction
for drawing, selecting, moving, resizing, and text-editing shapes.
"""

import platform

from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk, Pango

from fonts.font_manager import get_font_settings
from shared.utils import tuple_to_gdk_rgba
from sketch_pad.sketch_model import (
    _CLIPBOARD_XLAT,
    ACTOR_HEIGHT,
    ACTOR_WIDTH,
    CLOUD_MIN_HEIGHT,
    CLOUD_MIN_WIDTH,
    DATABASE_MIN_HEIGHT,
    DATABASE_MIN_WIDTH,
    TOPIC_MIN_HEIGHT,
    TOPIC_MIN_WIDTH,
    AbstractShape,
    ActorShape,
    ArrowLineStyle,
    ArrowShape,
    Board,
    CloudShape,
    DatabaseShape,
    RectangleShape,
    ToolMode,
    TopicShape,
    _render_font_size_texts,
)
from themes import get_theme

_MOD = Gdk.ModifierType.META_MASK if platform.system() == "Darwin" else Gdk.ModifierType.CONTROL_MASK


class SketchCanvas(Gtk.Widget):
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

    # ─────────────────────── Drawing ───────────────────────

    def do_snapshot(self, snapshot):
        width = self.get_width()
        height = self.get_height()
        theme = get_theme()
        if self._dark_mode:
            bg = _hex(theme.panel_bg)
            fg = _hex(theme.fg_color)
        else:
            bg = _hex(theme.fg_color)
            fg = _hex(theme.panel_bg)
        bounds = Graphene.Rect().init(0, 0, width, height)
        snapshot.push_clip(bounds)
        snapshot.append_color(tuple_to_gdk_rgba(bg), bounds)

        snapshot.save()
        snapshot.scale(self._zoom, self._zoom)
        snapshot.translate(Graphene.Point().init(self._pan_x, self._pan_y))

        if self._show_grid:
            self._draw_grid(snapshot, width, height, fg)

        grid = self._board.render()

        # Strip text from the grid for the shape being edited so only
        # _draw_editing_text renders it (single text source, no shift).
        if self._text_editing and self._text_shape_id:
            self._strip_editing_shape_text(grid)

        fd = Pango.FontDescription.new()
        fd.set_family(self._grid_font_family)
        fd.set_size(int(self._font_size * Pango.SCALE))

        # Fill backgrounds for shapes with fill_color
        self._draw_fill_colors(snapshot)

        # Board chars
        self._draw_chars(snapshot, grid, fd, fg)

        # Re-draw chars in custom text_color for shapes that have one
        self._draw_colored_chars(snapshot, grid, fd)

        # Custom font-size text overlays
        self._draw_custom_font_texts(snapshot, fg)

        # Preview while creating a shape
        if self._drawing and self._draw_start and self._draw_end:
            preview = self._make_preview_shape()
            if preview:
                pg: dict[tuple[int, int], str] = {}
                preview.render(pg)
                accent = _hex(theme.accent_color)
                self._draw_chars(snapshot, pg, fd, accent)

        # Selection highlight & handles
        self._draw_selection(snapshot, theme)

        # Alignment guides (shown while dragging shapes)
        if self._alignment_guides:
            self._draw_alignment_guides(snapshot, theme, width, height)

        # Marquee selection rectangle
        if self._marquee_selecting and self._marquee_start and self._marquee_end:
            ms, me = self._marquee_start, self._marquee_end
            accent = _hex(theme.accent_color)
            x = min(ms[0], me[0]) * self._cell_w
            y = min(ms[1], me[1]) * self._cell_h
            w = (abs(me[0] - ms[0]) + 1) * self._cell_w
            h = (abs(me[1] - ms[1]) + 1) * self._cell_h
            snapshot.append_color(tuple_to_gdk_rgba(accent, 0.15), Graphene.Rect().init(x, y, w, h))
            builder = Gsk.PathBuilder.new()
            builder.add_rect(Graphene.Rect().init(x, y, w, h))
            stroke = Gsk.Stroke.new(1)
            stroke.set_dash([4, 3])
            snapshot.append_stroke(builder.to_path(), stroke, tuple_to_gdk_rgba(accent, 0.6))

        # Text cursor
        if self._text_editing:
            self._draw_editing_text(snapshot, fg, bg)
            self._draw_text_selection(snapshot, theme, fg, bg)
            self._draw_text_cursor(snapshot, theme)

        # Magnetic snap indicators
        if self._drawing:
            for snap_data in [self._draw_snap_start, self._draw_snap_end]:
                if snap_data:
                    conn, sc, sr = snap_data
                    if conn:
                        accent = _hex(theme.accent_color)
                        cx = sc * self._cell_w + self._cell_w / 2
                        cy = sr * self._cell_h + self._cell_h / 2
                        builder = Gsk.PathBuilder.new()
                        builder.add_circle(Graphene.Point().init(cx, cy), 8)
                        stroke = Gsk.Stroke.new(1)
                        snapshot.append_stroke(builder.to_path(), stroke, tuple_to_gdk_rgba(accent, 0.6))

        snapshot.restore()
        snapshot.pop()

    def _draw_grid(self, snapshot, width, height, fg_color):
        vc = int(width / (self._cell_w * self._zoom)) + 2
        vr = int(height / (self._cell_h * self._zoom)) + 2
        sc = int(-self._pan_x / self._cell_w) - 1
        sr = int(-self._pan_y / self._cell_h) - 1
        builder = Gsk.PathBuilder.new()
        for col in range(sc, sc + vc):
            x = col * self._cell_w
            builder.move_to(x, sr * self._cell_h)
            builder.line_to(x, (sr + vr) * self._cell_h)
        for row in range(sr, sr + vr):
            y = row * self._cell_h
            builder.move_to(sc * self._cell_w, y)
            builder.line_to((sc + vc) * self._cell_w, y)
        stroke = Gsk.Stroke.new(0.5)
        snapshot.append_stroke(builder.to_path(), stroke, tuple_to_gdk_rgba(fg_color, 0.06))

    def _strip_editing_shape_text(self, grid: dict[tuple[int, int], str]):
        """Remove text chars from grid for the shape being edited."""
        shape = self._board.get_shape(self._text_shape_id)
        if not shape or getattr(shape, "font_size", None):
            return  # Font-size shapes use Pango overlay, not grid text
        if isinstance(shape, (RectangleShape, DatabaseShape, TopicShape, CloudShape)):
            interior = shape.get_interior_bounds()
            if interior:
                il, it, ir, ib = interior
                for r in range(it, ib + 1):
                    for c in range(il, ir + 1):
                        if (c, r) in grid:
                            grid[(c, r)] = " "
        elif isinstance(shape, ArrowShape) and shape.text:
            path = shape._compute_path()
            if path:
                mid = path[len(path) // 2]
                lines = shape.text.split("\n")
                num_lines = len(lines)
                for i, line in enumerate(lines):
                    h_offset = -(len(line) // 2)
                    for j in range(len(line)):
                        key = (mid[0] + h_offset + j, mid[1] - num_lines + i)
                        if key in grid:
                            grid[key] = " "
        elif isinstance(shape, ActorShape) and shape.text:
            text_row = shape.top + ACTOR_HEIGHT
            text_start = shape.left + (ACTOR_WIDTH - len(shape.text)) // 2
            for j in range(len(shape.text)):
                key = (text_start + j, text_row)
                if key in grid:
                    grid[key] = " "

    def _draw_chars(self, snapshot, grid: dict, fd, color: tuple):
        if not grid:
            return
        ctx = self.get_pango_context()
        if not ctx:
            return
        rgba = tuple_to_gdk_rgba(color)
        layout = Pango.Layout.new(ctx)
        layout.set_font_description(fd)
        for (col, row), ch in grid.items():
            if not ch or ch == " ":
                continue
            layout.set_text(ch, -1)
            snapshot.save()
            snapshot.translate(Graphene.Point().init(col * self._cell_w, row * self._cell_h))
            snapshot.append_layout(layout, rgba)
            snapshot.restore()

    def _draw_fill_colors(self, snapshot):
        """Draw filled background rectangles for shapes with fill_color."""
        for shape in self._board.z_sorted():
            fc = shape.fill_color
            if not fc:
                continue
            if isinstance(shape, ArrowShape):
                continue
            interior = shape.get_interior_bounds()
            if not interior:
                continue
            left, top, right, bottom = interior
            # Expand fill toward the border lines, leaving only 1px gap
            half_cw = self._cell_w / 2
            half_ch = self._cell_h / 2
            expand_x = half_cw - 1
            expand_y = half_ch - 1
            x = left * self._cell_w - expand_x
            y = top * self._cell_h - expand_y
            w = (right - left + 1) * self._cell_w + 2 * expand_x
            h = (bottom - top + 1) * self._cell_h + 2 * expand_y
            snapshot.append_color(tuple_to_gdk_rgba(_hex(fc)), Graphene.Rect().init(x, y, w, h))

    def _draw_colored_chars(self, snapshot, grid: dict, fd):
        """Re-draw chars in custom color for shapes that have one."""
        ctx = self.get_pango_context()
        if not ctx:
            return
        # Build color map: (col, row) -> hex_color
        color_map: dict[tuple[int, int], str] = {}
        for shape in self._board.z_sorted():
            # Arrow line coloring via fill_color
            if isinstance(shape, ArrowShape) and shape.fill_color:
                all_chars: dict[tuple[int, int], str] = {}
                shape.render(all_chars)
                text_chars: dict[tuple[int, int], str] = {}
                shape.render_text(text_chars)
                for pos in all_chars:
                    if pos not in text_chars and pos in grid:
                        color_map[pos] = shape.fill_color
            # Text coloring via text_color
            tc = shape.text_color
            if not tc:
                continue
            temp: dict[tuple[int, int], str] = {}
            shape.render_text(temp)
            for pos in temp:
                if pos in grid:
                    color_map[pos] = tc
        if not color_map:
            return
        layout = Pango.Layout.new(ctx)
        layout.set_font_description(fd)
        # Group by color to minimise RGBA object creation
        by_color: dict[str, list[tuple[int, int]]] = {}
        for pos, hc in color_map.items():
            by_color.setdefault(hc, []).append(pos)
        for hc, positions in by_color.items():
            rgba = tuple_to_gdk_rgba(_hex(hc))
            for col, row in positions:
                ch = grid.get((col, row))
                if not ch or ch == " ":
                    continue
                layout.set_text(ch, -1)
                snapshot.save()
                snapshot.translate(Graphene.Point().init(col * self._cell_w, row * self._cell_h))
                snapshot.append_layout(layout, rgba)
                snapshot.restore()

    def _draw_custom_font_texts(self, snapshot, fg):
        """Render text for shapes with a custom font_size as centred Pango layouts."""
        ctx = self.get_pango_context()
        if not ctx:
            return
        fg_rgba = tuple_to_gdk_rgba(fg)
        for shape in self._board.z_sorted():
            if not getattr(shape, "font_size", None) or not shape.text:
                continue
            text_rgba = tuple_to_gdk_rgba(_hex(shape.text_color)) if shape.text_color else fg_rgba
            fd = Pango.FontDescription.new()
            fd.set_family(self._font_family)
            fd.set_size(int(shape.font_size * Pango.SCALE))
            layout = Pango.Layout.new(ctx)
            layout.set_font_description(fd)
            layout.set_text(shape.text, -1)
            layout.set_alignment(Pango.Alignment.CENTER)

            if isinstance(shape, (RectangleShape, DatabaseShape, TopicShape, CloudShape)):
                # Centre text in interior pixel area
                if isinstance(shape, (TopicShape, CloudShape, DatabaseShape)):
                    interior = shape.get_interior_bounds()
                    if interior:
                        il, it, ir, ib = interior
                        ix = il * self._cell_w
                        iy = it * self._cell_h
                        iw = (ir - il + 1) * self._cell_w
                        ih = (ib - it + 1) * self._cell_h
                    else:
                        continue
                else:
                    ix = (shape.left + 1) * self._cell_w
                    iy = (shape.top + 1) * self._cell_h
                    iw = (shape.width - 2) * self._cell_w
                    ih = (shape.height - 2) * self._cell_h
                layout.set_width(int(iw * Pango.SCALE))
                _, text_ext = layout.get_pixel_extents()
                ty = iy + max(0, (ih - text_ext.height) / 2)
                snapshot.save()
                snapshot.translate(Graphene.Point().init(ix, ty))
                snapshot.append_layout(layout, text_rgba)
                snapshot.restore()
            elif isinstance(shape, ArrowShape):
                anchor = shape.get_text_anchor()
                cx = anchor[0] * self._cell_w + self._cell_w / 2
                cy = anchor[1] * self._cell_h + self._cell_h / 2
                _, text_ext = layout.get_pixel_extents()
                snapshot.save()
                snapshot.translate(Graphene.Point().init(cx - text_ext.width / 2, cy - text_ext.height / 2))
                snapshot.append_layout(layout, text_rgba)
                snapshot.restore()

    def _visual_bounds(self, shape):
        """Pixel bounds of shape's visible border ink, tighter than cell bounds."""
        ci = self._char_ink
        if not ci:
            return (
                shape.left * self._cell_w,
                shape.top * self._cell_h,
                shape.width * self._cell_w,
                shape.height * self._cell_h,
            )
        if isinstance(shape, CloudShape):
            u = ci.get("_", (0, 0, int(self._cell_w), int(self._cell_h)))
            lp = ci.get("(", (0, 0, int(self._cell_w), int(self._cell_h)))
            rp = ci.get(")", (0, 0, int(self._cell_w), int(self._cell_h)))
            top_y = shape.top * self._cell_h + u[1]
            bot_y = shape.bottom * self._cell_h + u[1] + u[3]
            left_x = shape.left * self._cell_w + lp[0]
            right_x = shape.right * self._cell_w + rp[0] + rp[2]
        elif isinstance(shape, DatabaseShape):
            # Use ─/│ ink for tight bounds, same as RectangleShape.
            hl = ci.get("─", (0, 0, int(self._cell_w), int(self._cell_h)))
            vl = ci.get("│", (0, 0, int(self._cell_w), int(self._cell_h)))
            top_y = shape.top * self._cell_h + hl[1]
            bot_y = shape.bottom * self._cell_h + hl[1] + hl[3]
            left_x = shape.left * self._cell_w + vl[0]
            right_x = shape.right * self._cell_w + vl[0] + vl[2]
        elif isinstance(shape, (RectangleShape, TopicShape)):
            hl = ci.get("─", (0, 0, int(self._cell_w), int(self._cell_h)))
            vl = ci.get("│", (0, 0, int(self._cell_w), int(self._cell_h)))
            top_y = shape.top * self._cell_h + hl[1]
            bot_y = shape.bottom * self._cell_h + hl[1] + hl[3]
            left_x = shape.left * self._cell_w + vl[0]
            right_x = shape.right * self._cell_w + vl[0] + vl[2]
        else:
            return (
                shape.left * self._cell_w,
                shape.top * self._cell_h,
                shape.width * self._cell_w,
                shape.height * self._cell_h,
            )
        return (left_x, top_y, right_x - left_x, bot_y - top_y)

    def _draw_selection(self, snapshot, theme):
        if not self._selected_ids:
            return
        accent = _hex(theme.accent_color)
        for shape in self.selected_shapes:
            if isinstance(shape, ArrowShape) and self._text_only_selection and len(self._selected_ids) == 1:
                self._draw_text_only_sel(snapshot, shape, accent)
            elif isinstance(shape, ArrowShape):
                self._draw_arrow_sel(snapshot, shape, accent)
            else:
                vx, vy, vw, vh = self._visual_bounds(shape)
                pad = 2
                builder = Gsk.PathBuilder.new()
                builder.add_rect(Graphene.Rect().init(vx - pad, vy - pad, vw + 2 * pad, vh + 2 * pad))
                stroke = Gsk.Stroke.new(2.0)
                stroke.set_dash([5, 3])
                snapshot.append_stroke(builder.to_path(), stroke, tuple_to_gdk_rgba(accent, 0.7))
                if len(self._selected_ids) == 1:
                    self._draw_resize_handles(snapshot, shape, accent)

    def _draw_arrow_sel(self, snapshot, shape: ArrowShape, accent):
        path = shape._compute_path()
        if len(path) < 2:
            return
        # Arrow path highlight
        builder = Gsk.PathBuilder.new()
        x0 = path[0][0] * self._cell_w + self._cell_w / 2
        y0 = path[0][1] * self._cell_h + self._cell_h / 2
        builder.move_to(x0, y0)
        for c, r in path[1:]:
            builder.line_to(c * self._cell_w + self._cell_w / 2, r * self._cell_h + self._cell_h / 2)
        stroke = Gsk.Stroke.new(3)
        snapshot.append_stroke(builder.to_path(), stroke, tuple_to_gdk_rgba(accent, 0.55))
        # Endpoint handles — connected endpoints get a diamond, unconnected get a circle
        for end_name, (c, r), conn in [
            ("start", (shape.start_col, shape.start_row), shape.start_connection),
            ("end", (shape.end_col, shape.end_row), shape.end_connection),
        ]:
            cx = c * self._cell_w + self._cell_w / 2
            cy = r * self._cell_h + self._cell_h / 2
            if conn:
                # Diamond for connected endpoints
                ds = 6
                builder = Gsk.PathBuilder.new()
                builder.move_to(cx, cy - ds)
                builder.line_to(cx + ds, cy)
                builder.line_to(cx, cy + ds)
                builder.line_to(cx - ds, cy)
                builder.close()
                snapshot.append_fill(builder.to_path(), Gsk.FillRule.WINDING, tuple_to_gdk_rgba(accent, 0.9))
                if conn.pinned:
                    # Inner dot to indicate pinned state
                    if self._dark_mode:
                        dot_color = tuple_to_gdk_rgba((0, 0, 0), 0.8)
                    else:
                        dot_color = tuple_to_gdk_rgba((1, 1, 1), 0.8)
                    builder = Gsk.PathBuilder.new()
                    builder.add_circle(Graphene.Point().init(cx, cy), 2)
                    snapshot.append_fill(builder.to_path(), Gsk.FillRule.WINDING, dot_color)
            else:
                # Circle for unconnected endpoints
                builder = Gsk.PathBuilder.new()
                builder.add_circle(Graphene.Point().init(cx, cy), 5)
                snapshot.append_fill(builder.to_path(), Gsk.FillRule.WINDING, tuple_to_gdk_rgba(accent, 0.8))
        # Highlight connected shapes at connection points
        self._draw_connection_hints(snapshot, shape, accent)

    def _draw_text_only_sel(self, snapshot, shape: ArrowShape, accent):
        """Draw selection highlight only around the arrow's text label."""
        pad = 2
        if shape.font_size and shape.text:
            # Pixel-accurate bounds for custom font_size text
            ctx = self.get_pango_context()
            if not ctx:
                return
            fd = Pango.FontDescription.new()
            fd.set_family(self._font_family)
            fd.set_size(int(shape.font_size * Pango.SCALE))
            layout = Pango.Layout.new(ctx)
            layout.set_font_description(fd)
            layout.set_text(shape.text, -1)
            layout.set_alignment(Pango.Alignment.CENTER)
            anchor = shape.get_text_anchor()
            cx = anchor[0] * self._cell_w + self._cell_w / 2
            cy = anchor[1] * self._cell_h + self._cell_h / 2
            _, text_ext = layout.get_pixel_extents()
            vx = cx - text_ext.width / 2 - pad
            vy = cy - text_ext.height / 2 - pad
            vw = text_ext.width + 2 * pad
            vh = text_ext.height + 2 * pad
        else:
            bounds = shape.text_bounds()
            if not bounds:
                return
            left, top, right, bottom = bounds
            vx = left * self._cell_w - pad
            vy = top * self._cell_h - pad
            vw = (right - left + 1) * self._cell_w + 2 * pad
            vh = (bottom - top + 1) * self._cell_h + 2 * pad
        builder = Gsk.PathBuilder.new()
        builder.add_rect(Graphene.Rect().init(vx, vy, vw, vh))
        stroke = Gsk.Stroke.new(2.0)
        stroke.set_dash([5, 3])
        snapshot.append_stroke(builder.to_path(), stroke, tuple_to_gdk_rgba(accent, 0.7))

    def _draw_connection_hints(self, snapshot, arrow: ArrowShape, accent):
        """Draw a subtle highlight on each shape connected to this arrow."""
        for conn in [arrow.start_connection, arrow.end_connection]:
            if not conn:
                continue
            target = self._board.get_shape(conn.shape_id)
            if not target:
                continue
            ec, er = target.edge_point_from_connection(conn.edge, conn.ratio)
            cx = ec * self._cell_w + self._cell_w / 2
            cy = er * self._cell_h + self._cell_h / 2
            # Outer glow ring on the shape edge
            builder = Gsk.PathBuilder.new()
            builder.add_circle(Graphene.Point().init(cx, cy), 20)
            snapshot.append_fill(builder.to_path(), Gsk.FillRule.WINDING, tuple_to_gdk_rgba(accent, 0.35))
            # Mid glow ring
            builder = Gsk.PathBuilder.new()
            builder.add_circle(Graphene.Point().init(cx, cy), 12)
            snapshot.append_fill(builder.to_path(), Gsk.FillRule.WINDING, tuple_to_gdk_rgba(accent, 0.45))
            # Inner bright dot
            builder = Gsk.PathBuilder.new()
            builder.add_circle(Graphene.Point().init(cx, cy), 5)
            snapshot.append_fill(builder.to_path(), Gsk.FillRule.WINDING, tuple_to_gdk_rgba(accent, 0.85))
            # Highlight on the connected shape border
            sx = target.left * self._cell_w - 4
            sy = target.top * self._cell_h - 4
            sw = target.width * self._cell_w + 8
            sh = target.height * self._cell_h + 8
            builder = Gsk.PathBuilder.new()
            builder.add_rect(Graphene.Rect().init(sx, sy, sw, sh))
            stroke = Gsk.Stroke.new(2.5)
            snapshot.append_stroke(builder.to_path(), stroke, tuple_to_gdk_rgba(accent, 0.45))

    def _compute_alignment_guides(self):
        """Compute alignment guide lines between dragged shapes and other shapes."""
        self._alignment_guides.clear()
        moving_ids = self._selected_ids
        if not moving_ids:
            return

        # Collect edges and centers of moving shapes (non-arrows only)
        moving_lefts, moving_rights, moving_tops, moving_bottoms = [], [], [], []
        moving_cx, moving_cy = [], []
        for shape in self.selected_shapes:
            if isinstance(shape, ArrowShape):
                continue
            moving_lefts.append(shape.left)
            moving_rights.append(shape.right)
            moving_tops.append(shape.top)
            moving_bottoms.append(shape.bottom)
            moving_cx.append(shape.left + shape.width / 2)
            moving_cy.append(shape.top + shape.height / 2)

        if not moving_lefts:
            return

        # Collect edges and centers of stationary shapes
        guides = []
        for shape in self._board.shapes.values():
            if shape.id in moving_ids or isinstance(shape, ArrowShape):
                continue
            other_cols = [shape.left, shape.right, shape.left + shape.width / 2]
            other_rows = [shape.top, shape.bottom, shape.top + shape.height / 2]
            # Check vertical alignment (same column)
            for mc in moving_lefts + moving_rights + moving_cx:
                for oc in other_cols:
                    if abs(mc - oc) < 0.5:
                        guides.append(("v", oc))
            # Check horizontal alignment (same row)
            for mr in moving_tops + moving_bottoms + moving_cy:
                for orow in other_rows:
                    if abs(mr - orow) < 0.5:
                        guides.append(("h", orow))

        # Deduplicate
        self._alignment_guides = list(set(guides))

    def _draw_alignment_guides(self, snapshot, theme, width, height):
        """Draw alignment guide lines across the canvas."""
        accent = _hex(theme.accent_color)
        # Visible range in grid coords
        vw = width / self._zoom
        vh = height / self._zoom
        min_col = -self._pan_x / self._cell_w - 10 if self._cell_w > 0 else 0
        max_col = min_col + vw / self._cell_w + 20 if self._cell_w > 0 else 100
        min_row = -self._pan_y / self._cell_h - 10 if self._cell_h > 0 else 0
        max_row = min_row + vh / self._cell_h + 20 if self._cell_h > 0 else 100

        for kind, pos in self._alignment_guides:
            builder = Gsk.PathBuilder.new()
            if kind == "v":
                x = pos * self._cell_w + self._cell_w / 2
                builder.move_to(x, min_row * self._cell_h)
                builder.line_to(x, max_row * self._cell_h)
            else:
                y = pos * self._cell_h + self._cell_h / 2
                builder.move_to(min_col * self._cell_w, y)
                builder.line_to(max_col * self._cell_w, y)
            stroke = Gsk.Stroke.new(0.8)
            stroke.set_dash([6, 4])
            snapshot.append_stroke(builder.to_path(), stroke, tuple_to_gdk_rgba(accent, 0.5))

    def _draw_resize_handles(self, snapshot, shape, accent):
        hs = 4
        vx, vy, vw, vh = self._visual_bounds(shape)
        pts = [
            (vx, vy),
            (vx + vw / 2, vy),
            (vx + vw, vy),
            (vx, vy + vh / 2),
            (vx + vw, vy + vh / 2),
            (vx, vy + vh),
            (vx + vw / 2, vy + vh),
            (vx + vw, vy + vh),
        ]
        rgba = tuple_to_gdk_rgba(accent, 0.8)
        for hx, hy in pts:
            snapshot.append_color(rgba, Graphene.Rect().init(hx - hs, hy - hs, hs * 2, hs * 2))

    def _draw_editing_text(self, snapshot, fg, bg):
        """Clear and re-render text for non-font-size shapes during editing.

        Font-size shapes are rendered solely by _draw_custom_font_texts,
        so this only handles grid-based (non-font-size) shapes.
        """
        shape = self._board.get_shape(self._text_shape_id) if self._text_shape_id else None
        if not shape:
            return

        fs = getattr(shape, "font_size", None)

        if fs:
            # Font-size shapes: text rendered by _draw_custom_font_texts only
            return

        # --- clear the interior so the grid text underneath is hidden ---
        interior = getattr(shape, "get_interior_bounds", lambda: None)()
        if interior:
            il, it, ir, ib = interior
            x = il * self._cell_w
            y = it * self._cell_h
            w = (ir - il + 1) * self._cell_w
            h = (ib - it + 1) * self._cell_h
            snapshot.append_color(tuple_to_gdk_rgba(bg), Graphene.Rect().init(x, y, w, h))
        elif isinstance(shape, ArrowShape):
            anchor = shape.get_text_anchor()
            num_lines = len(self._text_buffer)
            max_w = max((len(l) for l in self._text_buffer), default=0)
            if max_w and num_lines:
                ax = (anchor[0] - max_w // 2 - 1) * self._cell_w
                ay = (anchor[1] - num_lines + 1) * self._cell_h
                aw = (max_w + 2) * self._cell_w
                ah = num_lines * self._cell_h
                snapshot.append_color(tuple_to_gdk_rgba(bg), Graphene.Rect().init(ax, ay, aw, ah))

        # --- render text from the buffer at cursor-aligned positions ---
        ctx = self.get_pango_context()
        if not ctx:
            return
        fg_rgba = tuple_to_gdk_rgba(fg)
        fd = Pango.FontDescription.new()
        fd.set_family(self._grid_font_family)
        fd.set_size(int(self._font_size * Pango.SCALE))
        layout = Pango.Layout.new(ctx)
        layout.set_font_description(fd)
        for line_idx, line_text in enumerate(self._text_buffer):
            for char_idx, ch in enumerate(line_text):
                col, row = self._text_pos_to_grid(line_idx, char_idx)
                layout.set_text(ch, -1)
                snapshot.save()
                snapshot.translate(Graphene.Point().init(col * self._cell_w, row * self._cell_h))
                snapshot.append_layout(layout, fg_rgba)
                snapshot.restore()

    def _draw_text_cursor(self, snapshot, theme):
        accent = _hex(theme.accent_color)
        shape = self._board.get_shape(self._text_shape_id) if self._text_shape_id else None
        fs = getattr(shape, "font_size", None) if shape else None
        if fs:
            x, y, h = self._custom_font_cursor_pos(shape)
            snapshot.append_color(tuple_to_gdk_rgba(accent, 0.8), Graphene.Rect().init(x, y, 2, h))
        else:
            x = self._text_cursor_col * self._cell_w
            y = self._text_cursor_row * self._cell_h
            snapshot.append_color(tuple_to_gdk_rgba(accent, 0.8), Graphene.Rect().init(x, y, 2, self._cell_h))

    def _text_pos_to_grid(self, line: int, char: int) -> tuple[int, int]:
        """Convert text buffer (line, char) to grid (col, row)."""
        shape = self._board.get_shape(self._text_shape_id) if self._text_shape_id else None
        if not shape:
            return (char, line)
        num_lines = len(self._text_buffer)
        line_text = self._text_buffer[line] if line < num_lines else ""
        if isinstance(shape, (RectangleShape, DatabaseShape, TopicShape, CloudShape)):
            interior = shape.get_interior_bounds()
            if interior:
                il, it, ir, ib = interior
                ih = ib - it + 1
                v_offset = max(0, (ih - num_lines) // 2)
                iw = ir - il + 1
                h_offset = max(0, (iw - len(line_text)) // 2)
                return (il + h_offset + char, it + v_offset + line)
            return (shape.left + char, shape.top + line)
        elif isinstance(shape, ArrowShape):
            anchor = shape.get_text_anchor()
            h_offset = -(len(line_text) // 2)
            return (anchor[0] + h_offset + char, anchor[1] - num_lines + line + 1)
        elif isinstance(shape, ActorShape):
            text_row = shape.top + shape.height - 1
            text_start = shape.left + (shape.width - len(line_text)) // 2
            return (text_start + char, text_row)
        elif isinstance(shape, TopicShape):
            interior = shape.get_interior_bounds()
            if interior:
                il, it, ir, ib = interior
                ih = ib - it + 1
                iw = ir - il + 1
                v_offset = max(0, (ih - num_lines) // 2)
                h_offset = max(0, (iw - len(line_text)) // 2)
                return (il + h_offset + char, it + v_offset + line)
            return (shape.left + 1 + char, shape.top)
        return (char, line)

    def _draw_text_selection(self, snapshot, theme, fg_color, bg_color):
        """Draw highlight rectangles over selected text and redraw chars with contrast."""
        if not self._has_text_selection():
            return
        sl, sc, el, ec = self._get_text_selection_ordered()
        accent = _hex(theme.accent_color)
        shape = self._board.get_shape(self._text_shape_id) if self._text_shape_id else None
        fs = getattr(shape, "font_size", None) if shape else None
        accent_rgba = tuple_to_gdk_rgba(accent, 0.45)

        # Collect rectangles and selected text fragments for redrawing
        rects = []
        for line_idx in range(sl, el + 1):
            line_text = self._text_buffer[line_idx] if line_idx < len(self._text_buffer) else ""
            start_c = sc if line_idx == sl else 0
            end_c = ec if line_idx == el else len(line_text)
            if start_c >= end_c:
                continue
            if fs and shape:
                xs, ys, lh = self._custom_font_cursor_pos(shape, line_idx, start_c)
                xe, _, _ = self._custom_font_cursor_pos(shape, line_idx, end_c)
                snapshot.append_color(accent_rgba, Graphene.Rect().init(xs, ys, xe - xs, lh))
                rects.append(("custom", line_idx, start_c, end_c, xs, ys, lh))
            else:
                cs, rs = self._text_pos_to_grid(line_idx, start_c)
                ce, _ = self._text_pos_to_grid(line_idx, end_c)
                snapshot.append_color(
                    accent_rgba,
                    Graphene.Rect().init(cs * self._cell_w, rs * self._cell_h, (ce - cs) * self._cell_w, self._cell_h),
                )
                rects.append(("grid", line_idx, start_c, end_c, cs, rs, None))

        # Redraw selected characters on top with background color for contrast
        ctx = self.get_pango_context()
        if not ctx:
            return
        bg_rgba = tuple_to_gdk_rgba(bg_color)
        fd = Pango.FontDescription.new()
        layout = Pango.Layout.new(ctx)
        for entry in rects:
            mode = entry[0]
            line_idx, start_c, end_c = entry[1], entry[2], entry[3]
            line_text = self._text_buffer[line_idx] if line_idx < len(self._text_buffer) else ""
            sel_text = line_text[start_c:end_c]
            if not sel_text:
                continue
            if mode == "custom" and fs:
                fd.set_family(self._font_family)
                xs, ys = entry[4], entry[5]
                fd.set_size(int(fs * Pango.SCALE))
                layout.set_font_description(fd)
                layout.set_text(sel_text, -1)
                snapshot.save()
                snapshot.translate(Graphene.Point().init(xs, ys))
                snapshot.append_layout(layout, bg_rgba)
                snapshot.restore()
            else:
                fd.set_family(self._grid_font_family)
                cs, rs = entry[4], entry[5]
                fd.set_size(int(self._font_size * Pango.SCALE))
                layout.set_font_description(fd)
                for j, ch in enumerate(sel_text):
                    layout.set_text(ch, -1)
                    snapshot.save()
                    snapshot.translate(Graphene.Point().init((cs + j) * self._cell_w, rs * self._cell_h))
                    snapshot.append_layout(layout, bg_rgba)
                    snapshot.restore()

    # ─────────────────────── Mouse Events ───────────────────────

    def _on_click(self, gesture, n_press, x, y):
        """Handle clicks: single-click exits text edit; double-click enters it."""
        # Single click while text editing: exit if outside shape, stay if inside
        if n_press == 1 and self._text_editing:
            col, row = self._screen_to_grid(x, y)
            shape = self._board.get_shape(self._text_shape_id)
            if not shape or not shape.contains(col, row):
                self._exit_text_edit()
                self._selected_ids.clear()
            self._double_click_pending = True  # always suppress drag-begin
            self.queue_draw()
            return

        if n_press >= 2:
            self._double_click_pending = True
            self._cancel_drawing()
            col, row = self._screen_to_grid(x, y)
            shape = self._board.get_shape_at(col, row)
            if shape:
                self._start_text_edit_for_shape(shape)
            else:
                # Multi-click outside any shape: exit text edit and deselect
                self._exit_text_edit()
                self._selected_ids.clear()
            self.queue_draw()

    def _cancel_drawing(self):
        self._drawing = False
        self._draw_start = None
        self._draw_end = None
        self._draw_snap_start = None
        self._draw_snap_end = None
        self._drag_start_screen = None
        self._marquee_selecting = False
        self._marquee_start = None
        self._marquee_end = None

    def _on_drag_begin(self, gesture, sx, sy):
        self.grab_focus()

        # Skip if double-click was just handled
        if self._double_click_pending:
            self._double_click_pending = False
            return

        btn = gesture.get_current_button()
        col, row = self._screen_to_grid(sx, sy)

        # Right-click → shape properties popup or pan
        if btn == 3:
            shape = self._board.get_shape_at(col, row)
            if shape:
                text_only = isinstance(shape, ArrowShape) and shape.text_contains(col, row)
                if shape.id in self._selected_ids and len(self._selected_ids) > 1:
                    shapes = self.selected_shapes
                else:
                    self._selected_ids = {shape.id}
                    self._text_only_selection = text_only
                    shapes = [shape]
                self.queue_draw()
                self._show_shape_properties(shapes, sx, sy, text_only=text_only)
                return
            self._panning = True
            self._pan_start_offset = (self._pan_x, self._pan_y)
            self._drag_start_screen = (sx, sy)
            return

        # Middle-click → pan
        if btn == 2:
            self._panning = True
            self._pan_start_offset = (self._pan_x, self._pan_y)
            self._drag_start_screen = (sx, sy)
            return

        if btn != 1:
            return

        # Pan tool – left-click drag pans the view
        if self._tool == ToolMode.PAN:
            self._panning = True
            self._pan_start_offset = (self._pan_x, self._pan_y)
            self._drag_start_screen = (sx, sy)
            return

        # Text editing is fully handled by _on_click; never start drag while editing
        if self._text_editing:
            return

        if self._tool == ToolMode.SELECT:
            # Check resize/endpoint handles BEFORE re-selecting (handles may be outside shape body)
            if len(self._selected_ids) == 1:
                # Arrow endpoint handles
                for shape in self.selected_shapes:
                    if isinstance(shape, ArrowShape):
                        ep = self._hit_arrow_endpoint(shape, sx, sy)
                        if ep:
                            self._arrow_ep_dragging = True
                            self._arrow_ep_end = ep
                            self._arrow_ep_shape_id = shape.id
                            self._drag_start_screen = (sx, sy)
                            return

                # Rectangle resize handles
                handle = self._hit_resize_handle(sx, sy)
                if handle:
                    shape = self.selected_shapes[0]
                    self._resizing = True
                    self._resize_handle = handle
                    self._resize_shape_id = shape.id
                    self._resize_orig = shape.to_dict()
                    self._drag_start_screen = (sx, sy)
                    return

            # Select shape under cursor (pass modifier for Cmd+click multi-select)
            state = gesture.get_current_event_state()
            cmd_held = bool(state & Gdk.ModifierType.META_MASK)
            self._handle_select_press(col, row, sx, sy, cmd_held=cmd_held)

            # Move drag
            if self._selected_ids:
                for shape in self.selected_shapes:
                    if shape.contains(col, row):
                        self._dragging = True
                        self._drag_start_screen = (sx, sy)
                        self._drag_start_pos = {}
                        for s in self.selected_shapes:
                            if isinstance(s, ArrowShape):
                                if self._text_only_selection and len(self._selected_ids) == 1:
                                    self._drag_start_pos[s.id] = (s.text_offset_col, s.text_offset_row)
                                else:
                                    self._drag_start_pos[s.id] = (s.start_col, s.start_row, s.end_col, s.end_row)
                            else:
                                self._drag_start_pos[s.id] = (s.left, s.top)
                        return

        elif self._tool == ToolMode.RECTANGLE:
            self._drawing = True
            self._draw_start = (col, row)
            self._draw_end = (col, row)
            self._drag_start_screen = (sx, sy)

        elif self._tool == ToolMode.ARROW:
            self._drawing = True
            snap = self._board.snap_to_edge(col, row)
            if snap:
                conn, sc, sr = snap
                self._draw_start = (sc, sr)
                self._draw_snap_start = snap
            else:
                self._draw_start = (col, row)
                self._draw_snap_start = None
            self._draw_end = self._draw_start
            self._drag_start_screen = (sx, sy)

        elif self._tool == ToolMode.ACTOR:
            # Place actor immediately on click, then revert to select
            actor = ActorShape(left=col, top=row)
            self._board.add_shape(actor)
            self._selected_ids = {actor.id}
            self._snapshot_history()
            self._tool = ToolMode.SELECT
            if self._on_tool_change:
                self._on_tool_change(ToolMode.SELECT)
            self.queue_draw()

        elif self._tool == ToolMode.DATABASE:
            # Place database immediately on click, then revert to select
            db = DatabaseShape(left=col, top=row)
            self._board.add_shape(db)
            self._selected_ids = {db.id}
            self._snapshot_history()
            self._tool = ToolMode.SELECT
            if self._on_tool_change:
                self._on_tool_change(ToolMode.SELECT)
            self.queue_draw()

        elif self._tool == ToolMode.TOPIC:
            # Start drawing a topic shape (like rectangle)
            self._drawing = True
            self._draw_start = (col, row)
            self._draw_end = (col, row)
            self._drag_start_screen = (sx, sy)

        elif self._tool == ToolMode.CLOUD:
            # Start drawing a cloud shape (like rectangle)
            self._drawing = True
            self._draw_start = (col, row)
            self._draw_end = (col, row)
            self._drag_start_screen = (sx, sy)

    def _on_drag_update(self, gesture, ox, oy):
        # Drawing creation
        if self._drawing and self._draw_start and self._drag_start_screen:
            sx, sy = self._drag_start_screen
            col, row = self._screen_to_grid(sx + ox, sy + oy)
            if self._tool == ToolMode.ARROW:
                snap = self._board.snap_to_edge(col, row)
                if snap:
                    self._draw_end = (snap[1], snap[2])
                    self._draw_snap_end = snap
                else:
                    self._draw_end = (col, row)
                    self._draw_snap_end = None
            else:
                self._draw_end = (col, row)
            self.queue_draw()
            return

        # Arrow endpoint drag
        if self._arrow_ep_dragging and self._drag_start_screen:
            sx, sy = self._drag_start_screen
            col, row = self._screen_to_grid(sx + ox, sy + oy)
            shape = self._board.get_shape(self._arrow_ep_shape_id)
            if shape and isinstance(shape, ArrowShape):
                snap = self._board.snap_to_edge(col, row, exclude_id=shape.id)
                if self._arrow_ep_end == "start":
                    if snap:
                        shape.start_col, shape.start_row = snap[1], snap[2]
                        conn = snap[0]
                        conn.pinned = True  # manual placement → immune to auto-optimization
                        shape.start_connection = conn
                    else:
                        shape.start_col, shape.start_row = col, row
                        shape.start_connection = None
                else:
                    if snap:
                        shape.end_col, shape.end_row = snap[1], snap[2]
                        conn = snap[0]
                        conn.pinned = True  # manual placement → immune to auto-optimization
                        shape.end_connection = conn
                    else:
                        shape.end_col, shape.end_row = col, row
                        shape.end_connection = None
                shape._update_bounds()
            self.queue_draw()
            return

        # Rectangle resize
        if self._resizing and self._drag_start_screen and self._resize_orig:
            sx, sy = self._drag_start_screen
            col, row = self._screen_to_grid(sx + ox, sy + oy)
            self._apply_resize(col, row)
            self._board.update_connections()
            self.queue_draw()
            return

        # Move
        if self._dragging and self._drag_start_screen:
            dcol = round(ox / self._zoom / self._cell_w) if self._cell_w > 0 else 0
            drow = round(oy / self._zoom / self._cell_h) if self._cell_h > 0 else 0

            # Text-only drag: move just the text offset on the arrow
            if self._text_only_selection and len(self._selected_ids) == 1:
                for shape in self.selected_shapes:
                    if isinstance(shape, ArrowShape):
                        orig = self._drag_start_pos.get(shape.id)
                        if orig and len(orig) == 2:
                            shape.text_offset_col = orig[0] + dcol
                            shape.text_offset_row = orig[1] + drow
                self.queue_draw()
                return

            moving_ids = self._selected_ids
            for shape in self.selected_shapes:
                orig = self._drag_start_pos.get(shape.id)
                if not orig:
                    continue
                if isinstance(shape, ArrowShape):
                    osc, osr, oec, oer = orig
                    # Only move endpoints not magnetically connected to non-moving boxes
                    if not shape.start_connection or shape.start_connection.shape_id in moving_ids:
                        shape.start_col = osc + dcol
                        shape.start_row = osr + drow
                    if not shape.end_connection or shape.end_connection.shape_id in moving_ids:
                        shape.end_col = oec + dcol
                        shape.end_row = oer + drow
                    shape._update_bounds()
                else:
                    shape.left = orig[0] + dcol
                    shape.top = orig[1] + drow
            self._board.update_connections()
            self._compute_alignment_guides()
            self.queue_draw()
            return

        # Marquee selection
        if self._marquee_selecting and self._drag_start_screen:
            sx, sy = self._drag_start_screen
            col, row = self._screen_to_grid(sx + ox, sy + oy)
            self._marquee_end = (col, row)
            self.queue_draw()
            return

        # Pan
        if self._panning and self._pan_start_offset:
            self._pan_x = self._pan_start_offset[0] + ox / self._zoom
            self._pan_y = self._pan_start_offset[1] + oy / self._zoom
            self._target_pan_x = self._pan_x
            self._target_pan_y = self._pan_y
            self._clamp_pan()
            self.queue_draw()

    def _on_drag_end(self, gesture, ox, oy):
        if self._drawing:
            if self._drag_start_screen:
                sx, sy = self._drag_start_screen
                col, row = self._screen_to_grid(sx + ox, sy + oy)
                if self._tool == ToolMode.ARROW:
                    snap = self._board.snap_to_edge(col, row)
                    if snap:
                        self._draw_end = (snap[1], snap[2])
                        self._draw_snap_end = snap
                    else:
                        self._draw_end = (col, row)
                else:
                    self._draw_end = (col, row)
            self._finish_drawing()
            self._cancel_drawing()
            self.queue_draw()
            return
        if self._arrow_ep_dragging:
            # Apply final endpoint position from drag-end coordinates
            if self._drag_start_screen and self._arrow_ep_shape_id:
                sx, sy = self._drag_start_screen
                col, row = self._screen_to_grid(sx + ox, sy + oy)
                shape = self._board.get_shape(self._arrow_ep_shape_id)
                if shape and isinstance(shape, ArrowShape):
                    snap = self._board.snap_to_edge(col, row, exclude_id=shape.id)
                    if self._arrow_ep_end == "start":
                        if snap:
                            shape.start_col, shape.start_row = snap[1], snap[2]
                            conn = snap[0]
                            conn.pinned = True
                            shape.start_connection = conn
                        else:
                            shape.start_col, shape.start_row = col, row
                            shape.start_connection = None
                    else:
                        if snap:
                            shape.end_col, shape.end_row = snap[1], snap[2]
                            conn = snap[0]
                            conn.pinned = True
                            shape.end_connection = conn
                        else:
                            shape.end_col, shape.end_row = col, row
                            shape.end_connection = None
                    shape._update_bounds()
            self._arrow_ep_dragging = False
            self._arrow_ep_end = None
            self._arrow_ep_shape_id = None
            self._snapshot_history()
        if self._resizing:
            # Apply final resize from drag-end coordinates (the last drag-update
            # may have been coalesced by GTK, so re-apply with the actual end offsets).
            if self._drag_start_screen and self._resize_orig:
                sx, sy = self._drag_start_screen
                col, row = self._screen_to_grid(sx + ox, sy + oy)
                self._apply_resize(col, row)
            self._resizing = False
            self._resize_handle = None
            self._resize_shape_id = None
            self._resize_orig = None
            self._board.update_connections()
            self._snapshot_history()
        if self._dragging:
            # Apply final move position from drag-end coordinates
            if self._drag_start_screen and self._cell_w > 0 and self._cell_h > 0:
                dcol = round(ox / self._zoom / self._cell_w)
                drow = round(oy / self._zoom / self._cell_h)
                if self._text_only_selection and len(self._selected_ids) == 1:
                    for shape in self.selected_shapes:
                        if isinstance(shape, ArrowShape):
                            orig = self._drag_start_pos.get(shape.id)
                            if orig and len(orig) == 2:
                                shape.text_offset_col = orig[0] + dcol
                                shape.text_offset_row = orig[1] + drow
                else:
                    moving_ids = self._selected_ids
                    for shape in self.selected_shapes:
                        orig = self._drag_start_pos.get(shape.id)
                        if not orig:
                            continue
                        if isinstance(shape, ArrowShape):
                            osc, osr, oec, oer = orig
                            if not shape.start_connection or shape.start_connection.shape_id in moving_ids:
                                shape.start_col = osc + dcol
                                shape.start_row = osr + drow
                            if not shape.end_connection or shape.end_connection.shape_id in moving_ids:
                                shape.end_col = oec + dcol
                                shape.end_row = oer + drow
                            shape._update_bounds()
                        else:
                            shape.left = orig[0] + dcol
                            shape.top = orig[1] + drow
                    self._board.update_connections()
            self._dragging = False
            self._drag_start_pos.clear()
            self._alignment_guides.clear()
            self._snapshot_history()
        if self._marquee_selecting:
            if self._marquee_start and self._marquee_end:
                ms, me = self._marquee_start, self._marquee_end
                left = min(ms[0], me[0])
                top = min(ms[1], me[1])
                right = max(ms[0], me[0])
                bottom = max(ms[1], me[1])
                hits = self._board.shapes_in_region(left, top, right, bottom)
                self._selected_ids = {s.id for s in hits}
            self._marquee_selecting = False
            self._marquee_start = None
            self._marquee_end = None
            self.queue_draw()
        if self._panning:
            self._panning = False
            self._pan_start_offset = None
        self._drag_start_screen = None

    def _on_motion(self, controller, x, y):
        col, row = self._screen_to_grid(x, y)
        if self._on_status_change:
            self._on_status_change(col, row, int(self._zoom * 100))

    def _on_scroll(self, controller, dx, dy):
        state = controller.get_current_event_state()
        if state & _MOD:
            self.zoom(-0.1 if dy > 0 else 0.1)
        else:
            self._target_pan_x -= dx * self._SCROLL_PAN_STEP / self._zoom
            self._target_pan_y -= dy * self._SCROLL_PAN_STEP / self._zoom
            if self._scroll_tick_id is None:
                self._scroll_tick_id = self.add_tick_callback(self._scroll_tick)
        return True

    def _on_scroll_end(self, controller):
        """Snap to final target when kinetic scrolling finishes."""
        if self._scroll_tick_id is not None:
            self._pan_x = self._target_pan_x
            self._pan_y = self._target_pan_y
            self._clamp_pan()
            self._target_pan_x = self._pan_x
            self._target_pan_y = self._pan_y
            self.remove_tick_callback(self._scroll_tick_id)
            self._scroll_tick_id = None
            self.queue_draw()

    def _scroll_tick(self, widget, frame_clock):
        lerp = self._smooth_lerp
        prev_x, prev_y = self._pan_x, self._pan_y
        self._pan_x += (self._target_pan_x - self._pan_x) * lerp
        self._pan_y += (self._target_pan_y - self._pan_y) * lerp
        self._clamp_pan()
        # If clamped, snap target to actual to avoid fighting the boundary
        if self._pan_x != prev_x + (self._target_pan_x - prev_x) * lerp:
            self._target_pan_x = self._pan_x
        if self._pan_y != prev_y + (self._target_pan_y - prev_y) * lerp:
            self._target_pan_y = self._pan_y
        self.queue_draw()
        # Stop ticking once close enough
        if abs(self._target_pan_x - self._pan_x) < 0.5 and abs(self._target_pan_y - self._pan_y) < 0.5:
            self._pan_x = self._target_pan_x
            self._pan_y = self._target_pan_y
            self._scroll_tick_id = None
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    # ─────────────────────── Select Tool ───────────────────────

    def _handle_select_press(self, col: int, row: int, sx: float, sy: float, *, cmd_held: bool = False):
        self._exit_text_edit()
        shape = self._board.get_shape_at(col, row)
        # Detect text-only hit on arrow labels
        text_only = isinstance(shape, ArrowShape) and shape.text_contains(col, row)
        if shape:
            if cmd_held:
                if shape.id in self._selected_ids:
                    self._selected_ids.discard(shape.id)
                else:
                    self._selected_ids.add(shape.id)
                self._text_only_selection = False
            else:
                if shape.id not in self._selected_ids:
                    self._selected_ids = {shape.id}
                self._text_only_selection = text_only
        else:
            if not cmd_held:
                self._selected_ids.clear()
            self._text_only_selection = False
            self._marquee_selecting = True
            self._marquee_start = (col, row)
            self._marquee_end = (col, row)
            self._drag_start_screen = (sx, sy)
        self.queue_draw()

    def _hit_resize_handle(self, sx: float, sy: float) -> str | None:
        if not self._selected_ids:
            return None
        shape = self.selected_shapes[0] if self.selected_shapes else None
        if not shape or isinstance(shape, ArrowShape):
            return None
        r = 8
        vx, vy, vw, vh = self._visual_bounds(shape)

        # Convert canvas coords to screen coords
        def _to_screen(cx, cy):
            return ((cx + self._pan_x) * self._zoom, (cy + self._pan_y) * self._zoom)

        handles = {
            "tl": _to_screen(vx, vy),
            "tr": _to_screen(vx + vw, vy),
            "bl": _to_screen(vx, vy + vh),
            "br": _to_screen(vx + vw, vy + vh),
            "tc": _to_screen(vx + vw / 2, vy),
            "bc": _to_screen(vx + vw / 2, vy + vh),
            "ml": _to_screen(vx, vy + vh / 2),
            "mr": _to_screen(vx + vw, vy + vh / 2),
        }
        for name, (hx, hy) in handles.items():
            if abs(sx - hx) <= r and abs(sy - hy) <= r:
                return name
        return None

    def _hit_arrow_endpoint(self, shape: ArrowShape, sx: float, sy: float) -> str | None:
        r = 10
        for end_name, (c, rr) in [("start", (shape.start_col, shape.start_row)), ("end", (shape.end_col, shape.end_row))]:
            ex, ey = self._grid_to_screen(c, rr)
            # Center of the cell
            ex += self._cell_w * self._zoom / 2
            ey += self._cell_h * self._zoom / 2
            if abs(sx - ex) <= r and abs(sy - ey) <= r:
                return end_name
        return None

    def _apply_resize(self, cursor_col: int, cursor_row: int):
        shape = self._board.get_shape(self._resize_shape_id)
        if not shape or isinstance(shape, (ArrowShape, ActorShape)):
            return
        o = self._resize_orig
        ol, ot = o["left"], o["top"]
        or_ = ol + o["width"] - 1
        ob = ot + o["height"] - 1
        nl, nt, nr, nb = ol, ot, or_, ob
        h = self._resize_handle
        if h in ("tl", "ml", "bl"):
            nl = min(cursor_col, or_ - 1)
        if h in ("tr", "mr", "br"):
            nr = max(cursor_col, ol + 1)
        if h in ("tl", "tc", "tr"):
            nt = min(cursor_row, ob - 1)
        if h in ("bl", "bc", "br"):
            nb = max(cursor_row, ot + 1)
        # Enforce minimum size
        min_w, min_h = 2, 2
        if isinstance(shape, DatabaseShape):
            min_w, min_h = shape.min_size_for_text() if shape.text else (DATABASE_MIN_WIDTH, DATABASE_MIN_HEIGHT)
        elif isinstance(shape, CloudShape):
            min_w, min_h = shape.min_size_for_text() if shape.text else (CLOUD_MIN_WIDTH, CLOUD_MIN_HEIGHT)
        elif isinstance(shape, TopicShape):
            min_w, min_h = TOPIC_MIN_WIDTH, TOPIC_MIN_HEIGHT
        elif isinstance(shape, RectangleShape) and shape.text:
            min_w, min_h = shape.min_size_for_text()
        if nr - nl + 1 < min_w:
            if h in ("tl", "ml", "bl"):
                nl = nr - min_w + 1
            else:
                nr = nl + min_w - 1
        if nb - nt + 1 < min_h:
            if h in ("tl", "tc", "tr"):
                nt = nb - min_h + 1
            else:
                nb = nt + min_h - 1
        shape.left = nl
        shape.top = nt
        shape.width = nr - nl + 1
        shape.height = nb - nt + 1

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

    # ─────────────────────── Text Editing ───────────────────────

    def _start_text_edit_for_shape(self, shape: AbstractShape):
        self._exit_text_edit()
        # Reset any drag state left over from the first click of a double-click
        self._dragging = False
        self._drag_start_pos.clear()
        self._text_editing = True
        self._text_shape_id = shape.id
        self._selected_ids = {shape.id}

        if isinstance(shape, (RectangleShape, DatabaseShape, CloudShape)):
            self._text_buffer = shape.text.split("\n") if shape.text else [""]
            self._text_cursor_line = len(self._text_buffer) - 1
            self._text_cursor_char = len(self._text_buffer[-1])
            interior = shape.get_interior_bounds()
            if interior:
                self._update_text_cursor_position(shape)
            else:
                self._text_cursor_col = shape.left
                self._text_cursor_row = shape.top
        elif isinstance(shape, ArrowShape):
            self._text_buffer = shape.text.split("\n") if shape.text else [""]
            self._text_cursor_line = len(self._text_buffer) - 1
            self._text_cursor_char = len(self._text_buffer[-1])
            self._update_text_cursor_position(shape)
        elif isinstance(shape, ActorShape):
            self._text_buffer = [shape.text] if shape.text else [""]
            self._text_cursor_line = 0
            self._text_cursor_char = len(self._text_buffer[0])
            self._update_text_cursor_position(shape)
        elif isinstance(shape, TopicShape):
            if shape.font_size:
                self._text_buffer = shape.text.split("\n") if shape.text else [""]
                self._text_cursor_line = len(self._text_buffer) - 1
                self._text_cursor_char = len(self._text_buffer[-1])
            else:
                self._text_buffer = [shape.text] if shape.text else [""]
                self._text_cursor_line = 0
                self._text_cursor_char = len(self._text_buffer[0])
            self._update_text_cursor_position(shape)
        self._collapse_selection()
        self.queue_draw()

    def _exit_text_edit(self):
        if not self._text_editing:
            return
        self._text_editing = False
        shape = self._board.get_shape(self._text_shape_id) if self._text_shape_id else None
        if shape:
            text = "\n".join(self._text_buffer)
            if isinstance(shape, (RectangleShape, DatabaseShape, ArrowShape, CloudShape)):
                shape.text = text
            elif isinstance(shape, ActorShape):
                shape.text = self._text_buffer[0] if self._text_buffer else ""
                shape.__post_init__()  # Update bounds for text
            elif isinstance(shape, TopicShape):
                if shape.font_size:
                    shape.text = text
                else:
                    shape.text = self._text_buffer[0] if self._text_buffer else ""
            self._snapshot_history()
        self._text_shape_id = None
        self._text_buffer = []
        self._text_cursor_line = 0
        self._text_cursor_char = 0
        self._text_sel_anchor_line = 0
        self._text_sel_anchor_char = 0
        self.queue_draw()

    def _update_text_cursor_position(self, shape=None):
        """Compute cursor position from centered text layout."""
        if shape is None:
            shape = self._board.get_shape(self._text_shape_id) if self._text_shape_id else None
        if not shape:
            return
        num_lines = len(self._text_buffer)
        cur_line = self._text_cursor_line
        cur_char = self._text_cursor_char
        line_text = self._text_buffer[cur_line] if cur_line < num_lines else ""
        if isinstance(shape, (RectangleShape, DatabaseShape, CloudShape)):
            interior = shape.get_interior_bounds()
            if not interior:
                return
            il, it, ir, ib = interior
            inner_w = ir - il + 1
            inner_h = ib - it + 1
            v_offset = max(0, (inner_h - num_lines) // 2)
            h_offset = max(0, (inner_w - len(line_text)) // 2)
            self._text_cursor_row = it + v_offset + cur_line
            self._text_cursor_col = il + h_offset + cur_char
        elif isinstance(shape, ArrowShape):
            anchor = shape.get_text_anchor()
            line_text = self._text_buffer[cur_line] if cur_line < num_lines else ""
            h_offset = -(len(line_text) // 2)  # center text horizontally
            self._text_cursor_col = anchor[0] + h_offset + cur_char
            self._text_cursor_row = anchor[1] - num_lines + cur_line + 1
        elif isinstance(shape, ActorShape):
            # Text label positioned below the actor figure
            text_row = shape.top + ACTOR_HEIGHT
            text_start = shape.left + (ACTOR_WIDTH - len(line_text)) // 2
            self._text_cursor_row = text_row
            self._text_cursor_col = text_start + cur_char
        elif isinstance(shape, TopicShape):
            interior = shape.get_interior_bounds()
            if interior:
                il, it, ir, ib = interior
                inner_w = ir - il + 1
                inner_h = ib - it + 1
                v_offset = max(0, (inner_h - num_lines) // 2)
                h_offset = max(0, (inner_w - len(line_text)) // 2)
                self._text_cursor_row = it + v_offset + cur_line
                self._text_cursor_col = il + h_offset + cur_char
            else:
                left_div = 2
                right_div = shape.width - 3
                text_col = shape.left + left_div + 1 + (right_div - left_div - 1 - len(line_text)) // 2
                text_row = shape.top + shape.height // 2
                self._text_cursor_row = text_row
                self._text_cursor_col = text_col + cur_char

    def _handle_text_key(self, keyval: int, state: int) -> bool:
        mod = bool(state & _MOD)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        alt = bool(state & Gdk.ModifierType.ALT_MASK)

        if keyval == Gdk.KEY_Escape:
            self._exit_text_edit()
            return True

        # Cmd+A: select all text in shape
        if mod and keyval == Gdk.KEY_a:
            self._text_sel_anchor_line = 0
            self._text_sel_anchor_char = 0
            self._text_cursor_line = len(self._text_buffer) - 1
            self._text_cursor_char = len(self._text_buffer[-1]) if self._text_buffer else 0
            self._update_text_cursor_position()
            self.queue_draw()
            return True

        # Cmd+C: copy selected text
        if mod and keyval == Gdk.KEY_c:
            text = self._get_selected_text()
            if text:
                self.get_clipboard().set(text)
            return True

        # Cmd+X: cut selected text
        if mod and keyval == Gdk.KEY_x:
            text = self._get_selected_text()
            if text:
                self.get_clipboard().set(text)
                self._delete_text_selection()
                self._sync_text()
                self._update_text_cursor_position()
                self.queue_draw()
            return True

        # Cmd+V: paste text
        if mod and keyval == Gdk.KEY_v:
            self.get_clipboard().read_text_async(None, self._on_text_edit_paste_done)
            return True

        # Arrow keys with modifier support
        if keyval == Gdk.KEY_Left:
            if not shift and self._has_text_selection():
                sl, sc, _, _ = self._get_text_selection_ordered()
                self._text_cursor_line, self._text_cursor_char = sl, sc
            elif mod:
                self._text_cursor_char = 0
            elif alt:
                self._move_cursor_word_left()
            else:
                if self._text_cursor_char > 0:
                    self._text_cursor_char -= 1
                elif self._text_cursor_line > 0:
                    self._text_cursor_line -= 1
                    self._text_cursor_char = len(self._text_buffer[self._text_cursor_line])
            if not shift:
                self._collapse_selection()
            self._update_text_cursor_position()
            self.queue_draw()
            return True

        if keyval == Gdk.KEY_Right:
            if not shift and self._has_text_selection():
                _, _, el, ec = self._get_text_selection_ordered()
                self._text_cursor_line, self._text_cursor_char = el, ec
            elif mod:
                self._text_cursor_char = len(self._text_buffer[self._text_cursor_line]) if self._text_buffer else 0
            elif alt:
                self._move_cursor_word_right()
            else:
                line = self._text_buffer[self._text_cursor_line]
                if self._text_cursor_char < len(line):
                    self._text_cursor_char += 1
                elif self._text_cursor_line < len(self._text_buffer) - 1:
                    self._text_cursor_line += 1
                    self._text_cursor_char = 0
            if not shift:
                self._collapse_selection()
            self._update_text_cursor_position()
            self.queue_draw()
            return True

        if keyval == Gdk.KEY_Up:
            if self._text_cursor_line > 0:
                self._text_cursor_line -= 1
                self._text_cursor_char = min(self._text_cursor_char, len(self._text_buffer[self._text_cursor_line]))
            if not shift:
                self._collapse_selection()
            self._update_text_cursor_position()
            self.queue_draw()
            return True

        if keyval == Gdk.KEY_Down:
            if self._text_cursor_line < len(self._text_buffer) - 1:
                self._text_cursor_line += 1
                self._text_cursor_char = min(self._text_cursor_char, len(self._text_buffer[self._text_cursor_line]))
            if not shift:
                self._collapse_selection()
            self._update_text_cursor_position()
            self.queue_draw()
            return True

        # Home / End
        if keyval == Gdk.KEY_Home:
            self._text_cursor_char = 0
            if not shift:
                self._collapse_selection()
            self._update_text_cursor_position()
            self.queue_draw()
            return True

        if keyval == Gdk.KEY_End:
            self._text_cursor_char = len(self._text_buffer[self._text_cursor_line]) if self._text_buffer else 0
            if not shift:
                self._collapse_selection()
            self._update_text_cursor_position()
            self.queue_draw()
            return True

        # Return
        if keyval == Gdk.KEY_Return:
            if self._has_text_selection():
                self._delete_text_selection()
            shape = self._board.get_shape(self._text_shape_id)
            if shape and isinstance(shape, (RectangleShape, DatabaseShape, TopicShape, CloudShape)):
                interior = shape.get_interior_bounds()
                if interior and len(self._text_buffer) >= interior[3] - interior[1] + 1:
                    return True
            line = self._text_buffer[self._text_cursor_line]
            after = line[self._text_cursor_char :]
            self._text_buffer[self._text_cursor_line] = line[: self._text_cursor_char]
            self._text_buffer.insert(self._text_cursor_line + 1, after)
            self._text_cursor_line += 1
            self._text_cursor_char = 0
            self._collapse_selection()
            self._sync_text()
            self._update_text_cursor_position()
            self.queue_draw()
            return True

        # Backspace
        if keyval == Gdk.KEY_BackSpace:
            if self._has_text_selection():
                self._delete_text_selection()
            elif alt:
                # Option+Backspace: delete word left
                line = self._text_buffer[self._text_cursor_line]
                pos = self._text_cursor_char
                while pos > 0 and line[pos - 1] == " ":
                    pos -= 1
                while pos > 0 and line[pos - 1] != " ":
                    pos -= 1
                self._text_buffer[self._text_cursor_line] = line[:pos] + line[self._text_cursor_char :]
                self._text_cursor_char = pos
            elif self._text_cursor_char > 0:
                line = self._text_buffer[self._text_cursor_line]
                self._text_buffer[self._text_cursor_line] = (
                    line[: self._text_cursor_char - 1] + line[self._text_cursor_char :]
                )
                self._text_cursor_char -= 1
            elif self._text_cursor_line > 0:
                prev_len = len(self._text_buffer[self._text_cursor_line - 1])
                self._text_buffer[self._text_cursor_line - 1] += self._text_buffer[self._text_cursor_line]
                self._text_buffer.pop(self._text_cursor_line)
                self._text_cursor_line -= 1
                self._text_cursor_char = prev_len
            self._collapse_selection()
            self._sync_text()
            self._update_text_cursor_position()
            self.queue_draw()
            return True

        # Delete (forward)
        if keyval == Gdk.KEY_Delete:
            if self._has_text_selection():
                self._delete_text_selection()
            else:
                line = self._text_buffer[self._text_cursor_line]
                if self._text_cursor_char < len(line):
                    self._text_buffer[self._text_cursor_line] = (
                        line[: self._text_cursor_char] + line[self._text_cursor_char + 1 :]
                    )
                elif self._text_cursor_line < len(self._text_buffer) - 1:
                    self._text_buffer[self._text_cursor_line] += self._text_buffer[self._text_cursor_line + 1]
                    self._text_buffer.pop(self._text_cursor_line + 1)
            self._collapse_selection()
            self._sync_text()
            self._update_text_cursor_position()
            self.queue_draw()
            return True

        # Regular character input
        ch = chr(keyval) if 32 <= keyval <= 126 else None
        if ch and self._text_buffer:
            if self._has_text_selection():
                self._delete_text_selection()
            shape = self._board.get_shape(self._text_shape_id)
            max_w = None
            if shape and isinstance(shape, (RectangleShape, DatabaseShape, TopicShape, CloudShape)):
                if getattr(shape, "font_size", None):
                    fs = shape.font_size
                    char_w = fs * 0.6
                    if isinstance(shape, (TopicShape, CloudShape, DatabaseShape)):
                        interior = shape.get_interior_bounds()
                        iw = (interior[2] - interior[0] + 1) * self._cell_w if interior else (shape.width - 2) * self._cell_w
                    else:
                        iw = (shape.width - 2) * self._cell_w
                    max_w = int(iw / char_w) if char_w > 0 else None
                else:
                    interior = shape.get_interior_bounds()
                    if interior:
                        max_w = interior[2] - interior[0] + 1
            line = self._text_buffer[self._text_cursor_line]
            if max_w is None or len(line) < max_w:
                self._text_buffer[self._text_cursor_line] = (
                    line[: self._text_cursor_char] + ch + line[self._text_cursor_char :]
                )
                self._text_cursor_char += 1
            self._collapse_selection()
            self._sync_text()
            self._update_text_cursor_position()
            self.queue_draw()
            return True
        return False

    def _sync_text(self):
        shape = self._board.get_shape(self._text_shape_id) if self._text_shape_id else None
        if shape and isinstance(shape, (RectangleShape, DatabaseShape, ArrowShape, CloudShape)):
            shape.text = "\n".join(self._text_buffer)
        elif shape and isinstance(shape, ActorShape):
            shape.text = self._text_buffer[0] if self._text_buffer else ""
            shape.__post_init__()
        elif shape and isinstance(shape, TopicShape):
            if shape.font_size:
                shape.text = "\n".join(self._text_buffer)
            else:
                shape.text = self._text_buffer[0] if self._text_buffer else ""

    # ─────────────────────── Text Selection ───────────────────────

    def _has_text_selection(self) -> bool:
        return self._text_sel_anchor_line != self._text_cursor_line or self._text_sel_anchor_char != self._text_cursor_char

    def _collapse_selection(self):
        self._text_sel_anchor_line = self._text_cursor_line
        self._text_sel_anchor_char = self._text_cursor_char

    def _get_text_selection_ordered(self) -> tuple[int, int, int, int]:
        """Return (start_line, start_char, end_line, end_char) in order."""
        a = (self._text_sel_anchor_line, self._text_sel_anchor_char)
        c = (self._text_cursor_line, self._text_cursor_char)
        if a <= c:
            return (*a, *c)
        return (*c, *a)

    def _get_selected_text(self) -> str:
        if not self._has_text_selection():
            return ""
        sl, sc, el, ec = self._get_text_selection_ordered()
        if sl == el:
            return self._text_buffer[sl][sc:ec]
        parts = [self._text_buffer[sl][sc:]]
        for i in range(sl + 1, el):
            parts.append(self._text_buffer[i])
        parts.append(self._text_buffer[el][:ec])
        return "\n".join(parts)

    def _delete_text_selection(self):
        if not self._has_text_selection():
            return
        sl, sc, el, ec = self._get_text_selection_ordered()
        if sl == el:
            line = self._text_buffer[sl]
            self._text_buffer[sl] = line[:sc] + line[ec:]
        else:
            before = self._text_buffer[sl][:sc]
            after = self._text_buffer[el][ec:]
            self._text_buffer[sl] = before + after
            del self._text_buffer[sl + 1 : el + 1]
        self._text_cursor_line = sl
        self._text_cursor_char = sc
        self._collapse_selection()

    def _move_cursor_word_left(self):
        line = self._text_buffer[self._text_cursor_line]
        pos = self._text_cursor_char
        if pos == 0 and self._text_cursor_line > 0:
            self._text_cursor_line -= 1
            self._text_cursor_char = len(self._text_buffer[self._text_cursor_line])
            return
        while pos > 0 and line[pos - 1] == " ":
            pos -= 1
        while pos > 0 and line[pos - 1] != " ":
            pos -= 1
        self._text_cursor_char = pos

    def _move_cursor_word_right(self):
        line = self._text_buffer[self._text_cursor_line]
        pos = self._text_cursor_char
        if pos >= len(line) and self._text_cursor_line < len(self._text_buffer) - 1:
            self._text_cursor_line += 1
            self._text_cursor_char = 0
            return
        while pos < len(line) and line[pos] != " ":
            pos += 1
        while pos < len(line) and line[pos] == " ":
            pos += 1
        self._text_cursor_char = pos

    def _on_text_edit_paste_done(self, clipboard, result):
        try:
            text = clipboard.read_text_finish(result)
        except Exception:
            return
        if not text:
            return
        if self._has_text_selection():
            self._delete_text_selection()
        lines = text.split("\n")
        cur_line = self._text_buffer[self._text_cursor_line]
        before = cur_line[: self._text_cursor_char]
        after = cur_line[self._text_cursor_char :]
        if len(lines) == 1:
            self._text_buffer[self._text_cursor_line] = before + lines[0] + after
            self._text_cursor_char += len(lines[0])
        else:
            self._text_buffer[self._text_cursor_line] = before + lines[0]
            for i, ln in enumerate(lines[1:-1], 1):
                self._text_buffer.insert(self._text_cursor_line + i, ln)
            self._text_buffer.insert(self._text_cursor_line + len(lines) - 1, lines[-1] + after)
            self._text_cursor_line += len(lines) - 1
            self._text_cursor_char = len(lines[-1])
        self._collapse_selection()
        self._sync_text()
        self._update_text_cursor_position()
        self.queue_draw()

    # ─────────────────────── Keyboard ───────────────────────

    def _on_key(self, controller, keyval, keycode, state):
        if self._text_editing:
            return self._handle_text_key(keyval, state)

        mod = state & _MOD

        # Undo / Redo
        if mod and keyval == Gdk.KEY_z:
            if state & Gdk.ModifierType.SHIFT_MASK:
                self.redo()
            else:
                self.undo()
            return True

        # Copy / Cut / Paste
        if mod and keyval == Gdk.KEY_c:
            self._copy_selection()
            return True
        if mod and keyval == Gdk.KEY_x:
            self._cut_selection()
            return True
        if mod and keyval == Gdk.KEY_v:
            self._paste()
            return True

        # Select all
        if mod and keyval == Gdk.KEY_a:
            self._selected_ids = set(self._board.shapes.keys())
            self.queue_draw()
            return True

        # Zoom in / out / reset
        if mod and keyval in (Gdk.KEY_equal, Gdk.KEY_plus):
            self.zoom(0.1)
            return True
        if mod and keyval == Gdk.KEY_minus:
            self.zoom(-0.1)
            return True
        if mod and keyval == Gdk.KEY_0:
            self.zoom_reset()
            return True

        # Delete
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace) and self._selected_ids:
            for sid in list(self._selected_ids):
                self._board.remove_shape(sid)
            self._selected_ids.clear()
            self._snapshot_history()
            self.queue_draw()
            return True

        # Arrow keys – move selection
        if self._selected_ids and keyval in (Gdk.KEY_Left, Gdk.KEY_Right, Gdk.KEY_Up, Gdk.KEY_Down):
            dc = {Gdk.KEY_Left: -1, Gdk.KEY_Right: 1}.get(keyval, 0)
            dr = {Gdk.KEY_Up: -1, Gdk.KEY_Down: 1}.get(keyval, 0)
            if self._text_only_selection and len(self._selected_ids) == 1:
                for shape in self.selected_shapes:
                    if isinstance(shape, ArrowShape):
                        shape.text_offset_col += dc
                        shape.text_offset_row += dr
                    else:
                        shape.move(dc, dr)
            else:
                for shape in self.selected_shapes:
                    shape.move(dc, dr)
            self._board.update_connections()
            self._snapshot_history()
            self.queue_draw()
            return True

        # Escape
        if keyval == Gdk.KEY_Escape:
            self._selected_ids.clear()
            self.queue_draw()
            return True

        # Tool shortcuts
        tool_keys = {
            Gdk.KEY_v: ToolMode.SELECT,
            Gdk.KEY_V: ToolMode.SELECT,
            Gdk.KEY_h: ToolMode.PAN,
            Gdk.KEY_H: ToolMode.PAN,
            Gdk.KEY_r: ToolMode.RECTANGLE,
            Gdk.KEY_R: ToolMode.RECTANGLE,
            Gdk.KEY_b: ToolMode.RECTANGLE,
            Gdk.KEY_B: ToolMode.RECTANGLE,
            Gdk.KEY_a: ToolMode.ARROW,
            Gdk.KEY_A: ToolMode.ARROW,
            Gdk.KEY_l: ToolMode.ARROW,
            Gdk.KEY_L: ToolMode.ARROW,
            Gdk.KEY_p: ToolMode.ACTOR,
            Gdk.KEY_P: ToolMode.ACTOR,
            Gdk.KEY_t: ToolMode.TOPIC,
            Gdk.KEY_T: ToolMode.TOPIC,
            Gdk.KEY_d: ToolMode.DATABASE,
            Gdk.KEY_D: ToolMode.DATABASE,
            Gdk.KEY_c: ToolMode.CLOUD,
            Gdk.KEY_C: ToolMode.CLOUD,
        }
        if keyval in tool_keys and not mod:
            self.tool = tool_keys[keyval]
            return True

        # Grid toggle
        if keyval in (Gdk.KEY_g, Gdk.KEY_G) and not mod:
            self._show_grid = not self._show_grid
            self.queue_draw()
            return True

        # Dark mode toggle
        if keyval in (Gdk.KEY_m, Gdk.KEY_M) and not mod:
            self._dark_mode = not self._dark_mode
            if self._on_dark_mode_change:
                self._on_dark_mode_change(self._dark_mode)
            self.queue_draw()
            return True

        return False

    # ─────────────────────── Clipboard ───────────────────────

    # In-memory buffer keeps structured shape data for internal paste;
    # the system clipboard gets visual ASCII art for external paste.
    _internal_clipboard: list[dict] | None = None

    def _copy_selection(self):
        if not self._selected_ids:
            return
        shapes = list(self.selected_shapes)
        if not shapes:
            return
        # Store structured data in memory for internal paste
        SketchCanvas._internal_clipboard = [s.to_dict() for s in shapes]
        # Put visual ASCII art on the system clipboard for external paste
        grid: dict[tuple[int, int], str] = {}
        # Render arrows first, then boxes on top (same order as Board.render)
        for s in sorted(shapes, key=lambda s: s.z_order):
            if isinstance(s, ArrowShape):
                s.render(grid)
        for s in sorted(shapes, key=lambda s: s.z_order):
            if not isinstance(s, ArrowShape):
                s.render(grid)
        _render_font_size_texts(shapes, grid)
        ascii_art = self._grid_to_text(grid)
        if ascii_art:
            self.get_clipboard().set(ascii_art)

    def _cut_selection(self):
        self._copy_selection()
        for sid in list(self._selected_ids):
            self._board.remove_shape(sid)
        self._selected_ids.clear()
        self._snapshot_history()
        self.queue_draw()

    def _paste(self):
        if SketchCanvas._internal_clipboard:
            self._paste_shapes(SketchCanvas._internal_clipboard)
        else:
            self.get_clipboard().read_text_async(None, self._on_paste_done)

    def _paste_shapes(self, shape_dicts: list[dict]):
        """Paste shapes from the internal clipboard buffer."""
        import copy as _copy
        import uuid as _uuid

        shape_dicts = _copy.deepcopy(shape_dicts)
        id_map = {}
        for sd in shape_dicts:
            old_id = sd.get("id", "")
            new_id = _uuid.uuid4().hex[:8]
            id_map[old_id] = new_id
            sd["id"] = new_id
        for sd in shape_dicts:
            if sd.get("type") == "arrow":
                for conn_key in ("start_connection", "end_connection"):
                    conn = sd.get(conn_key)
                    if conn and conn.get("shape_id") in id_map:
                        conn["shape_id"] = id_map[conn["shape_id"]]
        new_ids = set()
        for sd in shape_dicts:
            shape = AbstractShape.from_dict(sd)
            self._board.add_shape(shape)
            new_ids.add(shape.id)
        self._selected_ids = new_ids
        self._snapshot_history()
        self.queue_draw()

    def _on_paste_done(self, clipboard, result):
        try:
            text = clipboard.read_text_finish(result)
        except Exception:
            return
        if not text:
            return

        # Fallback: paste plain text as a rectangle
        shape = RectangleShape(
            left=0, top=0, width=max(len(l) for l in text.split("\n")) + 2, height=len(text.split("\n")) + 2, text=text
        )
        self._board.add_shape(shape)
        self._selected_ids = {shape.id}
        self._snapshot_history()
        self.queue_draw()

    @staticmethod
    def _grid_to_text(grid: dict) -> str:
        if not grid:
            return ""
        min_c = min(c for c, _ in grid)
        max_c = max(c for c, _ in grid)
        min_r = min(r for _, r in grid)
        max_r = max(r for _, r in grid)
        lines = []
        for row in range(min_r, max_r + 1):
            lines.append("".join(grid.get((col, row), " ") for col in range(min_c, max_c + 1)).rstrip())
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines).translate(_CLIPBOARD_XLAT)

    # ─────────────────────── Zoom / Undo ───────────────────────

    def _on_pinch_begin(self, gesture, sequence):
        self._pinch_start_zoom = self._zoom

    def _on_pinch_scale_changed(self, gesture, scale):
        new_zoom = max(0.3, min(3.0, self._pinch_start_zoom * scale))
        if new_zoom == self._zoom:
            return
        ok, cx, cy = gesture.get_bounding_box_center()
        if ok:
            old_zoom = self._zoom
            self._pan_x += cx / new_zoom - cx / old_zoom
            self._pan_y += cy / new_zoom - cy / old_zoom
        self._zoom = new_zoom
        self._target_pan_x = self._pan_x
        self._target_pan_y = self._pan_y
        self._clamp_pan()
        self.queue_draw()

    def zoom(self, delta: float):
        self._zoom = max(0.3, min(3.0, self._zoom + delta))
        self._clamp_pan()
        self.queue_draw()

    def zoom_reset(self):
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._target_pan_x = 0.0
        self._target_pan_y = 0.0
        self._clamp_pan()
        self.queue_draw()

    def export_to_image(self, path: str):
        """Export the current sketch to a PNG or JPEG image file."""
        from sketch_pad.sketch_model import _render_font_size_texts

        grid = self._board.render()

        # Compute bounds on a separate copy that includes font_size text
        # so the image is large enough, but don't pollute the drawing grid
        # (font_size text is rendered separately by _draw_custom_font_texts).
        bounds_grid = dict(grid)
        _render_font_size_texts(self._board.z_sorted(), bounds_grid)
        if not bounds_grid:
            return

        padding = 20
        scale = 2  # HiDPI export for crisp text
        min_col = min(c for c, _ in bounds_grid)
        max_col = max(c for c, _ in bounds_grid)
        min_row = min(r for _, r in bounds_grid)
        max_row = max(r for _, r in bounds_grid)

        img_w = int((max_col - min_col + 1) * self._cell_w + padding * 2)
        img_h = int((max_row - min_row + 1) * self._cell_h + padding * 2)
        img_w = max(img_w, 1)
        img_h = max(img_h, 1)

        # Build render node tree using GtkSnapshot
        snap = Gtk.Snapshot()
        snap.scale(scale, scale)

        # Background
        if self._dark_mode:
            bg = _hex(get_theme().panel_bg)
            fg = _hex(get_theme().fg_color)
        else:
            bg = _hex(get_theme().fg_color)
            fg = _hex(get_theme().panel_bg)
        snap.append_color(tuple_to_gdk_rgba(bg), Graphene.Rect().init(0, 0, img_w, img_h))

        snap.save()
        snap.translate(Graphene.Point().init(padding - min_col * self._cell_w, padding - min_row * self._cell_h))

        # Draw grid chars (excludes font_size text to avoid double rendering)
        fd = Pango.FontDescription.new()
        fd.set_family(self._grid_font_family)
        fd.set_size(int(self._font_size * Pango.SCALE))
        self._draw_chars(snap, grid, fd, fg)

        # Custom font-size texts rendered via Pango (single source of truth)
        self._draw_custom_font_texts(snap, fg)

        snap.restore()

        node = snap.to_node()
        if not node:
            return

        # Render to texture using the widget's GPU renderer
        renderer = self.get_native().get_renderer()
        viewport = Graphene.Rect().init(0, 0, img_w * scale, img_h * scale)
        texture = renderer.render_texture(node, viewport)

        lower = path.lower()
        if lower.endswith((".jpg", ".jpeg")):
            # Convert texture to JPEG via PIL
            png_bytes = texture.save_to_png_bytes()
            try:
                import io

                from PIL import Image

                img = Image.open(io.BytesIO(png_bytes.get_data()))
                img = img.convert("RGB")
                img.save(path, "JPEG", quality=95)
            except ImportError:
                # Fallback: save as PNG if PIL not available
                fallback = path.rsplit(".", 1)[0] + ".png"
                texture.save_to_png(fallback)
                return fallback
        else:
            texture.save_to_png(path)

        return path

    def _show_shape_properties(self, shapes, sx, sy, *, text_only=False):
        """Show the shape properties popup for selected shape(s)."""
        parent = self.get_root()
        if not parent:
            return
        from sketch_pad.shape_properties_popup import ShapePropertiesPopup

        def on_apply(shape_id, **props):
            self.set_shape_property(shape_id, **props)

        popup = ShapePropertiesPopup(parent, shapes, on_apply, text_only=text_only)
        popup.present()

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


# ─────────────────────── Helpers ───────────────────────


def _hex(color: str) -> tuple[float, float, float]:
    h = color.lstrip("#")
    if len(h) == 6:
        return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)
    return (0.8, 0.85, 0.95)
