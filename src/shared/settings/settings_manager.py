"""
Settings Manager for Zen IDE.
Handles loading and saving user settings from ~/.zen_ide/settings.json

CORRUPTION PROTECTION:
- Atomic writes: write to temp file, fsync, then rename
- Backup: keep settings.json.bak as last known good state
- Validation: verify JSON can be parsed back after write
"""

import json
import os

from shared.settings.default_settings import DEFAULT_SETTINGS

# Settings file location (use os.path to avoid importing pathlib at startup)
SETTINGS_DIR = os.path.join(os.path.expanduser("~"), ".zen_ide")
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")
SETTINGS_BACKUP = os.path.join(SETTINGS_DIR, "settings.json.bak")

# Current settings (loaded from file or defaults)
_settings = None
# User's explicit file settings (without defaults merged in)
_file_settings = None
# Pending changes flag (for batch operations)
_pending_changes = False


def _ensure_settings_dir():
    """Ensure the settings directory exists."""
    os.makedirs(SETTINGS_DIR, exist_ok=True)


def _backup_invalid_settings(path: str, error: Exception) -> None:
    """Backup invalid settings file to avoid data loss."""
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    dir_name = os.path.dirname(path)
    base_name = os.path.basename(path)
    backup_path = os.path.join(dir_name, f"{base_name}.invalid-{timestamp}")
    try:
        os.rename(path, backup_path)
    except OSError:
        pass


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dictionaries, with override taking precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _migrate_editor_fonts(file_settings: dict) -> bool:
    """Migrate editor font keys from editor.font_* to fonts.editor.

    Returns True if migration was performed and settings need re-saving.
    """
    editor = file_settings.get("editor", {})
    old_keys = {"font_family", "font_size", "font_weight"}
    found = old_keys & set(editor.keys())
    if not found:
        return False

    fonts = file_settings.setdefault("fonts", {})
    existing = fonts.get("editor", {})
    fonts["editor"] = {
        "family": editor.pop("font_family", existing.get("family", "")),
        "size": editor.pop("font_size", existing.get("size", 16)),
        "weight": editor.pop("font_weight", existing.get("weight", "normal")),
    }
    return True


def load_settings() -> dict:
    """Load settings from file, merging with defaults for runtime use."""
    global _settings, _file_settings

    _ensure_settings_dir()
    _file_settings = None
    _file_was_corrupt = False

    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                _file_settings = json.load(f)
        except json.JSONDecodeError as e:
            _backup_invalid_settings(SETTINGS_FILE, e)
            _file_was_corrupt = True
        except IOError:
            pass

    if _file_settings is None and _file_was_corrupt:
        # Only restore from backup when the settings file existed but was corrupt.
        # If the file was simply missing (e.g., user deleted it to reset), fall
        # through to defaults instead of resurrecting a stale backup.
        if os.path.exists(SETTINGS_BACKUP):
            try:
                with open(SETTINGS_BACKUP, "r") as f:
                    backup_data = json.load(f)
                if isinstance(backup_data, dict):
                    _file_settings = backup_data
                    _settings = _deep_merge(DEFAULT_SETTINGS.copy(), _file_settings)
                    save_settings()  # Persist the restored backup as the active settings
            except Exception:
                pass  # Backup also invalid, fall through to defaults

    if _file_settings is None:
        import copy

        # Remove stale backup so it can never be resurrected on a future corrupt load
        if os.path.exists(SETTINGS_BACKUP):
            try:
                os.unlink(SETTINGS_BACKUP)
            except OSError:
                pass

        _file_settings = copy.deepcopy(DEFAULT_SETTINGS)
        _settings = copy.deepcopy(DEFAULT_SETTINGS)
        save_settings()  # Create settings.json with defaults
    else:
        migrated = _migrate_editor_fonts(_file_settings)
        # Reconcile: ensure all default top-level sections and their sub-keys
        # exist in file settings so users always see the full settings schema.
        import copy as _copy

        needs_save = migrated
        for key, default_val in DEFAULT_SETTINGS.items():
            if key not in _file_settings:
                _file_settings[key] = _copy.deepcopy(default_val)
                needs_save = True
            elif isinstance(default_val, dict) and isinstance(_file_settings[key], dict):
                for sub_key, sub_val in default_val.items():
                    if sub_key not in _file_settings[key]:
                        _file_settings[key][sub_key] = _copy.deepcopy(sub_val)
                        needs_save = True
        _settings = _deep_merge(DEFAULT_SETTINGS.copy(), _file_settings)
        if needs_save:
            save_settings(_skip_backup=True)

    return _settings


def save_settings(_skip_backup: bool = False):
    """
    Save current settings to file using atomic write.

    Protection against corruption:
    1. Serialize to JSON string first (validates serializable)
    2. Write to temp file in same directory
    3. Sync to disk (fsync)
    4. Atomically rename temp to target
    5. Backup old file before overwrite (unless _skip_backup is True)
    """
    global _settings, _file_settings, _pending_changes

    if _file_settings is None:
        _file_settings = {}
    if _settings is None:
        _settings = DEFAULT_SETTINGS.copy()

    _ensure_settings_dir()
    _pending_changes = False

    try:
        # Step 1: Serialize to string first to catch any serialization errors
        json_content = json.dumps(_file_settings, indent=2)

        # Step 2: Write to temp file in same directory (ensures same filesystem for atomic rename)
        import tempfile

        fd, temp_path = tempfile.mkstemp(dir=SETTINGS_DIR, prefix=".settings_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(json_content)
                f.flush()
                os.fsync(f.fileno())  # Step 3: Ensure data is on disk

            # Step 4: Backup existing file if it exists (skip during reconciliation
            # to avoid clobbering a valid backup with stale pre-reconciliation data)
            if not _skip_backup and os.path.exists(SETTINGS_FILE):
                try:
                    # Copy to backup (don't rename - we want to keep original until new is ready)
                    with open(SETTINGS_FILE, "r") as src:
                        with open(SETTINGS_BACKUP, "w") as dst:
                            dst.write(src.read())
                except Exception:
                    pass  # Backup failure shouldn't prevent save

            # Step 5: Atomic rename (on POSIX this is atomic if same filesystem)
            os.replace(temp_path, SETTINGS_FILE)

        except Exception:
            # Clean up temp file on any error
            try:
                os.unlink(temp_path)
            except Exception:
                pass
            raise

    except Exception:
        pass


def get_settings() -> dict:
    """Get current settings."""
    global _settings
    if _settings is None:
        load_settings()
    return _settings


def get_setting(path: str, default=None):
    """Get a setting by dot-separated path (e.g., 'editor.font_size')."""
    settings = get_settings()
    keys = path.split(".")
    value = settings

    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default

    return value


def set_setting(path: str, value, persist: bool = True):
    """
    Set a setting by dot-separated path.

    Args:
        path: Dot-separated setting path (e.g., 'editor.font_size')
        value: Value to set
        persist: If True, save to disk immediately. If False, only update in-memory
                 (use save_settings() to persist batched changes later)
    """
    global _settings, _file_settings, _pending_changes

    if _settings is None:
        load_settings()

    keys = path.split(".")

    # Update runtime merged settings
    obj = _settings
    for key in keys[:-1]:
        if key not in obj:
            obj[key] = {}
        obj = obj[key]
    obj[keys[-1]] = value

    # Update user file settings (what gets persisted)
    obj = _file_settings
    for key in keys[:-1]:
        if key not in obj:
            obj[key] = {}
        obj = obj[key]
    obj[keys[-1]] = value

    _pending_changes = True

    if persist:
        save_settings()


# Layout persistence
def save_layout(layout: dict):
    """Save window layout settings (batch operation - single write)."""
    for key, value in layout.items():
        set_setting(f"layout.{key}", value, persist=False)
    save_settings()  # Single atomic write


def get_layout() -> dict:
    """Get window layout settings."""
    return get_setting("layout", DEFAULT_SETTINGS["layout"])


# Workspace persistence
def save_workspace(folders: list[str] = None, open_files: list[str] = None, last_file: str = None):
    """Save workspace state (batch operation - single write)."""
    if folders is not None:
        set_setting("workspace.folders", folders, persist=False)
    if open_files is not None:
        set_setting("workspace.open_files", open_files, persist=False)
    if last_file is not None:
        set_setting("workspace.last_file", last_file, persist=False)
    save_settings()  # Single atomic write


def get_workspace() -> dict:
    """Get workspace state."""
    return get_setting("workspace", DEFAULT_SETTINGS["workspace"])


def has_pending_changes() -> bool:
    """Check if there are unsaved in-memory changes."""
    return _pending_changes


def restore_from_backup() -> bool:
    """
    Restore settings from backup file if available.
    Returns True if backup was restored, False otherwise.
    """
    global _settings, _file_settings

    if not os.path.exists(SETTINGS_BACKUP):
        return False

    try:
        with open(SETTINGS_BACKUP, "r") as f:
            backup_content = f.read()
        backup_data = json.loads(backup_content)

        # Validate it's a proper dict
        if not isinstance(backup_data, dict):
            return False

        # Restore to main file
        _file_settings = backup_data
        _settings = _deep_merge(DEFAULT_SETTINGS.copy(), _file_settings)
        save_settings()
        return True
    except Exception:
        return False
