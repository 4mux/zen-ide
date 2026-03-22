"""
IDE State Writer — writes editor context to ~/.zen_ide/ide_state.json.

The state file provides a dynamic bridge between the Zen IDE editor and
AI CLI terminals (Claude CLI, Copilot CLI).  It is updated whenever the
user switches tabs, opens/closes files, or the workspace changes, so
that AI agents can query it mid-conversation for up-to-date context.
"""

import json
import os
import tempfile

_STATE_DIR = os.path.join(os.path.expanduser("~"), ".zen_ide")
_STATE_FILE = os.path.join(_STATE_DIR, "ide_state.json")


def write_ide_state(
    *,
    active_file: str = "",
    open_files: list[str] | None = None,
    workspace_folders: list[str] | None = None,
    workspace_file: str = "",
    git_branch: str = "",
) -> None:
    """Write current IDE state to ``~/.zen_ide/ide_state.json``.

    Uses atomic write (write-to-temp then rename) to avoid partial reads.
    Silently ignores errors — this is best-effort context, not critical data.
    """
    state = {
        "active_file": active_file,
        "open_files": open_files or [],
        "workspace_folders": workspace_folders or [],
        "workspace_file": workspace_file,
        "git_branch": git_branch,
    }
    try:
        os.makedirs(_STATE_DIR, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=_STATE_DIR, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, _STATE_FILE)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception:
        pass


def read_ide_state() -> dict:
    """Read the current IDE state (for tests / debugging).

    Returns an empty dict if the file is missing or corrupt.
    """
    try:
        with open(_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_state_file_path() -> str:
    """Return the absolute path to the IDE state file."""
    return _STATE_FILE
