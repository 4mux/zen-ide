"""Tests for AI terminal spinner lifecycle — escape filtering, idle detection, and commit state machine."""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from ai.ai_terminal_view import AITerminalView, _strip_escape_fragments

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_view():
    """Create an AITerminalView with GTK/VTE plumbing mocked out."""
    with patch.object(AITerminalView, "__init__", lambda self, **kw: None):
        view = AITerminalView.__new__(AITerminalView)

    # Replicate the __init__ state we need
    view._current_provider = "claude_cli"
    view._input_buf = []
    view._title_inferred = True  # skip title inference in tests
    view._waiting_for_response = False
    view._commit_ready = True
    view._in_escape_seq = False
    view._in_osc_seq = False
    view._idle_poll_id = 0
    view._last_contents_serial = 0
    view._vscroll_adj = MagicMock()
    view._vscroll_adj.get_value.return_value = 100.0
    view._vscroll_inhibit = False
    view._vscroll_hide_id = 0
    view._vscroll_hovering = False
    view._jog_tick_id = 0
    view._vscrollbar = MagicMock()
    view.on_processing_changed = MagicMock()
    view.on_title_inferred = None
    view.on_user_prompt = None
    view.shell_pid = 42
    view.terminal = MagicMock()
    return view


def _send_commit(view, text):
    """Simulate the VTE commit signal with the given text."""
    view._on_vte_commit(None, text, len(text))


# ---------------------------------------------------------------------------
# _strip_escape_fragments
# ---------------------------------------------------------------------------


class TestStripEscapeFragments:
    def test_removes_csi_fragment(self):
        assert _strip_escape_fragments("[?1;2c") == ""

    def test_removes_bracketed_paste(self):
        assert _strip_escape_fragments("[200~") == ""

    def test_preserves_normal_text(self):
        assert _strip_escape_fragments("hello world") == "hello world"

    def test_mixed(self):
        assert _strip_escape_fragments("hello[?1;2c world") == "hello world"

    def test_does_not_eat_user_input_after_bracket(self):
        """Regression: '[p' from '[ping' was matched as escape fragment."""
        assert _strip_escape_fragments("[ping") == "[ping" or _strip_escape_fragments("[ping").endswith("ping")
        # Single letter after [ without params must NOT be stripped
        assert "ping" in _strip_escape_fragments("[ping")
        assert "hello" in _strip_escape_fragments("[hello")

    def test_requires_params_in_csi_fragment(self):
        """CSI fragments need digits or ? between [ and the final letter."""
        assert _strip_escape_fragments("[?25h") == ""
        assert _strip_escape_fragments("[200~") == ""
        assert _strip_escape_fragments("[1;2c") == ""
        # No params → not a fragment
        assert _strip_escape_fragments("ping") == "ping"

    def test_da2_residue(self):
        """DA2 response residue like '>65;6003;1c' is stripped."""
        assert _strip_escape_fragments(">65;6003;1c") == ""
        assert _strip_escape_fragments(">65;6003;1cping") == "ping"

    def test_leading_junk_stripped(self):
        """Leading non-alphanumeric chars from escape params are stripped."""
        assert _strip_escape_fragments(";?>ping") == "ping"

    def test_preserves_leading_digits(self):
        """User input starting with digits is preserved."""
        assert _strip_escape_fragments("3 things to fix") == "3 things to fix"


# ---------------------------------------------------------------------------
# Escape sequence filtering in _on_vte_commit
# ---------------------------------------------------------------------------


class TestEscapeSequenceFiltering:
    """Escape sequences must not be mistaken for user input."""

    def test_focus_out_does_not_stop_spinner(self):
        """VTE focus-out (\x1b[O) must not stop the spinner."""
        view = _make_view()
        view._waiting_for_response = True

        _send_commit(view, "\x1b[O")

        assert view._waiting_for_response is True
        view.on_processing_changed.assert_not_called()

    def test_focus_in_does_not_stop_spinner(self):
        """VTE focus-in (\x1b[I) must not stop the spinner."""
        view = _make_view()
        view._waiting_for_response = True

        _send_commit(view, "\x1b[I")

        assert view._waiting_for_response is True
        view.on_processing_changed.assert_not_called()

    def test_cursor_report_does_not_stop_spinner(self):
        """Cursor position report (\x1b[6;1R) must not stop the spinner."""
        view = _make_view()
        view._waiting_for_response = True

        _send_commit(view, "\x1b[6;1R")

        assert view._waiting_for_response is True
        view.on_processing_changed.assert_not_called()

    def test_bracketed_paste_end_does_not_stop_spinner(self):
        """Bracketed paste end (\x1b[201~) must not stop the spinner."""
        view = _make_view()
        view._waiting_for_response = True

        _send_commit(view, "\x1b[201~")

        assert view._waiting_for_response is True
        view.on_processing_changed.assert_not_called()

    def test_real_typing_after_escape_still_works(self):
        """Real user input after an escape sequence should be processed."""
        view = _make_view()
        view._waiting_for_response = True

        _send_commit(view, "\x1b[Oa")

        # 'a' is real input → spinner should stop
        assert view._waiting_for_response is False
        view.on_processing_changed.assert_called_once_with(False)

    def test_escape_state_resets_between_commits(self):
        """A partial escape at end of one commit shouldn't leak into the next."""
        view = _make_view()
        view._waiting_for_response = True

        # Incomplete escape — only ESC byte
        _send_commit(view, "\x1b")
        assert view._in_escape_seq is True

        # Next commit has the rest plus terminator
        _send_commit(view, "[I")
        # Should have consumed the escape, no side effects
        assert view._waiting_for_response is True
        assert view._in_escape_seq is False

    def test_dcs_sequence_fully_consumed(self):
        """Regression: DCS (\x1bP...\x1b\\) like XTVERSION must not leak payload."""
        view = _make_view()
        view._waiting_for_response = True

        # XTVERSION response: \x1bP>|VTE(6003)\x1b\\
        _send_commit(view, "\x1bP>|VTE(6003)\x1b\\")

        # All consumed — no printable chars should reach the buffer
        assert view._input_buf == []
        assert view._waiting_for_response is True
        view.on_processing_changed.assert_not_called()

    def test_dcs_across_commits(self):
        """DCS split across two commit calls is still consumed."""
        view = _make_view()

        _send_commit(view, "\x1bP>|VTE")
        assert view._in_escape_seq is True
        assert view._in_osc_seq is True  # DCS uses osc-like payload mode

        _send_commit(view, "(6003)\x1b\\")
        assert view._in_escape_seq is False
        assert view._input_buf == []

    def test_osc_sequence_consumed(self):
        """OSC (\x1b]...BEL) sequences are fully consumed."""
        view = _make_view()
        view._waiting_for_response = True

        _send_commit(view, "\x1b]0;window title\x07")

        assert view._input_buf == []
        assert view._waiting_for_response is True


# ---------------------------------------------------------------------------
# Commit handler state machine
# ---------------------------------------------------------------------------


class TestCommitStateMachine:
    """Test the spinner start/stop transitions driven by VTE commit."""

    def test_enter_with_text_starts_spinner(self):
        view = _make_view()

        _send_commit(view, "hello\r")

        assert view._waiting_for_response is True
        view.on_processing_changed.assert_called_once_with(True)

    def test_enter_without_text_does_not_start_spinner(self):
        view = _make_view()

        _send_commit(view, "\r")

        assert view._waiting_for_response is False
        view.on_processing_changed.assert_not_called()

    def test_typing_while_waiting_stops_spinner(self):
        view = _make_view()
        view._waiting_for_response = True

        _send_commit(view, "x")

        assert view._waiting_for_response is False
        view.on_processing_changed.assert_called_once_with(False)

    def test_backspace_while_waiting_stops_spinner(self):
        view = _make_view()
        view._waiting_for_response = True
        view._input_buf = ["a"]

        _send_commit(view, "\x7f")

        assert view._waiting_for_response is False
        view.on_processing_changed.assert_called_once_with(False)

    def test_commit_always_processes_input(self):
        """Commits are processed even before _commit_ready (no gating)."""
        view = _make_view()
        view._commit_ready = False

        _send_commit(view, "hello\r")

        # Input is processed regardless of _commit_ready
        assert view._waiting_for_response is True
        view.on_processing_changed.assert_called_once_with(True)

    def test_second_enter_while_waiting_restarts_cycle(self):
        """Typing a new prompt while waiting stops then restarts the spinner."""
        view = _make_view()

        _send_commit(view, "first\r")
        assert view._waiting_for_response is True
        view.on_processing_changed.assert_called_once_with(True)

        view.on_processing_changed.reset_mock()
        # Typing "second\r" while waiting: 's' stops spinner, '\r' restarts it
        _send_commit(view, "second\r")
        calls = [c.args for c in view.on_processing_changed.call_args_list]
        assert calls == [(False,), (True,)]
        assert view._waiting_for_response is True


# ---------------------------------------------------------------------------
# Title inference regression tests
# ---------------------------------------------------------------------------


class TestTitleInference:
    """Regression tests for tab title inference from user input."""

    def test_title_inferred_on_first_message(self):
        """Title should be inferred from the very first user message."""
        view = _make_view()
        view._title_inferred = False
        view.on_title_inferred = MagicMock()

        _send_commit(view, "fix the bug in main.py\r")

        assert view._title_inferred is True
        view.on_title_inferred.assert_called_once()
        title = view.on_title_inferred.call_args[0][0]
        assert len(title) > 0
        assert "fix" in title.lower() or "bug" in title.lower()

    def test_title_not_set_if_infer_returns_none(self):
        """Regression: _title_inferred must stay False if infer_title returns None."""
        view = _make_view()
        view._title_inferred = False
        view.on_title_inferred = MagicMock()

        # Single char — too short to infer
        _send_commit(view, "x\r")

        # Title was not inferred — flag should remain False so next message retries
        if not view.on_title_inferred.called:
            assert view._title_inferred is False

    def test_title_retries_on_subsequent_messages(self):
        """If first message doesn't produce a title, subsequent messages should retry."""
        view = _make_view()
        view._title_inferred = False
        view.on_title_inferred = MagicMock()

        # First message might not produce a good title
        _send_commit(view, "\r")  # empty
        assert view._title_inferred is False

        # Second message should still try
        _send_commit(view, "fix the bug in main.py\r")
        assert view._title_inferred is True
        view.on_title_inferred.assert_called_once()

    def test_startup_noise_does_not_corrupt_title(self):
        """Regression: VTE startup escape sequences must not appear in title."""
        view = _make_view()
        view._title_inferred = False
        view.on_title_inferred = MagicMock()

        # Simulate startup noise followed by user input
        _send_commit(view, "\x1b[?1;2c")  # DA response
        _send_commit(view, "\x1bP>|VTE(6003)\x1b\\")  # XTVERSION
        _send_commit(view, "fix the bug\r")

        assert view._title_inferred is True
        title = view.on_title_inferred.call_args[0][0]
        assert "vte" not in title.lower()
        assert "fix" in title.lower() or "bug" in title.lower()

    def test_input_not_dropped_before_commit_ready(self):
        """Regression: user typing before _commit_ready must not be dropped."""
        view = _make_view()
        view._commit_ready = False
        view._title_inferred = False
        view.on_title_inferred = MagicMock()

        # User types before commit_ready
        _send_commit(view, "hello world\r")

        # Input should be processed — no gating
        assert view._waiting_for_response is True
        assert view._title_inferred is True
        view.on_title_inferred.assert_called_once()

    def test_escape_fragments_stripped_from_title_input(self):
        """Regression: '[ping' must produce 'Ping', not 'Ing'."""
        view = _make_view()
        view._title_inferred = False
        view.on_title_inferred = MagicMock()

        # Simulate stray [ in buffer followed by user input
        view._input_buf = ["["]
        _send_commit(view, "ping\r")

        assert view._title_inferred is True
        title = view.on_title_inferred.call_args[0][0]
        # Must contain "ping", not be truncated to "ing"
        assert "ping" in title.lower()


# ---------------------------------------------------------------------------
# PTY idle detection (_check_idle)
# ---------------------------------------------------------------------------


class TestIdleDetection:
    """Test the PTY-based idle poll that stops the spinner."""

    def test_content_still_changing_keeps_polling(self):
        view = _make_view()
        view._waiting_for_response = True
        view._last_contents_serial = 5
        view._idle_prev_serial = -1
        view._idle_poll_id = 1

        result = view._check_idle()

        # Serial changed → keep polling
        assert result is True
        assert view._waiting_for_response is True
        assert view._idle_prev_serial == 5

    def test_content_stable_and_cli_is_foreground_stops_spinner(self):
        view = _make_view()
        view._waiting_for_response = True
        view._last_contents_serial = 5
        view._idle_prev_serial = 5  # stable
        view._idle_poll_id = 1

        mock_pty = MagicMock()
        mock_pty.get_fd.return_value = 3
        view.terminal.get_pty.return_value = mock_pty

        with patch("os.tcgetpgrp", return_value=42):  # matches shell_pid
            result = view._check_idle()

        assert result is False
        assert view._waiting_for_response is False
        view.on_processing_changed.assert_called_once_with(False)

    def test_content_stable_but_subprocess_running_keeps_polling(self):
        view = _make_view()
        view._waiting_for_response = True
        view._last_contents_serial = 5
        view._idle_prev_serial = 5  # stable
        view._idle_poll_id = 1

        mock_pty = MagicMock()
        mock_pty.get_fd.return_value = 3
        view.terminal.get_pty.return_value = mock_pty

        # Different PID → a tool subprocess is the foreground process
        with patch("os.tcgetpgrp", return_value=999):
            result = view._check_idle()

        assert result is True
        assert view._waiting_for_response is True

    def test_no_pty_keeps_polling(self):
        view = _make_view()
        view._waiting_for_response = True
        view._last_contents_serial = 5
        view._idle_prev_serial = 5
        view._idle_poll_id = 1

        view.terminal.get_pty.return_value = None

        result = view._check_idle()

        assert result is True
        assert view._waiting_for_response is True

    def test_tcgetpgrp_oserror_keeps_polling(self):
        view = _make_view()
        view._waiting_for_response = True
        view._last_contents_serial = 5
        view._idle_prev_serial = 5
        view._idle_poll_id = 1

        mock_pty = MagicMock()
        mock_pty.get_fd.return_value = 3
        view.terminal.get_pty.return_value = mock_pty

        with patch("os.tcgetpgrp", side_effect=OSError("bad fd")):
            result = view._check_idle()

        assert result is True
        assert view._waiting_for_response is True

    def test_not_waiting_stops_immediately(self):
        view = _make_view()
        view._waiting_for_response = False
        view._idle_poll_id = 1

        result = view._check_idle()

        assert result is False
        assert view._idle_poll_id == 0

    def test_contents_changed_increments_serial(self):
        view = _make_view()
        assert view._last_contents_serial == 0

        view._on_contents_changed(None)
        assert view._last_contents_serial == 1

        view._on_contents_changed(None)
        view._on_contents_changed(None)
        assert view._last_contents_serial == 3


class TestVirtualScrollbarOverlay:
    def test_show_virtual_scrollbar_temporarily_reveals_and_reschedules(self):
        view = _make_view()
        view._vscrollbar = MagicMock()
        view._vscroll_hide_id = 17

        with (
            patch("terminal.terminal_jog_wheel.GLib.source_remove") as mock_remove,
            patch("terminal.terminal_jog_wheel.GLib.timeout_add", return_value=23) as mock_timeout,
        ):
            view._show_virtual_scrollbar_temporarily()

        mock_remove.assert_called_once_with(17)
        view._vscrollbar.set_visible.assert_called_once_with(True)
        mock_timeout.assert_called_once()
        assert view._vscroll_hide_id == 23

    def test_vscroll_reset_hides_scrollbar(self):
        view = _make_view()
        view._vscrollbar = MagicMock()
        view._vscroll_hide_id = 31
        view._vscroll_inhibit = False
        view._jog_tick_id = 0

        adj = MagicMock()
        adj.get_value.return_value = 50.0
        view._vscroll_adj = adj

        with patch("terminal.terminal_jog_wheel.GLib.source_remove") as mock_remove:
            view._vscroll_reset()

        mock_remove.assert_called_once_with(31)
        # Jog snaps to center from both _vscroll_reset and _hide_immediately
        assert adj.set_value.call_count == 2
        view._vscrollbar.set_visible.assert_called_once_with(False)
        assert view._vscroll_hide_id == 0
