"""Bdb-based Python debugger — zero-dependency debugging.

Two components:
- BdbBridge: bdb.Bdb subclass that runs in the debuggee subprocess
- BdbClient: manages the subprocess from the IDE process

Communication: JSON lines over stdin (commands) / stdout (events+responses).
User stdout/stderr is captured and forwarded as "output" events.
"""

import io
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import Future
from typing import Callable

# Path to this file — used by BdbClient to launch the subprocess
_BRIDGE_SCRIPT = os.path.abspath(__file__)


# ── IDE side ──────────────────────────────────────────────────────────────────


class BdbClient:
    """Manages communication with the bdb debugger subprocess."""

    def __init__(self, on_event: Callable[[str, dict], None]):
        self._on_event = on_event
        self._process: subprocess.Popen | None = None
        self._reader_thread: threading.Thread | None = None
        self._running = False
        self._seq = 0
        self._pending: dict[int, Future] = {}
        self._lock = threading.Lock()

    def start(
        self,
        script_path: str,
        python: str = "",
        cwd: str = "",
        env: dict[str, str] | None = None,
        args: list[str] | None = None,
    ) -> None:
        """Launch the debugger subprocess."""
        python = python or sys.executable
        cmd = [python, "-u", _BRIDGE_SCRIPT, script_path]
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
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def stop(self) -> None:
        """Terminate the subprocess."""
        self._running = False
        if self._process:
            self._send_cmd({"cmd": "quit"})
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
        cmd: dict = {"cmd": "set_break", "file": file, "line": line}
        if condition:
            cmd["condition"] = condition
        self._send_cmd(cmd)

    def clear_file_breaks(self, file: str) -> None:
        self._send_cmd({"cmd": "clear_file_breaks", "file": file})

    def run(self, stop_on_entry: bool = False) -> None:
        self._send_cmd({"cmd": "run", "stop_on_entry": stop_on_entry})

    def continue_(self) -> None:
        self._send_cmd({"cmd": "continue"})

    def step_over(self) -> None:
        self._send_cmd({"cmd": "step_over"})

    def step_into(self) -> None:
        self._send_cmd({"cmd": "step_into"})

    def step_out(self) -> None:
        self._send_cmd({"cmd": "step_out"})

    def set_frame(self, frame_id: int) -> None:
        self._send_cmd({"cmd": "set_frame", "frame_id": frame_id})

    # ── Request/response commands (return Future) ──

    def get_stack(self) -> Future:
        return self._send_request({"cmd": "get_stack"})

    def get_scopes(self, frame_id: int = 0) -> Future:
        return self._send_request({"cmd": "get_scopes", "frame_id": frame_id})

    def get_variables(self, ref: int) -> Future:
        return self._send_request({"cmd": "get_variables", "ref": ref})

    def evaluate(self, expr: str, frame_id: int = 0) -> Future:
        return self._send_request({"cmd": "evaluate", "expr": expr, "frame_id": frame_id})

    # ── Internal ──

    def _send_cmd(self, cmd: dict) -> None:
        if not self._process or not self._process.stdin:
            return
        try:
            data = json.dumps(cmd) + "\n"
            self._process.stdin.write(data.encode("utf-8"))
            self._process.stdin.flush()
        except (BrokenPipeError, OSError):
            self._running = False

    def _send_request(self, cmd: dict) -> Future:
        with self._lock:
            self._seq += 1
            req_id = self._seq
        cmd["id"] = req_id
        future: Future = Future()
        with self._lock:
            self._pending[req_id] = future
        self._send_cmd(cmd)
        return future

    def _reader_loop(self) -> None:
        """Read JSON lines from subprocess stdout."""
        while self._running and self._process:
            try:
                line = self._process.stdout.readline()
                if not line:
                    break
                line = line.decode("utf-8").strip()
                if not line:
                    continue
                msg = json.loads(line)
                self._dispatch(msg)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            except (OSError, ValueError):
                break

        self._running = False
        from shared.main_thread import main_thread_call

        main_thread_call(self._on_event, "terminated", {})

    def _dispatch(self, msg: dict) -> None:
        event = msg.get("event", "")

        if event == "response":
            # Response to a request — resolve the pending Future
            req_id = msg.get("id")
            with self._lock:
                future = self._pending.pop(req_id, None)
            if future and not future.done():
                future.set_result(msg)
        else:
            # Event — dispatch to main thread
            from shared.main_thread import main_thread_call

            main_thread_call(self._on_event, event, msg)


# ── Subprocess side ───────────────────────────────────────────────────────────

# Everything below runs in the debuggee subprocess only.
# No IDE imports (gi, themes, shared, etc.) — only stdlib.


class _OutputRedirector(io.TextIOBase):
    """Captures writes to stdout/stderr and sends as protocol events."""

    def __init__(self, category: str, send_fn):
        self._category = category
        self._send_fn = send_fn

    def write(self, text):
        if text:
            self._send_fn("output", {"text": text, "category": self._category})
        return len(text) if text else 0

    def flush(self):
        pass

    @property
    def encoding(self):
        return "utf-8"

    def isatty(self):
        return False


def _safe_repr(obj, limit=200):
    try:
        r = repr(obj)
        return (r[:limit] + "...") if len(r) > limit else r
    except Exception:
        return f"<{type(obj).__name__}>"


def _is_expandable(obj):
    if isinstance(obj, (str, bytes, int, float, bool, complex, type(None))):
        return False
    if isinstance(obj, (dict, list, tuple, set, frozenset)):
        return len(obj) > 0
    return hasattr(obj, "__dict__") and bool(vars(obj))


def _run_debuggee():
    """Entry point when this module is run as a script."""
    import bdb
    import traceback

    if len(sys.argv) < 2:
        sys.exit("Usage: python bdb_debugger.py <script> [args...]")

    script = os.path.abspath(sys.argv[1])
    sys.argv = sys.argv[1:]  # Adjust argv for the debuggee

    # Save real stdio before redirecting
    real_stdin = sys.stdin
    real_stdout = sys.stdout

    def send_event(event: str, body: dict | None = None):
        msg = json.dumps({"event": event, **(body or {})})
        real_stdout.write(msg + "\n")
        real_stdout.flush()

    # Redirect user's stdio
    sys.stdout = _OutputRedirector("stdout", send_event)
    sys.stderr = _OutputRedirector("stderr", send_event)
    sys.stdin = open(os.devnull, "r")

    # Create debugger
    dbg = _BdbBridge(real_stdin, send_event)

    # Read setup commands (breakpoints) until "run"
    stop_on_entry = False
    while True:
        line = real_stdin.readline()
        if not line:
            sys.exit(0)
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
        except json.JSONDecodeError:
            continue

        action = cmd.get("cmd", "")
        if action == "run":
            stop_on_entry = cmd.get("stop_on_entry", False)
            break
        elif action == "set_break":
            dbg.set_break(cmd["file"], cmd["line"], cond=cmd.get("condition") or None)
        elif action == "clear_file_breaks":
            dbg.clear_all_file_breaks(cmd["file"])

    dbg._stop_on_entry = stop_on_entry

    # Add script directory to path
    script_dir = os.path.dirname(script)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    # Run the script
    exit_code = 0
    try:
        with open(script) as f:
            code = compile(f.read(), script, "exec")

        globs = {
            "__name__": "__main__",
            "__file__": script,
            "__builtins__": __builtins__,
        }

        dbg.run(code, globs)

    except bdb.BdbQuit:
        pass
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else 1
    except Exception:
        send_event("output", {"text": traceback.format_exc(), "category": "stderr"})
        exit_code = 1

    send_event("terminated", {"exit_code": exit_code})


class _BdbBridge(object):
    """Bdb subclass that communicates with the IDE via JSON lines.

    Inherits from bdb.Bdb at runtime only (when running as subprocess).
    """

    def __init__(self, cmd_input, send_fn):
        import bdb

        # Dynamically inherit from bdb.Bdb
        self.__class__ = type("_BdbBridge", (_BdbBridge, bdb.Bdb), {})
        bdb.Bdb.__init__(self)

        self._cmd_input = cmd_input
        self._send_fn = send_fn
        self._var_refs: dict[int, object] = {}
        self._var_ref_counter = 0
        self._frames: list = []
        self._current_frame_index = 0
        self._initial_stop_done = False
        self._stop_on_entry = False
        self._hit_breakpoint = False

    # ── bdb overrides ──

    def dispatch_line(self, frame):
        import bdb

        self._hit_breakpoint = False
        if self.stop_here(frame) or self.break_here(frame):
            self.user_line(frame)
            if self.quitting:
                raise bdb.BdbQuit
        return self.trace_dispatch

    def break_here(self, frame):
        import bdb

        result = bdb.Bdb.break_here(self, frame)
        if result:
            self._hit_breakpoint = True
        return result

    def user_line(self, frame):
        if self._is_internal(frame):
            self.set_continue()
            return

        # First line: skip unless stop_on_entry or breakpoint
        if not self._initial_stop_done:
            self._initial_stop_done = True
            if not self._stop_on_entry and not self._hit_breakpoint:
                self.set_continue()
                return

        reason = "breakpoint" if self._hit_breakpoint else "step"
        self._stop_at(frame, reason)

    def user_exception(self, frame, exc_info):
        if self._is_internal(frame):
            return
        exc_type, exc_value, _ = exc_info
        self._send(
            "output",
            {
                "text": f"\n{exc_type.__name__}: {exc_value}\n",
                "category": "stderr",
            },
        )
        self._stop_at(frame, "exception")

    # ── Stop + command loop ──

    def _stop_at(self, frame, reason: str):
        """Notify IDE we stopped and enter the command loop."""
        self._frames = self._collect_frames(frame)
        self._current_frame_index = 0
        self._var_refs.clear()
        self._var_ref_counter = 0

        self._send(
            "stopped",
            {
                "file": frame.f_code.co_filename,
                "line": frame.f_lineno,
                "reason": reason,
            },
        )
        self._command_loop()

    def _command_loop(self):
        """Block and process commands until execution resumes."""
        while True:
            line = self._cmd_input.readline()
            if not line:
                self.set_quit()
                return

            line = line.strip()
            if not line:
                continue

            try:
                cmd = json.loads(line)
            except json.JSONDecodeError:
                continue

            action = cmd.get("cmd", "")
            req_id = cmd.get("id")

            # ── Resume commands ──
            if action == "continue":
                self.set_continue()
                return
            elif action == "step_over":
                self.set_next(self._frames[0])
                return
            elif action == "step_into":
                self.set_step()
                return
            elif action == "step_out":
                if len(self._frames) > 1:
                    self.set_return(self._frames[0])
                else:
                    self.set_continue()
                return
            elif action == "quit":
                self.set_quit()
                return

            # ── Non-resume commands (processed without resuming) ──
            elif action == "set_break":
                self.set_break(cmd["file"], cmd["line"], cond=cmd.get("condition") or None)
            elif action == "clear_file_breaks":
                self.clear_all_file_breaks(cmd["file"])
            elif action == "set_frame":
                fi = cmd.get("frame_id", 0)
                if 0 <= fi < len(self._frames):
                    self._current_frame_index = fi

            # ── Inspection requests (send response) ──
            elif action == "get_stack":
                self._send(
                    "response",
                    {
                        "id": req_id,
                        "frames": self._serialize_frames(),
                    },
                )
            elif action == "get_scopes":
                fi = cmd.get("frame_id", self._current_frame_index)
                self._send(
                    "response",
                    {
                        "id": req_id,
                        "scopes": self._get_scopes(fi),
                    },
                )
            elif action == "get_variables":
                ref = cmd.get("ref", 0)
                self._send(
                    "response",
                    {
                        "id": req_id,
                        "variables": self._get_variables(ref),
                    },
                )
            elif action == "evaluate":
                fi = cmd.get("frame_id", self._current_frame_index)
                result = self._evaluate(cmd.get("expr", ""), fi)
                self._send(
                    "response",
                    {
                        "id": req_id,
                        "result": result,
                    },
                )

    # ── Helpers ──

    def _send(self, event: str, body: dict | None = None):
        self._send_fn(event, body or {})

    def _is_internal(self, frame) -> bool:
        fn = frame.f_code.co_filename
        return fn == __file__ or "bdb.py" in fn or fn.startswith("<")

    def _collect_frames(self, frame) -> list:
        frames = []
        f = frame
        while f is not None:
            if not self._is_internal(f):
                frames.append(f)
            f = f.f_back
        return frames

    def _serialize_frames(self) -> list[dict]:
        return [
            {
                "id": i,
                "name": f.f_code.co_name,
                "file": os.path.abspath(f.f_code.co_filename),
                "line": f.f_lineno,
            }
            for i, f in enumerate(self._frames)
        ]

    def _get_scopes(self, frame_id: int) -> list[dict]:
        if frame_id >= len(self._frames):
            return []
        frame = self._frames[frame_id]

        # Locals
        local_ref = self._store_ref(dict(frame.f_locals))

        # Globals — filter builtins and dunders
        user_globals = {k: v for k, v in frame.f_globals.items() if not k.startswith("__")}
        global_ref = self._store_ref(user_globals)

        return [
            {"name": "Locals", "ref": local_ref},
            {"name": "Globals", "ref": global_ref},
        ]

    def _get_variables(self, ref: int) -> list[dict]:
        obj = self._var_refs.get(ref)
        if obj is None:
            return []

        items: list[tuple] = []
        if isinstance(obj, dict):
            items = list(obj.items())[:200]
        elif isinstance(obj, (list, tuple)):
            items = [(str(i), v) for i, v in enumerate(obj[:200])]
        elif isinstance(obj, (set, frozenset)):
            items = [(str(i), v) for i, v in enumerate(sorted(obj, key=repr)[:200])]
        elif hasattr(obj, "__dict__"):
            items = list(vars(obj).items())[:200]

        variables = []
        for name, value in items:
            var: dict = {
                "name": str(name),
                "value": _safe_repr(value),
                "type": type(value).__name__,
                "ref": 0,
            }
            if _is_expandable(value):
                var["ref"] = self._store_ref(value)
            variables.append(var)
        return variables

    def _store_ref(self, obj) -> int:
        self._var_ref_counter += 1
        self._var_refs[self._var_ref_counter] = obj
        return self._var_ref_counter

    def _evaluate(self, expr: str, frame_id: int) -> str:
        if frame_id >= len(self._frames):
            return "Error: invalid frame"
        frame = self._frames[frame_id]
        try:
            result = eval(expr, frame.f_globals, frame.f_locals)
            return repr(result)
        except SyntaxError:
            try:
                exec(expr, frame.f_globals, frame.f_locals)
                return ""
            except Exception as e:
                return f"Error: {e}"
        except Exception as e:
            return f"Error: {e}"


if __name__ == "__main__":
    _run_debuggee()
