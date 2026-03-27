"""Debug Configuration — Python-only launch configs.

Loads launch configurations from .zen/launch.json and provides
zero-config debugging for Python files using the bdb-based debugger.
"""

import json
import os
from dataclasses import dataclass, field


@dataclass
class DebugConfig:
    """A single debug launch configuration."""

    name: str
    program: str = ""
    python: str = ""  # Python executable (default: sys.executable)
    args: list[str] = field(default_factory=list)
    cwd: str = ""
    env: dict[str, str] = field(default_factory=dict)
    stop_on_entry: bool = False

    @property
    def type(self) -> str:
        return "python"


def create_default_config(file_path: str, workspace_folders: list[str] | None = None) -> DebugConfig | None:
    """Create a zero-config launch configuration for a Python file.

    Returns None if the file is not a Python file.
    """
    if not file_path.endswith(".py"):
        return None

    cwd = workspace_folders[0] if workspace_folders else os.path.dirname(file_path)

    return DebugConfig(
        name=f"Python: {os.path.basename(file_path)}",
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
        # Only load Python configurations
        entry_type = entry.get("type", "")
        if entry_type and entry_type != "python":
            continue

        program = entry.get("program", "")
        if program:
            program = substitute_variables(program, workspace_folder=workspace_folder)

        cwd = entry.get("cwd", workspace_folder)
        if cwd:
            cwd = substitute_variables(cwd, workspace_folder=workspace_folder)

        config = DebugConfig(
            name=entry.get("name", "Unnamed"),
            program=program,
            python=entry.get("python", ""),
            args=entry.get("args", []),
            cwd=cwd,
            env=entry.get("env", {}),
            stop_on_entry=entry.get("stopOnEntry", False),
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
            "type": "python",
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
        entries.append(entry)

    data = {"version": "0.2.0", "configurations": entries}
    launch_file = os.path.join(zen_dir, "launch.json")
    with open(launch_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
