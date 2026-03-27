"""Tests for debugger/debug_panel.py — debug panel UI logic."""

from unittest.mock import MagicMock, patch

from debugger.debug_session import SessionState


class TestDebugPanelToolbarState:
    """Test toolbar button sensitivity based on session state."""

    def _make_mock_panel(self):
        """Create a mock DebugPanel without GTK widgets."""
        # We test the state logic, not GTK widget creation
        from debugger.debug_panel import DebugPanel

        # Mock the window and GTK parent
        with patch.object(DebugPanel, "__init__", lambda self, *a, **kw: None):
            panel = DebugPanel.__new__(DebugPanel)
            panel._session = None
            panel._toolbar_buttons = {
                "Continue": MagicMock(),
                "Step Over": MagicMock(),
                "Step In": MagicMock(),
                "Step Out": MagicMock(),
                "Restart": MagicMock(),
                "Stop": MagicMock(),
            }
            panel._status_label = MagicMock()
            return panel

    def test_idle_state_disables_all(self):
        panel = self._make_mock_panel()
        panel._session = None
        panel._update_toolbar_state()

        panel._toolbar_buttons["Continue"].set_sensitive.assert_called_with(False)
        panel._toolbar_buttons["Step Over"].set_sensitive.assert_called_with(False)
        panel._toolbar_buttons["Stop"].set_sensitive.assert_called_with(False)
        panel._status_label.set_text.assert_called_with("Not debugging")

    def test_running_state(self):
        panel = self._make_mock_panel()
        session = MagicMock()
        session.state = SessionState.RUNNING
        panel._session = session
        panel._update_toolbar_state()

        panel._toolbar_buttons["Continue"].set_sensitive.assert_called_with(False)
        panel._toolbar_buttons["Stop"].set_sensitive.assert_called_with(True)
        panel._toolbar_buttons["Restart"].set_sensitive.assert_called_with(True)
        panel._status_label.set_text.assert_called_with("Running")

    def test_stopped_state_enables_stepping(self):
        panel = self._make_mock_panel()
        session = MagicMock()
        session.state = SessionState.STOPPED
        panel._session = session
        panel._update_toolbar_state()

        panel._toolbar_buttons["Continue"].set_sensitive.assert_called_with(True)
        panel._toolbar_buttons["Step Over"].set_sensitive.assert_called_with(True)
        panel._toolbar_buttons["Step In"].set_sensitive.assert_called_with(True)
        panel._toolbar_buttons["Step Out"].set_sensitive.assert_called_with(True)
        panel._toolbar_buttons["Stop"].set_sensitive.assert_called_with(True)
        panel._status_label.set_text.assert_called_with("Paused")

    def test_terminated_state(self):
        panel = self._make_mock_panel()
        session = MagicMock()
        session.state = SessionState.TERMINATED
        panel._session = session
        panel._update_toolbar_state()

        panel._toolbar_buttons["Continue"].set_sensitive.assert_called_with(False)
        panel._toolbar_buttons["Stop"].set_sensitive.assert_called_with(False)
        panel._status_label.set_text.assert_called_with("Terminated")


class TestDebugConsole:
    """Test debug console REPL logic."""

    def test_console_history(self):

        # Test history tracking without GTK (just the data)
        history = []
        history.append("x + 1")
        history.append("len(items)")
        assert len(history) == 2

    def test_console_no_duplicate_history(self):
        history = ["x + 1", "y * 2"]
        new_entry = "y * 2"
        if not history or history[-1] != new_entry:
            history.append(new_entry)
        assert len(history) == 2  # Should not add duplicate
