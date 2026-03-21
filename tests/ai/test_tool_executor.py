"""Tests for ai.tool_executor module."""

import pytest
from ai.tool_executor import ToolExecutor


@pytest.fixture
def workspace(tmp_path):
    """Create a temporary workspace with some test files."""
    (tmp_path / "hello.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "data.txt").write_text("line1\nline2\nline3\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("import os\ndef main():\n    pass\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def executor(workspace):
    return ToolExecutor(str(workspace))


class TestReadFile:
    def test_read_existing_file(self, executor, workspace):
        result = executor.execute("read_file", {"file_path": "hello.py"})
        assert "print('hello')" in result

    def test_read_missing_file(self, executor):
        result = executor.execute("read_file", {"file_path": "missing.py"})
        assert "Error" in result
        assert "not found" in result

    def test_read_file_no_path(self, executor):
        result = executor.execute("read_file", {})
        assert "Error" in result

    def test_read_nested_file(self, executor, workspace):
        result = executor.execute("read_file", {"file_path": "src/app.py"})
        assert "import os" in result


class TestWriteFile:
    def test_write_new_file(self, executor, workspace):
        result = executor.execute("write_file", {"file_path": "new.txt", "content": "hello world"})
        assert "Successfully wrote" in result
        assert (workspace / "new.txt").read_text() == "hello world"

    def test_write_creates_dirs(self, executor, workspace):
        result = executor.execute("write_file", {"file_path": "a/b/c.txt", "content": "deep"})
        assert "Successfully wrote" in result
        assert (workspace / "a" / "b" / "c.txt").read_text() == "deep"

    def test_write_overwrite(self, executor, workspace):
        result = executor.execute("write_file", {"file_path": "hello.py", "content": "new content"})
        assert "Successfully wrote" in result
        assert (workspace / "hello.py").read_text() == "new content"

    def test_write_no_path(self, executor):
        result = executor.execute("write_file", {"content": "x"})
        assert "Error" in result


class TestEditFile:
    def test_edit_replaces_text(self, executor, workspace):
        result = executor.execute(
            "edit_file",
            {
                "file_path": "hello.py",
                "old_text": "print('hello')",
                "new_text": "print('world')",
            },
        )
        assert "Successfully edited" in result
        assert (workspace / "hello.py").read_text() == "print('world')\n"

    def test_edit_text_not_found(self, executor, workspace):
        result = executor.execute(
            "edit_file",
            {
                "file_path": "hello.py",
                "old_text": "not_here",
                "new_text": "replacement",
            },
        )
        assert "Error" in result
        assert "not found" in result

    def test_edit_multiple_matches(self, executor, workspace):
        (workspace / "dup.txt").write_text("aaa\naaa\n")
        result = executor.execute(
            "edit_file",
            {
                "file_path": "dup.txt",
                "old_text": "aaa",
                "new_text": "bbb",
            },
        )
        assert "Error" in result
        assert "2 locations" in result

    def test_edit_missing_file(self, executor):
        result = executor.execute(
            "edit_file",
            {
                "file_path": "missing.py",
                "old_text": "x",
                "new_text": "y",
            },
        )
        assert "Error" in result
        assert "not found" in result


class TestListFiles:
    def test_list_all_py(self, executor, workspace):
        result = executor.execute("list_files", {"pattern": "**/*.py"})
        assert "hello.py" in result
        assert "app.py" in result

    def test_list_no_match(self, executor):
        result = executor.execute("list_files", {"pattern": "**/*.xyz"})
        assert "No files" in result

    def test_list_with_path(self, executor, workspace):
        result = executor.execute("list_files", {"pattern": "*.py", "path": "src"})
        assert "app.py" in result


class TestSearchFiles:
    def test_search_pattern(self, executor, workspace):
        result = executor.execute("search_files", {"pattern": "import"})
        assert "app.py" in result

    def test_search_no_match(self, executor):
        result = executor.execute("search_files", {"pattern": "nonexistent_pattern_xyz"})
        assert "No matches" in result

    def test_search_with_include(self, executor, workspace):
        result = executor.execute("search_files", {"pattern": "print", "include": "*.py"})
        assert "hello.py" in result


class TestRunCommand:
    def test_run_echo(self, executor):
        result = executor.execute("run_command", {"command": "echo hello"})
        assert "hello" in result

    def test_run_failing_command(self, executor):
        result = executor.execute("run_command", {"command": "false"})
        assert "Exit code:" in result

    def test_run_no_command(self, executor):
        result = executor.execute("run_command", {})
        assert "Error" in result


class TestUnknownTool:
    def test_unknown_tool(self, executor):
        result = executor.execute("unknown_tool", {})
        assert "Unknown tool" in result


class TestPathSecurity:
    def test_path_traversal_blocked(self, executor):
        result = executor.execute("read_file", {"file_path": "../../etc/passwd"})
        assert "Error" in result
        assert "outside" in result
