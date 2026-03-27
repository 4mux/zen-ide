"""
Gutter Diff Renderer - vertical diff indicators in the editor gutter.

Uses a Gtk.DrawingArea overlay on top of the GtkSourceView to draw colored
bars at the left edge of each line, synchronized with the view's scroll position.

Shows colored bars next to line numbers:
- Green bar: added lines
- Yellow bar: modified lines
- Red triangle: deleted lines
"""

import difflib
import os
import threading

from gi.repository import GLib, Graphene, Gtk, GtkSource

from constants import GUTTER_DIFF_WIDTH
from shared.git_manager import get_git_manager
from shared.main_thread import main_thread_call
from shared.utils import hex_to_gdk_rgba
from themes import get_theme

_NO_REPO = object()  # Sentinel: file is outside any git repo


class GutterDiffRenderer:
    """Draws colored diff indicators as an overlay on the editor gutter area."""

    def __init__(self, view: GtkSource.View):
        self._view = view
        self._diff_lines = {}  # line_num (0-based) -> "add" | "change" | "del"
        self._file_path = None
        self._head_content = None
        self._update_timeout_id = None
        self._buffer_changed_id = None

        # Connect to buffer changes
        buf = view.get_buffer()
        if buf:
            self._buffer_changed_id = buf.connect("changed", self._on_buffer_changed)

    def set_file_path(self, file_path: str):
        """Set file path and fetch HEAD content for diff."""
        self._file_path = file_path
        self._fetch_head_content()

    def _fetch_head_content(self):
        """Fetch HEAD version of the file in a background thread."""
        if not self._file_path or not os.path.isfile(self._file_path):
            self._head_content = None
            self._compute_diff()
            return

        file_path = self._file_path

        def do_fetch():
            git = get_git_manager()
            repo_root = git.get_repo_root(file_path)
            if not repo_root:
                main_thread_call(self._set_head_content, _NO_REPO)
                return
            rel_path = os.path.relpath(file_path, repo_root)
            content = git.get_file_at_ref(repo_root, rel_path, "HEAD")
            if content is None:
                # File not in HEAD — check if it's tracked/staged at all
                # If not tracked, treat as outside repo (no diff bars)
                if not git.is_file_tracked(repo_root, rel_path):
                    main_thread_call(self._set_head_content, _NO_REPO)
                    return
            main_thread_call(self._set_head_content, content)

        thread = threading.Thread(target=do_fetch, daemon=True)
        thread.start()

    def _set_head_content(self, content):
        self._head_content = content
        self._compute_diff()

    def _on_buffer_changed(self, buffer):
        """Debounced handler for buffer changes."""
        if self._update_timeout_id:
            GLib.source_remove(self._update_timeout_id)
        self._update_timeout_id = GLib.timeout_add(500, self._schedule_diff_update)

    def _schedule_diff_update(self):
        self._update_timeout_id = None
        self._compute_diff()
        return False

    def _compute_diff(self):
        """Compare current buffer against HEAD to find changed lines."""
        new_diff_lines = {}

        buf = self._view.get_buffer()
        if not buf:
            if self._diff_lines:
                self._diff_lines = new_diff_lines
                self._queue_redraw()
            return

        start = buf.get_start_iter()
        end = buf.get_end_iter()
        current_text = buf.get_text(start, end, True)
        current_lines = current_text.splitlines(keepends=True)

        if self._head_content is _NO_REPO:
            # File is outside any git repo — no diff indicators
            pass
        elif self._head_content is None:
            # New file in a git repo — all lines are added
            if self._file_path:
                for i in range(len(current_lines)):
                    new_diff_lines[i] = "add"
        else:
            head_lines = self._head_content.splitlines(keepends=True)
            opcodes = difflib.SequenceMatcher(None, head_lines, current_lines).get_opcodes()

            for tag, _i1, _i2, j1, j2 in opcodes:
                if tag == "replace":
                    for line in range(j1, j2):
                        new_diff_lines[line] = "change"
                elif tag == "insert":
                    for line in range(j1, j2):
                        new_diff_lines[line] = "add"
                elif tag == "delete":
                    if j1 < len(current_lines):
                        new_diff_lines[j1] = "del"

        # Only redraw if diff actually changed
        if new_diff_lines != self._diff_lines:
            self._diff_lines = new_diff_lines
            self._queue_redraw()

    def _queue_redraw(self):
        """Trigger a redraw of the view to update diff indicators."""
        self._view.queue_draw()

    def refresh_head(self):
        """Re-fetch HEAD content (call after file save)."""
        self._fetch_head_content()

    def draw(self, snapshot, vis_range=None, fold_unsafe=None):
        """Draw diff indicators using GtkSnapshot (called from ZenSourceView.do_snapshot).

        vis_range: optional (start_ln, end_ln) tuple to avoid redundant get_visible_rect.
        """
        if not self._diff_lines:
            return

        view = self._view
        buf = view.get_buffer()
        if not buf:
            return

        theme = get_theme()
        width = GUTTER_DIFF_WIDTH

        # Cache parsed colors as Gdk.RGBA
        color_add = hex_to_gdk_rgba(theme.git_added, 0.9)
        color_change = hex_to_gdk_rgba(theme.git_modified, 0.9)
        color_del = hex_to_gdk_rgba(theme.git_deleted, 0.9)

        # Position indicators just to the left of the text area
        text_x, _ = view.buffer_to_window_coords(Gtk.TextWindowType.WIDGET, 0, 0)
        indicator_x = max(text_x - width - 2, 0)

        # Use pre-computed visible range if available
        if vis_range is not None:
            start_ln, end_ln = vis_range
        else:
            visible = view.get_visible_rect()
            start_it, _ = view.get_line_at_y(visible.y)
            end_it, _ = view.get_line_at_y(visible.y + visible.height)
            start_ln = start_it.get_line()
            end_ln = end_it.get_line()

        rect = Graphene.Rect()

        # Get fold-unsafe lines from the view if not passed explicitly
        if fold_unsafe is None:
            fold_unsafe = getattr(self._view, "_fold_unsafe_lines", set())

        for line_num in range(start_ln, end_ln + 1):
            dtype = self._diff_lines.get(line_num)
            if not dtype:
                continue
            if line_num in fold_unsafe:
                continue

            if dtype == "add":
                color = color_add
            elif dtype == "change":
                color = color_change
            elif dtype == "del":
                color = color_del
            else:
                continue

            # Get line position in buffer coordinates
            it = buf.get_iter_at_line(line_num)
            if it is None:
                continue
            # Handle GTK4 tuple return (bool, iter)
            try:
                it = it[1]
            except (TypeError, IndexError):
                pass
            y, lh = view.get_line_yrange(it)
            _, wy = view.buffer_to_window_coords(Gtk.TextWindowType.WIDGET, 0, y)

            if dtype == "del":
                rect.init(indicator_x, wy, width, min(lh, 4))
            else:
                rect.init(indicator_x, wy, width, lh)
            snapshot.append_color(color, rect)
