# Zen IDE User Directory (`~/.zen_ide/`)

**Created_at:** 2026-03-03  
**Updated_at:** 2026-03-08  
**Status:** Active  
**Goal:** Document the `~/.zen_ide/` directory structure and all config/state files  
**Scope:** `settings.json`, `dev_pad.json`, `themes/`, `notes/`, `aliases`  

---

The `~/.zen_ide/` directory stores all user-specific data, configuration, and state for Zen IDE. This directory is created automatically on first run.

---

## Directory Structure

```
~/.zen_ide/
├── settings.json           # User preferences and layout state
├── settings.json.bak       # Backup of last known good settings
├── dev_pad.json            # Dev Pad activity history
├── bash_history            # Terminal command history
├── aliases                 # Custom shell aliases (sourced in terminal)
├── crash_log.txt           # Crash reports (newest first)
├── native_crash.log        # Native signal crash recovery
├── model_cache.json        # Cached AI model lists
├── font_cache.txt          # Cached Nerd Font detection
├── ide_state.json          # Dynamic IDE editor state for AI context
├── ai_pids/                # AI process tracking (ephemeral)
│   └── <pid>.txt           # PID file per IDE instance
├── notes/                  # Dev Pad notes storage
│   └── <note_id>.md        # Individual markdown notes
└── themes/                 # Custom user themes (planned)
    └── *.json              # JSON theme files
```

---

## File Reference

### `settings.json`

Main configuration file containing all user preferences, editor settings, layout positions, and workspace state. Managed by `SettingsManager`.

**Corruption Protection:**

The settings file is protected against corruption through multiple safeguards:

1. **Atomic writes** — Changes are written to a temp file first, synced to disk (`fsync`), then atomically renamed to replace the original
2. **Automatic backup** — Before each write, the current file is backed up to `settings.json.bak`
3. **Batch operations** — Layout/workspace saves use batch mode to avoid multiple rapid writes
4. **Invalid file handling** — Corrupted JSON is renamed to `settings.json.invalid-<timestamp>` and defaults are restored

**Recovery options:**
- Restore from backup: `cp ~/.zen_ide/settings.json.bak ~/.zen_ide/settings.json`
- Reset to defaults: Delete `settings.json` and restart Zen IDE

**Categories:**
- **Theme** — Active color theme (`theme`)
- **Editor** — Font, tab size, word wrap, line numbers, etc.
- **Terminal** — Font, scrollback lines, shell path
- **Explorer** — File tree font settings
- **AI** — Provider selection, model preferences, inline suggestions
- **Layout** — Splitter positions, window dimensions
- **Workspace** — Open folders, files, last active file
- **Behavior** — Dev Pad auto-show, vim emulation, terminal layout
- **Formatters** — Per-extension format commands
- **Diagnostics** — Per-extension linter commands
- **Navigation** — Code navigation backend

See [docs/2026_02_12_settings_reference.md](2026_02_12_settings_reference.md) for the complete settings reference.

**Location:** `~/.zen_ide/settings.json`  
**Source:** `src/shared/settings/settings_manager.py`

---

### `dev_pad.json`

Stores the activity history displayed in the Dev Pad panel. Tracks file edits, git operations, searches, and other developer activities.

**Format:**
```json
{
  "activities": [
    {
      "id": "abc123",
      "timestamp": "2024-01-15T10:30:00",
      "activity_type": "file_edit",
      "title": "Edited main.py",
      "description": "Modified function calculate_total()",
      "link_type": "file",
      "link_target": "/path/to/main.py",
      "metadata": {}
    }
  ]
}
```

**Limit:** 500 activities (oldest pruned automatically)

**Location:** `~/.zen_ide/dev_pad.json`  
**Source:** `src/dev_pad/dev_pad_storage.py`

---

### `notes/`

Directory containing markdown notes created from the Dev Pad panel. Each note is stored as a separate `.md` file with a unique ID.

**Location:** `~/.zen_ide/notes/`  
**Source:** `src/dev_pad/dev_pad_storage.py`

---

### `bash_history`

Persistent command history for the integrated terminal. Commands are saved across sessions.

**Location:** `~/.zen_ide/bash_history`  
**Source:** `src/terminal/terminal_shell.py`

---

### `aliases`

Optional file for custom shell aliases. If present, it's sourced automatically when the integrated terminal starts.

**Example:**
```bash
alias ll='ls -la'
alias gs='git status'
```

**Location:** `~/.zen_ide/aliases`  
**Source:** `src/terminal/terminal_shell.py`

---

### `crash_log.txt`

Crash report log with Python exception tracebacks. Newest crashes are prepended to the top of the file. Used for debugging IDE issues.

**Format:**
```
============================================================
CRASH: 2024-01-15 10:30:00
============================================================
Exception: ValueError: invalid literal for int()

Traceback:
  File "src/editor.py", line 42, in foo
    ...
```

**Location:** `~/.zen_ide/crash_log.txt`  
**Source:** `src/shared/crash_log.py`

---

### `native_crash.log`

Temporary file used by Python's `faulthandler` module to capture native crashes (SIGSEGV, SIGABRT, etc.). On startup, if this file contains data, it's recovered and merged into `crash_log.txt`.

**Location:** `~/.zen_ide/native_crash.log`  
**Source:** `src/shared/crash_log.py`

---

### `model_cache.json`

Cached list of available AI models from providers (Claude CLI, GitHub Copilot). Avoids repeated CLI queries on every AI panel open.

**Location:** `~/.zen_ide/model_cache.json`  
**Source:** `src/ai/ai_chat_terminal.py`

---

### `font_cache.txt`

Cached result of Nerd Font detection. Stores the detected font family name to avoid repeated system font enumeration.

**Location:** `~/.zen_ide/font_cache.txt`  
**Source:** `src/treeview/tree_icons.py`

---

### `ide_state.json`

Dynamic editor state file updated on every tab switch, file open, and file close. Provides a real-time bridge between the Zen IDE editor and AI CLI terminals (Claude CLI, Copilot CLI) so that AI agents can query it mid-conversation for the user's current context.

**Format:**
```json
{
  "active_file": "/path/to/currently/viewed/file.py",
  "open_files": ["/path/to/file1.py", "/path/to/file2.py"],
  "workspace_folders": ["/path/to/project"],
  "workspace_file": "",
  "git_branch": "main"
}
```

**How AI CLIs use this:**
- Environment variables (`ZEN_ACTIVE_FILE`, `ZEN_OPEN_FILES`, `ZEN_WORKSPACE_FOLDERS`, `ZEN_GIT_BRANCH`) are set at CLI spawn time
- A system prompt is appended (via `--append-system-prompt` for Claude CLI, `--system-prompt` for Copilot CLI) pointing to this file
- The file is atomically updated so CLIs can read it safely at any time

**Location:** `~/.zen_ide/ide_state.json`  
**Source:** `src/shared/ide_state_writer.py`

---

### `ai_pids/`

Directory containing PID tracking files for AI subprocess management. Each running IDE instance creates a file named `<pid>.txt` containing the PIDs of any AI processes it spawned.

**Purpose:**
- Track AI processes (Claude CLI, Copilot) spawned by the IDE
- Clean up orphaned AI processes on startup (from crashed sessions)
- Prevent multiple IDE instances from interfering with each other

**Format:** One PID per line
```
12345
12346
```

**Lifecycle:** Files are created when AI processes start and deleted when the IDE exits cleanly. Orphaned files (from crashes) are cleaned up on next startup.

**Location:** `~/.zen_ide/ai_pids/`  
**Source:** `src/ai/ai_process_tracker.py`

---

### `themes/` (Planned)

Directory for user-defined custom themes. JSON files placed here are loaded alongside built-in themes in the Theme Picker.

See [docs/2026_03_03_custom_themes.md](2026_03_03_custom_themes.md) for the theme JSON format and usage.

**Location:** `~/.zen_ide/themes/`  
**Source:** `src/themes/custom_theme_loader.py` (planned)

---

## Security & Privacy

The `~/.zen_ide/` directory contains user-specific data only:
- No credentials or secrets are stored
- No telemetry or usage data is collected
- All data stays local to the user's machine

To completely reset Zen IDE to defaults, delete the `~/.zen_ide/` directory:
```bash
rm -rf ~/.zen_ide
```

---

## Backup Recommendations

Files worth backing up:
- `settings.json` — Your complete configuration
- `aliases` — Custom terminal aliases
- `themes/*.json` — Custom themes (once implemented)
- `notes/` — Dev Pad notes

Files safe to delete (regenerated automatically):
- `crash_log.txt`
- `native_crash.log`
- `model_cache.json`
- `font_cache.txt`
- `ide_state.json`
- `ai_pids/` (entire directory)
