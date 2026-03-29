"""Debug Configuration — launch configs for supported languages.

Loads launch configurations from settings.json and provides
zero-config debugging for Python (bdb), C/C++ (GDB), JS/TS (Node),
and DAP-based adapters (Rust via codelldb, Ruby via rdbg, etc.).
"""

import os
from dataclasses import dataclass, field

from shared.settings.settings_manager import get_setting, set_setting

_SUPPORTED_TYPES = {"python", "cppdbg", "node", "codelldb", "rdbg", "dap"}


@dataclass
class DebugConfig:
    """A single debug launch configuration."""

    name: str
    _type: str = "python"
    program: str = ""
    python: str = ""  # Python executable (default: sys.executable)
    args: list[str] = field(default_factory=list)
    cwd: str = ""
    env: dict[str, str] = field(default_factory=dict)
    stop_on_entry: bool = False
    adapter_path: str = ""  # Explicit DAP adapter executable path
    adapter_args: list[str] = field(default_factory=list)
    request: str = "launch"  # DAP request type: "launch" or "attach"

    @property
    def type(self) -> str:
        return self._type


def _detect_type(file_path: str) -> str | None:
    """Detect debug type from file extension using settings."""
    ext = os.path.splitext(file_path)[1].lower()
    file_types = get_setting("debugger.file_types", {})
    return file_types.get(ext)


def create_default_config(file_path: str, workspace_folders: list[str] | None = None) -> DebugConfig | None:
    """Create a zero-config launch configuration for a supported file.

    Returns None if the file type is not supported.
    """
    debug_type = _detect_type(file_path)
    if debug_type is None:
        return None

    cwd = workspace_folders[0] if workspace_folders else os.path.dirname(file_path)
    basename = os.path.basename(file_path)

    _TYPE_LABELS = {
        "python": "Python",
        "node": "Node",
        "codelldb": "Rust",
        "rdbg": "Ruby",
    }

    if debug_type == "cppdbg":
        lang = "C++" if os.path.splitext(file_path)[1].lower() in (".cpp", ".cc", ".cxx", ".c++", ".hpp") else "C"
        label = lang
    else:
        label = _TYPE_LABELS.get(debug_type, debug_type)

    return DebugConfig(
        name=f"{label}: {basename}",
        _type=debug_type,
        program=file_path,
        cwd=cwd,
    )


def substitute_variables(value: str, file_path: str = "", workspace_folder: str = "") -> str:
    """Replace ${variable} placeholders in config values."""
    if not value or "${" not in value:
        return value
    result = value
    result = result.replace("${file}", file_path)
    result = result.replace("${workspaceFolder}", workspace_folder)
    if file_path:
        result = result.replace("${fileBasename}", os.path.basename(file_path))
        result = result.replace("${fileBasenameNoExtension}", os.path.splitext(os.path.basename(file_path))[0])
        result = result.replace("${fileDirname}", os.path.dirname(file_path))
        result = result.replace("${fileExtname}", os.path.splitext(file_path)[1])
    if workspace_folder:
        result = result.replace("${workspaceFolderBasename}", os.path.basename(workspace_folder))
    return result


def _parse_config_entry(entry: dict, workspace_folder: str = "") -> DebugConfig | None:
    """Parse a single configuration dict into a DebugConfig."""
    entry_type = entry.get("type", "python")
    if entry_type not in _SUPPORTED_TYPES:
        return None

    program = entry.get("program", "")
    if program:
        program = substitute_variables(program, workspace_folder=workspace_folder)

    cwd = entry.get("cwd", workspace_folder)
    if cwd:
        cwd = substitute_variables(cwd, workspace_folder=workspace_folder)

    return DebugConfig(
        name=entry.get("name", "Unnamed"),
        _type=entry_type,
        program=program,
        python=entry.get("python", ""),
        args=entry.get("args", []),
        cwd=cwd,
        env=entry.get("env", {}),
        stop_on_entry=entry.get("stopOnEntry", False),
        adapter_path=entry.get("adapterPath", ""),
        adapter_args=entry.get("adapterArgs", []),
        request=entry.get("request", "launch"),
    )


def load_configurations(workspace_folder: str = "") -> list[DebugConfig]:
    """Load debug configurations from settings.json."""
    entries = get_setting("debugger.configurations", [])
    configs = []
    for entry in entries:
        config = _parse_config_entry(entry, workspace_folder)
        if config:
            configs.append(config)
    return configs


def save_configurations(configs: list[DebugConfig]) -> None:
    """Save debug configurations to settings.json."""
    entries = []
    for config in configs:
        entry: dict = {
            "name": config.name,
            "type": config.type,
            "program": config.program,
        }
        if config.python:
            entry["python"] = config.python
        if config.args:
            entry["args"] = config.args
        if config.cwd:
            entry["cwd"] = config.cwd
        if config.env:
            entry["env"] = config.env
        if config.stop_on_entry:
            entry["stopOnEntry"] = True
        if config.adapter_path:
            entry["adapterPath"] = config.adapter_path
        if config.adapter_args:
            entry["adapterArgs"] = config.adapter_args
        if config.request != "launch":
            entry["request"] = config.request
        entries.append(entry)

    set_setting("debugger.configurations", entries)
