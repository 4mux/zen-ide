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

from gi.repository import GLib, GtkSource

from shared.git_manager import get_git_manager
from shared.main_thread import main_thread_call

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
        self._gutter_renderer = None  # GitDiffGutterRenderer for gutter display

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
            if self._gutter_renderer:
                self._gutter_renderer.set_diff_lines(self._diff_lines)
            self._queue_redraw()

    def _queue_redraw(self):
        """Trigger a redraw of the view to update diff indicators."""
        self._view.queue_draw()

    def refresh_head(self):
        """Re-fetch HEAD content (call after file save)."""
        self._fetch_head_content()
