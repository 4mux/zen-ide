"""DAP (Debug Adapter Protocol) client — generic adapter for any DAP server.

Speaks JSON-RPC with Content-Length framing over stdin/stdout of a
subprocess. Provides the same interface as BdbClient/GdbClient/NodeClient
so DebugSession can use it transparently.

Ref: https://microsoft.github.io/debug-adapter-protocol/specification
"""

import json
import os
import subprocess
import threading
from concurrent.futures import Future
from typing import Callable

from shared.main_thread import main_thread_call

from .dap_registry import DapAdapterInfo


class DapClient:
    """Manages communication with a DAP debug adapter subprocess."""

    def __init__(self, on_event: Callable[[str, dict], None], adapter_info: DapAdapterInfo):
        self._on_event = on_event
        self._adapter_info = adapter_info
        self._process: subprocess.Popen | None = None
        self._reader_thread: threading.Thread | None = None
        self._running = False
        self._seq = 0
        self._pending: dict[int, Future] = {}
        self._lock = threading.Lock()
        self._capabilities: dict = {}
        self._initialized_event = threading.Event()
        self._thread_id: int = 1  # default thread for single-thread targets

        # Buffer breakpoints per-file until configurationDone
        self._pending_breakpoints: dict[str, list[tuple[int, str]]] = {}  # file -> [(line, condition)]

    def start(
        self,
        script_path: str,
        python: str = "",
        cwd: str = "",
        env: dict[str, str] | None = None,
        args: list[str] | None = None,
    ) -> None:
        """Launch the DAP adapter subprocess and initialize."""
        proc_env = os.environ.copy()
        if env:
            proc_env.update(env)

        self._process = subprocess.Popen(
            self._adapter_info.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd or None,
            env=proc_env,
        )
        self._running = True
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

        # DAP initialize handshake
        init_resp = self._send_request_sync("initialize", {
            "clientID": "zen-ide",
            "clientName": "Zen IDE",
            "adapterID": self._adapter_info.type,
            "pathFormat": "path",
            "linesStartAt1": True,
            "columnsStartAt1": True,
            "supportsVariableType": True,
            "supportsRunInTerminalRequest": False,
        }, timeout=10)

        if init_resp:
            self._capabilities = init_resp

        # DAP launch request
        launch_args = {
            self._adapter_info.launch_args_key: script_path,
            "cwd": cwd,
            "stopOnEntry": False,  # controlled by run()
        }
        launch_args.update(self._adapter_info.extra_launch_args)
        if args:
            launch_args["args"] = args
        if env:
            launch_args["env"] = env

        self._send_request_sync("launch", launch_args, timeout=15)

        # Wait for the 'initialized' event from the adapter
        self._initialized_event.wait(timeout=10)

    def stop(self) -> None:
        """Disconnect and terminate the adapter."""
        self._running = False
        if self._process:
            try:
                self._send_msg("request", "disconnect", {"terminateDebuggee": True})
            except Exception:
                pass
            try:
                self._process.terminate()
                self._process.wait(timeout=3)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    self._process.kill()
                except OSError:
                    pass
            self._process = None
        with self._lock:
            for fut in self._pending.values():
                if not fut.done():
                    fut.cancel()
            self._pending.clear()

    @property
    def is_running(self) -> bool:
        return self._running and self._process is not None

    # -- Fire-and-forget commands --

    def set_break(self, file: str, line: int, condition: str = "") -> None:
        self._pending_breakpoints.setdefault(file, []).append((line, condition))

    def clear_file_breaks(self, file: str) -> None:
        self._pending_breakpoints.pop(file, None)
        if self.is_running:
            self._send_set_breakpoints(file, [])

    def run(self, stop_on_entry: bool = False) -> None:
        # Flush all buffered breakpoints to the adapter
        for file_path, bp_list in self._pending_breakpoints.items():
            self._send_set_breakpoints(file_path, bp_list)

        self._send_request_sync("configurationDone", {}, timeout=5)

    def continue_(self) -> None:
        self._send_msg("request", "continue", {"threadId": self._thread_id})

    def step_over(self) -> None:
        self._send_msg("request", "next", {"threadId": self._thread_id})

    def step_into(self) -> None:
        self._send_msg("request", "stepIn", {"threadId": self._thread_id})

    def step_out(self) -> None:
        self._send_msg("request", "stepOut", {"threadId": self._thread_id})

    def set_frame(self, frame_id: int) -> None:
        # DAP has no set-frame command; tracked locally
        self._current_frame_id = frame_id

    # -- Request/response commands (return Future) --

    def get_stack(self) -> Future:
        fut = self._send_request_async("stackTrace", {
            "threadId": self._thread_id,
            "startFrame": 0,
            "levels": 50,
        })
        return self._map_future(fut, self._transform_stack)

    def get_scopes(self, frame_id: int = 0) -> Future:
        fut = self._send_request_async("scopes", {"frameId": frame_id})
        return self._map_future(fut, self._transform_scopes)

    def get_variables(self, ref: int) -> Future:
        fut = self._send_request_async("variables", {"variablesReference": ref})
        return self._map_future(fut, self._transform_variables)

    def evaluate(self, expr: str, frame_id: int = 0) -> Future:
        fut = self._send_request_async("evaluate", {
            "expression": expr,
            "frameId": frame_id,
            "context": "repl",
        })
        return self._map_future(fut, self._transform_evaluate)

    # -- Response transformers (DAP -> internal format) --

    @staticmethod
    def _transform_stack(resp: dict) -> dict:
        frames = []
        for sf in resp.get("body", {}).get("stackFrames", []):
            source = sf.get("source", {})
            frames.append({
                "id": sf.get("id", 0),
                "name": sf.get("name", "<unknown>"),
                "file": source.get("path", ""),
                "line": sf.get("line", 0),
            })
        return {"frames": frames}

    @staticmethod
    def _transform_scopes(resp: dict) -> dict:
        scopes = []
        for s in resp.get("body", {}).get("scopes", []):
            scopes.append({
                "name": s.get("name", ""),
                "ref": s.get("variablesReference", 0),
            })
        return {"scopes": scopes}

    @staticmethod
    def _transform_variables(resp: dict) -> dict:
        variables = []
        for v in resp.get("body", {}).get("variables", []):
            variables.append({
                "name": v.get("name", ""),
                "value": v.get("value", ""),
                "type": v.get("type", ""),
                "ref": v.get("variablesReference", 0),
            })
        return {"variables": variables}

    @staticmethod
    def _transform_evaluate(resp: dict) -> dict:
        body = resp.get("body", {})
        return {"result": body.get("result", "")}

    # -- Breakpoint helper --

    def _send_set_breakpoints(self, file_path: str, bp_list: list[tuple[int, str]]) -> None:
        """Send setBreakpoints request for a single file."""
        breakpoints = []
        for line, condition in bp_list:
            bp: dict = {"line": line}
            if condition:
                bp["condition"] = condition
            breakpoints.append(bp)

        self._send_request_sync("setBreakpoints", {
            "source": {"path": file_path},
            "breakpoints": breakpoints,
        }, timeout=5)

    # -- DAP message I/O --

    def _send_msg(self, msg_type: str, command: str, arguments: dict | None = None) -> int:
        """Send a DAP message and return its sequence number."""
        with self._lock:
            self._seq += 1
            seq = self._seq

        msg: dict = {
            "seq": seq,
            "type": msg_type,
            "command": command,
        }
        if arguments is not None:
            msg["arguments"] = arguments

        data = json.dumps(msg)
        content = data.encode("utf-8")
        header = f"Content-Length: {len(content)}\r\n\r\n".encode("ascii")

        if self._process and self._process.stdin:
            try:
                self._process.stdin.write(header + content)
                self._process.stdin.flush()
            except (OSError, BrokenPipeError):
                pass

        return seq

    def _send_request_async(self, command: str, arguments: dict | None = None) -> Future:
        """Send a request and return a Future for the response."""
        fut: Future = Future()
        seq = self._send_msg("request", command, arguments)
        with self._lock:
            self._pending[seq] = fut
        return fut

    def _send_request_sync(self, command: str, arguments: dict | None = None, timeout: float = 5) -> dict | None:
        """Send a request and block for the response."""
        fut = self._send_request_async(command, arguments)
        try:
            return fut.result(timeout=timeout)
        except Exception:
            return None

    def _reader_loop(self) -> None:
        """Read DAP messages from adapter stdout (Content-Length framing)."""
        stdout = self._process.stdout
        try:
            while self._running and self._process:
                # Read headers
                content_length = self._read_headers(stdout)
                if content_length is None:
                    break

                # Read body
                body = stdout.read(content_length)
                if len(body) < content_length:
                    break

                try:
                    msg = json.loads(body.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

                self._dispatch(msg)
        except (OSError, ValueError):
            pass
        finally:
            if self._running:
                self._running = False
                main_thread_call(self._on_event, "terminated", {"exit_code": -1})

    @staticmethod
    def _read_headers(stream) -> int | None:
        """Read Content-Length from DAP headers. Returns length or None on EOF."""
        content_length = None
        while True:
            line = stream.readline()
            if not line:
                return None
            line = line.decode("ascii", errors="replace").strip()
            if not line:
                break  # empty line separates headers from body
            if line.lower().startswith("content-length:"):
                try:
                    content_length = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
        return content_length

    def _dispatch(self, msg: dict) -> None:
        """Route an incoming DAP message."""
        msg_type = msg.get("type", "")

        if msg_type == "response":
            self._handle_response(msg)
        elif msg_type == "event":
            self._handle_event(msg)
        elif msg_type == "request":
            # Reverse request from adapter (e.g. runInTerminal)
            self._handle_reverse_request(msg)

    def _handle_response(self, msg: dict) -> None:
        """Resolve a pending Future with the response."""
        req_seq = msg.get("request_seq", 0)
        with self._lock:
            fut = self._pending.pop(req_seq, None)
        if fut and not fut.done():
            if msg.get("success", True):
                fut.set_result(msg)
            else:
                error_msg = msg.get("message", "unknown error")
                fut.set_exception(RuntimeError(f"DAP error: {error_msg}"))

    def _handle_event(self, msg: dict) -> None:
        """Handle a DAP event."""
        event = msg.get("event", "")
        body = msg.get("body", {})

        if event == "initialized":
            self._initialized_event.set()

        elif event == "stopped":
            self._thread_id = body.get("threadId", self._thread_id)
            reason = body.get("reason", "step")
            # Fetch top frame to get file/line (DAP stopped events don't include it)
            self._fetch_stop_location(reason)

        elif event == "output":
            category = body.get("category", "stdout")
            text = body.get("output", "")
            if text and category in ("stdout", "stderr", "console"):
                main_thread_call(self._on_event, "output", {"text": text, "category": category})

        elif event in ("terminated", "exited"):
            exit_code = body.get("exitCode", 0)
            self._running = False
            main_thread_call(self._on_event, "terminated", {"exit_code": exit_code})

    def _fetch_stop_location(self, reason: str) -> None:
        """Fetch stack trace to get stopped file/line, then emit stopped event."""
        try:
            resp = self._send_request_sync("stackTrace", {
                "threadId": self._thread_id,
                "startFrame": 0,
                "levels": 1,
            }, timeout=5)

            file_path = ""
            line = 0
            if resp:
                frames = resp.get("body", {}).get("stackFrames", [])
                if frames:
                    top = frames[0]
                    source = top.get("source", {})
                    file_path = source.get("path", "")
                    line = top.get("line", 0)

            main_thread_call(self._on_event, "stopped", {
                "file": file_path,
                "line": line,
                "reason": reason,
            })
        except Exception:
            main_thread_call(self._on_event, "stopped", {
                "file": "",
                "line": 0,
                "reason": reason,
            })

    def _handle_reverse_request(self, msg: dict) -> None:
        """Respond to reverse requests from the adapter with an error."""
        seq = msg.get("seq", 0)
        command = msg.get("command", "")
        # Reject unsupported reverse requests
        error_resp: dict = {
            "seq": 0,
            "type": "response",
            "request_seq": seq,
            "command": command,
            "success": False,
            "message": f"Reverse request '{command}' not supported",
        }
        data = json.dumps(error_resp).encode("utf-8")
        header = f"Content-Length: {len(data)}\r\n\r\n".encode("ascii")
        if self._process and self._process.stdin:
            try:
                self._process.stdin.write(header + data)
                self._process.stdin.flush()
            except (OSError, BrokenPipeError):
                pass

    # -- Utility --

    @staticmethod
    def _map_future(source: Future, transform) -> Future:
        """Create a new Future that applies a transform to the source result."""
        result_fut: Future = Future()

        def _on_done(f):
            try:
                result_fut.set_result(transform(f.result()))
            except Exception as e:
                result_fut.set_exception(e)

        source.add_done_callback(_on_done)
        return result_fut
