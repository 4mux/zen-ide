# AI Terminal

**Created_at:** 2026-03-21
**Updated_at:** 2026-03-24
**Status:** Active
**Goal:** Document the current AI system — VTE-based terminal running CLI tools, multi-tab sessions, context injection, inline completions, and debug logging
**Scope:** `src/ai/`, `src/editor/inline_completion/`, `src/shared/ide_state_writer.py`, `src/shared/ai_debug_log.py`, `src/popups/ai_settings_popup.py`, `src/main/window_state.py`

---

## Overview

Zen IDE's AI system has two independent subsystems:

1. **AI Terminal** — a VTE-based panel that runs the `claude` or `copilot` CLI directly inside a real terminal emulator, with multi-tab session management.
2. **Inline Completions** — ghost-text code suggestions in the editor, powered by the Copilot HTTP API (FIM endpoint).

The AI Terminal replaced ~6,400 lines of custom HTTP-streaming, ANSI-buffer, and DrawingArea rendering code with ~800 lines of VTE integration. The CLI tools handle streaming output, tool use, colours, and interactive UX natively.

---

## AI Terminal Architecture

### Component Overview

```
AITerminalStack
│
├─ Tab bar: [Claude ▾] ────── [🗑] [+] [⛶]
│
├─ AITerminalView[0] (TerminalView)
│   ├─ AITerminalHeader
│   ├─ Gtk.ScrolledWindow
│   └─ Vte.Terminal → spawns claude/copilot binary
│
├─ AITerminalView[1] ...
└─ AITerminalView[n] ...
```

### Files

| File | LOC | Purpose |
|------|-----|---------|
| `src/ai/ai_terminal_view.py` | ~580 | Core AI terminal — spawns CLI, session management, provider switching |
| `src/ai/ai_terminal_stack.py` | ~760 | Multi-tab container with two layout modes |
| `src/ai/ai_terminal_header.py` | ~75 | Header bar: CLI picker, clear, add, maximize |
| `src/ai/tab_title_inferrer.py` | ~536 | Smart tab titles from first user message |
| `src/ai/spinner.py` | ~20 | Braille spinner animation |
| `src/ai/__init__.py` | — | Module init with lazy imports |

---

### AITerminalView

Inherits from `TerminalView` and overrides only three things:

| Override | Purpose |
|----------|---------|
| `_create_ui()` | Uses `AITerminalHeader` instead of regular header |
| `spawn_shell()` | Launches claude/copilot binary via VTE |
| `_on_header_click()` | Shows CLI picker popup |

Everything else — theme colours, scroll smoothing, keyboard shortcuts, font settings, maximize — is inherited from `TerminalView`.

**Key features:**

- **Session persistence** — detects session IDs and resumes via `--resume <id>` (Claude) or `--continue` (Copilot)
- **Provider switching** — per-tab provider choice (claude_cli or copilot_cli)
- **Yolo mode** — `--dangerously-skip-permissions` (Claude) or `--yolo` (Copilot)
- **Tab title inference** — auto-generates meaningful title from first user message
- **Processing spinner** — braille animation during AI processing via `on_processing_changed` callback
- **Scroll speed** — customisable via settings

**Session storage locations:**

| CLI | Path |
|-----|------|
| Claude | `~/.claude/projects/{path-hash}/{session_id}.jsonl` |
| Copilot | `~/.copilot/session-state/{session_id}/events.jsonl` |

---

### AITerminalStack

Container for multiple `AITerminalView` instances. Two layout modes:

**Horizontal tab mode** (default: `behavior.ai_chat_on_vertical_stack = False`):
- Scrollable tab bar: `[Claude ▾] ────────── [🗑] [+] [⛶]`
- `Gtk.Stack` shows only the active chat
- Per-tab spinners during processing
- Tab close buttons

**Vertical stack mode** (`behavior.ai_chat_on_vertical_stack = True`):
- All chats visible simultaneously
- Each pane has its own header
- Focus border highlights active pane

**Coordinated session detection** — when multiple tabs spawn simultaneously, the stack prevents duplicate session IDs:

1. Snapshot existing sessions before spawning
2. Spawn all views
3. After 4s, collect new sessions sorted by mtime
4. Assign new sessions to tabs in spawn order

**State persistence:**

```python
save_state() → [{
    "title": "Chat title",
    "provider": "claude_cli|copilot_cli",
    "session_id": "uuid",
    "active_idx": 0  # First entry only
}]
```

---

### AITerminalHeader

```
[Claude ▾] ─────────────────────── [🗑️] [+] [⛶]
```

- **Label button** — clickable, shows active CLI name with `▾` indicator
- **Clear button** — resets VTE buffer
- **Add button** — opens a new chat tab
- **Maximize button** — expands panel to fill the bottom area

---

### Tab Title Inference

`TabTitleInferrer` generates meaningful tab titles (max 30 chars) from the first user message:

- Semantic pattern matching: `"what's the diff between X and Y?"` → `"X Vs Y"`
- 86 common abbreviations (python→py, database→db, etc.)
- 150+ filler words removed
- 25+ action verbs kept (fix, debug, refactor, etc.)

---

## CLI Selection & Binary Discovery

### Provider selection logic

When `ai.provider` is empty or unavailable:

1. `claude` binary (preferred)
2. `copilot` binary (fallback)
3. Error message in VTE if neither found

### Binary search paths

| CLI | Search paths |
|-----|-------------|
| Claude | `~/.local/bin/claude`, `/usr/local/bin/claude`, `$PATH` |
| Copilot | NVM dirs (`~/.nvm/versions/node/*/bin/copilot`), `~/.local/bin/copilot`, `/usr/local/bin/copilot`, `$PATH` |

### CLI picker popup

Clicking the header label opens a popup:

```
Select AI
  ✓ Claude
    Copilot
```

Switching providers: persists to `ai.provider` → SIGTERM current process → reset VTE → spawn new binary after 200ms.

---

## AI Settings Popup

`src/popups/ai_settings_popup.py` — accessed via keybinding or menu.

- **Provider selector** — dropdown: Claude CLI / Copilot CLI
- **Model selector** — dynamically populated via async background fetch
- Handles dropdown popover focus gracefully

---

## Context Injection

The IDE injects editor state into AI CLIs so they have awareness of the current workspace, open files, and git state.

### Injection mechanisms

| Mechanism | Target | Source |
|-----------|--------|--------|
| Environment variables | Both CLIs | Set before `spawn_shell()` |
| `--append-system-prompt` | Claude CLI | `CLIProvider.append_ide_context()` |
| `~/.copilot/copilot-instructions.md` | Copilot CLI | Written between managed markers |
| `~/.zen_ide/ide_state.json` | Both CLIs (on-demand) | `IdeStateWriter` on tab switch |

### Environment variables

Set on the VTE child process before spawn:

| Variable | Content |
|----------|---------|
| `ZEN_ACTIVE_FILE` | Absolute path to the currently focused editor file |
| `ZEN_OPEN_FILES` | Comma-separated list of all open file paths |
| `ZEN_WORKSPACE_FOLDERS` | Comma-separated workspace root paths |
| `ZEN_GIT_BRANCH` | Current git branch name |
| `ZEN_IDE_STATE_FILE` | Path to `~/.zen_ide/ide_state.json` |

### System prompt injection

Both providers receive a human-readable context block:

```
## Zen IDE Context
You are running inside Zen IDE. The user has the following editor state:
- Active file (currently viewing): src/main.py
- Open files: main.py, utils.py, config.py
- Workspace folders: /home/user/project
- Git branch: feature-x

This state was captured at launch. For the latest editor state
during this conversation, read: ~/.zen_ide/ide_state.json
```

- **Claude:** appended via `--append-system-prompt "<context>"`
- **Copilot:** written to `~/.copilot/copilot-instructions.md` between `<!-- zen-ide-context-start -->` and `<!-- zen-ide-context-end -->` markers

### IDE state file

`src/shared/ide_state_writer.py` — atomic write to `~/.zen_ide/ide_state.json`.

- Written on tab switch, file open/close, workspace change (debounced 200ms)
- Git queries run in a background thread to avoid blocking the main thread
- AI CLIs can read this file mid-conversation for up-to-date context

```json
{
  "active_file": "src/main.py",
  "open_files": ["src/main.py", "src/utils.py"],
  "workspace_folders": ["/home/user/project"],
  "workspace_file": "/home/user/project.zen-workspace",
  "git_branch": "feature-x"
}
```

---

## Inline Completions

Ghost-text code suggestions rendered as a visual overlay in the editor. Uses the **Copilot HTTP API** directly — completely independent of the AI Terminal.

### Files

| File | Purpose |
|------|---------|
| `src/editor/inline_completion/inline_completion_manager.py` | Orchestrator: debounce, keystroke handling, lifecycle |
| `src/editor/inline_completion/inline_completion_provider.py` | API request, prompt building, caching, FIM/chat fallback |
| `src/editor/inline_completion/ghost_text_renderer.py` | GtkSnapshot visual overlay, accept/dismiss, streaming |
| `src/editor/inline_completion/context_gatherer.py` | Context extraction: prefix/suffix, cross-file imports |
| `src/editor/inline_completion/copilot_api.py` | HTTP client, OAuth token exchange, FIM endpoint |

### Complete lifecycle

```
User types → on_buffer_changed
    ↓
Record keystroke → adaptive debounce (250–800ms)
    ↓
gather_context(editor_tab) → CompletionContext:
    - prefix (last 1500 chars before cursor)
    - suffix (first 500 chars after cursor)
    - file_path, language, cursor_line/col
    - related_snippets from open tabs / imports
    ↓
Check CompletionCache (LRU, 50 entries, keyed by context hash)
    ↓  MISS
CopilotAPI.complete_fim() → HTTP POST to api.githubcopilot.com/v1/completions
    ↓
_clean_response() → strip markdown fences, FIM cursor, prose
_deduplicate() → remove lines already in prefix/suffix
    ↓
Cache result → GLib.idle_add() back to main thread
    ↓
GhostTextRenderer.show(text)
    - Render as visual overlay via GtkSnapshot
    - Never modifies the buffer (preserves undo stack)
    ↓
User presses Tab → insert into buffer as undoable action
User presses Esc → dismiss ghost text
```

### Context gathering

`CompletionContext` dataclass built by `context_gatherer.py`:

| Field | Source | Size limit |
|-------|--------|------------|
| `prefix` | Text before cursor | Last 1500 chars |
| `suffix` | Text after cursor | First 500 chars |
| `file_path` | Active editor tab | — |
| `language` | GtkSourceView language ID | — |
| `cursor_line` / `cursor_col` | Buffer cursor position | 1-indexed |
| `related_snippets` | Cross-file context | Max 10 snippets |

**Related snippets** gathered from:
1. Open editor tabs (first 300 chars of each)
2. Import statements (parse imports, read snippet from resolved file)
3. Max 10 snippets, tagged with relevance: `open_tab`, `import`, `same_dir`

### Authentication

1. Read OAuth token from `~/.config/github-copilot/apps.json`
2. Exchange for session token via `POST https://api.github.com/copilot_internal/v2/token`
3. Session token cached in memory; refreshed 60s before expiry
4. Bearer token sent in `Authorization` header

### FIM system prompt

```
You are a code completion engine embedded in a code editor.
Output ONLY the code that should be inserted at █.
- Output raw code ONLY — no markdown, explanation, commentary
- Never describe or review the code
- If █ is in a comment, complete naturally
- Do NOT repeat existing code
- Output NOTHING if no meaningful completion
```

### Ghost text rendering

`GhostTextRenderer` — visual-only overlay via GtkSnapshot:

- **Never modifies the buffer** — drawing happens in the view's snapshot method
- **Preserves undo stack** — accepted text inserted via `buffer.begin_user_action()`
- **Multi-line support** — first line at cursor position, subsequent lines at left margin
- **Styling:** theme's `fg_dim` colour, 55% alpha, italic

Rendering order in `EditorTab.do_snapshot()`:
1. Parent `GtkSource.View.do_snapshot()`
2. Indent guides
3. Gutter diff indicators
4. Colour swatches
5. **Ghost text overlay**
6. Custom block cursor

### Keybindings

| Keybinding | Action |
|------------|--------|
| `Tab` | Accept full completion |
| `Escape` | Dismiss |
| `Cmd+Right` / `Ctrl+Right` | Accept next word |
| `Cmd+Down` / `Ctrl+Down` | Accept next line |
| `Alt+]` | Cycle to next suggestion |
| `Alt+[` | Cycle to previous suggestion |
| `Alt+\` | Manual trigger |
| Any other key | Dismiss current ghost text |

### Safety mechanisms

| Mechanism | Details |
|-----------|---------|
| Adaptive debounce | 250ms–800ms based on typing speed |
| API retry cooldown | 30s cooldown after failure |
| LRU cache | 50-entry cache keyed by MD5 of prefix + suffix + language |
| Max tokens | 500 tokens per request |
| Request cancellation | Pending requests cancelled when new keystrokes arrive |
| Prose filtering | Rejects responses with prose indicators (high word length, space ratios) |
| Trailing whitespace heuristic | Skips trigger if line ends with trailing whitespace after a "complete" character |

---

## Debug Logging

`src/shared/ai_debug_log.py` — append-only structured logging to `~/.zen_ide/ai_debug_log.txt`.

```python
from shared.ai_debug_log import ai_log

ai_log.request("anthropic", "claude-sonnet-4", msg_count=5)
ai_log.chunk(234)                                # Bytes received
ai_log.complete(1.8, 4096)                       # Duration, response length
ai_log.error("HTTP 500: internal …")
ai_log.tool_use("read_file", {"file_path": "…"})
ai_log.tool_result("read_file", ok=True, chars=1200)
ai_log.event("stale_watchdog", "cancelled after 90s")
```

- Automatic rotation at 2 MB
- Thread-safe append
- Lightweight (always on)
- Inline completions logged with `[IC]` prefix

---

## Class Hierarchy

```
ZenIDE (main window)
├── WindowStateMixin
│   ├── _ai_enabled (setting: ai.is_enabled)
│   ├── _get_editor_context() → dict
│   └── ai_chat: AITerminalStack
│
├── AITerminalStack (Gtk.Box)
│   ├── _views: list[AITerminalView]
│   ├── _active_idx: int
│   ├── save_state() → list[dict]
│   └── Proxies: spawn_shell, focus_input, is_processing, stop_ai
│
├── AITerminalView (TerminalView + JogWheelScrollbarMixin)
│   ├── terminal: Vte.Terminal (PTY)
│   ├── _current_provider / _current_model (per-tab)
│   ├── _session_id (for resume)
│   ├── spawn_shell(), stop_ai(), is_processing()
│   └── AITerminalHeader, TabTitleInferrer
│
├── CLIManager (singleton)
│   ├── _providers: dict[str, CLIProvider]
│   │   ├── ClaudeCLI
│   │   └── CopilotCLI
│   ├── availability(), resolve(), fetch_models()
│   └── build_argv(), list_sessions()
│
├── EditorTab
│   └── InlineCompletionManager
│       ├── _provider: InlineCompletionProvider
│       │   ├── _api: CopilotAPI
│       │   └── _cache: CompletionCache (LRU)
│       ├── _renderer: GhostTextRenderer
│       └── _debounce: AdaptiveDebounce
│
└── IdeStateWriter
    └── write_ide_state() → ~/.zen_ide/ide_state.json
```

---

## Window Integration

### Auto-start

On IDE open, `window_state._deferred_init_panels()` calls `ai_chat.spawn_shell()` immediately after the regular terminal. The CLI launches without user action.

### Window module interface

`AITerminalStack` / `AITerminalView` implement the interface expected by window modules:

| Method | Called by | Behaviour |
|--------|-----------|-----------|
| `spawn_shell()` | `window_state._deferred_init_panels` | Launch CLI binary in VTE |
| `focus_input()` | `window_actions._on_focus_ai_chat` | `terminal.grab_focus()` |
| `is_processing()` | `window_actions._on_stop_ai` | Always `False` (CLI manages its own state) |
| `stop_ai()` | `window_actions._on_stop_ai` | Sends `Ctrl+C` (`\x03`) to VTE |
| `cleanup()` | `window_state` on close | Inherited `TerminalShellMixin.cleanup()` |
| `update_font()` | `window_fonts` on font change | Refreshes VTE font + header label font |
| `change_directory(path)` | window on workspace change | Sets working directory for all tabs |
| `save_state()` | `window_state` on close | Returns tab list for persistence |

### Startup sequence

1. Create `AITerminalStack` with optional `saved_tabs`
2. Call `ai_chat.spawn_shell()` → resolves CLI binary → spawns in VTE with `--resume` if saved session
3. Detect new session IDs by mtime after 4s
4. Restore tab selection from saved state

### On exit

1. `ai_chat.save_state()` → returns tab list (title, provider, session_id, active_idx)
2. Persist to state file
3. `ai_chat.cleanup()` → kills all running CLIs

---

## Settings

| Key | Values | Default | Description |
|-----|--------|---------|-------------|
| `ai.is_enabled` | `true` / `false` | `true` | Master toggle — hides panel when `false` |
| `ai.provider` | `""`, `"claude_cli"`, `"copilot_cli"` | `""` (auto) | Active CLI; empty = auto-detect |
| `ai.yolo_mode` | `true` / `false` | `true` | Skip tool permission prompts |
| `ai.show_inline_suggestions` | `true` / `false` | `true` | Ghost-text inline completions |
| `ai.inline_completion.trigger_delay_ms` | number | `500` | Debounce delay for inline suggestions |
| `ai.inline_completion.model` | string | `gpt-4.1-mini` | Model for inline completions |
| `behavior.ai_chat_on_vertical_stack` | `true` / `false` | `false` | Vertical stack vs horizontal tab layout |
| `fonts.ai_chat` | object | `{"family": "Source Code Pro", "size": 16}` | Font for AI chat panel |

---

## Deleted Files

The following files from the old HTTP-streaming system have been deleted:

| File | Was |
|------|-----|
| `ai_chat_tabs.py` | Multi-session tab management |
| `ai_chat_terminal.py` | Core chat view with HTTP streaming and tool loop |
| `anthropic_http_provider.py` | Anthropic Messages API provider |
| `copilot_http_provider.py` | Copilot Chat API provider |
| `chat_canvas.py` | GtkSnapshot-based DrawingArea renderer |
| `ansi_buffer.py` | ANSI escape code parser |
| `terminal_markdown_renderer.py` | Streaming markdown → ANSI converter |
| `context_injector.py` | Workspace context injection for system prompt |
| `context_truncation.py` | Conversation truncation to reduce tokens |
| `tool_definitions.py` | Provider-agnostic tool schemas |
| `tool_executor.py` | Tool call execution (file I/O, shell) |
| `block_cursor_text_view.py` | Input text view with block cursor |
| `dock_badge.py` | macOS dock notification badge |
| `markdown_formatter.py` | GtkTextBuffer markdown formatting |
| `api_key_setup_popup.py` | API key configuration popup |

These are no longer needed because the CLI tools handle all of this natively.

---

## Superseded Documentation

The following docs describe the old HTTP-streaming system and are **no longer accurate**:

- `2026_01_22_ai_strategy.md` — old HTTP-only architecture, tool use, context truncation
- `2026_01_25_ai_setup_guide.md` — old API key setup (no longer HTTP-based)
- `2026_03_15_ai_chat_architecture.md` — old component map (16 modules, ~8K LOC)
- `2026_03_07_ai_chat_scroll_stability_plan.md` — old ChatCanvas scroll issues
- `2026_03_10_ai_chat_debug_checklist.md` — old rendering pipeline debugging
- `2026_03_14_ai_chat_reactiveness.md` — old streaming latency improvements
- `2026_03_15_ai_chat_view_analysis.md` — old bug/regression catalog
- `2026_03_15_ai_chat_view_fix_plan.md` — old fix plan
- `2026_03_17_sleep_on_ai_completion.md` — referenced old `ai_chat_terminal.py`

The inline completion doc (`2026_03_04_ai_inline_completion.md`) remains partially relevant — the inline completion system still uses the Copilot HTTP API, but references to CLI providers in that doc are outdated.
