"""
Editor Minimap - Git diff and diagnostic indicator strip for the code editor.
Shows colored markers alongside the GtkSource.Map minimap for:
- Git diff regions (added/modified/deleted lines vs HEAD)
- Diagnostic hints (errors, warnings from GtkSourceView tags)
"""

import difflib
import os
import threading

from gi.repository import Gdk, GLib, Graphene, Gtk, GtkSource

from constants import EDITOR_MINIMAP_INDICATOR_WIDTH
from shared.git_manager import get_git_manager
from shared.main_thread import main_thread_call
from themes import get_theme

_NO_REPO = object()  # Sentinel: file is outside any git repo


class EditorMinimap(Gtk.Widget):
    """Vertical indicator strip showing git diff markers and diagnostic hints."""

    def __init__(self, source_view: GtkSource.View, scrolled_window: Gtk.ScrolledWindow):
        super().__init__()
        self._view = source_view
        self._buffer = source_view.get_buffer()
        self._scrolled = scrolled_window

        self._total_lines = 0
        self._diff_lines = {}  # line_num (0-based) -> "add" | "change" | "del"
        self._diagnostic_lines = {}  # line_num (0-based) -> "error" | "warning" | "info"
        self._viewport_start = 0.0
        self._viewport_end = 0.0
        self._file_path = None
        self._head_content = None
        self._update_timeout_id = None
        self._scroll_redraw_id = None
        self._cached_colors = None  # Pre-parsed theme colors for draw

        self.set_size_request(EDITOR_MINIMAP_INDICATOR_WIDTH, -1)
        self.set_vexpand(True)
        self.set_hexpand(False)

        # Click to jump
        click = Gtk.GestureClick()
        click.set_button(1)
        click.connect("pressed", self._on_click)
        self.add_controller(click)

        # Drag to scroll
        drag = Gtk.GestureDrag()
        drag.set_button(1)
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        self.add_controller(drag)

        # Track scroll changes for viewport indicator
        vadj = self._scrolled.get_vadjustment()
        vadj.connect("value-changed", self._on_scroll_changed)
        vadj.connect("notify::upper", self._on_scroll_changed)

        # Track buffer changes with debounce
        self._buffer.connect("changed", self._on_buffer_changed)

    def set_file_path(self, file_path: str):
        """Set the file path and trigger initial git diff computation."""
        self._file_path = file_path
        self._fetch_head_content()

    def _fetch_head_content(self):
        """Fetch the HEAD version of the file in a background thread."""
        if not self._file_path or not os.path.isfile(self._file_path):
            self._head_content = None
            self._schedule_diff_update()
            return

        file_path = self._file_path

        def do_fetch():
            git = get_git_manager()
            repo_root = git.get_repo_root(file_path)
            if not repo_root:
                main_thread_call(self._set_head_content, _NO_REPO)
                return
            rel_path = os.path.relpath(file_path, repo_root)
            if not git.is_file_tracked(repo_root, rel_path):
                main_thread_call(self._set_head_content, None)
                return
            content = git.get_file_at_ref(repo_root, rel_path, "HEAD")
            main_thread_call(self._set_head_content, content)

        thread = threading.Thread(target=do_fetch, daemon=True)
        thread.start()

    def _set_head_content(self, content):
        """Called on main thread after fetching HEAD content."""
        self._head_content = content
        self._compute_diff()

    def _on_buffer_changed(self, buffer):
        """Debounced handler for buffer changes."""
        if self._update_timeout_id:
            GLib.source_remove(self._update_timeout_id)
        self._update_timeout_id = GLib.timeout_add(500, self._schedule_diff_update)

    def _schedule_diff_update(self):
        """Recompute diff and redraw."""
        self._update_timeout_id = None
        self._compute_diff()
        return False

    def _compute_diff(self):
        """Compare current buffer content against HEAD to find changed lines."""
        self._diff_lines = {}

        start = self._buffer.get_start_iter()
        end = self._buffer.get_end_iter()
        current_text = self._buffer.get_text(start, end, True)
        current_lines = current_text.splitlines(keepends=True)
        self._total_lines = len(current_lines) or 1

        if self._head_content is _NO_REPO:
            # File is outside any git repo — no diff indicators
            pass
        elif self._head_content is None:
            # New file in a git repo - all lines are "added"
            if self._file_path:
                for i in range(len(current_lines)):
                    self._diff_lines[i] = "add"
        else:
            head_lines = self._head_content.splitlines(keepends=True)
            opcodes = difflib.SequenceMatcher(None, head_lines, current_lines).get_opcodes()

            for tag, i1, i2, j1, j2 in opcodes:
                if tag == "replace":
                    for line in range(j1, j2):
                        self._diff_lines[line] = "change"
                elif tag == "insert":
                    for line in range(j1, j2):
                        self._diff_lines[line] = "add"
                elif tag == "delete":
                    # Mark the line where deletion happened
                    if j1 < len(current_lines):
                        self._diff_lines[j1] = "del"

        self._update_viewport()
        self.queue_draw()

    def refresh_head(self):
        """Re-fetch HEAD content (call after file save)."""
        self._fetch_head_content()

    def set_diagnostics(self, diagnostics: dict):
        """Update diagnostic markers. diagnostics: {line_num: severity}."""
        self._diagnostic_lines = diagnostics
        self.queue_draw()

    def _on_scroll_changed(self, *args):
        """Update viewport position from scroll adjustment (throttled)."""
        self._update_viewport()
        if not self._scroll_redraw_id:
            self._scroll_redraw_id = GLib.idle_add(self._scroll_redraw)

    def _update_viewport(self):
        """Calculate viewport fraction from scroll position."""
        vadj = self._scrolled.get_vadjustment()
        upper = vadj.get_upper()
        if upper <= 0:
            self._viewport_start = 0.0
            self._viewport_end = 1.0
            return
        page = vadj.get_page_size()
        value = vadj.get_value()
        self._viewport_start = value / upper
        self._viewport_end = (value + page) / upper

    def _scroll_redraw(self):
        """Coalesce scroll redraws into a single idle callback."""
        self._scroll_redraw_id = None
        self.queue_draw()
        return False

    def do_snapshot(self, snapshot):
        """Draw diff markers, diagnostic markers, and viewport indicator."""
        width = self.get_width()
        height = self.get_height()

        theme = get_theme()
        from shared.utils import hex_to_rgb_float

        # Cache parsed theme colors to avoid re-parsing on every draw
        if self._cached_colors is None or self._cached_colors.get("_theme") != theme.name:
            self._cached_colors = {
                "_theme": theme.name,
                "bg": hex_to_rgb_float(theme.main_bg),
                "add": hex_to_rgb_float(theme.git_added),
                "change": hex_to_rgb_float(theme.git_modified),
                "del": hex_to_rgb_float(theme.git_deleted),
                "error": hex_to_rgb_float(theme.term_red),
                "warning": hex_to_rgb_float(theme.warning_color),
                "info": hex_to_rgb_float(theme.term_blue),
                "fg": hex_to_rgb_float(theme.fg_color),
            }

        colors = self._cached_colors
        rect = Graphene.Rect()

        # Background - match minimap bg
        r, g, b = colors["bg"]
        bg_color = Gdk.RGBA()
        bg_color.red, bg_color.green, bg_color.blue, bg_color.alpha = r, g, b, 1.0
        rect.init(0, 0, width, height)
        snapshot.append_color(bg_color, rect)

        if self._total_lines == 0 or height == 0:
            return

        line_height = height / self._total_lines
        min_marker_h = max(line_height, 2)

        # Draw git diff markers (full width of strip)
        marker_w = max(width - 2, 3)

        marker_color = Gdk.RGBA()
        for line_num, dtype in self._diff_lines.items():
            y = (line_num / self._total_lines) * height
            color = colors.get(dtype)
            if color is None:
                continue
            dr, dg, db = color
            marker_color.red, marker_color.green, marker_color.blue, marker_color.alpha = dr, dg, db, 0.9
            rect.init(1, y, marker_w, min_marker_h)
            snapshot.append_color(marker_color, rect)

        # Draw diagnostic markers (full width, overlays diff markers)
        for line_num, severity in self._diagnostic_lines.items():
            y = (line_num / self._total_lines) * height
            color = colors.get(severity)
            if color is None:
                continue
            dr, dg, db = color
            marker_color.red, marker_color.green, marker_color.blue, marker_color.alpha = dr, dg, db, 0.9
            rect.init(1, y, marker_w, min_marker_h)
            snapshot.append_color(marker_color, rect)

        # Viewport indicator
        if self._viewport_end > self._viewport_start:
            vy_start = self._viewport_start * height
            vy_end = self._viewport_end * height
            vr, vg, vb = colors["fg"]

            # Viewport background
            vp_color = Gdk.RGBA()
            vp_color.red, vp_color.green, vp_color.blue, vp_color.alpha = vr, vg, vb, 0.10
            rect.init(0, vy_start, width, vy_end - vy_start)
            snapshot.append_color(vp_color, rect)

            # Border lines using thin rectangles
            border_color = Gdk.RGBA()
            border_color.red, border_color.green, border_color.blue, border_color.alpha = vr, vg, vb, 0.25
            rect.init(0, vy_start, width, 1)
            snapshot.append_color(border_color, rect)
            rect.init(0, vy_end - 1, width, 1)
            snapshot.append_color(border_color, rect)

    def _on_click(self, gesture, n_press, x, y):
        """Jump to clicked position."""
        self._jump_to_y(y)

    def _on_drag_begin(self, gesture, start_x, start_y):
        """Start drag scrolling.

        Make the viewport "stick" to the mouse like in VSCode: record the
        click position relative to the viewport rectangle (if the click was
        inside it). During the drag we keep that relative offset under the
        mouse so the handle follows the cursor instead of jumping/centering
        the target line.
        """
        self._drag_start_y = start_y

        # Compute current viewport geometry in pixels
        height = self.get_allocated_height()
        vadj = self._scrolled.get_vadjustment()
        upper = float(vadj.get_upper())
        page = float(vadj.get_page_size())
        # Guard against zero-height content
        if height <= 0 or upper <= 0:
            self._drag_vp_offset = 0.0
            # Fallback to previous behaviour
            self._jump_to_y(start_y)
            return

        vy_start = (float(vadj.get_value()) / upper) * height
        vy_end = ((float(vadj.get_value()) + page) / upper) * height

        # If clicked inside current viewport, remember offset within viewport
        if start_y >= vy_start and start_y <= vy_end:
            self._drag_vp_offset = start_y - vy_start
        else:
            # Click was outside viewport - behave like a grab in the middle
            self._drag_vp_offset = (vy_end - vy_start) / 2.0

        # Jump initially so user sees immediate feedback
        self._apply_drag_position(start_y)

    def _on_drag_update(self, gesture, offset_x, offset_y):
        """Continue drag scrolling."""
        current_y = self._drag_start_y + offset_y
        self._apply_drag_position(current_y)

    def _apply_drag_position(self, mouse_y: float):
        """Set the scroll position so that the point at mouse_y - _drag_vp_offset
        becomes the top of the viewport (i.e. viewport_start * height).
        """
        if self._total_lines == 0:
            return

        height = self.get_allocated_height()
        if height == 0:
            return

        vadj = self._scrolled.get_vadjustment()
        upper = float(vadj.get_upper())
        page = float(vadj.get_page_size())

        # Desired viewport top in pixels
        desired_vy_start = mouse_y - getattr(self, "_drag_vp_offset", 0.0)

        # Clamp to allowable range
        max_vy_start = max(0.0, height - (page / upper) * height) if upper > 0 else 0.0
        desired_vy_start = max(0.0, min(desired_vy_start, max_vy_start))

        # Convert back to adjustment value and apply
        desired_fraction = desired_vy_start / height
        desired_value = desired_fraction * upper

        # Clamp against adjustment min/max
        min_val = float(vadj.get_lower())
        max_val = float(vadj.get_upper() - page)
        desired_value = max(min_val, min(desired_value, max_val))

        vadj.set_value(desired_value)

    def _jump_to_y(self, y):
        """Scroll editor to the line corresponding to y position."""
        if self._total_lines == 0:
            return
        height = self.get_allocated_height()
        if height == 0:
            return
        frac = max(0.0, min(1.0, y / height))
        line = int(frac * self._total_lines)
        line = max(0, min(line, self._total_lines - 1))

        # Scroll the source view to the target line
        target_iter = self._buffer.get_iter_at_line(line)
        try:
            success, it = target_iter
            if success:
                self._view.scroll_to_iter(it, 0.0, True, 0.0, 0.5)
        except (TypeError, ValueError):
            self._view.scroll_to_iter(target_iter, 0.0, True, 0.0, 0.5)
