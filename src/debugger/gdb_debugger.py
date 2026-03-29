"""GDB Machine Interface client — C/C++ debugging via GDB.

Speaks GDB/MI protocol over stdin/stdout. Provides the same interface
as BdbClient so DebugSession can use either adapter transparently.

Flow:
1. Compile source with -g (debug symbols)
2. Launch gdb --interpreter=mi on the binary
3. Set breakpoints, run, step, inspect variables via MI commands
4. Parse MI output records into events/responses for the IDE
"""

import json
import os
import re
import shutil
import subprocess
import threading
from concurrent.futures import Future
from typing import Callable


class GdbClient:
    """Manages communication with GDB via Machine Interface protocol."""

    def __init__(self, on_event: Callable[[str, dict], None]):
        self._on_event = on_event
        self._process: subprocess.Popen | None = None
        self._reader_thread: threading.Thread | None = None
        self._running = False
        self._seq = 0
        self._pending: dict[int, Future] = {}
        self._lock = threading.Lock()
        self._program_path = ""
        # Variable reference tracking (mirrors BdbClient's approach)
        self._var_refs: dict[int, str] = {}  # ref_id -> gdb varobj name
        self._var_ref_counter = 0

    def start(
        self,
        script_path: str,
        python: str = "",  # unused, kept for interface compat
        cwd: str = "",
        env: dict[str, str] | None = None,
        args: list[str] | None = None,
    ) -> None:
        """Compile (if source) and launch GDB on the binary."""
        self._program_path = script_path
        self._program_args = args or []

        # Determine if we need to compile
        binary = self._resolve_binary(script_path, cwd)
        if binary is None:
            raise RuntimeError(f"Failed to compile or locate binary for {script_path}")

        gdb_path = shutil.which("gdb")
        if not gdb_path:
            raise RuntimeError("gdb not found in PATH")

        cmd = [gdb_path, "--interpreter=mi", "--quiet", binary]

        proc_env = os.environ.copy()
        if env:
            proc_env.update(env)
        # Prevent GDB from asking confirmations
        proc_env["GDB_BATCH_MODE"] = "1"

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

        # Wait for GDB startup prompt
        self._send_mi("-gdb-set confirm off")
        self._send_mi("-gdb-set pagination off")
        self._send_mi("-gdb-set print pretty on")

    def stop(self) -> None:
        """Terminate GDB."""
        self._running = False
        if self._process:
            self._send_mi("-gdb-exit")
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
        bp_cmd = f"-break-insert {file}:{line}"
        self._send_mi(bp_cmd)
        if condition:
            # We'll apply condition after break is set; GDB assigns a number
            # For simplicity, use the CLI command form
            self._send_mi(f"-break-condition {file}:{line} {condition}")

    def clear_file_breaks(self, file: str) -> None:
        # Delete all breakpoints in this file via CLI
        self._send_mi(f"-interpreter-exec console \"clear {file}:1\"", ignore_error=True)
        # More reliable: list then delete
        self._send_mi_request("-break-list", self._make_clear_callback(file))

    def run(self, stop_on_entry: bool = False) -> None:
        if self._program_args:
            args_str = " ".join(self._program_args)
            self._send_mi(f"-exec-arguments {args_str}")
        if stop_on_entry:
            self._send_mi("-exec-run --start")
        else:
            self._send_mi("-exec-run")

    def continue_(self) -> None:
        self._send_mi("-exec-continue")

    def step_over(self) -> None:
        self._send_mi("-exec-next")

    def step_into(self) -> None:
        self._send_mi("-exec-step")

    def step_out(self) -> None:
        self._send_mi("-exec-finish")

    def set_frame(self, frame_id: int) -> None:
        self._send_mi(f"-stack-select-frame {frame_id}")

    # ── Request/response commands (return Future) ──

    def get_stack(self) -> Future:
        future: Future = Future()
        with self._lock:
            self._seq += 1
            token = self._seq
            self._pending[token] = future
        self._send_mi(f"{token}-stack-list-frames")
        return future

    def get_scopes(self, frame_id: int = 0) -> Future:
        """GDB doesn't have 'scopes' per se — we synthesize Locals."""
        future: Future = Future()
        # Select frame first, then list locals
        self._send_mi(f"-stack-select-frame {frame_id}")
        with self._lock:
            self._seq += 1
            token = self._seq
            self._pending[token] = future
        self._send_mi(f"{token}-stack-list-variables --simple-values")
        return future

    def get_variables(self, ref: int) -> Future:
        """Expand a variable reference (children of a struct/array)."""
        future: Future = Future()
        varobj_name = self._var_refs.get(ref, "")
        if not varobj_name:
            future.set_result({"variables": []})
            return future
        with self._lock:
            self._seq += 1
            token = self._seq
            self._pending[token] = future
        self._send_mi(f"{token}-var-list-children --all-values {varobj_name}")
        return future

    def evaluate(self, expr: str, frame_id: int = 0) -> Future:
        future: Future = Future()
        self._send_mi(f"-stack-select-frame {frame_id}")
        with self._lock:
            self._seq += 1
            token = self._seq
            self._pending[token] = future
        self._send_mi(f"{token}-data-evaluate-expression {expr}")
        return future

    # ── Internal ──

    def _resolve_binary(self, source_path: str, cwd: str) -> str | None:
        """Compile source to binary with debug symbols, or return path if already a binary."""
        ext = os.path.splitext(source_path)[1].lower()

        if ext not in (".c", ".cpp", ".cc", ".cxx", ".c++"):
            # Assume it's already a binary
            if os.path.isfile(source_path) and os.access(source_path, os.X_OK):
                return source_path
            return None

        # Check for Makefile in the source directory or cwd
        source_dir = os.path.dirname(source_path)
        makefile_dir = self._find_makefile_dir(source_path, cwd)

        if makefile_dir:
            return self._compile_with_make(makefile_dir, source_path)

        # No Makefile — compile single file directly
        return self._compile_single(source_path, cwd)

    def _find_makefile_dir(self, source_path: str, cwd: str) -> str | None:
        """Walk up from source file looking for a Makefile."""
        d = os.path.dirname(os.path.abspath(source_path))
        stop = os.path.dirname(cwd) if cwd else "/"
        while d and d != stop and len(d) > 1:
            if os.path.isfile(os.path.join(d, "Makefile")):
                return d
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
        return None

    def _compile_with_make(self, makefile_dir: str, source_path: str) -> str | None:
        """Run make with debug flags and return the binary path."""
        from shared.main_thread import main_thread_call

        main_thread_call(
            self._on_event,
            "output",
            {"text": f"Compiling with make (debug flags)...\n", "category": "console"},
        )

        # Determine if C or C++
        ext = os.path.splitext(source_path)[1].lower()
        if ext in (".cpp", ".cc", ".cxx", ".c++"):
            extra_flags = "CXXFLAGS=-std=c++17 -Wall -Wextra -g -O0"
        else:
            extra_flags = "CFLAGS=-std=c11 -Wall -Wextra -g -O0"

        try:
            result = subprocess.run(
                ["make", "clean"],
                cwd=makefile_dir,
                capture_output=True,
                timeout=30,
            )
            result = subprocess.run(
                ["make", extra_flags],
                cwd=makefile_dir,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                main_thread_call(
                    self._on_event,
                    "output",
                    {"text": f"Compile error:\n{result.stderr}\n", "category": "stderr"},
                )
                return None

            if result.stdout:
                main_thread_call(
                    self._on_event,
                    "output",
                    {"text": result.stdout, "category": "stdout"},
                )

            # Find the binary — look for TARGET in Makefile or common names
            binary = self._find_binary_from_makefile(makefile_dir)
            if binary:
                return binary

        except (subprocess.TimeoutExpired, OSError) as e:
            main_thread_call(
                self._on_event,
                "output",
                {"text": f"Make failed: {e}\n", "category": "stderr"},
            )
        return None

    def _find_binary_from_makefile(self, makefile_dir: str) -> str | None:
        """Try to determine the binary produced by make."""
        # Parse Makefile for TARGET variable
        makefile = os.path.join(makefile_dir, "Makefile")
        try:
            with open(makefile) as f:
                for line in f:
                    m = re.match(r"^TARGET\s*[:?]?=\s*(\S+)", line)
                    if m:
                        target = m.group(1)
                        binary = os.path.join(makefile_dir, target)
                        if os.path.isfile(binary):
                            return binary
        except OSError:
            pass

        # Fallback: look for common names
        for name in ("a.out", "main", "demo", "app"):
            path = os.path.join(makefile_dir, name)
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path

        return None

    def _compile_single(self, source_path: str, cwd: str) -> str | None:
        """Compile a single C/C++ source file with debug symbols."""
        from shared.main_thread import main_thread_call

        ext = os.path.splitext(source_path)[1].lower()
        compiler = "g++" if ext in (".cpp", ".cc", ".cxx", ".c++") else "gcc"

        if not shutil.which(compiler):
            main_thread_call(
                self._on_event,
                "output",
                {"text": f"{compiler} not found in PATH\n", "category": "stderr"},
            )
            return None

        output_dir = cwd or os.path.dirname(source_path)
        basename = os.path.splitext(os.path.basename(source_path))[0]
        binary = os.path.join(output_dir, basename)

        main_thread_call(
            self._on_event,
            "output",
            {"text": f"Compiling {os.path.basename(source_path)} with debug symbols...\n", "category": "console"},
        )

        try:
            result = subprocess.run(
                [compiler, "-g", "-O0", source_path, "-o", binary, "-lm"],
                capture_output=True,
                text=True,
                cwd=cwd or None,
                timeout=30,
            )
            if result.returncode != 0:
                main_thread_call(
                    self._on_event,
                    "output",
                    {"text": f"Compile error:\n{result.stderr}\n", "category": "stderr"},
                )
                return None
            return binary
        except (subprocess.TimeoutExpired, OSError) as e:
            main_thread_call(
                self._on_event,
                "output",
                {"text": f"Compilation failed: {e}\n", "category": "stderr"},
            )
            return None

    def _send_mi(self, command: str, ignore_error: bool = False) -> None:
        """Send a MI command to GDB."""
        if not self._process or not self._process.stdin:
            return
        try:
            data = command + "\n"
            self._process.stdin.write(data.encode("utf-8"))
            self._process.stdin.flush()
        except (BrokenPipeError, OSError):
            self._running = False

    def _send_mi_request(self, command: str, callback) -> None:
        """Send a MI command with a token and invoke callback on response."""
        with self._lock:
            self._seq += 1
            token = self._seq
        future: Future = Future()
        future.add_done_callback(callback)
        with self._lock:
            self._pending[token] = future
        self._send_mi(f"{token}{command}")

    def _make_clear_callback(self, file: str):
        """Create callback to clear breakpoints for a file after -break-list."""
        def _callback(future):
            try:
                result = future.result(timeout=2)
                table = result.get("BreakpointTable", {})
                for bp in table.get("body", []):
                    bp_file = bp.get("fullname", bp.get("file", ""))
                    if bp_file and os.path.abspath(bp_file) == os.path.abspath(file):
                        bp_num = bp.get("number", "")
                        if bp_num:
                            self._send_mi(f"-break-delete {bp_num}")
            except Exception:
                pass
        return _callback

    def _reader_loop(self) -> None:
        """Read and parse GDB/MI output."""
        while self._running and self._process:
            try:
                raw = self._process.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                self._parse_mi_line(line)
            except (OSError, ValueError):
                break

        self._running = False
        from shared.main_thread import main_thread_call

        main_thread_call(self._on_event, "terminated", {"exit_code": 0})

    def _parse_mi_line(self, line: str) -> None:
        """Parse a single GDB/MI output record."""
        from shared.main_thread import main_thread_call

        if not line or line == "(gdb)":
            return

        # Result record: token ^status,key=value,...
        m = re.match(r"^(\d+)\^(\w+)(,(.*))?$", line)
        if m:
            token = int(m.group(1))
            status = m.group(2)
            payload_str = m.group(4) or ""
            payload = _parse_mi_dict(payload_str) if payload_str else {}
            self._handle_result(token, status, payload)
            return

        # Unsolicited result: ^status,...
        m = re.match(r"^\^(\w+)(,(.*))?$", line)
        if m:
            return  # Ignore unsolicited results without tokens

        # Async exec record: *stopped,...  or *running,...
        m = re.match(r"^\*(\w+)(,(.*))?$", line)
        if m:
            reason = m.group(1)
            payload_str = m.group(3) or ""
            payload = _parse_mi_dict(payload_str) if payload_str else {}
            self._handle_async_exec(reason, payload)
            return

        # Async notify record: =thread-group-added,...
        if line.startswith("="):
            return  # Ignore notify records

        # Console stream: ~"text"
        m = re.match(r'^~"(.*)"$', line)
        if m:
            text = _mi_unescape(m.group(1))
            main_thread_call(
                self._on_event, "output", {"text": text, "category": "stdout"}
            )
            return

        # Target stream: @"text"
        m = re.match(r'^@"(.*)"$', line)
        if m:
            text = _mi_unescape(m.group(1))
            main_thread_call(
                self._on_event, "output", {"text": text, "category": "stdout"}
            )
            return

        # Log stream: &"text"
        if line.startswith("&"):
            return  # Ignore GDB log messages

    def _handle_result(self, token: int, status: str, payload: dict) -> None:
        """Handle a result record (response to a token-prefixed command)."""
        with self._lock:
            future = self._pending.pop(token, None)

        if not future or future.done():
            return

        if status == "done":
            # Transform the result depending on what was requested
            result = self._transform_result(payload)
            future.set_result(result)
        elif status == "error":
            msg = payload.get("msg", "Unknown GDB error")
            future.set_result({"error": msg})
        else:
            future.set_result(payload)

    def _transform_result(self, payload: dict) -> dict:
        """Transform GDB/MI result into the format DebugSession expects."""
        # Stack frames
        if "stack" in payload:
            frames = []
            stack_data = payload["stack"]
            if isinstance(stack_data, list):
                for i, frame_entry in enumerate(stack_data):
                    f = frame_entry.get("frame", frame_entry) if isinstance(frame_entry, dict) else {}
                    frames.append({
                        "id": int(f.get("level", i)),
                        "name": f.get("func", "<unknown>"),
                        "file": f.get("fullname", f.get("file", "")),
                        "line": int(f.get("line", 0)),
                    })
            return {"frames": frames}

        # Variables list (from -stack-list-variables)
        if "variables" in payload:
            local_ref = self._store_vars_as_scope(payload["variables"])
            return {
                "scopes": [
                    {"name": "Locals", "ref": local_ref},
                ],
            }

        # Variable children (from -var-list-children)
        if "children" in payload:
            variables = []
            children = payload["children"]
            if isinstance(children, list):
                for child_entry in children:
                    child = child_entry.get("child", child_entry) if isinstance(child_entry, dict) else {}
                    name = child.get("exp", child.get("name", ""))
                    value = child.get("value", "")
                    vtype = child.get("type", "")
                    numchild = int(child.get("numchild", 0))
                    ref = 0
                    if numchild > 0:
                        varobj_name = child.get("name", "")
                        ref = self._store_varobj(varobj_name)
                    variables.append({
                        "name": name,
                        "value": value,
                        "type": vtype,
                        "ref": ref,
                    })
            return {"variables": variables}

        # Expression evaluation
        if "value" in payload:
            return {"result": payload["value"]}

        # Breakpoint table (for clear operations)
        if "BreakpointTable" in payload:
            return payload

        return payload

    def _handle_async_exec(self, reason: str, payload: dict) -> None:
        """Handle async execution records (*stopped, *running)."""
        from shared.main_thread import main_thread_call

        if reason == "stopped":
            stop_reason = payload.get("reason", "unknown")

            # Map GDB stop reasons to our reasons
            if stop_reason in ("breakpoint-hit",):
                mapped_reason = "breakpoint"
            elif stop_reason in ("end-stepping-range", "function-finished"):
                mapped_reason = "step"
            elif stop_reason in ("signal-received",):
                sig = payload.get("signal-name", "")
                if sig in ("SIGSEGV", "SIGABRT", "SIGFPE", "SIGBUS"):
                    mapped_reason = "exception"
                    sig_meaning = payload.get("signal-meaning", sig)
                    main_thread_call(
                        self._on_event,
                        "output",
                        {"text": f"\nSignal: {sig} ({sig_meaning})\n", "category": "stderr"},
                    )
                else:
                    mapped_reason = "pause"
            elif stop_reason == "exited-normally":
                main_thread_call(self._on_event, "terminated", {"exit_code": 0})
                return
            elif stop_reason in ("exited", "exited-signalled"):
                code = int(payload.get("exit-code", 1))
                main_thread_call(self._on_event, "terminated", {"exit_code": code})
                return
            else:
                mapped_reason = "step"

            # Extract file/line from the frame info
            frame = payload.get("frame", {})
            file_path = frame.get("fullname", frame.get("file", ""))
            line = int(frame.get("line", 0))

            # Clear old variable objects for the new stop
            self._var_refs.clear()
            self._var_ref_counter = 0

            main_thread_call(
                self._on_event,
                "stopped",
                {
                    "file": file_path,
                    "line": line,
                    "reason": mapped_reason,
                },
            )
        elif reason == "running":
            pass  # Session already tracks this

    def _store_vars_as_scope(self, variables: list) -> int:
        """Create variable objects for a list of locals and return a scope ref."""
        self._var_ref_counter += 1
        scope_ref = self._var_ref_counter
        # Store the raw variable list — we'll serve it directly in get_variables
        self._var_refs[scope_ref] = f"__scope_{scope_ref}"

        # Create GDB variable objects for each variable so we can expand them
        var_list = []
        for v in variables:
            if isinstance(v, dict):
                var_list.append(v)

        # Store as a special mapping
        if not hasattr(self, "_scope_vars"):
            self._scope_vars: dict[int, list[dict]] = {}
        self._scope_vars[scope_ref] = var_list

        return scope_ref

    def _store_varobj(self, varobj_name: str) -> int:
        """Store a GDB variable object name and return a reference ID."""
        self._var_ref_counter += 1
        ref = self._var_ref_counter
        self._var_refs[ref] = varobj_name
        return ref

    def _get_scope_variables(self, ref: int) -> list[dict]:
        """Get variables for a scope reference (used by overridden get_variables)."""
        scope_vars = getattr(self, "_scope_vars", {})
        raw_vars = scope_vars.get(ref, [])
        variables = []
        for v in raw_vars:
            name = v.get("name", "")
            value = v.get("value", "")
            vtype = v.get("type", "")

            # Create a GDB varobj for expandable types
            ref_id = 0
            if vtype and not vtype.startswith(("int", "char", "float", "double",
                                                "bool", "long", "short", "unsigned",
                                                "_Bool", "size_t", "ssize_t")):
                # Might be expandable — create varobj
                try:
                    self._send_mi_create_varobj(name, ref_id)
                except Exception:
                    pass

            variables.append({
                "name": name,
                "value": value,
                "type": vtype,
                "ref": ref_id,
            })
        return variables

    def _send_mi_create_varobj(self, expr: str, parent_ref: int) -> None:
        """Create a GDB variable object for inspection."""
        self._send_mi(f"-var-create - * {expr}")


# ── GDB/MI output parsing ──────────────────────────────────────────────────


def _mi_unescape(s: str) -> str:
    """Unescape a GDB/MI C-style string."""
    # Process backslash first to avoid double-unescaping
    result = []
    i = 0
    n = len(s)
    while i < n:
        if s[i] == "\\" and i + 1 < n:
            c = s[i + 1]
            if c == "n":
                result.append("\n")
            elif c == "t":
                result.append("\t")
            elif c == '"':
                result.append('"')
            elif c == "\\":
                result.append("\\")
            else:
                result.append(c)
            i += 2
        else:
            result.append(s[i])
            i += 1
    return "".join(result)


def _parse_mi_dict(s: str) -> dict:
    """Parse a GDB/MI key=value,... string into a Python dict.

    Handles nested tuples {}, lists [], and quoted strings.
    """
    result = {}
    i = 0
    n = len(s)

    while i < n:
        # Skip whitespace and commas
        while i < n and s[i] in " ,":
            i += 1
        if i >= n:
            break

        # Parse key
        key_start = i
        while i < n and s[i] not in "=,{}[]":
            i += 1
        key = s[key_start:i].strip()
        if not key:
            i += 1
            continue

        if i >= n or s[i] != "=":
            i += 1
            continue
        i += 1  # skip '='

        if i >= n:
            break

        # Parse value
        if s[i] == '"':
            # Quoted string
            val, i = _parse_mi_string(s, i)
            result[key] = val
        elif s[i] == '{':
            # Tuple/dict
            val, i = _parse_mi_tuple(s, i)
            result[key] = val
        elif s[i] == '[':
            # List
            val, i = _parse_mi_list(s, i)
            result[key] = val
        else:
            # Unquoted value (until comma or end)
            val_start = i
            while i < n and s[i] not in ",{}[]":
                i += 1
            result[key] = s[val_start:i].strip()

    return result


def _parse_mi_string(s: str, pos: int) -> tuple[str, int]:
    """Parse a quoted string starting at pos, return (value, new_pos)."""
    assert s[pos] == '"'
    i = pos + 1
    n = len(s)
    chars = []
    while i < n:
        if s[i] == "\\" and i + 1 < n:
            next_ch = s[i + 1]
            if next_ch == "n":
                chars.append("\n")
            elif next_ch == "t":
                chars.append("\t")
            elif next_ch == '"':
                chars.append('"')
            elif next_ch == "\\":
                chars.append("\\")
            else:
                chars.append(next_ch)
            i += 2
        elif s[i] == '"':
            i += 1
            break
        else:
            chars.append(s[i])
            i += 1
    return "".join(chars), i


def _parse_mi_tuple(s: str, pos: int) -> tuple[dict, int]:
    """Parse a tuple {...} starting at pos."""
    assert s[pos] == "{"
    i = pos + 1
    n = len(s)
    content_chars = []
    depth = 1
    while i < n and depth > 0:
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                i += 1
                break
        if depth > 0:
            content_chars.append(s[i])
        i += 1
    content = "".join(content_chars)
    return _parse_mi_dict(content), i


def _parse_mi_list(s: str, pos: int) -> tuple[list, int]:
    """Parse a list [...] starting at pos."""
    assert s[pos] == "["
    i = pos + 1
    n = len(s)
    items = []

    while i < n:
        # Skip whitespace and commas
        while i < n and s[i] in " ,":
            i += 1
        if i >= n or s[i] == "]":
            i += 1
            break

        if s[i] == '"':
            val, i = _parse_mi_string(s, i)
            items.append(val)
        elif s[i] == "{":
            val, i = _parse_mi_tuple(s, i)
            items.append(val)
        elif s[i] == "[":
            val, i = _parse_mi_list(s, i)
            items.append(val)
        else:
            # Check for key=value pairs in list (GDB does this for results)
            key_start = i
            while i < n and s[i] not in "=,[]{}":
                i += 1
            key = s[key_start:i].strip()
            if i < n and s[i] == "=":
                i += 1  # skip =
                if i < n and s[i] == '"':
                    val, i = _parse_mi_string(s, i)
                    items.append({key: val})
                elif i < n and s[i] == "{":
                    val, i = _parse_mi_tuple(s, i)
                    items.append({key: val})
                elif i < n and s[i] == "[":
                    val, i = _parse_mi_list(s, i)
                    items.append({key: val})
                else:
                    val_start = i
                    while i < n and s[i] not in ",[]{}":
                        i += 1
                    items.append({key: s[val_start:i].strip()})
            else:
                if key:
                    items.append(key)

    return items, i
