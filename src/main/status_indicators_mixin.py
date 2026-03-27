"""Status bar indicator logic — file info, diagnostics, git, position, encoding."""

import os
import threading
from typing import Optional

from gi.repository import GLib

from constants import STATUS_BAR_FONT_FAMILY, STATUS_BAR_HORIZONTAL_PADDING
from fonts import get_font_settings
from icons import get_file_icon, get_icon_font_name, icon_font_fallback
from shared.git_manager import get_git_manager
from shared.main_thread import main_thread_call
from shared.settings import get_setting
from themes import get_theme


class StatusIndicatorsMixin:
    """Mixin: individual status indicator widgets/logic for the status bar."""

    def _font_markup(self, text: str, color: str, size: int | None = None, font_family: str | None = None) -> str:
        """Build Pango markup that always uses the fixed status bar font family."""
        font_settings = get_font_settings("editor")
        font_size = size if size is not None else font_settings.get("size", 13)
        if font_family is None:
            font_family = STATUS_BAR_FONT_FAMILY or font_settings["family"]
        font_family = icon_font_fallback(font_family)
        escaped_text = GLib.markup_escape_text(text)
        return f'<span foreground="{color}" font_family="{font_family}" size="{font_size * 1024}" weight="500">{escaped_text}</span>'

    def set_workspace_folders(self, folders: list, workspace_name: str = None, workspace_file: str = None):
        """Set workspace folders for git branch detection."""
        self._workspace_folders = folders
        if workspace_file and os.path.isfile(workspace_file):
            path = workspace_file
            home = os.path.expanduser("~")
            if path.startswith(home):
                path = "~" + path[len(home) :]
            self._workspace_name = path
        elif workspace_name:
            self._workspace_name = workspace_name
        elif folders:
            path = folders[0]
            home = os.path.expanduser("~")
            if path.startswith(home):
                path = "~" + path[len(home) :]
            self._workspace_name = path
        else:
            self._workspace_name = None

    def set_file(self, file_path: Optional[str]):
        """Update the current file display."""
        self._current_file = file_path

        if file_path:
            # Show full path or just filename based on setting
            show_full = get_setting("status_bar.show_full_path", True)
            if show_full:
                home = os.path.expanduser("~")
                if file_path.startswith(home):
                    display_path = "~" + file_path[len(home) :]
                else:
                    display_path = file_path
            else:
                display_path = os.path.basename(file_path)
            self._filepath_label.set_label(display_path)
            self._filepath_box.set_visible(True)

            # Detect file type
            self._file_type = self._detect_file_type(file_path)
            self._filetype_label.set_label(self._file_type)
            self._filetype_icon.set_use_markup(True)
            self._refresh_filetype_icon()

            # Detect encoding
            self.set_encoding(self._detect_encoding(file_path))

            # Show file-specific sections
            self._filetype_box.set_visible(True)
            self._encoding_box.set_visible(True)
            self._position_box.set_visible(True)
            self._percent_box.set_visible(True)
            self._right_box.set_margin_end(0)
            self._modified_box.set_visible(self._modified)

            # Update git branch (async)
            self._update_git_branch(file_path)
        else:
            self._file_type = ""
            self._filetype_label.set_label("")
            self._filetype_icon.set_label("")
            self._filetype_box.set_visible(False)
            self._git_label.set_label("")
            self._git_box.set_visible(False)
            self._encoding_box.set_visible(False)
            self._position_box.set_visible(False)
            self._percent_box.set_visible(False)
            self._right_box.set_margin_end(STATUS_BAR_HORIZONTAL_PADDING)
            self._modified_box.set_visible(False)
            # Show workspace name when no file is open
            if self._workspace_name:
                self._filepath_label.set_label(self._workspace_name)
                self._filepath_box.set_visible(True)
            else:
                self._filepath_label.set_label("")
                self._filepath_box.set_visible(False)

    def set_file_type(self, file_type: str):
        """Set the file type label directly."""
        self._file_type = file_type
        self._filetype_label.set_label(file_type)
        self._filetype_icon.set_label("")

    def _refresh_filetype_icon(self):
        """Re-render the filetype icon with current theme accent color."""
        if not self._current_file:
            return
        icon, _color = get_file_icon(self._current_file)
        font_settings = get_font_settings("editor")
        icon_size = font_settings.get("size", 13) + 4
        icon_font = get_icon_font_name()
        self._filetype_icon.set_markup(self._font_markup(icon, self._accent_color, icon_size, font_family=icon_font))

    def set_modified(self, modified: bool):
        """Update the modified indicator."""
        self._modified = modified
        self._modified_label.set_label("\u0394" if modified else "")
        self._modified_box.set_visible(modified)

    def set_inspect_mode(self, active: bool):
        """Show or hide the INSPECT mode indicator."""
        self._inspect_label.set_visible(active)

    def set_debug_state(self, state: str):
        """Show or hide the DEBUG mode indicator in the status bar.

        Args:
            state: One of "idle", "initializing", "running", "stopped", "terminated",
                   or empty string to hide.
        """
        if not state or state in ("idle", "terminated"):
            self._debug_label.set_visible(False)
        else:
            labels = {
                "initializing": "DEBUG: Starting",
                "running": "DEBUG: Running",
                "stopped": "DEBUG: Paused",
            }
            self._debug_label.set_label(labels.get(state, f"DEBUG: {state}"))
            self._debug_label.set_visible(True)

    def set_position(self, line: int, col: int, total_lines: int):
        """Update cursor position and percentage (throttled to ~30fps)."""
        self._line = line
        self._col = col
        self._pending_total_lines = total_lines
        if not hasattr(self, "_position_update_pending") or not self._position_update_pending:
            self._position_update_pending = True
            GLib.timeout_add(33, self._flush_position_update)

    def _flush_position_update(self):
        """Flush pending position update to UI."""
        self._position_update_pending = False
        self._position_label.set_label(f"{self._line}:{self._col}")
        total_lines = self._pending_total_lines

        # Calculate percentage
        if total_lines <= 1:
            percent_text = "Top"
        elif self._line == 1:
            percent_text = "Top"
        elif self._line >= total_lines:
            percent_text = "Bot"
        else:
            percent = int((self._line / total_lines) * 100)
            percent_text = f"{percent}%"

        self._percent_label.set_label(percent_text)
        return False

    def set_encoding(self, encoding: str):
        """Update encoding display."""
        self._encoding = encoding
        self._encoding_label.set_label(encoding)

    def set_diagnostics(self, errors: int, warnings: int):
        """Update diagnostics (error/warning counts) display."""
        self._errors = errors
        self._warnings = warnings
        self._refresh_diagnostics()

    def _refresh_diagnostics(self):
        """Re-render diagnostic labels with current theme colors."""
        from icons import IconsManager

        theme = get_theme()
        font_settings = get_font_settings("editor")
        icon_size = font_settings.get("size", 13) + 4
        icon_font = get_icon_font_name()
        # Zero-count diagnostics always use white to match other status bar texts.
        zero_color = "white"

        err_color = theme.term_red if self._errors > 0 else zero_color
        self._error_icon_label.set_markup(
            self._font_markup(IconsManager.ERROR_X, err_color, icon_size, font_family=icon_font)
        )
        self._error_count_label.set_markup(self._font_markup(str(self._errors), err_color))

        warn_color = theme.warning_color if self._warnings > 0 else zero_color
        self._warning_icon_label.set_markup(
            self._font_markup(IconsManager.WARNING, warn_color, icon_size, font_family=icon_font)
        )
        self._warning_count_label.set_markup(self._font_markup(str(self._warnings), warn_color))

        self._diagnostics_box.set_visible(True)

    def _on_diagnostics_box_clicked(self, gesture, n_press, x, y):
        """Handle click on diagnostics indicator."""
        if self.on_diagnostics_clicked:
            self.on_diagnostics_clicked()

    def _detect_encoding(self, file_path: str) -> str:
        """Detect file encoding by reading initial bytes."""
        try:
            with open(file_path, "rb") as f:
                raw = f.read(4)
            if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
                return "UTF-16"
            if raw.startswith(b"\xef\xbb\xbf"):
                return "UTF-8-BOM"
            # Try decoding as UTF-8
            with open(file_path, "r", encoding="utf-8") as f:
                f.read(8192)
            return "UTF-8"
        except (UnicodeDecodeError, OSError):
            return "Binary"

    def _detect_file_type(self, file_path: str) -> str:
        """Detect file type from extension."""
        ext = os.path.splitext(file_path)[1].lower()
        type_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascriptreact",
            ".tsx": "typescriptreact",
            ".html": "html",
            ".css": "css",
            ".scss": "scss",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".md": "markdown",
            ".rs": "rust",
            ".go": "go",
            ".java": "java",
            ".c": "c",
            ".cpp": "cpp",
            ".h": "c",
            ".hpp": "cpp",
            ".rb": "ruby",
            ".php": "php",
            ".sh": "shell",
            ".bash": "shell",
            ".zsh": "shell",
            ".sql": "sql",
            ".xml": "xml",
            ".toml": "toml",
            ".lua": "lua",
            ".vim": "vim",
            ".swift": "swift",
            ".kt": "kotlin",
            ".scala": "scala",
            ".clj": "clojure",
            ".ex": "elixir",
            ".exs": "elixir",
            ".erl": "erlang",
            ".hs": "haskell",
            ".ml": "ocaml",
            ".r": "r",
            ".jl": "julia",
            ".dart": "dart",
            ".vue": "vue",
            ".svelte": "svelte",
            ".zen_sketch": "sketch",
        }
        # Workspace files use compound extensions
        from constants import WORKSPACE_EXTENSIONS

        basename = os.path.basename(file_path)
        for ws_ext in WORKSPACE_EXTENSIONS:
            if basename.endswith(ws_ext):
                return "workspace"
        return type_map.get(ext, ext.lstrip(".") if ext else "text")

    def _update_git_branch(self, file_path: str):
        """Update git branch in background thread."""
        from icons import IconsManager

        def _get_branch():
            git = get_git_manager()
            # Try file's own directory first
            file_dir = os.path.dirname(file_path)
            if os.path.isdir(file_dir):
                repo_root = git.get_repo_root(file_dir)
                if repo_root:
                    return git.get_current_branch(repo_root)

            # Fall back to workspace folders
            for folder in self._workspace_folders or []:
                if os.path.isdir(folder):
                    repo_root = git.get_repo_root(folder)
                    if repo_root:
                        return git.get_current_branch(repo_root)

            return None

        def _on_result(branch):
            if branch:
                self._git_branch = branch
                self._git_label.set_label(branch)
                self._git_icon.set_label(IconsManager.GIT_BRANCH)
                self._git_box.set_visible(True)
            else:
                self._git_branch = None
                self._git_label.set_label("")
                self._git_box.set_visible(False)

        def _thread_func():
            branch = _get_branch()
            main_thread_call(_on_result, branch)

        thread = threading.Thread(target=_thread_func, daemon=True)
        thread.start()
