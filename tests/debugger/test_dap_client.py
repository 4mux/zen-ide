"""Tests for debugger/dap_client.py — DAP protocol client."""

import json
from concurrent.futures import Future
from unittest.mock import MagicMock, patch

from debugger.dap_client import DapClient
from debugger.dap_registry import DapAdapterInfo


def _make_dap_message(msg: dict) -> bytes:
    """Encode a DAP message with Content-Length framing."""
    body = json.dumps(msg).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


class TestDapClientTransformers:
    """Test response transformers (no subprocess needed)."""

    def test_transform_stack(self):
        resp = {
            "body": {
                "stackFrames": [
                    {
                        "id": 1,
                        "name": "main",
                        "source": {"path": "/src/main.rs"},
                        "line": 10,
                    },
                    {
                        "id": 2,
                        "name": "run",
                        "source": {"path": "/src/lib.rs"},
                        "line": 42,
                    },
                ]
            }
        }
        result = DapClient._transform_stack(resp)
        assert len(result["frames"]) == 2
        assert result["frames"][0]["name"] == "main"
        assert result["frames"][0]["file"] == "/src/main.rs"
        assert result["frames"][0]["line"] == 10
        assert result["frames"][1]["id"] == 2

    def test_transform_stack_empty(self):
        result = DapClient._transform_stack({"body": {"stackFrames": []}})
        assert result["frames"] == []

    def test_transform_scopes(self):
        resp = {
            "body": {
                "scopes": [
                    {"name": "Locals", "variablesReference": 5},
                    {"name": "Globals", "variablesReference": 10},
                ]
            }
        }
        result = DapClient._transform_scopes(resp)
        assert len(result["scopes"]) == 2
        assert result["scopes"][0]["name"] == "Locals"
        assert result["scopes"][0]["ref"] == 5

    def test_transform_variables(self):
        resp = {
            "body": {
                "variables": [
                    {"name": "x", "value": "42", "type": "i32", "variablesReference": 0},
                    {"name": "v", "value": "Vec[3]", "type": "Vec<i32>", "variablesReference": 7},
                ]
            }
        }
        result = DapClient._transform_variables(resp)
        assert len(result["variables"]) == 2
        assert result["variables"][0]["name"] == "x"
        assert result["variables"][0]["value"] == "42"
        assert result["variables"][1]["ref"] == 7

    def test_transform_evaluate(self):
        resp = {"body": {"result": "hello world", "variablesReference": 0}}
        result = DapClient._transform_evaluate(resp)
        assert result["result"] == "hello world"

    def test_transform_evaluate_empty(self):
        result = DapClient._transform_evaluate({"body": {}})
        assert result["result"] == ""


class TestDapClientBreakpointBuffer:
    """Test breakpoint buffering before configurationDone."""

    def _make_client(self):
        on_event = MagicMock()
        info = DapAdapterInfo(command=["fake"], type="test")
        client = DapClient(on_event, info)
        return client

    def test_set_break_buffers(self):
        client = self._make_client()
        client.set_break("/src/main.rs", 10)
        client.set_break("/src/main.rs", 20, "x > 5")
        client.set_break("/src/lib.rs", 5)

        assert len(client._pending_breakpoints["/src/main.rs"]) == 2
        assert len(client._pending_breakpoints["/src/lib.rs"]) == 1

    def test_clear_file_breaks_removes_buffer(self):
        client = self._make_client()
        client.set_break("/src/main.rs", 10)
        client.clear_file_breaks("/src/main.rs")
        assert "/src/main.rs" not in client._pending_breakpoints

    def test_clear_nonexistent_file_is_safe(self):
        client = self._make_client()
        client.clear_file_breaks("/nonexistent.rs")


class TestDapClientMapFuture:
    """Test the Future mapping utility."""

    def test_map_future_transforms_result(self):
        source = Future()
        mapped = DapClient._map_future(source, lambda x: x * 2)
        source.set_result(5)
        assert mapped.result(timeout=1) == 10

    def test_map_future_propagates_exception(self):
        source = Future()
        mapped = DapClient._map_future(source, lambda x: x["missing"])
        source.set_result({})
        try:
            mapped.result(timeout=1)
            assert False, "Should have raised"
        except KeyError:
            pass


class TestDapClientMessageFormat:
    """Test DAP message encoding."""

    def _make_client(self):
        on_event = MagicMock()
        info = DapAdapterInfo(command=["fake"], type="test")
        client = DapClient(on_event, info)
        client._process = MagicMock()
        client._process.stdin = MagicMock()
        client._running = True
        return client

    def test_send_msg_format(self):
        client = self._make_client()
        written_data = bytearray()
        client._process.stdin.write = lambda data: written_data.extend(data)
        client._process.stdin.flush = MagicMock()

        client._send_msg("request", "continue", {"threadId": 1})

        raw = bytes(written_data)
        header, body = raw.split(b"\r\n\r\n", 1)
        assert header.startswith(b"Content-Length:")
        msg = json.loads(body)
        assert msg["type"] == "request"
        assert msg["command"] == "continue"
        assert msg["arguments"]["threadId"] == 1
        assert "seq" in msg

    def test_send_msg_increments_seq(self):
        client = self._make_client()
        client._process.stdin.write = MagicMock()
        client._process.stdin.flush = MagicMock()

        seq1 = client._send_msg("request", "next", {})
        seq2 = client._send_msg("request", "stepIn", {})
        assert seq2 == seq1 + 1


class TestDapClientDispatch:
    """Test message dispatch logic."""

    def _make_client(self):
        on_event = MagicMock()
        info = DapAdapterInfo(command=["fake"], type="test")
        client = DapClient(on_event, info)
        return client

    def test_handle_response_resolves_future(self):
        client = self._make_client()
        fut = Future()
        with client._lock:
            client._pending[42] = fut

        client._handle_response(
            {
                "type": "response",
                "request_seq": 42,
                "command": "continue",
                "success": True,
                "body": {},
            }
        )

        assert fut.done()
        assert fut.result()["success"] is True

    def test_handle_response_error(self):
        client = self._make_client()
        fut = Future()
        with client._lock:
            client._pending[7] = fut

        client._handle_response(
            {
                "type": "response",
                "request_seq": 7,
                "command": "evaluate",
                "success": False,
                "message": "variable not found",
            }
        )

        assert fut.done()
        try:
            fut.result()
            assert False, "Should have raised"
        except RuntimeError as e:
            assert "variable not found" in str(e)

    def test_handle_initialized_event(self):
        client = self._make_client()
        assert not client._initialized_event.is_set()

        client._handle_event(
            {
                "type": "event",
                "event": "initialized",
                "body": {},
            }
        )

        assert client._initialized_event.is_set()

    @patch("debugger.dap_client.main_thread_call")
    def test_handle_output_event(self, mock_main_thread):
        client = self._make_client()
        client._handle_event(
            {
                "type": "event",
                "event": "output",
                "body": {"category": "stdout", "output": "hello\n"},
            }
        )

        mock_main_thread.assert_called_once_with(client._on_event, "output", {"text": "hello\n", "category": "stdout"})

    @patch("debugger.dap_client.main_thread_call")
    def test_handle_terminated_event(self, mock_main_thread):
        client = self._make_client()
        client._running = True
        client._handle_event(
            {
                "type": "event",
                "event": "terminated",
                "body": {},
            }
        )

        assert not client._running
        mock_main_thread.assert_called_once_with(client._on_event, "terminated", {"exit_code": 0})

    @patch("debugger.dap_client.main_thread_call")
    def test_handle_exited_event(self, mock_main_thread):
        client = self._make_client()
        client._running = True
        client._handle_event(
            {
                "type": "event",
                "event": "exited",
                "body": {"exitCode": 1},
            }
        )

        mock_main_thread.assert_called_once_with(client._on_event, "terminated", {"exit_code": 1})


class TestReadHeaders:
    """Test Content-Length header parsing."""

    def test_parse_valid_header(self):
        import io

        stream = io.BytesIO(b"Content-Length: 42\r\n\r\n")
        assert DapClient._read_headers(stream) == 42

    def test_parse_with_extra_headers(self):
        import io

        stream = io.BytesIO(b"Content-Length: 100\r\nContent-Type: utf-8\r\n\r\n")
        assert DapClient._read_headers(stream) == 100

    def test_eof_returns_none(self):
        import io

        stream = io.BytesIO(b"")
        assert DapClient._read_headers(stream) is None
