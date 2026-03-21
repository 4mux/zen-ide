"""Tests for yolo mode (ai.yolo_mode setting).

Yolo mode appends a permission-skipping flag to AI CLI commands:
  - Claude CLI: --dangerously-skip-permissions
  - Copilot CLI: --yolo

When disabled, those flags are omitted, requiring interactive confirmation.
"""

from unittest.mock import patch

import shared.settings.settings_manager as sm
from shared.settings.default_settings import DEFAULT_SETTINGS

# ---------------------------------------------------------------------------
# Default setting
# ---------------------------------------------------------------------------


class TestYoloModeDefaultSetting:
    """Verify yolo_mode default in settings."""

    def test_default_is_true(self):
        assert DEFAULT_SETTINGS["ai"]["yolo_mode"] is True


# ---------------------------------------------------------------------------
# Claude CLI command building
# ---------------------------------------------------------------------------


def _build_claude_cmd(yolo_value):
    """Simulate the Claude CLI command-building branch (mirrors _run_ai_cli)."""
    cmd = [
        "claude",
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        "sonnet",
        "--allowedTools",
        "Edit,Write,Read,Glob,Grep,Bash",
    ]
    with patch.object(sm, "_settings", {"ai": {"yolo_mode": yolo_value}}):
        if sm.get_setting("ai.yolo_mode", True):
            cmd.append("--dangerously-skip-permissions")
    return cmd


class TestClaudeCLIYoloMode:
    """Verify Claude CLI includes/excludes --dangerously-skip-permissions."""

    def test_yolo_enabled_appends_flag(self):
        cmd = _build_claude_cmd(True)
        assert "--dangerously-skip-permissions" in cmd

    def test_yolo_disabled_omits_flag(self):
        cmd = _build_claude_cmd(False)
        assert "--dangerously-skip-permissions" not in cmd

    def test_flag_appears_once(self):
        cmd = _build_claude_cmd(True)
        assert cmd.count("--dangerously-skip-permissions") == 1


# ---------------------------------------------------------------------------
# Copilot CLI command building
# ---------------------------------------------------------------------------


def _build_copilot_cmd(yolo_value):
    """Simulate the Copilot CLI command-building branch (mirrors _run_ai_cli)."""
    cmd = [
        "copilot",
        "--prompt",
        "hello",
        "--model",
        "claude-opus-4.5",
        "--allow-all-paths",
        "--allow-all-tools",
        "--output-format",
        "json",
        "--stream",
        "on",
        "--silent",
    ]
    with patch.object(sm, "_settings", {"ai": {"yolo_mode": yolo_value}}):
        if sm.get_setting("ai.yolo_mode", True):
            cmd.append("--yolo")
    return cmd


class TestCopilotCLIYoloMode:
    """Verify Copilot CLI includes/excludes --yolo."""

    def test_yolo_enabled_appends_flag(self):
        cmd = _build_copilot_cmd(True)
        assert "--yolo" in cmd

    def test_yolo_disabled_omits_flag(self):
        cmd = _build_copilot_cmd(False)
        assert "--yolo" not in cmd

    def test_flag_appears_once(self):
        cmd = _build_copilot_cmd(True)
        assert cmd.count("--yolo") == 1


# ---------------------------------------------------------------------------
# get_setting integration
# ---------------------------------------------------------------------------


class TestYoloModeSettingLookup:
    """Verify get_setting returns correct yolo_mode values."""

    def test_returns_true_from_defaults(self):
        with patch.object(sm, "_settings", {"ai": {"yolo_mode": True}}):
            assert sm.get_setting("ai.yolo_mode") is True

    def test_returns_false_when_disabled(self):
        with patch.object(sm, "_settings", {"ai": {"yolo_mode": False}}):
            assert sm.get_setting("ai.yolo_mode") is False

    def test_returns_default_when_key_missing(self):
        with patch.object(sm, "_settings", {"ai": {}}):
            assert sm.get_setting("ai.yolo_mode", True) is True

    def test_returns_default_when_ai_section_missing(self):
        with patch.object(sm, "_settings", {}):
            assert sm.get_setting("ai.yolo_mode", True) is True


# ---------------------------------------------------------------------------
# Tool iteration limit (yolo_mode bypasses the limit)
# ---------------------------------------------------------------------------

from ai.ai_chat_terminal import _MAX_TOOL_ITERATIONS


def _should_limit_tools(yolo_value: bool, iteration_count: int) -> bool:
    """Simulate the tool-use limit check from _on_tool_use.

    Returns True when the limit would be enforced (i.e. processing stops).
    """
    with patch.object(sm, "_settings", {"ai": {"yolo_mode": yolo_value}}):
        yolo_mode = sm.get_setting("ai.yolo_mode", True)
        return not yolo_mode and iteration_count > _MAX_TOOL_ITERATIONS


class TestToolIterationLimit:
    """Verify tool iteration limit respects yolo_mode."""

    def test_yolo_enabled_no_limit_at_max(self):
        """In yolo mode, hitting _MAX_TOOL_ITERATIONS does NOT trigger the limit."""
        assert _should_limit_tools(True, _MAX_TOOL_ITERATIONS + 1) is False

    def test_yolo_enabled_no_limit_at_extreme(self):
        """In yolo mode, even extreme iteration counts are allowed."""
        assert _should_limit_tools(True, 10000) is False

    def test_yolo_disabled_no_limit_below_max(self):
        """Without yolo mode, iterations below the limit are allowed."""
        assert _should_limit_tools(False, _MAX_TOOL_ITERATIONS - 1) is False

    def test_yolo_disabled_no_limit_at_max(self):
        """Without yolo mode, exactly _MAX_TOOL_ITERATIONS is still allowed (> not >=)."""
        assert _should_limit_tools(False, _MAX_TOOL_ITERATIONS) is False

    def test_yolo_disabled_limit_above_max(self):
        """Without yolo mode, exceeding _MAX_TOOL_ITERATIONS triggers the limit."""
        assert _should_limit_tools(False, _MAX_TOOL_ITERATIONS + 1) is True

    def test_max_tool_iterations_is_5(self):
        """Verify the constant value for documentation purposes."""
        assert _MAX_TOOL_ITERATIONS == 5


# ---------------------------------------------------------------------------
# System prompt includes unlimited-tools instruction in yolo mode
# ---------------------------------------------------------------------------


def _build_system_prompt(yolo_value: bool) -> str:
    """Simulate the system prompt building from _run_ai_http."""
    system_parts = [
        "You are a coding assistant integrated into Zen IDE.",
        "You have tools to read, write, edit files, search code, and run commands.",
        "Use tools to fulfill the user's requests — make real changes, don't just suggest them.",
        "When editing files, prefer edit_file for surgical changes over write_file.",
    ]
    with patch.object(sm, "_settings", {"ai": {"yolo_mode": yolo_value}}):
        yolo_mode = sm.get_setting("ai.yolo_mode", True)
        if yolo_mode:
            system_parts.append(
                "\nIMPORTANT: There is NO tool use limit. You have UNLIMITED tool calls per response. "
                "Never stop mid-task to say you've reached a limit. Never output '[Tool use limit reached]' or similar. "
                "Always complete the full task in a single response, using as many tool calls as needed."
            )
    return "\n".join(system_parts)


class TestSystemPromptYoloMode:
    """Verify system prompt includes unlimited-tools instruction when yolo is enabled."""

    def test_yolo_enabled_includes_unlimited_instruction(self):
        prompt = _build_system_prompt(True)
        assert "NO tool use limit" in prompt
        assert "UNLIMITED tool calls" in prompt

    def test_yolo_enabled_forbids_limit_message(self):
        prompt = _build_system_prompt(True)
        assert "Never output '[Tool use limit reached]'" in prompt

    def test_yolo_disabled_omits_unlimited_instruction(self):
        prompt = _build_system_prompt(False)
        assert "NO tool use limit" not in prompt
        assert "UNLIMITED tool calls" not in prompt


# ---------------------------------------------------------------------------
# Tool limit pattern detection (auto-continue in yolo mode)
# ---------------------------------------------------------------------------

from ai.ai_chat_terminal import AIChatTerminalView


class TestToolLimitPatternDetection:
    """Verify _TOOL_LIMIT_PATTERNS catches hallucinated limit messages."""

    pattern = AIChatTerminalView._TOOL_LIMIT_PATTERNS

    def test_bracket_tool_use_limit_reached(self):
        assert self.pattern.search("[Tool use limit reached]")

    def test_bracket_stopped(self):
        assert self.pattern.search("[Stopped]")

    def test_unbracketed_tool_use_limit_reached(self):
        assert self.pattern.search("Tool use limit reached")

    def test_ive_reached_the_tool_use_limit(self):
        assert self.pattern.search("I've reached the tool use limit")

    def test_ive_reached_my_tool_limit(self):
        assert self.pattern.search("I've reached my tool limit")

    def test_i_have_reached_the_tool_use_limit(self):
        assert self.pattern.search("I have reached the tool-use limit")

    def test_ive_used_all_tool_calls(self):
        assert self.pattern.search("I've used all of my tool calls")

    def test_reached_maximum_tool_calls(self):
        assert self.pattern.search("reached the maximum number of tool calls")

    def test_stopping_due_to_tool_limit(self):
        assert self.pattern.search("stopping here due to the tool use limit")

    def test_stopping_because_of_tool_limit(self):
        assert self.pattern.search("stopping now because of tool limit")

    def test_normal_text_not_matched(self):
        assert not self.pattern.search("I used the read_file tool to check the contents")

    def test_normal_tool_mention_not_matched(self):
        assert not self.pattern.search("Let me use another tool to verify")

    def test_case_insensitive(self):
        assert self.pattern.search("TOOL USE LIMIT REACHED")
        assert self.pattern.search("tool use limit reached")

    def test_strip_from_response(self):
        text = "Here is the result.\n\n[Tool use limit reached]"
        cleaned = self.pattern.sub("", text)
        assert "[Tool use limit reached]" not in cleaned
        assert "Here is the result." in cleaned
