# AI Terminal

**Created_at:** 2026-03-21
**Updated_at:** 2026-03-21
**Status:** Active
**Goal:** Document the current AI system — VTE-based terminal running CLI tools, multi-tab sessions, inline completions
**Scope:** `src/ai/`, `src/editor/inline_completion/`, `src/popups/ai_settings_popup.py`

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

## Inline Completions (Separate System)

Inline ghost-text completions use the **Copilot HTTP API** directly — completely independent of the AI Terminal.

### Location

`src/editor/inline_completion/copilot_api.py`

### How it works

1. Reads OAuth token from `~/.config/github-copilot/apps.json`
2. Exchanges for session token via GitHub API
3. Sends FIM (fill-in-middle) requests to `api.githubcopilot.com/v1/completions`

### Key methods

- `complete_fim(prefix, suffix, language, file_path)` — single completion
- `complete_fim_multi(..., n=3)` — alternative suggestions
- `complete_stream(prompt, ..., on_chunk, on_done)` — streaming completions

### Safety mechanisms

| Mechanism | Details |
|-----------|---------|
| Adaptive debounce | 250ms–800ms based on typing speed |
| API retry cooldown | 30s cooldown after failure |
| LRU cache | 50-entry cache keyed by MD5 of prefix + suffix + language |
| Max tokens | 500 tokens per request |
| Request cancellation | Pending requests cancelled when new keystrokes arrive |

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
