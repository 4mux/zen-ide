"""Terminal file navigation mixin.

Provides file path detection, matching, and navigation for terminal output.
Handles Cmd+click to open files, VTE regex matching, and path resolution.
"""

import os
import re

from gi.repository import Gdk, Vte

# Well-known filenames without extensions that should be navigable
KNOWN_EXTENSIONLESS = r"Makefile|Dockerfile|Vagrantfile|Procfile|Gemfile|Rakefile|Guardfile|Brewfile|Justfile"

# Regex pattern for matching file paths in terminal output
# Matches paths like: terraform/ses_templates.tf, ./src/main.py, /abs/path.txt
# Also matches extensionless known files: Makefile, path/to/Makefile
# Also matches with line numbers: file.py:42, file.py:42:10
FILE_PATH_PATTERN = re.compile(
    r'(?:^|[\s:"\'])'
    r"([./]?(?:[\w.-]+/)*(?:(?:[\w.-]+\.[\w]+)|(?:" + KNOWN_EXTENSIONLESS + r")))"
    r"(?::(\d+))?(?::(\d+))?"
    r'(?=[\s:"\',]|$)'
)


class TerminalFileNavigationMixin:
    """Mixin providing file path detection and navigation in terminal output."""

    def _setup_file_path_matching(self):
        """Setup regex matching for file paths to enable visual underlining."""
        try:
            # VTE regex pattern for file paths (will be underlined when hovered)
            # Matches files with extensions and known extensionless files (Makefile, Dockerfile, etc.)
            pattern = (
                r'(?:^|[\s:"\'])\K'
                r"([./]?(?:[\w.-]+/)*(?:[\w.-]+\.[a-zA-Z0-9]+|" + KNOWN_EXTENSIONLESS + r"))"
                r'(?::\d+)?(?::\d+)?(?=[\s:"\',]|$)'
            )

            regex = Vte.Regex.new_for_match(
                pattern,
                -1,  # -1 means use strlen
                0x00000400,  # PCRE2_MULTILINE
            )

            self._file_path_match_id = self.terminal.match_add_regex(regex, 0)
            self.terminal.match_set_cursor_name(self._file_path_match_id, "pointer")
        except Exception:
            self._file_path_match_id = None

    def _on_terminal_click(self, gesture, n_press, x, y):
        """Handle click on terminal - Cmd+click opens file paths."""
        state = gesture.get_current_event_state()
        meta = state & Gdk.ModifierType.META_MASK
        ctrl = state & Gdk.ModifierType.CONTROL_MASK

        if not (meta or ctrl):
            return

        file_path, line_num = self._get_file_path_from_vte_match(x, y)
        if not file_path:
            file_path, line_num = self._get_file_path_at_position(x, y)
        if file_path:
            self._open_file_path(file_path, line_num)

    def _get_file_path_from_vte_match(self, x, y):
        """Extract file path using VTE's built-in regex match at pixel coordinates."""
        if not hasattr(self, "_file_path_match_id") or self._file_path_match_id is None:
            return None, None

        try:
            matched_text, tag = self.terminal.check_match_at(x, y)
            if matched_text and tag == self._file_path_match_id:
                m = FILE_PATH_PATTERN.search(matched_text)
                if m:
                    return m.group(1), int(m.group(2)) if m.group(2) else None
        except Exception:
            pass

        return None, None

    def _get_file_path_at_position(self, x, y):
        """Extract file path from terminal text at clicked position.

        Returns (file_path, line_number) tuple, or (None, None) if no file found.
        """
        char_width = self.terminal.get_char_width()
        char_height = self.terminal.get_char_height()

        if char_width <= 0 or char_height <= 0:
            return None, None

        col = int(x / char_width)
        row = int(y / char_height)

        try:
            row_count = self.terminal.get_row_count()

            text_lines = []
            for r in range(max(0, row - 1), min(row_count, row + 2)):
                line_text = self._get_row_text(r)
                if line_text:
                    text_lines.append((r, line_text))

            if not text_lines:
                return None, None

            for row_idx, line in text_lines:
                if row_idx == row:
                    return self._extract_file_path_at_column(line, col)

            for row_idx, line in text_lines:
                result = self._extract_file_path_at_column(line, col)
                if result[0]:
                    return result

        except Exception:
            pass

        return None, None

    def _get_row_text(self, row):
        """Get text content of a specific terminal row."""
        try:
            col_count = self.terminal.get_column_count()
            result = self.terminal.get_text_range_format(Vte.Format.TEXT, row, 0, row, col_count - 1)

            if result:
                text = result[0] if isinstance(result, tuple) else result
                return text.rstrip("\n") if text else None
        except Exception:
            pass

        return None

    def _extract_file_path_at_column(self, line, col):
        """Extract file path from line text, preferring paths near the given column.

        Returns (file_path, line_number) tuple.
        """
        if not line:
            return None, None

        matches = []
        for match in FILE_PATH_PATTERN.finditer(line):
            file_path = match.group(1)
            line_num = int(match.group(2)) if match.group(2) else None
            start_pos = match.start(1)
            end_pos = match.end(1)
            matches.append((file_path, line_num, start_pos, end_pos))

        if not matches:
            return None, None

        best_match = None
        best_distance = float("inf")

        for file_path, line_num, start_pos, end_pos in matches:
            if start_pos <= col <= end_pos:
                return file_path, line_num

            if col < start_pos:
                distance = start_pos - col
            else:
                distance = col - end_pos

            if distance < best_distance:
                best_distance = distance
                best_match = (file_path, line_num)

        if best_match and best_distance <= 10:
            return best_match

        return None, None

    def _open_file_path(self, file_path, line_num=None):
        """Open the file path in the editor."""
        if not self.on_open_file:
            return

        if not os.path.isabs(file_path):
            resolved_path = self._resolve_file_path(file_path)
            if resolved_path:
                file_path = resolved_path
            else:
                return

        if os.path.isfile(file_path):
            self.on_open_file(file_path, line_num)

    def _resolve_file_path(self, relative_path):
        """Resolve a relative path to an absolute path using workspace folders and cwd.

        Only searches the workspace folder that contains the terminal's cwd,
        preventing cross-repo navigation when a file is missing locally.
        """
        candidate = os.path.join(self.cwd, relative_path)
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)

        if self._get_workspace_folders:
            cwd_abs = os.path.abspath(self.cwd)
            for folder in self._get_workspace_folders():
                folder_abs = os.path.abspath(folder)
                if not cwd_abs.startswith(folder_abs + os.sep) and cwd_abs != folder_abs:
                    continue
                candidate = os.path.join(folder_abs, relative_path)
                if os.path.isfile(candidate):
                    return os.path.abspath(candidate)

        return None
