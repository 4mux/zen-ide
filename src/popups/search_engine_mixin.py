"""
Search engine module for global search — ripgrep integration.

Extracted from global_search_dialog.py — contains SearchResult, search backend,
and SearchEngineMixin for use by GlobalSearchDialog.

Requires ripgrep (rg) to be installed (see ``make install-system-deps``).
"""

import fnmatch
import os
import subprocess

from shared.git_ignore_utils import collect_global_patterns, get_global_patterns

# Binary file extensions to skip
BINARY_EXTENSIONS = frozenset(
    {
        ".pyc",
        ".pyo",
        ".so",
        ".dll",
        ".dylib",
        ".exe",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".ico",
        ".svg",
        ".webp",
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",
        ".mp3",
        ".mp4",
        ".wav",
        ".avi",
        ".mov",
        ".mkv",
        ".ttf",
        ".otf",
        ".woff",
        ".woff2",
        ".eot",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".class",
        ".jar",
        ".war",
        ".o",
        ".a",
        ".lib",
    }
)


class SearchResult:
    """Represents a single search result."""

    def __init__(self, file_path: str, line_number: int, line_text: str, match_start: int, match_end: int):
        self.file_path = file_path
        self.line_number = line_number
        self.line_text = line_text.strip()
        self.match_start = match_start
        self.match_end = match_end


class SearchEngineMixin:
    """Mixin providing ripgrep search backend for GlobalSearchDialog.

    Expects the host class to have:
        - self.workspace_folders: list[str]
        - self.case_sensitive: Gtk.CheckButton (with .get_active())
        - self._get_search_folders() -> list[str]
    """

    _search_generation: int = 0

    def _should_skip_path(self, rel_path: str) -> bool:
        """Check if a path should be excluded from search results."""
        global_patterns = get_global_patterns()
        parts = rel_path.replace("\\", "/").split("/")
        for part in parts:
            if part in global_patterns:
                return True
            for pattern in global_patterns:
                if "*" in pattern and fnmatch.fnmatch(part, pattern):
                    return True
        ext = os.path.splitext(rel_path)[1].lower()
        if ext in BINARY_EXTENSIONS:
            return True
        return False

    def _search_worker(self, query: str, generation: int, case_flag: list, search_folders: list):
        """Search worker running in background thread.

        All GTK widget state (case_flag, search_folders) is read on the main
        thread before this method is called, avoiding undefined behaviour.
        """
        from shared.main_thread import main_thread_call

        try:
            collect_global_patterns(self.workspace_folders)

            valid_folders = [f for f in search_folders if os.path.isdir(f)]
            if not valid_folders:
                if self._search_generation == generation:
                    main_thread_call(self._update_results, [])
                return

            search_results = self._ripgrep_search(valid_folders, query, case_flag)

            results = []
            if search_results:
                for file_path, line_num, line_text, match_start, match_end in search_results:
                    results.append(SearchResult(file_path, line_num, line_text, match_start, match_end))
                    if len(results) >= 500:
                        break

            if self._search_generation == generation:
                main_thread_call(self._update_results, results)
        except Exception:
            if self._search_generation == generation:
                main_thread_call(self._update_results, [])

    def _ripgrep_search(self, folders: list, query: str, case_flag: list) -> list | None:
        """Search all folders in a single ripgrep invocation.

        Ripgrep natively respects .gitignore per repo, handles binary
        detection, and parallelises across cores.
        """
        try:
            exclude_args = []
            for pattern in get_global_patterns():
                exclude_args.extend(["-g", f"!{pattern}"])

            result = subprocess.run(
                ["rg", "-n", "--no-heading", "--color=never", "--hidden", "-F"]
                + case_flag
                + exclude_args
                + ["--", query]
                + folders,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode not in (0, 1):
                return None

            results = []
            for line in result.stdout.split("\n"):
                if not line:
                    continue

                parts = line.split(":", 2)
                if len(parts) >= 3:
                    file_path = parts[0]

                    rel_path = file_path
                    for folder in folders:
                        if file_path.startswith(folder):
                            rel_path = file_path[len(folder) :].lstrip(os.sep)
                            break

                    if self._should_skip_path(rel_path):
                        continue

                    try:
                        line_num = int(parts[1])
                    except ValueError:
                        continue
                    line_text = parts[2]

                    match_start = line_text.lower().find(query.lower()) if case_flag else line_text.find(query)
                    match_end = match_start + len(query) if match_start >= 0 else 0

                    results.append((file_path, line_num, line_text, match_start, match_end))

                    if len(results) >= 500:
                        break

            return results
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return None
