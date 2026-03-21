"""Tests for shared/ide_state_writer.py — IDE state file for AI context."""

import json
from unittest.mock import patch

from shared.ide_state_writer import (
    get_state_file_path,
    read_ide_state,
    write_ide_state,
)


class TestWriteIdeState:
    """Test writing IDE state to JSON file."""

    def test_writes_all_fields(self, tmp_path):
        state_file = tmp_path / "ide_state.json"
        with (
            patch("shared.ide_state_writer._STATE_DIR", str(tmp_path)),
            patch("shared.ide_state_writer._STATE_FILE", str(state_file)),
        ):
            write_ide_state(
                active_file="/src/main.py",
                open_files=["/src/main.py", "/src/utils.py"],
                workspace_folders=["/projects/app"],
                workspace_file="/projects/app.code-workspace",
                git_branch="feature/new-ui",
            )

            data = json.loads(state_file.read_text())
            assert data["active_file"] == "/src/main.py"
            assert data["open_files"] == ["/src/main.py", "/src/utils.py"]
            assert data["workspace_folders"] == ["/projects/app"]
            assert data["workspace_file"] == "/projects/app.code-workspace"
            assert data["git_branch"] == "feature/new-ui"

    def test_writes_defaults_when_empty(self, tmp_path):
        state_file = tmp_path / "ide_state.json"
        with (
            patch("shared.ide_state_writer._STATE_DIR", str(tmp_path)),
            patch("shared.ide_state_writer._STATE_FILE", str(state_file)),
        ):
            write_ide_state()

            data = json.loads(state_file.read_text())
            assert data["active_file"] == ""
            assert data["open_files"] == []
            assert data["workspace_folders"] == []
            assert data["workspace_file"] == ""
            assert data["git_branch"] == ""

    def test_overwrites_previous_state(self, tmp_path):
        state_file = tmp_path / "ide_state.json"
        with (
            patch("shared.ide_state_writer._STATE_DIR", str(tmp_path)),
            patch("shared.ide_state_writer._STATE_FILE", str(state_file)),
        ):
            write_ide_state(active_file="/old.py")
            write_ide_state(active_file="/new.py")

            data = json.loads(state_file.read_text())
            assert data["active_file"] == "/new.py"

    def test_creates_directory_if_missing(self, tmp_path):
        nested = tmp_path / "subdir"
        state_file = nested / "ide_state.json"
        with (
            patch("shared.ide_state_writer._STATE_DIR", str(nested)),
            patch("shared.ide_state_writer._STATE_FILE", str(state_file)),
        ):
            write_ide_state(active_file="/test.py")
            assert state_file.exists()

    def test_silently_ignores_write_errors(self, tmp_path):
        """Writing to a read-only path should not raise."""
        with (
            patch("shared.ide_state_writer._STATE_DIR", "/nonexistent/readonly/path"),
            patch("shared.ide_state_writer._STATE_FILE", "/nonexistent/readonly/path/ide_state.json"),
            patch("os.makedirs", side_effect=PermissionError("no access")),
        ):
            write_ide_state(active_file="/test.py")


class TestReadIdeState:
    """Test reading IDE state from JSON file."""

    def test_reads_written_state(self, tmp_path):
        state_file = tmp_path / "ide_state.json"
        with (
            patch("shared.ide_state_writer._STATE_DIR", str(tmp_path)),
            patch("shared.ide_state_writer._STATE_FILE", str(state_file)),
        ):
            write_ide_state(active_file="/src/app.py", git_branch="main")
            state = read_ide_state()
            assert state["active_file"] == "/src/app.py"
            assert state["git_branch"] == "main"

    def test_returns_empty_dict_on_missing_file(self, tmp_path):
        with patch("shared.ide_state_writer._STATE_FILE", str(tmp_path / "missing.json")):
            assert read_ide_state() == {}

    def test_returns_empty_dict_on_corrupt_file(self, tmp_path):
        state_file = tmp_path / "ide_state.json"
        state_file.write_text("not valid json {{{")
        with patch("shared.ide_state_writer._STATE_FILE", str(state_file)):
            assert read_ide_state() == {}


class TestGetStateFilePath:
    """Test state file path helper."""

    def test_returns_string_path(self):
        path = get_state_file_path()
        assert isinstance(path, str)
        assert path.endswith("ide_state.json")
        assert ".zen_ide" in path


class TestAppendIdeContextPrompt:
    """Test the system prompt injection logic in AITerminalView."""

    def test_claude_cli_appends_system_prompt(self):
        from ai.ai_terminal_view import AITerminalView

        argv = ["/usr/bin/claude"]
        ctx = {
            "active_file": "/src/main.py",
            "open_files": ["/src/main.py", "/src/utils.py"],
            "workspace_folders": ["/projects/app"],
            "workspace_file": "",
            "git_branch": "main",
        }
        AITerminalView._append_ide_context_prompt(argv, "claude_cli", ctx)

        assert "--append-system-prompt" in argv
        prompt_idx = argv.index("--append-system-prompt")
        prompt_text = argv[prompt_idx + 1]
        assert "Active file" in prompt_text
        assert "/src/main.py" in prompt_text
        assert "main" in prompt_text
        assert "ide_state.json" in prompt_text

    def test_copilot_cli_writes_instructions_and_adds_dir(self):
        """Copilot CLI writes copilot-instructions.md and adds --add-dir."""
        from unittest.mock import patch as _patch

        from ai.ai_terminal_view import AITerminalView

        argv = ["/usr/bin/copilot"]
        ctx = {
            "active_file": "/src/app.rs",
            "open_files": ["/src/app.rs"],
            "workspace_folders": ["/projects/rust-app"],
            "workspace_file": "",
            "git_branch": "develop",
        }
        with _patch("ai.ai_terminal_view._write_copilot_instructions") as mock_write:
            AITerminalView._append_ide_context_prompt(argv, "copilot_cli", ctx)

            # Should write copilot instructions with context
            mock_write.assert_called_once()
            prompt_text = mock_write.call_args[0][0]
            assert "/src/app.rs" in prompt_text
            assert "develop" in prompt_text

        # Should add --add-dir for state file, but NOT -i
        assert "--add-dir" in argv
        assert "-i" not in argv

    def test_empty_context_does_not_append(self):
        from ai.ai_terminal_view import AITerminalView

        argv = ["/usr/bin/claude"]
        AITerminalView._append_ide_context_prompt(argv, "claude_cli", {})
        assert len(argv) == 1

    def test_none_context_does_not_append(self):
        from ai.ai_terminal_view import AITerminalView

        argv = ["/usr/bin/claude"]
        AITerminalView._append_ide_context_prompt(argv, "claude_cli", None)
        assert len(argv) == 1

    def test_partial_context_includes_available_fields(self):
        from ai.ai_terminal_view import AITerminalView

        argv = ["/usr/bin/claude"]
        ctx = {
            "active_file": "/src/test.py",
            "open_files": [],
            "workspace_folders": [],
            "workspace_file": "",
            "git_branch": "",
        }
        AITerminalView._append_ide_context_prompt(argv, "claude_cli", ctx)

        assert "--append-system-prompt" in argv
        prompt_text = argv[argv.index("--append-system-prompt") + 1]
        assert "/src/test.py" in prompt_text
        assert "Open files" not in prompt_text
        assert "Git branch" not in prompt_text


class TestWriteCopilotInstructions:
    """Test the copilot-instructions.md writer."""

    def test_creates_file_with_context(self, tmp_path):
        from unittest.mock import patch as _patch

        instructions_path = str(tmp_path / "copilot-instructions.md")
        with _patch("ai.ai_terminal_view._COPILOT_INSTRUCTIONS_PATH", instructions_path):
            from ai.ai_terminal_view import _write_copilot_instructions

            _write_copilot_instructions("## Zen IDE Context\n- Active file: /test.py")

            content = open(instructions_path).read()
            assert "zen-ide-context-start" in content
            assert "/test.py" in content
            assert "zen-ide-context-end" in content

    def test_preserves_existing_user_content(self, tmp_path):
        from unittest.mock import patch as _patch

        instructions_path = tmp_path / "copilot-instructions.md"
        instructions_path.write_text("# My custom instructions\nBe concise.\n")

        with _patch("ai.ai_terminal_view._COPILOT_INSTRUCTIONS_PATH", str(instructions_path)):
            from ai.ai_terminal_view import _write_copilot_instructions

            _write_copilot_instructions("## Zen IDE Context\n- Active file: /a.py")

            content = instructions_path.read_text()
            assert "# My custom instructions" in content
            assert "Be concise." in content
            assert "/a.py" in content

    def test_replaces_existing_managed_block(self, tmp_path):
        from unittest.mock import patch as _patch

        instructions_path = tmp_path / "copilot-instructions.md"
        instructions_path.write_text(
            "# My stuff\n<!-- zen-ide-context-start -->\nold context\n<!-- zen-ide-context-end -->\n# More stuff\n"
        )

        with _patch("ai.ai_terminal_view._COPILOT_INSTRUCTIONS_PATH", str(instructions_path)):
            from ai.ai_terminal_view import _write_copilot_instructions

            _write_copilot_instructions("new context")

            content = instructions_path.read_text()
            assert "old context" not in content
            assert "new context" in content
            assert "# My stuff" in content
            assert "# More stuff" in content
