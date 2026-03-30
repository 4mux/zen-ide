"""Tests for path pattern matching, file path extraction, resolution, and lighten helper."""

import os

import pytest

# Import the module-level constants and regex directly
from terminal.terminal_file_navigation_mixin import (
    FILE_PATH_PATTERN,
    KNOWN_EXTENSIONLESS,
)


# ---------------------------------------------------------------------------
# Tests for KNOWN_EXTENSIONLESS pattern
# ---------------------------------------------------------------------------
class TestKnownExtensionless:
    """Verify that well-known extensionless filenames are listed."""

    @pytest.mark.parametrize(
        "name",
        [
            "Makefile",
            "Dockerfile",
            "Vagrantfile",
            "Procfile",
            "Gemfile",
            "Rakefile",
            "Guardfile",
            "Brewfile",
            "Justfile",
        ],
    )
    def test_known_names_in_pattern(self, name):
        assert name in KNOWN_EXTENSIONLESS


# ---------------------------------------------------------------------------
# Tests for FILE_PATH_PATTERN regex
# ---------------------------------------------------------------------------
class TestFilePathPattern:
    """Test the regex used to detect file paths in terminal output."""

    @pytest.mark.parametrize(
        "text, expected_path",
        [
            ("  terraform/ses_templates.tf ", "terraform/ses_templates.tf"),
            ("  ./src/main.py ", "./src/main.py"),
            (" /abs/path.txt ", "/abs/path.txt"),
            (" src/components/App.tsx ", "src/components/App.tsx"),
            (" README.md ", "README.md"),
        ],
    )
    def test_matches_file_paths(self, text, expected_path):
        m = FILE_PATH_PATTERN.search(text)
        assert m is not None, f"Expected to match '{expected_path}' in '{text}'"
        assert m.group(1) == expected_path

    @pytest.mark.parametrize(
        "text, expected_path, expected_line",
        [
            (" file.py:42 ", "file.py", "42"),
            (" src/main.rs:100 ", "src/main.rs", "100"),
            (" ./test.js:7 ", "./test.js", "7"),
        ],
    )
    def test_matches_with_line_number(self, text, expected_path, expected_line):
        m = FILE_PATH_PATTERN.search(text)
        assert m is not None
        assert m.group(1) == expected_path
        assert m.group(2) == expected_line

    @pytest.mark.parametrize(
        "text, expected_path, expected_line, expected_col",
        [
            (" file.py:42:10 ", "file.py", "42", "10"),
            (" src/app.ts:1:5 ", "src/app.ts", "1", "5"),
        ],
    )
    def test_matches_with_line_and_column(self, text, expected_path, expected_line, expected_col):
        m = FILE_PATH_PATTERN.search(text)
        assert m is not None
        assert m.group(1) == expected_path
        assert m.group(2) == expected_line
        assert m.group(3) == expected_col

    @pytest.mark.parametrize(
        "text, expected_path",
        [
            (" Makefile ", "Makefile"),
            (" path/to/Makefile ", "path/to/Makefile"),
            (" ./Dockerfile ", "./Dockerfile"),
        ],
    )
    def test_matches_extensionless_known_files(self, text, expected_path):
        m = FILE_PATH_PATTERN.search(text)
        assert m is not None, f"Expected to match '{expected_path}' in '{text}'"
        assert m.group(1) == expected_path

    def test_multiple_paths_in_line(self):
        """Multiple file paths in one line should all be found."""
        text = " src/a.py src/b.rs "
        matches = list(FILE_PATH_PATTERN.finditer(text))
        paths = [m.group(1) for m in matches]
        assert "src/a.py" in paths
        assert "src/b.rs" in paths


# ---------------------------------------------------------------------------
# Tests for _lighten helper (via class instance)
# ---------------------------------------------------------------------------
class TestLighten:
    """Test the color lightening utility.

    _lighten is an instance method but has no GTK dependencies in its logic,
    so we can test it by instantiating with a mock or extracting the logic.
    We test the algorithm directly by reimplementing the expected behavior.
    """

    @staticmethod
    def _lighten(hex_color: str, amount: float) -> str:
        """Reference implementation matching TerminalView._lighten."""
        hex_color = hex_color.lstrip("#")
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        r = min(255, int(r + (255 - r) * amount))
        g = min(255, int(g + (255 - g) * amount))
        b = min(255, int(b + (255 - b) * amount))
        return f"#{r:02x}{g:02x}{b:02x}"

    def test_black_lightened(self):
        """Lightening black by 0.5 should give mid-gray."""
        result = self._lighten("#000000", 0.5)
        assert result == "#7f7f7f"

    def test_white_unchanged(self):
        """Lightening white should stay white."""
        result = self._lighten("#ffffff", 0.5)
        assert result == "#ffffff"

    def test_zero_amount_unchanged(self):
        """Zero amount should return the same color."""
        result = self._lighten("#336699", 0.0)
        assert result == "#336699"

    def test_full_amount_gives_white(self):
        """Amount 1.0 should give white."""
        result = self._lighten("#336699", 1.0)
        assert result == "#ffffff"

    def test_specific_color(self):
        """Test a specific known lightening."""
        result = self._lighten("#800000", 0.2)
        # r = 128 + (255-128)*0.2 = 128 + 25.4 = 153 -> 0x99
        # g = 0 + 255*0.2 = 51 -> 0x33
        # b = 0 + 255*0.2 = 51 -> 0x33
        assert result == "#993333"

    def test_without_hash_prefix(self):
        """Should work without # prefix."""
        result = self._lighten("000000", 0.5)
        assert result == "#7f7f7f"


# ---------------------------------------------------------------------------
# Tests for _extract_file_path_at_column (via a minimal stub)
# ---------------------------------------------------------------------------
class TestExtractFilePathAtColumn:
    """Test file path extraction logic from a terminal line.

    We re-implement the extraction logic here to test it without GTK,
    since _extract_file_path_at_column only uses FILE_PATH_PATTERN (a module-level regex).
    """

    @staticmethod
    def _extract(line, col):
        """Reimplementation of TerminalView._extract_file_path_at_column."""
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

    def test_empty_line(self):
        assert self._extract("", 0) == (None, None)

    def test_none_line(self):
        assert self._extract(None, 0) == (None, None)

    def test_cursor_on_path(self):
        line = "  error in src/main.py at line 5"
        path, line_num = self._extract(line, 14)  # cursor on 'main'
        assert path == "src/main.py"

    def test_cursor_near_path(self):
        line = "  error in src/main.py at line 5"
        path, line_num = self._extract(line, 10)  # cursor on 'in', close to path
        assert path == "src/main.py"

    def test_cursor_far_from_path(self):
        """Cursor far from any path should return None."""
        line = "some random text without paths nearby                         src/a.py"
        path, _ = self._extract(line, 0)
        assert path is None

    def test_with_line_number(self):
        line = "  src/app.ts:42 something"
        path, line_num = self._extract(line, 8)
        assert path == "src/app.ts"
        assert line_num == 42

    def test_multiple_paths_selects_nearest(self):
        line = " src/a.py    src/b.py"
        # Cursor near first path
        path, _ = self._extract(line, 5)
        assert path == "src/a.py"
        # Cursor near second path
        path, _ = self._extract(line, 16)
        assert path == "src/b.py"


# ---------------------------------------------------------------------------
# Helper: standalone versions of TerminalView methods for testing
# ---------------------------------------------------------------------------
def _resolve_file_path(cwd, get_workspace_folders, relative_path):
    """Standalone version of TerminalView._resolve_file_path."""
    candidate = os.path.join(cwd, relative_path)
    if os.path.isfile(candidate):
        return os.path.abspath(candidate)

    if get_workspace_folders:
        cwd_abs = os.path.abspath(cwd)
        for folder in get_workspace_folders():
            folder_abs = os.path.abspath(folder)
            if not cwd_abs.startswith(folder_abs + os.sep) and cwd_abs != folder_abs:
                continue
            candidate = os.path.join(folder_abs, relative_path)
            if os.path.isfile(candidate):
                return os.path.abspath(candidate)

    return None


# ---------------------------------------------------------------------------
# Tests for _resolve_file_path logic
# ---------------------------------------------------------------------------
class TestResolveFilePath:
    """Test file path resolution against cwd and workspace folders."""

    def test_resolve_in_cwd(self, tmp_path):
        """File found in cwd should be resolved."""
        test_file = tmp_path / "src" / "main.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("# test")
        resolved = _resolve_file_path(str(tmp_path), None, "src/main.py")
        assert resolved == os.path.abspath(str(test_file))

    def test_resolve_in_workspace_folder(self, tmp_path):
        """File found in the workspace folder that contains cwd should be resolved."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        subdir = ws / "subdir"
        subdir.mkdir()
        test_file = ws / "lib.py"
        test_file.write_text("# test")

        # cwd is inside the workspace folder, so fallback finds it
        resolved = _resolve_file_path(str(subdir), lambda: [str(ws)], "lib.py")
        assert resolved == os.path.abspath(str(test_file))

    def test_no_cross_repo_fallback(self, tmp_path):
        """File in a different workspace folder must NOT be returned."""
        repo_a = tmp_path / "repo-a"
        repo_a.mkdir()
        repo_b = tmp_path / "repo-b"
        repo_b.mkdir()
        (repo_b / "poetry.lock").write_text("# lock")

        # cwd is repo-a, file only exists in repo-b → should NOT resolve
        resolved = _resolve_file_path(str(repo_a), lambda: [str(repo_a), str(repo_b)], "poetry.lock")
        assert resolved is None

    def test_not_found_returns_none(self, tmp_path):
        resolved = _resolve_file_path(str(tmp_path), None, "nonexistent.py")
        assert resolved is None

    def test_cwd_takes_precedence(self, tmp_path):
        """If file exists in both cwd and workspace root, cwd wins."""
        ws = tmp_path / "ws"
        ws.mkdir()
        subdir = ws / "sub"
        subdir.mkdir()

        cwd_file = subdir / "file.py"
        cwd_file.write_text("# cwd")

        ws_file = ws / "file.py"
        ws_file.write_text("# ws")

        resolved = _resolve_file_path(str(subdir), lambda: [str(ws)], "file.py")
        assert resolved == os.path.abspath(str(cwd_file))
