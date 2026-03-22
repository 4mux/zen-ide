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
    view._idle_poll_id = 0
    view._last_contents_serial = 0
    view.on_processing_changed = MagicMock()
    view.on_title_inferred = None
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

    def test_commit_ready_false_ignores_everything(self):
        view = _make_view()
        view._commit_ready = False

        _send_commit(view, "hello\r")

        assert view._waiting_for_response is False
        view.on_processing_changed.assert_not_called()

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
        view.on_processing_changed.assert_not_called()

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
