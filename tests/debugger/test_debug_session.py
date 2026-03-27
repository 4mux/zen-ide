"""Tests for debugger/debug_session.py — debug session lifecycle and state machine."""

from concurrent.futures import Future
from unittest.mock import MagicMock

from debugger.debug_config import DebugConfig
from debugger.debug_session import DebugSession, Scope, SessionState, StackFrame, Variable


def _make_config(**kwargs):
    defaults = {"name": "Test", "program": "/test.py", "cwd": "/tmp"}
    defaults.update(kwargs)
    return DebugConfig(**defaults)


class TestSessionState:
    """Test session state enum."""

    def test_all_states_exist(self):
        assert SessionState.IDLE.value == "idle"
        assert SessionState.INITIALIZING.value == "initializing"
        assert SessionState.RUNNING.value == "running"
        assert SessionState.STOPPED.value == "stopped"
        assert SessionState.TERMINATED.value == "terminated"


class TestDataClasses:
    """Test data classes used by the debug panel."""

    def test_stack_frame(self):
        frame = StackFrame(id=0, name="main", source="/test.py", line=10)
        assert frame.name == "main"
        assert frame.source == "/test.py"
        assert frame.line == 10
        assert frame.column == 0

    def test_scope(self):
        scope = Scope(name="Locals", variables_reference=1)
        assert scope.name == "Locals"
        assert scope.variables_reference == 1
        assert scope.expensive is False

    def test_variable(self):
        var = Variable(name="x", value="42", type="int", variables_reference=0)
        assert var.name == "x"
        assert var.value == "42"
        assert var.type == "int"
        assert var.variables_reference == 0


class TestSessionInit:
    """Test session initialization."""

    def test_initial_state_is_idle(self):
        session = DebugSession(_make_config())
        assert session.state == SessionState.IDLE

    def test_no_current_frame_initially(self):
        session = DebugSession(_make_config())
        assert session.current_frame is None


class TestSessionCallbacks:
    """Test callback notifications."""

    def test_state_changed_callback(self):
        states = []
        session = DebugSession(_make_config(), on_state_changed=lambda s: states.append(s.state))
        session._set_state(SessionState.RUNNING)
        assert SessionState.RUNNING in states

    def test_output_callback(self):
        outputs = []
        session = DebugSession(_make_config(), on_output=lambda text, cat: outputs.append((text, cat)))
        session._emit_output("console", "hello")
        assert ("hello", "console") in outputs

    def test_callback_exception_doesnt_propagate(self):
        def bad_callback(s):
            raise RuntimeError("boom")

        session = DebugSession(_make_config(), on_state_changed=bad_callback)
        session._set_state(SessionState.RUNNING)  # Should not raise


class TestExecutionControl:
    """Test execution control methods require correct state."""

    def test_continue_requires_stopped_state(self):
        session = DebugSession(_make_config())
        session.state = SessionState.RUNNING
        session._client = MagicMock()
        session.continue_()  # Should be a no-op (not stopped)
        session._client.continue_.assert_not_called()

    def test_step_over_requires_stopped_state(self):
        session = DebugSession(_make_config())
        session.state = SessionState.IDLE
        session._client = MagicMock()
        session.step_over()
        session._client.step_over.assert_not_called()

    def test_step_into_requires_stopped_state(self):
        session = DebugSession(_make_config())
        session.state = SessionState.IDLE
        session._client = MagicMock()
        session.step_into()
        session._client.step_into.assert_not_called()

    def test_step_out_requires_stopped_state(self):
        session = DebugSession(_make_config())
        session.state = SessionState.IDLE
        session._client = MagicMock()
        session.step_out()
        session._client.step_out.assert_not_called()

    def test_continue_with_stopped_state(self):
        session = DebugSession(_make_config())
        session.state = SessionState.STOPPED
        mock_client = MagicMock()
        session._client = mock_client
        session.continue_()
        mock_client.continue_.assert_called_once()
        assert session.state == SessionState.RUNNING

    def test_step_over_with_stopped_state(self):
        session = DebugSession(_make_config())
        session.state = SessionState.STOPPED
        mock_client = MagicMock()
        session._client = mock_client
        session.step_over()
        mock_client.step_over.assert_called_once()

    def test_pause_is_noop(self):
        session = DebugSession(_make_config())
        session.state = SessionState.RUNNING
        session._client = MagicMock()
        session.pause()  # Should not raise


class TestEventHandling:
    """Test event handling from bdb subprocess."""

    def test_stopped_event_updates_state(self):
        session = DebugSession(_make_config())
        session.state = SessionState.RUNNING
        mock_client = MagicMock()
        # get_stack returns a future that resolves to empty stack
        future = Future()
        future.set_result({"frames": []})
        mock_client.get_stack.return_value = future
        session._client = mock_client

        session._on_event("stopped", {"file": "/test.py", "line": 10, "reason": "breakpoint"})
        assert session.state == SessionState.STOPPED

    def test_terminated_event_stops_session(self):
        outputs = []
        session = DebugSession(_make_config(), on_output=lambda c, t: outputs.append((c, t)))
        mock_client = MagicMock()
        session._client = mock_client

        session._on_event("terminated", {"exit_code": 0})
        assert session.state == SessionState.TERMINATED
        assert session._client is None

    def test_output_event_emits_output(self):
        outputs = []
        session = DebugSession(_make_config(), on_output=lambda t, c: outputs.append((t, c)))
        session._on_event("output", {"category": "stdout", "text": "hello\n"})
        assert ("hello\n", "stdout") in outputs


class TestStop:
    """Test session stop/cleanup."""

    def test_stop_clears_state(self):
        session = DebugSession(_make_config())
        mock_client = MagicMock()
        session._client = mock_client

        session.stop()
        assert session.state == SessionState.TERMINATED
        assert session._client is None
        mock_client.stop.assert_called_once()

    def test_stop_without_client_is_safe(self):
        session = DebugSession(_make_config())
        session.stop()  # Should not raise
        assert session.state == SessionState.TERMINATED


class TestInspection:
    """Test inspection methods."""

    def test_evaluate_not_stopped(self):
        session = DebugSession(_make_config())
        session.state = SessionState.RUNNING
        result = session.evaluate("x + 1")
        assert result == "<not stopped>"

    def test_get_call_stack_not_stopped(self):
        session = DebugSession(_make_config())
        session.state = SessionState.RUNNING
        assert session.get_call_stack() == []

    def test_get_variables_not_stopped(self):
        session = DebugSession(_make_config())
        session.state = SessionState.RUNNING
        assert session.get_variables(1) == []

    def test_get_scopes_not_stopped(self):
        session = DebugSession(_make_config())
        session.state = SessionState.RUNNING
        assert session.get_scopes() == []

    def test_set_current_frame(self):
        session = DebugSession(_make_config())
        session._client = MagicMock()
        frame = StackFrame(id=2, name="foo", source="/test.py", line=20)
        session.set_current_frame(frame)
        assert session.current_frame == frame
        session._client.set_frame.assert_called_once_with(2)
