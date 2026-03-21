"""Tests for pure helper functions in AI chat modules."""

import textwrap

from ai.ai_chat_terminal import AIChatTerminalView, _hex_to_ansi_fg

from ai import ai_chat_terminal as ai_chat_terminal_module


class TestHexToAnsiFg:
    """Test _hex_to_ansi_fg hex-to-ANSI conversion."""

    def test_pure_red(self):
        assert _hex_to_ansi_fg("#ff0000") == "\033[38;2;255;0;0m"

    def test_pure_green(self):
        assert _hex_to_ansi_fg("#00ff00") == "\033[38;2;0;255;0m"

    def test_pure_blue(self):
        assert _hex_to_ansi_fg("#0000ff") == "\033[38;2;0;0;255m"

    def test_white(self):
        assert _hex_to_ansi_fg("#ffffff") == "\033[38;2;255;255;255m"

    def test_black(self):
        assert _hex_to_ansi_fg("#000000") == "\033[38;2;0;0;0m"

    def test_without_hash(self):
        assert _hex_to_ansi_fg("61ffca") == "\033[38;2;97;255;202m"

    def test_accent_color(self):
        assert _hex_to_ansi_fg("#61ffca") == "\033[38;2;97;255;202m"


class TestLighten:
    """Test AIChatTerminalView._lighten color lightening."""

    @staticmethod
    def _lighten(hex_color, amount):
        """Extract pure logic from instance method."""
        hex_color = hex_color.lstrip("#")
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        r = min(255, int(r + (255 - r) * amount))
        g = min(255, int(g + (255 - g) * amount))
        b = min(255, int(b + (255 - b) * amount))
        return f"#{r:02x}{g:02x}{b:02x}"

    def test_black_fully_lightened_is_white(self):
        assert self._lighten("#000000", 1.0) == "#ffffff"

    def test_black_no_change(self):
        assert self._lighten("#000000", 0.0) == "#000000"

    def test_red_half_lightened(self):
        result = self._lighten("#ff0000", 0.5)
        assert result == "#ff7f7f"

    def test_white_stays_white(self):
        assert self._lighten("#ffffff", 0.5) == "#ffffff"

    def test_dark_grey_lightened(self):
        result = self._lighten("#333333", 0.5)
        # 0x33=51, lightened: 51 + (255-51)*0.5 = 51+102 = 153 = 0x99
        assert result == "#999999"

    def test_without_hash(self):
        assert self._lighten("000000", 1.0) == "#ffffff"


class TestWidgetTreeLookup:
    """Test widget ancestry checks used by panel click handling."""

    class _FakeWidget:
        def __init__(self, parent=None):
            self._parent = parent

        def get_parent(self):
            return self._parent

    def test_matches_same_widget(self):
        widget = self._FakeWidget()
        assert AIChatTerminalView._is_within_widget_tree(widget, widget) is True

    def test_matches_descendant_widget(self):
        ancestor = self._FakeWidget()
        child = self._FakeWidget(parent=ancestor)
        grandchild = self._FakeWidget(parent=child)

        assert AIChatTerminalView._is_within_widget_tree(grandchild, ancestor) is True

    def test_returns_false_for_unrelated_widget(self):
        ancestor = self._FakeWidget()
        unrelated = self._FakeWidget()

        assert AIChatTerminalView._is_within_widget_tree(unrelated, ancestor) is False


class TestResizeScrollPreservation:
    """Test resize-triggered scroll restoration helpers."""

    class _FakeAdjustment:
        def __init__(self, value=0, upper=1000, page_size=200):
            self.value = value
            self.upper = upper
            self.page_size = page_size

        def get_value(self):
            return self.value

        def set_value(self, value):
            self.value = value

        def get_upper(self):
            return self.upper

        def get_page_size(self):
            return self.page_size

    class _FakeScrolledWindow:
        def __init__(self, vadjustment):
            self._vadjustment = vadjustment

        def get_vadjustment(self):
            return self._vadjustment

    class _FakeTerminal:
        """Fake terminal that returns configurable scroll anchor and line Y."""

        def __init__(self, anchor_line=0, anchor_offset=0.0, line_y_map=None):
            self._anchor_line = anchor_line
            self._anchor_offset = anchor_offset
            self._line_y_map = line_y_map or {}

        def get_scroll_anchor(self):
            return (self._anchor_line, self._anchor_offset)

        def get_y_for_line(self, line_idx):
            return self._line_y_map.get(line_idx, 0.0)

    def test_restore_scroll_state_preserves_line_position(self, monkeypatch):
        """After resize, the same buffer line stays at the top of the viewport."""
        adjustment = self._FakeAdjustment(value=150, upper=1000, page_size=200)
        view = AIChatTerminalView.__new__(AIChatTerminalView)
        view._scrolled_window = self._FakeScrolledWindow(adjustment)
        view._scroll_generation = 0
        # Anchor at line 5 with 10px sub-line offset
        view.terminal = self._FakeTerminal(anchor_line=5, anchor_offset=10.0)

        state = view._capture_scroll_state()
        assert state["anchor_line"] == 5
        assert state["anchor_offset"] == 10.0

        # After resize, line 5 moved to y=300 in the new wrap map
        view.terminal = self._FakeTerminal(line_y_map={5: 300.0})
        adjustment.value = 0
        adjustment.upper = 1400

        monkeypatch.setattr(ai_chat_terminal_module.GLib, "idle_add", lambda callback, *args: callback(*args))

        view._restore_scroll_state(state, 1)

        # Should restore to line_y(5) + anchor_offset = 300 + 10 = 310
        assert adjustment.get_value() == 310.0

    def test_restore_scroll_state_keeps_bottom_pinned(self, monkeypatch):
        """When scrolled to bottom before resize, stay at bottom after."""
        adjustment = self._FakeAdjustment(value=600, upper=900, page_size=300)
        view = AIChatTerminalView.__new__(AIChatTerminalView)
        view._scrolled_window = self._FakeScrolledWindow(adjustment)
        view._scroll_generation = 0
        view.terminal = self._FakeTerminal(anchor_line=10, anchor_offset=0.0)

        state = view._capture_scroll_state()
        assert state["at_bottom"] is True

        adjustment.value = 0
        adjustment.upper = 1200

        monkeypatch.setattr(ai_chat_terminal_module.GLib, "idle_add", lambda callback, *args: callback(*args))

        view._restore_scroll_state(state, 1)

        # Should be at new bottom: 1200 - 300 = 900
        assert adjustment.get_value() == 900

    def test_scroll_to_bottom_ignores_stale_generation(self):
        adjustment = self._FakeAdjustment(value=80, upper=900, page_size=300)
        view = AIChatTerminalView.__new__(AIChatTerminalView)
        view._scrolled_window = self._FakeScrolledWindow(adjustment)
        view._scroll_generation = 3

        view.scroll_to_bottom(generation=2)

        assert adjustment.get_value() == 80


class TestWrapWithBar:
    """Test text wrapping with ▎ prefix."""

    @staticmethod
    def _wrap_with_bar(text, cols=80):
        """Extract pure logic from instance method."""
        available = max(cols - 2, 20)
        result = []
        for line in text.split("\n"):
            if not line:
                result.append("▎")
            elif len(line) <= available:
                result.append(f"▎ {line}")
            else:
                wrapped = textwrap.wrap(line, width=available)
                for wl in wrapped:
                    result.append(f"▎ {wl}")
                if not wrapped:
                    result.append("▎")
        return "\n".join(result)

    def test_single_line(self):
        assert self._wrap_with_bar("Hello") == "▎ Hello"

    def test_multi_line(self):
        result = self._wrap_with_bar("Hello\nWorld")
        assert result == "▎ Hello\n▎ World"

    def test_empty_line_gets_bar_only(self):
        result = self._wrap_with_bar("Hello\n\nWorld")
        assert result == "▎ Hello\n▎\n▎ World"

    def test_long_line_wraps(self):
        long_line = "a" * 100
        result = self._wrap_with_bar(long_line, cols=42)
        lines = result.split("\n")
        assert len(lines) >= 2
        assert all(line.startswith("▎") for line in lines)

    def test_empty_text(self):
        assert self._wrap_with_bar("") == "▎"

    def test_narrow_terminal_clamps_to_20(self):
        result = self._wrap_with_bar("short", cols=5)
        assert result == "▎ short"


class TestBuildPromptWithContext:
    """Test prompt assembly with file context and history."""

    @staticmethod
    def _build_prompt(user_message, file_path=None, messages=None):
        """Extract pure logic from instance method."""
        parts = []
        if file_path:
            parts.append(f"[Currently focused file: {file_path}]")
        if messages:
            history_parts = []
            recent_messages = messages[-10:]
            for msg in recent_messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "user":
                    history_parts.append(f"User: {content}")
                elif role == "assistant":
                    if len(content) > 2000:
                        content = content[:2000] + "...[truncated]"
                    history_parts.append(f"Assistant: {content}")
            if history_parts:
                parts.append("[Previous conversation]\n" + "\n\n".join(history_parts))
        parts.append(user_message)
        return "\n".join(parts) if len(parts) > 1 else user_message

    def test_message_only(self):
        assert self._build_prompt("hello") == "hello"

    def test_with_file_context(self):
        result = self._build_prompt("hello", file_path="/src/main.py")
        assert "[Currently focused file: /src/main.py]" in result
        assert "hello" in result

    def test_with_history(self):
        msgs = [
            {"role": "user", "content": "what is X?"},
            {"role": "assistant", "content": "X is ..."},
        ]
        result = self._build_prompt("follow up", messages=msgs)
        assert "User: what is X?" in result
        assert "Assistant: X is ..." in result
        assert "follow up" in result

    def test_truncates_long_assistant(self):
        msgs = [{"role": "assistant", "content": "a" * 3000}]
        result = self._build_prompt("q", messages=msgs)
        assert "...[truncated]" in result

    def test_only_last_10_messages(self):
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(15)]
        result = self._build_prompt("latest", messages=msgs)
        assert "msg5" in result  # 15-10=5, so msg5 is first included
        assert "msg4" not in result

    def test_with_file_and_history(self):
        msgs = [{"role": "user", "content": "hi"}]
        result = self._build_prompt("bye", file_path="/a.py", messages=msgs)
        lines = result.split("\n")
        assert lines[0] == "[Currently focused file: /a.py]"
        assert "bye" in result


class TestGetTabText:
    """Test tab text generation logic."""

    MAX_TITLE_LENGTH = 30

    @classmethod
    def _get_tab_text(cls, display_num, display_name=None, messages=None):
        """Extract pure logic from instance method (without infer_title)."""
        if display_name:
            clean_name = " ".join(display_name.split())
            if len(clean_name) > cls.MAX_TITLE_LENGTH:
                clean_name = clean_name[: cls.MAX_TITLE_LENGTH - 1] + "…"
            return clean_name.upper()
        return f"CHAT {display_num}"

    def test_fallback_chat_number(self):
        assert self._get_tab_text(1) == "CHAT 1"
        assert self._get_tab_text(5) == "CHAT 5"

    def test_display_name_uppercased(self):
        assert self._get_tab_text(1, display_name="my chat") == "MY CHAT"

    def test_display_name_whitespace_normalized(self):
        assert self._get_tab_text(1, display_name="  lots   of   spaces  ") == "LOTS OF SPACES"

    def test_display_name_truncated(self):
        long_name = "a" * 40
        result = self._get_tab_text(1, display_name=long_name)
        assert len(result) == self.MAX_TITLE_LENGTH
        assert result.endswith("…")

    def test_display_name_at_limit_not_truncated(self):
        exact_name = "a" * self.MAX_TITLE_LENGTH
        result = self._get_tab_text(1, display_name=exact_name)
        assert result == exact_name.upper()
        assert "…" not in result


class TestClaudeModelParsing:
    """Test Claude CLI model parsing logic from get_available_models."""

    @staticmethod
    def _parse_claude_models(help_text):
        """Extract the inline regex parsing logic from get_available_models."""
        import re

        models = set()
        alias_patterns = re.findall(r"'(sonnet|opus|haiku)'", help_text)
        full_model_patterns = re.findall(r"'(claude-[a-z0-9\-]+)'", help_text)
        for alias in alias_patterns:
            models.add(alias)
        for model in full_model_patterns:
            models.add(model)
        return sorted(list(models))

    def test_aliases_found(self):
        help_text = "Use --model with 'sonnet', 'opus', or 'haiku'"
        result = self._parse_claude_models(help_text)
        assert "sonnet" in result
        assert "opus" in result
        assert "haiku" in result

    def test_full_model_names(self):
        help_text = "Available: 'claude-sonnet-4-5-20250929' or 'claude-opus-4'"
        result = self._parse_claude_models(help_text)
        assert "claude-sonnet-4-5-20250929" in result
        assert "claude-opus-4" in result

    def test_mixed_aliases_and_full(self):
        help_text = "'sonnet' maps to 'claude-sonnet-4-5-20250929'"
        result = self._parse_claude_models(help_text)
        assert "sonnet" in result
        assert "claude-sonnet-4-5-20250929" in result

    def test_no_models_found(self):
        assert self._parse_claude_models("No model info here") == []

    def test_deduplication(self):
        help_text = "'sonnet' or 'sonnet'"
        result = self._parse_claude_models(help_text)
        assert result.count("sonnet") == 1


class TestSplitThinkingSegments:
    """Test _split_thinking_segments preserves segment order."""

    def test_plain_content_returns_single_content_segment(self):
        result = AIChatTerminalView._split_thinking_segments("hello world")
        assert result == [("content", "hello world")]

    def test_empty_text_returns_empty_list(self):
        assert AIChatTerminalView._split_thinking_segments("") == []

    def test_single_thinking_segment(self):
        text = "\u200bI am thinking"
        result = AIChatTerminalView._split_thinking_segments(text)
        assert result == [("thinking", "I am thinking")]

    def test_thinking_then_content(self):
        text = "\u200bthinking\u200ccontent"
        result = AIChatTerminalView._split_thinking_segments(text)
        assert result == [("thinking", "thinking"), ("content", "content")]

    def test_multiple_thinking_content_alternations(self):
        text = "\u200bthink1\u200ccontent1\u200bthink2\u200ccontent2"
        result = AIChatTerminalView._split_thinking_segments(text)
        assert result == [
            ("thinking", "think1"),
            ("content", "content1"),
            ("thinking", "think2"),
            ("content", "content2"),
        ]

    def test_preserves_order_unlike_split_thinking(self):
        """Verify segments preserve order while _split_thinking merges."""
        text = "\u200bthink1\u200ccontent1\u200bthink2\u200ccontent2"
        # _split_thinking merges everything
        thinking, content = AIChatTerminalView._split_thinking(text)
        assert thinking == "think1think2"
        assert content == "content1content2"
        # _split_thinking_segments preserves order
        segments = AIChatTerminalView._split_thinking_segments(text)
        assert len(segments) == 4
        assert segments[0] == ("thinking", "think1")
        assert segments[2] == ("thinking", "think2")
