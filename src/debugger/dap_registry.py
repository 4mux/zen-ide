"""DAP adapter registry — maps debug types to adapter executables.

Provides discovery for known DAP debug adapters (codelldb for Rust,
rdbg for Ruby) and supports explicit adapter paths from launch.json.
"""

import os
import shutil
from dataclasses import dataclass, field


@dataclass
class DapAdapterInfo:
    """Information needed to launch a DAP debug adapter."""

    command: list[str]
    type: str
    launch_args_key: str = "program"  # key name for the program path in launch args
    extra_launch_args: dict = field(default_factory=dict)


def _find_executable(name: str) -> str | None:
    """Find an executable in PATH."""
    return shutil.which(name)


# Built-in adapter definitions.
# Each entry maps a config type to the adapter command and settings.
_BUILTIN_ADAPTERS: dict[str, dict] = {
    "codelldb": {
        "command_candidates": [
            ["codelldb", "--port", "stdin"],
        ],
        "launch_args_key": "program",
    },
    "rdbg": {
        "command_candidates": [
            ["rdbg", "--open", "--command", "--"],
        ],
        "launch_args_key": "script",
        "extra_launch_args": {"command": "ruby"},
    },
}

# Map file extensions to config types for auto-detection.
_EXT_TO_TYPE: dict[str, str] = {
    ".rs": "codelldb",
    ".rb": "rdbg",
}


def find_adapter(config_type: str) -> DapAdapterInfo | None:
    """Look up a DAP adapter by config type.

    Returns None if the adapter type is unknown or the binary is not found.
    """
    entry = _BUILTIN_ADAPTERS.get(config_type)
    if entry is None:
        return None

    for candidate in entry["command_candidates"]:
        exe = candidate[0]
        if _find_executable(exe):
            return DapAdapterInfo(
                command=candidate,
                type=config_type,
                launch_args_key=entry.get("launch_args_key", "program"),
                extra_launch_args=entry.get("extra_launch_args", {}),
            )

    return None


def detect_dap_type(file_path: str) -> str | None:
    """Detect DAP adapter type from file extension.

    Returns None if the file type has no known DAP adapter.
    """
    ext = os.path.splitext(file_path)[1].lower()
    return _EXT_TO_TYPE.get(ext)


def make_adapter_from_path(adapter_path: str, adapter_args: list[str], config_type: str) -> DapAdapterInfo:
    """Create a DapAdapterInfo from an explicit adapter path."""
    return DapAdapterInfo(
        command=[adapter_path] + adapter_args,
        type=config_type,
    )
