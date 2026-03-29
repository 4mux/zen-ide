"""Debug Configuration — launch configs for supported languages.

Loads launch configurations from .zen/launch.json and provides
zero-config debugging for Python (bdb), C/C++ (GDB), JS/TS (Node),
and DAP-based adapters (Rust via codelldb, Ruby via rdbg, etc.).
"""

import json
import os
from dataclasses import dataclass, field

_PYTHON_EXTS = {".py"}
_C_CPP_EXTS = {".c", ".cpp", ".cc", ".cxx", ".c++", ".h", ".hpp"}
_JS_TS_EXTS = {".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx"}
_RUST_EXTS = {".rs"}
_RUBY_EXTS = {".rb"}


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
    """Detect debug type from file extension."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext in _PYTHON_EXTS:
        return "python"
    if ext in _C_CPP_EXTS:
        return "cppdbg"
    if ext in _JS_TS_EXTS:
        return "node"
    if ext in _RUST_EXTS:
        return "codelldb"
    if ext in _RUBY_EXTS:
        return "rdbg"
    return None


def create_default_config(file_path: str, workspace_folders: list[str] | None = None) -> DebugConfig | None:
    """Create a zero-config launch configuration for a supported file.

    Returns None if the file type is not supported.
    """
    debug_type = _detect_type(file_path)
    if debug_type is None:
        return None

    cwd = workspace_folders[0] if workspace_folders else os.path.dirname(file_path)
    basename = os.path.basename(file_path)

    if debug_type == "python":
        return DebugConfig(
            name=f"Python: {basename}",
            _type="python",
            program=file_path,
            cwd=cwd,
        )

    if debug_type == "node":
        return DebugConfig(
            name=f"Node: {basename}",
            _type="node",
            program=file_path,
            cwd=cwd,
        )

    if debug_type == "codelldb":
        return DebugConfig(
            name=f"Rust: {basename}",
            _type="codelldb",
            program=file_path,
            cwd=cwd,
        )

    if debug_type == "rdbg":
        return DebugConfig(
            name=f"Ruby: {basename}",
            _type="rdbg",
            program=file_path,
            cwd=cwd,
        )

    # C/C++
    lang = "C++" if os.path.splitext(file_path)[1].lower() in (".cpp", ".cc", ".cxx", ".c++", ".hpp") else "C"
    return DebugConfig(
        name=f"{lang}: {basename}",
        _type="cppdbg",
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


_SUPPORTED_TYPES = {"python", "cppdbg", "node", "codelldb", "rdbg", "dap"}


def load_launch_configs(workspace_folder: str) -> list[DebugConfig]:
    """Load debug configurations from .zen/launch.json."""
    launch_file = os.path.join(workspace_folder, ".zen", "launch.json")
    if not os.path.isfile(launch_file):
        return []

    try:
        with open(launch_file, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    configs = []
    for entry in data.get("configurations", []):
        entry_type = entry.get("type", "python")
        if entry_type not in _SUPPORTED_TYPES:
            continue

        program = entry.get("program", "")
        if program:
            program = substitute_variables(program, workspace_folder=workspace_folder)

        cwd = entry.get("cwd", workspace_folder)
        if cwd:
            cwd = substitute_variables(cwd, workspace_folder=workspace_folder)

        config = DebugConfig(
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
        configs.append(config)

    return configs


def save_launch_configs(workspace_folder: str, configs: list[DebugConfig]) -> None:
    """Save debug configurations to .zen/launch.json."""
    zen_dir = os.path.join(workspace_folder, ".zen")
    os.makedirs(zen_dir, exist_ok=True)

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

    data = {"version": "0.2.0", "configurations": entries}
    launch_file = os.path.join(zen_dir, "launch.json")
    with open(launch_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
