"""Debug Session Manager — orchestrates the debug lifecycle.

Sits between the UI and the bdb debugger subprocess. Manages state
transitions, breakpoint synchronization, and inspection data.
"""

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from .bdb_debugger import BdbClient
from .breakpoint_manager import get_breakpoint_manager


class SessionState(Enum):
    IDLE = "idle"
    INITIALIZING = "initializing"
    RUNNING = "running"
    STOPPED = "stopped"
    TERMINATED = "terminated"


@dataclass
class StackFrame:
    id: int
    name: str
    source: str
    line: int
    column: int = 0
    end_line: int | None = None


@dataclass
class Scope:
    name: str
    variables_reference: int
    expensive: bool = False


@dataclass
class Variable:
    name: str
    value: str
    type: str = ""
    variables_reference: int = 0
    children: list["Variable"] = field(default_factory=list)


class DebugSession:
    """Manages a single debug session lifecycle."""

    def __init__(
        self,
        config,
        on_state_changed: Callable[["DebugSession"], None] | None = None,
        on_output: Callable[[str, str], None] | None = None,
        on_stopped: Callable[["DebugSession", int, str, str, int], None] | None = None,
    ):
        self.state = SessionState.IDLE
        self._config = config
        self._client: BdbClient | None = None
        self._current_frame: StackFrame | None = None
        self._cached_stack: list[StackFrame] = []

        # Callbacks
        self._on_state_changed = on_state_changed
        self._on_output = on_output
        self._on_stopped = on_stopped  # (session, thread_id, reason, file, line)

        self._breakpoint_mgr = get_breakpoint_manager()

    @property
    def config(self):
        return self._config

    @property
    def current_frame(self) -> StackFrame | None:
        return self._current_frame

    # -- Lifecycle --

    def start(self, file_path: str = "", workspace_folder: str = "") -> None:
        """Start a debug session."""
        if self.state != SessionState.IDLE:
            return

        self._set_state(SessionState.INITIALIZING)

        program = self._config.program or file_path
        cwd = self._config.cwd or workspace_folder or os.path.dirname(file_path)
        python = self._config.python or ""

        self._client = BdbClient(self._on_event)

        try:
            self._client.start(
                script_path=program,
                python=python,
                cwd=cwd,
                env=self._config.env or None,
                args=self._config.args or None,
            )
        except Exception as e:
            self._emit_output("console", f"Failed to start debugger: {e}\n")
            self._set_state(SessionState.TERMINATED)
            return

        # Send breakpoints before running
        self._sync_all_breakpoints()

        # Start execution
        self._client.run(stop_on_entry=self._config.stop_on_entry)
        self._set_state(SessionState.RUNNING)

    def stop(self) -> None:
        """Stop the debug session."""
        if self._client:
            self._client.stop()
            self._client = None
        self._current_frame = None
        self._cached_stack.clear()
        self._set_state(SessionState.TERMINATED)

    def restart(self) -> None:
        """Restart the debug session."""
        config = self._config
        file_path = config.program
        cwd = config.cwd
        self.stop()
        self.state = SessionState.IDLE
        self.start(file_path, cwd)

    # -- Execution control --

    def continue_(self) -> None:
        if self.state != SessionState.STOPPED or not self._client:
            return
        self._client.continue_()
        self._set_state(SessionState.RUNNING)
        self._current_frame = None

    def step_over(self) -> None:
        if self.state != SessionState.STOPPED or not self._client:
            return
        self._client.step_over()
        self._set_state(SessionState.RUNNING)

    def step_into(self) -> None:
        if self.state != SessionState.STOPPED or not self._client:
            return
        self._client.step_into()
        self._set_state(SessionState.RUNNING)

    def step_out(self) -> None:
        if self.state != SessionState.STOPPED or not self._client:
            return
        self._client.step_out()
        self._set_state(SessionState.RUNNING)

    def pause(self) -> None:
        """Pause is not supported with bdb (no async command channel)."""
        pass

    # -- Inspection --

    def get_call_stack(self, thread_id: int | None = None) -> list[StackFrame]:
        """Get the call stack."""
        if not self._client or self.state != SessionState.STOPPED:
            return []
        try:
            result = self._client.get_stack().result(timeout=5)
            frames = [
                StackFrame(
                    id=f["id"],
                    name=f["name"],
                    source=f.get("file", ""),
                    line=f.get("line", 0),
                )
                for f in result.get("frames", [])
            ]
            self._cached_stack = frames
            if frames:
                self._current_frame = frames[0]
            return frames
        except Exception:
            return self._cached_stack

    def get_scopes(self, frame_id: int | None = None) -> list[Scope]:
        """Get scopes for a frame."""
        if not self._client or self.state != SessionState.STOPPED:
            return []
        fid = frame_id if frame_id is not None else (self._current_frame.id if self._current_frame else 0)
        try:
            result = self._client.get_scopes(fid).result(timeout=5)
            return [Scope(name=s["name"], variables_reference=s["ref"]) for s in result.get("scopes", [])]
        except Exception:
            return []

    def get_variables(self, variables_reference: int) -> list[Variable]:
        """Get variables for a scope or variable reference."""
        if not self._client or self.state != SessionState.STOPPED:
            return []
        try:
            result = self._client.get_variables(variables_reference).result(timeout=5)
            return [
                Variable(
                    name=v["name"],
                    value=v["value"],
                    type=v.get("type", ""),
                    variables_reference=v.get("ref", 0),
                )
                for v in result.get("variables", [])
            ]
        except Exception:
            return []

    def evaluate(self, expression: str, frame_id: int | None = None) -> str:
        """Evaluate an expression in the current debug context."""
        if not self._client or self.state != SessionState.STOPPED:
            return "<not stopped>"
        fid = frame_id if frame_id is not None else (self._current_frame.id if self._current_frame else 0)
        try:
            result = self._client.evaluate(expression, fid).result(timeout=5)
            return result.get("result", "")
        except Exception as e:
            return f"Error: {e}"

    def set_current_frame(self, frame: StackFrame) -> None:
        """Set the current frame for variable inspection."""
        self._current_frame = frame
        if self._client:
            self._client.set_frame(frame.id)

    # -- Breakpoint sync --

    def _sync_all_breakpoints(self) -> None:
        """Send all breakpoints to the debugger subprocess."""
        if not self._client:
            return
        for file_path, bps in self._breakpoint_mgr.get_all().items():
            lines = [(bp.line, bp.condition) for bp in bps if bp.enabled]
            if lines:
                for line, condition in lines:
                    self._client.set_break(file_path, line, condition)

    def sync_file_breakpoints(self, file_path: str) -> None:
        """Sync breakpoints for a specific file with the debugger."""
        if not self._client or not self._client.is_running:
            return
        # Clear existing breaks for this file, then set current ones
        self._client.clear_file_breaks(file_path)
        for bp in self._breakpoint_mgr.get_for_file(file_path):
            if bp.enabled:
                self._client.set_break(file_path, bp.line, bp.condition)

    # -- Event handler --

    def _on_event(self, event: str, body: dict) -> None:
        """Handle events from the bdb subprocess (called on main thread)."""
        if event == "stopped":
            self._handle_stopped(body)
        elif event == "output":
            category = body.get("category", "stdout")
            text = body.get("text", "")
            self._emit_output(category, text)
        elif event == "terminated":
            exit_code = body.get("exit_code", 0)
            self._emit_output("console", f"\nProcess exited with code {exit_code}\n")
            self.stop()

    def _handle_stopped(self, body: dict) -> None:
        """Handle a 'stopped' event — breakpoint hit or step completed."""
        self._set_state(SessionState.STOPPED)

        file_path = body.get("file", "")
        line = body.get("line", 0)
        reason = body.get("reason", "step")

        # Fetch call stack
        self._cached_stack = self.get_call_stack()

        if self._on_stopped:
            self._on_stopped(self, 1, reason, file_path, line)

    # -- Internal helpers --

    def _set_state(self, new_state: SessionState) -> None:
        self.state = new_state
        if self._on_state_changed:
            try:
                self._on_state_changed(self)
            except Exception:
                import logging

                logging.getLogger("zen.debug").exception("state_changed callback failed")

    def _emit_output(self, category: str, text: str) -> None:
        if self._on_output:
            try:
                self._on_output(text, category)
            except Exception:
                import logging

                logging.getLogger("zen.debug").exception("output callback failed")
