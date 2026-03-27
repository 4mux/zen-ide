"""Tests for debugger/bdb_debugger.py — bdb-based Python debugger."""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
from concurrent.futures import Future
from unittest.mock import MagicMock, patch

from debugger.bdb_debugger import BdbClient, _is_expandable, _safe_repr


class TestSafeRepr:
    """Test _safe_repr helper."""

    def test_simple_values(self):
        assert _safe_repr(42) == "42"
        assert _safe_repr("hello") == "'hello'"
        assert _safe_repr(None) == "None"

    def test_truncates_long_repr(self):
        long_list = list(range(1000))
        result = _safe_repr(long_list, limit=50)
        assert len(result) <= 54  # 50 + "..."
        assert result.endswith("...")

    def test_handles_repr_error(self):
        class BadRepr:
            def __repr__(self):
                raise ValueError("boom")

        result = _safe_repr(BadRepr())
        assert "BadRepr" in result


class TestIsExpandable:
    """Test _is_expandable helper."""

    def test_primitives_not_expandable(self):
        assert not _is_expandable(42)
        assert not _is_expandable("hello")
        assert not _is_expandable(3.14)
        assert not _is_expandable(True)
        assert not _is_expandable(None)

    def test_empty_containers_not_expandable(self):
        assert not _is_expandable([])
        assert not _is_expandable({})
        assert not _is_expandable(())
        assert not _is_expandable(set())

    def test_non_empty_containers_expandable(self):
        assert _is_expandable([1, 2, 3])
        assert _is_expandable({"a": 1})
        assert _is_expandable((1,))
        assert _is_expandable({1, 2})

    def test_objects_with_dict_expandable(self):
        class Foo:
            def __init__(self):
                self.x = 1

        assert _is_expandable(Foo())

    def test_objects_without_attrs_not_expandable(self):
        class Empty:
            __slots__ = ()

        assert not _is_expandable(Empty())


class TestBdbClientInit:
    """Test BdbClient initialization."""

    def test_init_defaults(self):
        client = BdbClient(lambda e, b: None)
        assert client._process is None
        assert not client.is_running
        assert client._seq == 0
        assert client._pending == {}

    def test_stop_without_start_is_safe(self):
        client = BdbClient(lambda e, b: None)
        client.stop()  # Should not raise


class TestBdbClientCommands:
    """Test BdbClient command sending."""

    def _make_client(self):
        client = BdbClient(lambda e, b: None)
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        client._process = mock_proc
        client._running = True
        return client

    def test_set_break_sends_json(self):
        client = self._make_client()
        client.set_break("/test.py", 10, condition="x > 5")

        written = client._process.stdin.write.call_args[0][0]
        msg = json.loads(written.decode("utf-8"))
        assert msg["cmd"] == "set_break"
        assert msg["file"] == "/test.py"
        assert msg["line"] == 10
        assert msg["condition"] == "x > 5"

    def test_continue_sends_json(self):
        client = self._make_client()
        client.continue_()

        written = client._process.stdin.write.call_args[0][0]
        msg = json.loads(written.decode("utf-8"))
        assert msg["cmd"] == "continue"

    def test_step_over_sends_json(self):
        client = self._make_client()
        client.step_over()

        written = client._process.stdin.write.call_args[0][0]
        msg = json.loads(written.decode("utf-8"))
        assert msg["cmd"] == "step_over"

    def test_step_into_sends_json(self):
        client = self._make_client()
        client.step_into()

        written = client._process.stdin.write.call_args[0][0]
        msg = json.loads(written.decode("utf-8"))
        assert msg["cmd"] == "step_into"

    def test_step_out_sends_json(self):
        client = self._make_client()
        client.step_out()

        written = client._process.stdin.write.call_args[0][0]
        msg = json.loads(written.decode("utf-8"))
        assert msg["cmd"] == "step_out"


class TestBdbClientRequests:
    """Test BdbClient request/response."""

    def _make_client(self):
        client = BdbClient(lambda e, b: None)
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        client._process = mock_proc
        client._running = True
        return client

    def test_get_stack_returns_future(self):
        client = self._make_client()
        future = client.get_stack()
        assert isinstance(future, Future)
        assert not future.done()

    def test_get_scopes_returns_future(self):
        client = self._make_client()
        future = client.get_scopes(frame_id=0)
        assert isinstance(future, Future)

    def test_get_variables_returns_future(self):
        client = self._make_client()
        future = client.get_variables(ref=1)
        assert isinstance(future, Future)

    def test_evaluate_returns_future(self):
        client = self._make_client()
        future = client.evaluate("x + 1", frame_id=0)
        assert isinstance(future, Future)

    def test_request_increments_seq(self):
        client = self._make_client()
        client.get_stack()
        assert client._seq == 1
        client.get_scopes()
        assert client._seq == 2

    def test_request_registers_pending(self):
        client = self._make_client()
        client.get_stack()
        assert 1 in client._pending


class TestBdbClientDispatch:
    """Test message dispatching."""

    def test_dispatch_response_resolves_future(self):
        client = BdbClient(lambda e, b: None)
        future = Future()
        client._pending[1] = future

        client._dispatch(
            {
                "event": "response",
                "id": 1,
                "frames": [{"id": 0, "name": "main", "file": "/test.py", "line": 10}],
            }
        )

        assert future.done()
        result = future.result()
        assert len(result["frames"]) == 1

    @patch("shared.main_thread.main_thread_call")
    def test_dispatch_event_calls_on_event(self, mock_mtc):
        events = []
        client = BdbClient(lambda e, b: events.append((e, b)))

        client._dispatch(
            {
                "event": "stopped",
                "file": "/test.py",
                "line": 10,
                "reason": "breakpoint",
            }
        )

        mock_mtc.assert_called_once()
        args = mock_mtc.call_args[0]
        assert args[1] == "stopped"
        assert args[2]["line"] == 10

    def test_stop_cancels_pending(self):
        client = BdbClient(lambda e, b: None)
        future = Future()
        client._pending[1] = future

        mock_proc = MagicMock()
        client._process = mock_proc
        client._running = True

        client.stop()
        assert len(client._pending) == 0
        assert not client._running


class TestBdbBridgeIntegration:
    """Integration test — run the bridge subprocess and interact with it."""

    def test_run_simple_script_to_completion(self):
        """Run a simple script with no breakpoints — should terminate."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("x = 42\nprint(x)\n")
            f.flush()
            script = f.name

        try:
            from debugger.bdb_debugger import _BRIDGE_SCRIPT

            proc = subprocess.Popen(
                [sys.executable, "-u", _BRIDGE_SCRIPT, script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            # Send "run" command
            proc.stdin.write(json.dumps({"cmd": "run"}).encode() + b"\n")
            proc.stdin.flush()

            # Read events
            events = []
            deadline = time.time() + 10
            while time.time() < deadline:
                line = proc.stdout.readline()
                if not line:
                    break
                msg = json.loads(line.decode("utf-8"))
                events.append(msg)
                if msg.get("event") == "terminated":
                    break

            proc.wait(timeout=5)

            # Should have output event with "42" and terminated event
            event_types = [e.get("event") for e in events]
            assert "terminated" in event_types
            output_texts = [e.get("text", "") for e in events if e.get("event") == "output"]
            assert any("42" in t for t in output_texts)

        finally:
            os.unlink(script)

    def test_breakpoint_stops_execution(self):
        """Set a breakpoint and verify the program stops there."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(
                textwrap.dedent("""\
                x = 1
                y = 2
                z = x + y
                print(z)
            """)
            )
            f.flush()
            script = f.name

        try:
            from debugger.bdb_debugger import _BRIDGE_SCRIPT

            proc = subprocess.Popen(
                [sys.executable, "-u", _BRIDGE_SCRIPT, script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            def send(cmd):
                proc.stdin.write(json.dumps(cmd).encode() + b"\n")
                proc.stdin.flush()

            def read_event(timeout=10):
                deadline = time.time() + timeout
                while time.time() < deadline:
                    line = proc.stdout.readline()
                    if line:
                        return json.loads(line.decode("utf-8"))
                return None

            # Set breakpoint on line 3 and run
            send({"cmd": "set_break", "file": script, "line": 3})
            send({"cmd": "run"})

            # Should stop at line 3
            events = []
            while True:
                evt = read_event()
                if evt is None:
                    break
                events.append(evt)
                if evt.get("event") == "stopped":
                    break

            stopped = [e for e in events if e.get("event") == "stopped"]
            assert len(stopped) == 1
            assert stopped[0]["line"] == 3

            # Get stack
            send({"cmd": "get_stack", "id": 1})
            resp = read_event()
            assert resp.get("event") == "response"
            assert len(resp["frames"]) >= 1
            assert resp["frames"][0]["line"] == 3

            # Get variables
            send({"cmd": "get_scopes", "id": 2, "frame_id": 0})
            resp = read_event()
            assert resp.get("event") == "response"
            assert len(resp["scopes"]) >= 1
            local_ref = resp["scopes"][0]["ref"]

            send({"cmd": "get_variables", "id": 3, "ref": local_ref})
            resp = read_event()
            assert resp.get("event") == "response"
            var_names = [v["name"] for v in resp["variables"]]
            assert "x" in var_names
            assert "y" in var_names

            # Continue to end
            send({"cmd": "continue"})
            while True:
                evt = read_event()
                if evt is None or evt.get("event") == "terminated":
                    break

            proc.wait(timeout=5)

        finally:
            os.unlink(script)
