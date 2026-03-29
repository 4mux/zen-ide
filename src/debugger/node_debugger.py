"""Node.js debugger client — JavaScript/TypeScript debugging via V8 Inspector.

Speaks Chrome DevTools Protocol (CDP) over WebSocket. Provides the same
interface as BdbClient/GdbClient so DebugSession can use it transparently.

Flow:
1. Launch node --inspect-brk=<port> <script> (or tsx for TypeScript)
2. Connect WebSocket to the V8 Inspector endpoint
3. Set breakpoints, step, inspect variables via CDP Debugger/Runtime domains
4. Parse CDP events into the IDE's event format
"""

import json
import os
import re
import shutil
import socket
import struct
import subprocess
import threading
import time
from concurrent.futures import Future
from http.client import HTTPConnection
from typing import Callable
from urllib.parse import urlparse

_JS_EXTS = {".js", ".mjs", ".cjs", ".jsx"}
_TS_EXTS = {".ts", ".mts", ".cts", ".tsx"}

# Node CJS wrapper injects these into every module scope — hide from user
_NODE_INTERNAL_VARS = {"exports", "require", "module", "__filename", "__dirname"}


class NodeClient:
    """Manages communication with Node.js via Chrome DevTools Protocol."""

    def __init__(self, on_event: Callable[[str, dict], None]):
        self._on_event = on_event
        self._process: subprocess.Popen | None = None
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stdout_thread: threading.Thread | None = None
        self._running = False
        self._seq = 0
        self._pending: dict[int, Future] = {}
        self._lock = threading.Lock()
        self._ws: socket.socket | None = None

        # CDP state
        self._scripts: dict[str, str] = {}  # scriptId -> file path
        self._call_frames: list[dict] = []  # from last Debugger.paused
        self._obj_refs: dict[int, str] = {}  # ref_id -> objectId
        self._obj_ref_counter = 0
        self._breakpoint_ids: list[str] = []  # CDP breakpoint IDs for clearing

        # The first pause is "Break on start" from --inspect-brk.
        # If stop_on_entry is False we auto-resume past it.
        self._first_pause = True
        self._stop_on_entry = False

    def start(
        self,
        script_path: str,
        python: str = "",  # unused, kept for interface compat
        cwd: str = "",
        env: dict[str, str] | None = None,
        args: list[str] | None = None,
    ) -> None:
        """Launch Node.js with --inspect-brk and connect via CDP."""
        port = _find_free_port()
        runtime, runtime_args = self._resolve_runtime(script_path)

        cmd = [runtime] + runtime_args + [f"--inspect-brk=127.0.0.1:{port}", script_path]
        if args:
            cmd.extend(args)

        proc_env = os.environ.copy()
        if env:
            proc_env.update(env)

        self._process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd or None,
            env=proc_env,
        )
        self._running = True

        # Read stderr to capture the "Debugger listening on ws://..." URL
        ws_url = self._wait_for_ws_url(port)
        if not ws_url:
            raise RuntimeError("Node.js debugger did not start — check that 'node' is installed")

        # Start stderr forwarding thread
        self._stderr_thread = threading.Thread(target=self._stderr_loop, daemon=True)
        self._stderr_thread.start()

        # Start stdout forwarding thread
        self._stdout_thread = threading.Thread(target=self._stdout_loop, daemon=True)
        self._stdout_thread.start()

        # Connect WebSocket
        self._ws = _ws_connect(ws_url)
        self._reader_thread = threading.Thread(target=self._ws_reader_loop, daemon=True)
        self._reader_thread.start()

        # Enable CDP domains (fire-and-forget — WebSocket ordering guarantees
        # these are processed before any breakpoint/resume commands we send later)
        self._send_cdp("Debugger.enable")
        self._send_cdp("Runtime.enable")

    def stop(self) -> None:
        """Terminate Node.js and close WebSocket."""
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except OSError:
                pass
            self._ws = None
        if self._process:
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

    # ── Fire-and-forget commands ──

    def set_break(self, file: str, line: int, condition: str = "") -> None:
        params: dict = {
            "url": _path_to_file_url(file),
            "lineNumber": line - 1,  # CDP is 0-based
        }
        if condition:
            params["condition"] = condition

        future = self._send_cdp_request("Debugger.setBreakpointByUrl", params)

        def _store_bp_id(f):
            try:
                resp = f.result(timeout=2)
                bp_id = resp.get("result", {}).get("breakpointId", "")
                if bp_id:
                    self._breakpoint_ids.append(bp_id)
            except Exception:
                pass

        future.add_done_callback(_store_bp_id)

    def clear_file_breaks(self, file: str) -> None:
        url = _path_to_file_url(file)
        # Remove all tracked breakpoints and re-set ones for other files
        ids_to_remove = list(self._breakpoint_ids)
        self._breakpoint_ids.clear()
        for bp_id in ids_to_remove:
            self._send_cdp("Debugger.removeBreakpoint", {"breakpointId": bp_id})

    def run(self, stop_on_entry: bool = False) -> None:
        self._stop_on_entry = stop_on_entry
        # Tell Node to start executing (it was waiting for this since --inspect-brk).
        # This triggers "Break on start" pause → _handle_paused decides what to do.
        self._send_cdp("Runtime.runIfWaitingForDebugger")

    def continue_(self) -> None:
        self._send_cdp("Debugger.resume")

    def step_over(self) -> None:
        self._send_cdp("Debugger.stepOver")

    def step_into(self) -> None:
        self._send_cdp("Debugger.stepInto")

    def step_out(self) -> None:
        self._send_cdp("Debugger.stepOut")

    def set_frame(self, frame_id: int) -> None:
        # CDP doesn't have a set_frame command; we track it locally
        pass

    # ── Request/response commands (return Future) ──

    def get_stack(self) -> Future:
        future: Future = Future()
        frames = []
        for i, cf in enumerate(self._call_frames):
            loc = cf.get("location", {})
            script_id = loc.get("scriptId", "")
            file_path = self._scripts.get(script_id, _file_url_to_path(cf.get("url", "")))
            frames.append({
                "id": i,
                "name": cf.get("functionName", "") or "<anonymous>",
                "file": file_path,
                "line": loc.get("lineNumber", 0) + 1,  # 1-based
            })
        future.set_result({"frames": frames})
        return future

    def get_scopes(self, frame_id: int = 0) -> Future:
        future: Future = Future()
        if frame_id >= len(self._call_frames):
            future.set_result({"scopes": []})
            return future

        cf = self._call_frames[frame_id]
        scopes = []
        for scope in cf.get("scopeChain", []):
            scope_type = scope.get("type", "")
            if scope_type == "global":
                continue
            obj = scope.get("object", {})
            object_id = obj.get("objectId", "")
            if object_id:
                ref = self._store_obj_ref(object_id)
                name = scope_type.capitalize()
                if name == "Local":
                    name = "Locals"
                scopes.append({"name": name, "ref": ref})
        future.set_result({"scopes": scopes})
        return future

    def get_variables(self, ref: int) -> Future:
        object_id = self._obj_refs.get(ref)
        if not object_id:
            future: Future = Future()
            future.set_result({"variables": []})
            return future

        cdp_future = self._send_cdp_request(
            "Runtime.getProperties",
            {"objectId": object_id, "ownProperties": True, "generatePreview": True},
        )

        result_future: Future = Future()

        def _on_props(f):
            try:
                resp = f.result(timeout=5)
                result = resp.get("result", {})
                props = result.get("result", [])
                variables = []
                for p in props:
                    if p.get("isOwn") is False:
                        continue
                    name = p.get("name", "")
                    if name in _NODE_INTERNAL_VARS:
                        continue
                    val_desc = p.get("value", {})
                    if not val_desc:
                        continue
                    value = val_desc.get("description", val_desc.get("value", ""))
                    if value is None:
                        value = "undefined"
                    vtype = val_desc.get("type", "")
                    subtype = val_desc.get("subtype", "")
                    display_type = subtype or vtype

                    var_ref = 0
                    child_oid = val_desc.get("objectId", "")
                    if child_oid:
                        var_ref = self._store_obj_ref(child_oid)

                    variables.append({
                        "name": name,
                        "value": str(value),
                        "type": display_type,
                        "ref": var_ref,
                    })
                result_future.set_result({"variables": variables})
            except Exception:
                result_future.set_result({"variables": []})

        cdp_future.add_done_callback(_on_props)
        return result_future

    def evaluate(self, expr: str, frame_id: int = 0) -> Future:
        if frame_id < len(self._call_frames):
            call_frame_id = self._call_frames[frame_id].get("callFrameId", "")
            cdp_future = self._send_cdp_request(
                "Debugger.evaluateOnCallFrame",
                {"callFrameId": call_frame_id, "expression": expr, "generatePreview": True},
            )
        else:
            cdp_future = self._send_cdp_request(
                "Runtime.evaluate",
                {"expression": expr, "generatePreview": True},
            )

        result_future: Future = Future()

        def _on_eval(f):
            try:
                resp = f.result(timeout=5)
                result = resp.get("result", {})
                if "exceptionDetails" in result:
                    exc = result["exceptionDetails"]
                    text = exc.get("text", "")
                    exc_obj = exc.get("exception", {})
                    desc = exc_obj.get("description", text)
                    result_future.set_result({"result": f"Error: {desc}"})
                else:
                    val = result.get("result", {})
                    desc = val.get("description", val.get("value", "undefined"))
                    result_future.set_result({"result": str(desc)})
            except Exception as e:
                result_future.set_result({"result": f"Error: {e}"})

        cdp_future.add_done_callback(_on_eval)
        return result_future

    # ── Internal ──

    def _resolve_runtime(self, script_path: str) -> tuple[str, list[str]]:
        """Determine which runtime to use (node, tsx, etc.)."""
        ext = os.path.splitext(script_path)[1].lower()
        is_ts = ext in _TS_EXTS

        if is_ts:
            tsx = shutil.which("tsx")
            if tsx:
                return tsx, []
            npx = shutil.which("npx")
            if npx:
                return npx, ["tsx"]

        node = shutil.which("node")
        if not node:
            raise RuntimeError("node not found in PATH")

        if is_ts:
            from shared.main_thread import main_thread_call

            main_thread_call(
                self._on_event,
                "output",
                {"text": "TypeScript: install 'tsx' globally (npm i -g tsx) for best experience.\n"
                         "Falling back to node (may not work for .ts files without a loader).\n",
                 "category": "console"},
            )

        return node, []

    def _wait_for_ws_url(self, port: int) -> str | None:
        """Read stderr until we get the WebSocket URL, with timeout."""
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and self._running:
            if self._process and self._process.poll() is not None:
                return None
            try:
                line = self._process.stderr.readline()
                if not line:
                    continue
                text = line.decode("utf-8", errors="replace").strip()
                m = re.search(r"ws://[\w.:]+/[\w-]+", text)
                if m:
                    return m.group(0)
            except (OSError, ValueError):
                break

        # Fallback: try the /json HTTP endpoint
        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=3)
            conn.request("GET", "/json")
            resp = conn.getresponse()
            data = json.loads(resp.read())
            conn.close()
            if data and isinstance(data, list):
                return data[0].get("webSocketDebuggerUrl", "")
        except Exception:
            pass
        return None

    def _stderr_loop(self) -> None:
        """Forward subprocess stderr as output events (filter inspector noise)."""
        while self._running and self._process:
            try:
                line = self._process.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace")
                stripped = text.strip()
                if not stripped:
                    continue
                # Skip Node inspector boilerplate
                if stripped.startswith(("Debugger listening on ws://",
                                       "Debugger attached",
                                       "For help, see: https://nodejs.org",
                                       "Waiting for the debugger")):
                    continue
                if text.strip():
                    from shared.main_thread import main_thread_call
                    main_thread_call(self._on_event, "output", {"text": text, "category": "stderr"})
            except (OSError, ValueError):
                break

    def _stdout_loop(self) -> None:
        """Forward subprocess stdout as output events."""
        while self._running and self._process:
            try:
                line = self._process.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace")
                if text:
                    from shared.main_thread import main_thread_call
                    main_thread_call(self._on_event, "output", {"text": text, "category": "stdout"})
            except (OSError, ValueError):
                break

    def _send_cdp(self, method: str, params: dict | None = None) -> None:
        """Send a CDP command (fire-and-forget)."""
        with self._lock:
            self._seq += 1
            msg_id = self._seq
        msg = {"id": msg_id, "method": method}
        if params:
            msg["params"] = params
        self._ws_send(json.dumps(msg))

    def _send_cdp_request(self, method: str, params: dict | None = None) -> Future:
        """Send a CDP command and return a Future for the response."""
        with self._lock:
            self._seq += 1
            msg_id = self._seq
        future: Future = Future()
        with self._lock:
            self._pending[msg_id] = future
        msg = {"id": msg_id, "method": method}
        if params:
            msg["params"] = params
        self._ws_send(json.dumps(msg))
        return future

    def _ws_send(self, data: str) -> None:
        """Send a text frame over the WebSocket."""
        if not self._ws:
            return
        try:
            _ws_send_text(self._ws, data)
        except (OSError, BrokenPipeError):
            self._running = False

    def _ws_reader_loop(self) -> None:
        """Read and dispatch CDP messages from the WebSocket."""
        while self._running and self._ws:
            try:
                data = _ws_recv(self._ws)
                if data is None:
                    break
                msg = json.loads(data)
                self._dispatch_cdp(msg)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            except (OSError, ValueError, ConnectionError):
                break

        self._running = False
        from shared.main_thread import main_thread_call
        main_thread_call(self._on_event, "terminated", {"exit_code": 0})

    def _dispatch_cdp(self, msg: dict) -> None:
        """Handle an incoming CDP message."""
        # Response to a request
        if "id" in msg and "method" not in msg:
            msg_id = msg["id"]
            with self._lock:
                future = self._pending.pop(msg_id, None)
            if future and not future.done():
                future.set_result(msg)
            return

        method = msg.get("method", "")
        params = msg.get("params", {})

        if method == "Debugger.scriptParsed":
            script_id = params.get("scriptId", "")
            url = params.get("url", "")
            if url and script_id:
                file_path = _file_url_to_path(url)
                if file_path:
                    self._scripts[script_id] = file_path

        elif method == "Debugger.paused":
            self._handle_paused(params)

        elif method == "Debugger.resumed":
            pass  # Session tracks running state

        elif method == "Runtime.consoleAPICalled":
            self._handle_console(params)

        elif method == "Runtime.exceptionThrown":
            details = params.get("exceptionDetails", {})
            exc = details.get("exception", {})
            text = exc.get("description", details.get("text", "Exception"))
            from shared.main_thread import main_thread_call
            main_thread_call(
                self._on_event, "output",
                {"text": f"\n{text}\n", "category": "stderr"},
            )

    def _handle_paused(self, params: dict) -> None:
        """Handle Debugger.paused event."""
        self._call_frames = params.get("callFrames", [])
        self._obj_refs.clear()
        self._obj_ref_counter = 0

        if not self._call_frames:
            return

        top = self._call_frames[0]
        loc = top.get("location", {})
        script_id = loc.get("scriptId", "")
        file_path = self._scripts.get(script_id, _file_url_to_path(top.get("url", "")))
        line = loc.get("lineNumber", 0) + 1  # 1-based

        # The first pause is "Break on start" from --inspect-brk.
        if self._first_pause:
            self._first_pause = False
            if not self._stop_on_entry:
                # Auto-resume past the initial break
                self._send_cdp("Debugger.resume")
                return
            # stop_on_entry=True: fall through to emit "stopped"

        reason = params.get("reason", "other")
        mapped_reason = {
            "Break": "breakpoint",
            "Break on start": "step",
            "debugCommand": "step",
            "other": "step",
            "exception": "exception",
            "promiseRejection": "exception",
        }.get(reason, "step")

        from shared.main_thread import main_thread_call
        main_thread_call(
            self._on_event, "stopped",
            {"file": file_path, "line": line, "reason": mapped_reason},
        )

    def _handle_console(self, params: dict) -> None:
        """Handle Runtime.consoleAPICalled event."""
        from shared.main_thread import main_thread_call

        call_type = params.get("type", "log")
        category = "stderr" if call_type in ("error", "warning") else "stdout"

        args = params.get("args", [])
        parts = []
        for arg in args:
            desc = arg.get("description", arg.get("value", ""))
            if desc is None:
                desc = "undefined"
            parts.append(str(desc))
        text = " ".join(parts) + "\n"

        main_thread_call(self._on_event, "output", {"text": text, "category": category})

    def _store_obj_ref(self, object_id: str) -> int:
        self._obj_ref_counter += 1
        ref = self._obj_ref_counter
        self._obj_refs[ref] = object_id
        return ref


# ── Minimal WebSocket client (RFC 6455, text frames only) ─────────────────


def _ws_connect(url: str) -> socket.socket:
    """Connect to a WebSocket endpoint. Returns raw socket."""
    import base64

    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path or "/"

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect((host, port))

    # WebSocket handshake
    key_b64 = base64.b64encode(os.urandom(16)).decode()

    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key_b64}\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"\r\n"
    )
    sock.sendall(request.encode())

    # Read response headers
    response = b""
    while b"\r\n\r\n" not in response:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("WebSocket handshake failed: connection closed")
        response += chunk

    if b"101" not in response.split(b"\r\n")[0]:
        raise ConnectionError(f"WebSocket handshake failed: {response.split(b'\r\n')[0].decode()}")

    sock.settimeout(None)  # blocking reads from here
    return sock


def _ws_send_text(sock: socket.socket, data: str) -> None:
    """Send a WebSocket text frame (client-masked per RFC 6455)."""
    payload = data.encode("utf-8")
    length = len(payload)
    mask_key = os.urandom(4)

    header = bytearray()
    header.append(0x81)  # FIN + text opcode

    if length < 126:
        header.append(0x80 | length)  # MASK bit set
    elif length < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack(">H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack(">Q", length))

    header.extend(mask_key)

    masked = bytearray(payload)
    for i in range(length):
        masked[i] ^= mask_key[i % 4]

    sock.sendall(bytes(header) + bytes(masked))


def _ws_recv(sock: socket.socket) -> str | None:
    """Receive a WebSocket text frame. Returns None on close."""

    def _recv_exact(n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("WebSocket closed")
            buf.extend(chunk)
        return bytes(buf)

    try:
        header = _recv_exact(2)
    except ConnectionError:
        return None

    opcode = header[0] & 0x0F
    masked = (header[1] & 0x80) != 0
    length = header[1] & 0x7F

    if opcode == 0x8:  # close frame
        return None

    if length == 126:
        length = struct.unpack(">H", _recv_exact(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", _recv_exact(8))[0]

    mask_key = _recv_exact(4) if masked else None
    payload = bytearray(_recv_exact(length))

    if mask_key:
        for i in range(length):
            payload[i] ^= mask_key[i % 4]

    if opcode == 0x9:  # ping → pong
        _ws_send_pong(sock, bytes(payload))
        return _ws_recv(sock)

    return payload.decode("utf-8", errors="replace")


def _ws_send_pong(sock: socket.socket, data: bytes) -> None:
    """Send a WebSocket pong frame."""
    mask_key = os.urandom(4)
    length = len(data)
    header = bytearray([0x8A, 0x80 | length])  # FIN + pong, masked
    header.extend(mask_key)
    masked = bytearray(data)
    for i in range(length):
        masked[i] ^= mask_key[i % 4]
    sock.sendall(bytes(header) + bytes(masked))


# ── Helpers ──────────────────────────────────────────────────────────────────


def _find_free_port() -> int:
    """Find a free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _path_to_file_url(path: str) -> str:
    """Convert an absolute file path to a file:// URL."""
    abs_path = os.path.abspath(path)
    return f"file://{abs_path}"


def _file_url_to_path(url: str) -> str:
    """Convert a file:// URL to a local path. Returns '' for non-file URLs."""
    if url.startswith("file://"):
        return url[7:]
    return ""
