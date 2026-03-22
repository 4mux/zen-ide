"""
Code Navigation module for Zen IDE.
Dispatches Cmd+Click go-to-definition to language-specific handlers.

Language-specific logic lives in:
- code_navigation_py.py  (Python)
- code_navigation_tf.py  (Terraform)
- code_navigation_ts.py  (TypeScript/JavaScript)
"""

import os
from typing import Callable, Optional

from gi.repository import GLib, Gtk, GtkSource

from editor.nav_highlight import nav_highlight

from .code_navigation_py import PythonNavigationMixin
from .code_navigation_tf import TerraformNavigationMixin
from .code_navigation_ts import TypeScriptNavigationMixin


class CodeNavigation(PythonNavigationMixin, TerraformNavigationMixin, TypeScriptNavigationMixin):
    """
    Handles Cmd+Click code navigation for the GTK editor.

    Delegates to language-specific mixins:
    - PythonNavigationMixin: Python imports, classes, functions, variables
    - TerraformNavigationMixin: Terraform resource/data/module references
    - TypeScriptNavigationMixin: TS/JS imports, functions, classes, interfaces, types
    """

    def __init__(
        self,
        open_file_callback: Callable[[str, Optional[int]], bool],
        get_workspace_folders: Callable[[], list] = None,
        get_current_buffer_view: Callable[[], Optional[tuple]] = None,
    ):
        """
        Initialize the code navigation system.

        Args:
            open_file_callback: Function to open a file, signature: (path, line_number) -> bool
            get_workspace_folders: Function to get workspace folder paths
            get_current_buffer_view: Function returning (buffer, view) for the current tab
        """
        self.open_file_callback = open_file_callback
        self.get_workspace_folders = get_workspace_folders
        self.get_current_buffer_view = get_current_buffer_view
        self._pending_navigate_symbol = None
        self._pending_file_path = None
        self._pending_navigate_line = None
        self._navigation_timeout_id = None

    def handle_cmd_click(
        self,
        buffer: GtkSource.Buffer,
        view: GtkSource.View,
        file_path: str,
        click_iter: Gtk.TextIter,
    ) -> bool:
        """
        Handle Cmd+Click at a position in the editor.

        Args:
            buffer: The source buffer
            view: The source view
            file_path: Path to the current file
            click_iter: TextIter at click position

        Returns:
            True if navigation was handled, False otherwise
        """
        if not file_path:
            return False

        # Try file path navigation first (works for any file type)
        if self._try_navigate_file_path(buffer, file_path, click_iter):
            return True

        ext = os.path.splitext(file_path)[1].lower()

        if ext in (".py", ".pyw", ".pyi"):
            return self._handle_python_click(buffer, view, file_path, click_iter)

        if ext == ".tf":
            return self._handle_terraform_click(buffer, view, file_path, click_iter)

        if ext in (".ts", ".tsx", ".js", ".jsx"):
            return self._handle_ts_click(buffer, view, file_path, click_iter)

        return False

    # File path characters: alphanumeric, _, -, ., /, ~
    _FILE_PATH_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.~/#")

    def get_file_path_at_iter(self, buffer: GtkSource.Buffer, it: Gtk.TextIter) -> Optional[str]:
        """Extract a file path string at the given iterator position."""
        line_start = it.copy()
        line_start.set_line_offset(0)
        line_end = it.copy()
        if not line_end.ends_line():
            line_end.forward_to_line_end()

        line_content = buffer.get_text(line_start, line_end, True)
        col = it.get_line_offset()

        if col >= len(line_content):
            return None

        # Current char must be a path character
        if line_content[col] not in self._FILE_PATH_CHARS:
            return None

        start = col
        end = col

        while start > 0 and line_content[start - 1] in self._FILE_PATH_CHARS:
            start -= 1
        while end < len(line_content) and line_content[end] in self._FILE_PATH_CHARS:
            end += 1

        path_str = line_content[start:end].rstrip(".")
        if not path_str:
            return None

        # Must look like a file path (contains / or has a file extension)
        if "/" not in path_str and "." not in path_str:
            return None
        # Must contain at least one / to distinguish from plain dotted identifiers
        if "/" not in path_str:
            return None

        return path_str

    def _try_navigate_file_path(
        self,
        buffer: GtkSource.Buffer,
        current_file: str,
        click_iter: Gtk.TextIter,
    ) -> bool:
        """Try to resolve and open a file path found at click position."""
        path_str = self.get_file_path_at_iter(buffer, click_iter)
        if not path_str:
            return False

        # Strip fragment (e.g. #/PaymentDetails from OpenAPI $ref)
        file_path = path_str.split("#")[0] if "#" in path_str else path_str

        # Resolve relative to current file's directory
        current_dir = os.path.dirname(current_file)
        resolved = os.path.normpath(os.path.join(current_dir, file_path))

        if os.path.isfile(resolved):
            return self.open_file_callback(resolved)

        # Try workspace roots
        if self.get_workspace_folders:
            for root in self.get_workspace_folders():
                candidate = os.path.normpath(os.path.join(root, file_path))
                if os.path.isfile(candidate):
                    return self.open_file_callback(candidate)

        return False

    def _get_word_at_iter(self, buffer: GtkSource.Buffer, it: Gtk.TextIter) -> Optional[str]:
        """Get the identifier at the given iterator position."""
        line_start = it.copy()
        line_start.set_line_offset(0)
        line_end = it.copy()
        if not line_end.ends_line():
            line_end.forward_to_line_end()

        line_content = buffer.get_text(line_start, line_end, True)
        col = it.get_line_offset()

        if col >= len(line_content):
            return None

        start = col
        end = col

        while start > 0 and (line_content[start - 1].isalnum() or line_content[start - 1] == "_"):
            start -= 1

        while end < len(line_content) and (line_content[end].isalnum() or line_content[end] == "_"):
            end += 1

        if start < end:
            return line_content[start:end]
        return None

    def _get_chain_at_iter(self, buffer: GtkSource.Buffer, it: Gtk.TextIter) -> Optional[str]:
        """Get the full dotted chain at the iterator (e.g., 'os.path.join')."""
        line_start = it.copy()
        line_start.set_line_offset(0)
        line_end = it.copy()
        if not line_end.ends_line():
            line_end.forward_to_line_end()

        line_content = buffer.get_text(line_start, line_end, True)
        col = it.get_line_offset()

        if col >= len(line_content):
            return None

        start = col
        end = col

        while start > 0:
            char = line_content[start - 1]
            if char.isalnum() or char in "_.":
                start -= 1
            else:
                break

        while end < len(line_content):
            char = line_content[end]
            if char.isalnum() or char in "_.":
                end += 1
            else:
                break

        chain = line_content[start:end].strip(".")
        return chain if chain else None

    def _navigate_to_line(self, buffer: GtkSource.Buffer, view: GtkSource.View, line: int, symbol: str = None):
        """Navigate to a line with highlighting."""
        line_0 = max(0, line - 1)

        result = buffer.get_iter_at_line(line_0)
        try:
            it = result[1]
        except (TypeError, IndexError):
            it = result

        buffer.place_cursor(it)
        view.scroll_to_iter(it, 0.2, False, 0.0, 0.5)

        if symbol:
            nav_highlight.highlight_symbol(buffer, line, symbol)
        else:
            nav_highlight.highlight_line(buffer, line)

    def _schedule_pending_navigation(self):
        """Schedule navigation, canceling any previous pending timeout."""
        if self._navigation_timeout_id is not None:
            GLib.source_remove(self._navigation_timeout_id)
        self._navigation_timeout_id = GLib.timeout_add(300, self._do_pending_navigation)

    def _do_pending_navigation(self) -> bool:
        """Called after file is opened to navigate to symbol."""
        self._navigation_timeout_id = None
        if not self._pending_navigate_symbol or not self._pending_file_path:
            return False

        symbol = self._pending_navigate_symbol
        pending_line = self._pending_navigate_line
        self._pending_navigate_symbol = None
        self._pending_file_path = None
        self._pending_navigate_line = None

        if self.get_current_buffer_view:
            try:
                result = self.get_current_buffer_view()
                if result:
                    buffer, view = result
                    if pending_line:
                        self._navigate_to_line(buffer, view, pending_line, symbol=symbol)
                    else:
                        self.navigate_to_symbol_in_buffer(buffer, view, symbol)
            except Exception:
                pass

        return False

    def navigate_to_symbol_in_buffer(
        self,
        buffer: GtkSource.Buffer,
        view: GtkSource.View,
        symbol: str,
    ) -> bool:
        """Navigate to a symbol definition in the given buffer."""
        content = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)

        line_num = self._ts_py.find_symbol_in_content(content, symbol)
        if not line_num:
            line_num = self._ts_js.find_symbol_in_content(content, symbol)
        if line_num:
            self._navigate_to_line(buffer, view, line_num, symbol=symbol)
            return True

        # Check for re-export pattern (from .x import symbol)
        import_line = self._ts_py.find_import_line(content, symbol)
        if import_line:
            self._navigate_to_line(buffer, view, import_line, symbol=symbol)
            return True

        return False
