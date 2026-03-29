"""DAP adapter registry — maps debug types to adapter executables.

Provides discovery for DAP debug adapters configured in settings.json
and supports explicit adapter paths from launch.json.
"""

import os
import shutil
from dataclasses import dataclass, field

from shared.settings.settings_manager import get_setting


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


def _get_adapters() -> dict[str, dict]:
    """Get adapter definitions from settings."""
    return get_setting("debugger.adapters", {})


def _get_ext_to_type() -> dict[str, str]:
    """Get file-extension-to-debug-type map from settings."""
    return get_setting("debugger.file_types", {})


def find_adapter(config_type: str) -> DapAdapterInfo | None:
    """Look up a DAP adapter by config type.

    Returns None if the adapter type is unknown or the binary is not found.
    """
    entry = _get_adapters().get(config_type)
    if entry is None:
        return None

    command = entry.get("command", [])
    if not command:
        return None

    exe = command[0]
    if not _find_executable(exe):
        return None

    return DapAdapterInfo(
        command=list(command),
        type=config_type,
        launch_args_key=entry.get("launch_args_key", "program"),
        extra_launch_args=entry.get("extra_launch_args", {}),
    )


def detect_dap_type(file_path: str) -> str | None:
    """Detect DAP adapter type from file extension.

    Returns None if the file type has no known DAP adapter.
    """
    ext = os.path.splitext(file_path)[1].lower()
    adapters = _get_adapters()
    file_types = _get_ext_to_type()
    debug_type = file_types.get(ext)
    # Only return types that have a DAP adapter entry
    if debug_type and debug_type in adapters:
        return debug_type
    return None


def make_adapter_from_path(adapter_path: str, adapter_args: list[str], config_type: str) -> DapAdapterInfo:
    """Create a DapAdapterInfo from an explicit adapter path."""
    return DapAdapterInfo(
        command=[adapter_path] + adapter_args,
        type=config_type,
    )
