"""Breakpoint Manager — persistent breakpoint tracking across files.

Manages breakpoints independently of debug sessions. Persists to
~/.zen_ide/breakpoints.json alongside other Zen IDE settings.
"""

import json
import os
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from shared.settings import SETTINGS_DIR


class BreakpointType(Enum):
    LINE = "line"
    CONDITIONAL = "conditional"
    LOGPOINT = "logpoint"
    EXCEPTION = "exception"
    FUNCTION = "function"


@dataclass
class Breakpoint:
    file_path: str
    line: int
    enabled: bool = True
    condition: str = ""
    hit_condition: str = ""
    log_message: str = ""
    bp_type: BreakpointType = BreakpointType.LINE
    verified: bool = False  # Set by adapter after setBreakpoints response

    @property
    def is_conditional(self) -> bool:
        return self.bp_type == BreakpointType.CONDITIONAL and bool(self.condition)

    @property
    def is_logpoint(self) -> bool:
        return self.bp_type == BreakpointType.LOGPOINT and bool(self.log_message)


_BREAKPOINTS_FILE = os.path.join(SETTINGS_DIR, "breakpoints.json")


class BreakpointManager:
    """Manages breakpoints across files. Persists to ~/.zen_ide/breakpoints.json."""

    def __init__(self):
        self._breakpoints: dict[str, list[Breakpoint]] = {}  # file_path -> [Breakpoint]
        self._subscribers: list[Callable[[str, str], None]] = []  # (file_path, action) callbacks
        self._exception_filters: list[str] = []  # e.g. ["uncaught", "raised"]
        self._function_breakpoints: list[str] = []
        self.load()

    def toggle(self, file_path: str, line: int) -> bool:
        """Toggle a breakpoint at file:line. Returns True if added, False if removed."""
        existing = self._find(file_path, line)
        if existing:
            self.remove(file_path, line)
            return False
        else:
            self.add(file_path, line)
            return True

    def add(self, file_path: str, line: int, condition: str = "", log_message: str = "") -> Breakpoint:
        """Add a breakpoint at file:line."""
        # Don't add duplicate
        existing = self._find(file_path, line)
        if existing:
            return existing

        bp_type = BreakpointType.LINE
        if condition:
            bp_type = BreakpointType.CONDITIONAL
        elif log_message:
            bp_type = BreakpointType.LOGPOINT

        bp = Breakpoint(
            file_path=file_path,
            line=line,
            condition=condition,
            log_message=log_message,
            bp_type=bp_type,
        )
        self._breakpoints.setdefault(file_path, []).append(bp)
        self._notify(file_path, "added")
        self.save()
        return bp

    def remove(self, file_path: str, line: int) -> None:
        """Remove a breakpoint at file:line."""
        bps = self._breakpoints.get(file_path)
        if not bps:
            return
        self._breakpoints[file_path] = [bp for bp in bps if bp.line != line]
        if not self._breakpoints[file_path]:
            del self._breakpoints[file_path]
        self._notify(file_path, "removed")
        self.save()

    def set_enabled(self, file_path: str, line: int, enabled: bool) -> None:
        """Enable or disable a breakpoint."""
        bp = self._find(file_path, line)
        if bp:
            bp.enabled = enabled
            self._notify(file_path, "changed")
            self.save()

    def set_condition(self, file_path: str, line: int, condition: str) -> None:
        """Set a condition on a breakpoint (making it conditional)."""
        bp = self._find(file_path, line)
        if bp:
            bp.condition = condition
            bp.bp_type = BreakpointType.CONDITIONAL if condition else BreakpointType.LINE
            self._notify(file_path, "changed")
            self.save()

    def set_log_message(self, file_path: str, line: int, log_message: str) -> None:
        """Set a log message on a breakpoint (making it a logpoint)."""
        bp = self._find(file_path, line)
        if bp:
            bp.log_message = log_message
            bp.bp_type = BreakpointType.LOGPOINT if log_message else BreakpointType.LINE
            self._notify(file_path, "changed")
            self.save()

    def get_for_file(self, file_path: str) -> list[Breakpoint]:
        """Get all breakpoints for a file."""
        return list(self._breakpoints.get(file_path, []))

    def get_all(self) -> dict[str, list[Breakpoint]]:
        """Get all breakpoints grouped by file."""
        return dict(self._breakpoints)

    def get_enabled_lines(self, file_path: str) -> list[int]:
        """Get line numbers of enabled breakpoints for a file."""
        return [bp.line for bp in self._breakpoints.get(file_path, []) if bp.enabled]

    def get_enabled_conditions(self, file_path: str) -> list[str]:
        """Get conditions for enabled breakpoints (parallel to get_enabled_lines)."""
        return [bp.condition for bp in self._breakpoints.get(file_path, []) if bp.enabled]

    def clear_file(self, file_path: str) -> None:
        """Remove all breakpoints for a file."""
        if file_path in self._breakpoints:
            del self._breakpoints[file_path]
            self._notify(file_path, "cleared")
            self.save()

    def clear_all(self) -> None:
        """Remove all breakpoints."""
        files = list(self._breakpoints.keys())
        self._breakpoints.clear()
        for f in files:
            self._notify(f, "cleared")
        self.save()

    def has_breakpoints(self, file_path: str) -> bool:
        """Check if a file has any breakpoints."""
        return bool(self._breakpoints.get(file_path))

    # -- Exception breakpoints --

    def set_exception_filters(self, filters: list[str]) -> None:
        """Set exception breakpoint filters (e.g., ["uncaught", "raised"])."""
        self._exception_filters = filters
        self._notify("", "exception_changed")

    def get_exception_filters(self) -> list[str]:
        return list(self._exception_filters)

    # -- Function breakpoints --

    def add_function_breakpoint(self, name: str) -> None:
        if name not in self._function_breakpoints:
            self._function_breakpoints.append(name)
            self._notify("", "function_changed")

    def remove_function_breakpoint(self, name: str) -> None:
        if name in self._function_breakpoints:
            self._function_breakpoints.remove(name)
            self._notify("", "function_changed")

    def get_function_breakpoints(self) -> list[str]:
        return list(self._function_breakpoints)

    # -- Persistence --

    def save(self) -> None:
        """Save breakpoints to disk."""
        data = {
            "breakpoints": {},
            "exception_filters": self._exception_filters,
            "function_breakpoints": self._function_breakpoints,
        }
        for file_path, bps in self._breakpoints.items():
            data["breakpoints"][file_path] = [
                {
                    "line": bp.line,
                    "enabled": bp.enabled,
                    "condition": bp.condition,
                    "hit_condition": bp.hit_condition,
                    "log_message": bp.log_message,
                    "type": bp.bp_type.value,
                }
                for bp in bps
            ]
        try:
            os.makedirs(SETTINGS_DIR, exist_ok=True)
            with open(_BREAKPOINTS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass

    def load(self) -> None:
        """Load breakpoints from disk."""
        if not os.path.isfile(_BREAKPOINTS_FILE):
            return
        try:
            with open(_BREAKPOINTS_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return

        self._breakpoints.clear()
        for file_path, bps in data.get("breakpoints", {}).items():
            for bp_data in bps:
                bp = Breakpoint(
                    file_path=file_path,
                    line=bp_data.get("line", 0),
                    enabled=bp_data.get("enabled", True),
                    condition=bp_data.get("condition", ""),
                    hit_condition=bp_data.get("hit_condition", ""),
                    log_message=bp_data.get("log_message", ""),
                    bp_type=BreakpointType(bp_data.get("type", "line")),
                )
                self._breakpoints.setdefault(file_path, []).append(bp)

        self._exception_filters = data.get("exception_filters", [])
        self._function_breakpoints = data.get("function_breakpoints", [])

    # -- Change notification --

    def subscribe(self, callback: Callable[[str, str], None]) -> None:
        """Subscribe to breakpoint changes. callback(file_path, action)."""
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable) -> None:
        """Remove a subscription."""
        self._subscribers = [s for s in self._subscribers if s is not callback]

    # -- Internal --

    def _find(self, file_path: str, line: int) -> Breakpoint | None:
        """Find a breakpoint at file:line."""
        for bp in self._breakpoints.get(file_path, []):
            if bp.line == line:
                return bp
        return None

    def _notify(self, file_path: str, action: str) -> None:
        """Notify subscribers of a change."""
        for callback in self._subscribers:
            try:
                callback(file_path, action)
            except Exception:
                pass


# Singleton instance
_instance: BreakpointManager | None = None


def get_breakpoint_manager() -> BreakpointManager:
    """Get the singleton BreakpointManager instance."""
    global _instance
    if _instance is None:
        _instance = BreakpointManager()
    return _instance
