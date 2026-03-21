# AI Chat System Architecture

**Created_at:** 2026-03-15
**Updated_at:** 2026-03-21
**Status:** Superseded — see [AI Terminal](2026_03_21_ai_terminal.md) for the current system
**Goal:** Document the full architecture, data flow, and component interactions of the AI chat system
**Scope:** `src/ai/` (all 16 modules, ~8,040 LOC)

> **Superseded:** This entire document describes the old AI chat system which has been replaced by the VTE-based AI Terminal. All components described below (ChatCanvas, AnsiBuffer, BlockCursorTextView, AIChatTerminalView, CLI providers, PTY provider, system tag stripper, process tracker) have been deleted. See [2026_03_21_ai_terminal.md](2026_03_21_ai_terminal.md) for the current architecture.

---

## Overview

The AI chat system provides a multi-session, streaming chat interface that connects to external AI CLIs (Claude CLI, GitHub Copilot CLI). It renders AI responses in real-time with markdown formatting, syntax highlighting, and ANSI colors using a custom `GtkSnapshot`-based canvas.

**Total**: 16 Python modules, ~8,040 lines of code.

---

## Component Map

| Layer | Files | Purpose |
|-------|-------|---------|
| **UI** | `ai_chat_tabs.py`, `ai_chat_terminal.py`, `chat_canvas.py`, `block_cursor_text_view.py` | Session management, input, rendering |
| **Providers** | `claude_cli_provider.py`, `copilot_cli_provider.py`, `pty_cli_provider.py` | CLI abstraction, process spawning, JSON streaming |
| **Rendering** | `terminal_markdown_renderer.py`, `ansi_buffer.py`, `markdown_formatter.py` | Markdown→ANSI conversion, ANSI parsing, GtkTextBuffer formatting |
| **Utilities** | `spinner.py`, `system_tag_stripper.py`, `tab_title_inferrer.py`, `dock_badge.py`, `ai_process_tracker.py` | Animation, tag cleanup, title generation, macOS badge, PID tracking |
| **Entry** | `__init__.py` | Lazy import facade |

---

## Data Flow

### User Message → Displayed Response

```
User types in BlockCursorTextView → Enter key
    ↓
AIChatTerminalView._on_key_pressed() → _on_send()
    ↓
Extract text, store in self.messages[], persist to ~/.zen_ide/chats/{session}.json
    ↓
_build_prompt_with_context() → inject workspace path, focused file
    ↓
_run_ai_cli() → spawn CLI subprocess (Claude JSON stream or Copilot PTY)
    ↓
Stream chunks arrive:
    Claude: _handle_claude_output() parses stream-json events
    Copilot: _handle_copilot_output() processes PTY output
    ↓
SystemTagStripper.feed() → removes XML system tags (<reminder>, <sql_tables>, etc.)
    ↓
TerminalMarkdownRenderer.feed() → converts markdown to ANSI-escaped text
    ↓
_on_response_chunk() → ChatCanvas.feed() / feed_immediate()
    ↓
ChatCanvas schedules GLib.idle_add redraw (or immediate for first token)
    ↓
AnsiBuffer.feed() → parses ANSI codes into StyledSpan objects
    ↓
do_snapshot() → GtkSnapshot renders styled spans with Pango layouts
```

---

## Provider System

Three provider implementations, each with different trade-offs:

### ClaudeCLIProvider (`claude_cli_provider.py`, 473 LOC)

- **Interface**: JSON streaming via `--output-format stream-json`
- **Events**: `content_block_delta`, `tool_use`, `thinking_delta`
- **Process**: `subprocess.Popen` with `fcntl` non-blocking I/O
- **Model discovery**: Parses `claude --help` output dynamically
- **Tool formatting**: Maps tool names (Read, Write, Bash, Grep, etc.) to user-friendly display
- **Hidden tools**: `report_intent`, `fetch_copilot_cli_documentation` suppressed from display
- **Timeout**: 5 minutes no-data triggers timeout error
- **Environment**: Sets `NO_COLOR=1` to get clean JSON

### CopilotCLIProvider (`copilot_cli_provider.py`, 145 LOC)

- **Scope**: CLI path detection and model list parsing only
- **Model discovery**: Regex extraction from `copilot --help` choices
- **Search paths**: NVM directories, homebrew, `which copilot`

### PTYCLIProvider (`pty_cli_provider.py`, 334 LOC)

- **Interface**: Real pseudo-terminal via `pty.openpty()`
- **I/O**: Background thread with `select.select()` polling
- **Filtering**: Strips braille spinners, control chars, ANSI escapes, garbled hex
- **Process**: `os.fork()` + `os.execvpe()` with full environment
- **Cleanup**: SIGTERM → SIGKILL sequence

---

## UI Components

### ChatCanvas (`chat_canvas.py`, 794 LOC)

Custom `Gtk.DrawingArea` that replaces VTE for AI chat output.

- **Buffer**: `AnsiBuffer` holds `list[list[StyledSpan]]` — 2D array of styled text spans
- **Rendering**: `GtkSnapshot` + `Pango.Layout` per line, cached via `_layout_cache`
- **Dirty tracking**: Only invalidates changed lines (`dirty_lines` set)
- **Selection**: `GestureDrag` for text selection, multi-click for word/line
- **Two feed modes**:
  - `feed()` — coalesced via `GLib.idle_add()` (normal streaming)
  - `feed_immediate()` — synchronous redraw (first-token fast path)
- **Non-focusable**: Prevents scroll-to-focus jumps during streaming

### BlockCursorTextView (`block_cursor_text_view.py`, 89 LOC)

`Gtk.TextView` subclass for the chat input field.

- Optional wide (block) cursor via `wide_cursor` setting
- Cursor blink via `cursor_blink` setting with configurable on/off timing
- Hides native caret with CSS `caret-color: transparent`
- Draws block cursor via `shared.block_cursor_draw.draw_block_cursor()`

### AIChatTerminalView (`ai_chat_terminal.py`, 2,614 LOC)

Main chat window — the largest component.

- **State**: messages list, provider/model selection, processing flag, scroll generation
- **Provider switching**: Auto-detects available CLIs, reads `ai.provider` setting
- **Context injection**: Workspace folders, focused file path appended to prompt
- **Scroll preservation**: Generation counter prevents stale operations, 4 retry attempts
- **Message persistence**: JSON files in `~/.zen_ide/chats/{session_id}.json`
- **Chat history**: Maintains last 100 messages per session

### AIChatTabs (`ai_chat_tabs.py`, 1,384 LOC)

Multi-session tab management with two layout modes.

- **Horizontal** (default): Scrollable tab bar + `Gtk.Stack`
- **Vertical stack**: All chats visible, per-pane headers with +/× buttons
- **Tab buttons**: `AITabButton` with spinner animation during processing
- **Theme propagation**: `_on_theme_change()` updates all tabs
- **Dynamic CSS**: Font family/size applied per session

---

## Rendering Pipeline

### SystemTagStripper (`system_tag_stripper.py`, 114 LOC)

Removes XML system tags from streamed AI output before rendering.

- Strips paired tags: `<reminder>...</reminder>`, `<sql_tables>...</sql_tables>`
- Strips self-closing tags: `<br />`
- **Streaming-safe**: Buffers partial tags (e.g., `<remi` could become `<reminder>`)
- **Timeout**: Flushes stale partial tags after 200ms
- **Buffer limit**: 4096 chars max to prevent stalls
- **Blank line collapsing**: Reduces 3+ consecutive newlines to 2

### TerminalMarkdownRenderer (`terminal_markdown_renderer.py`, 741 LOC)

Streaming markdown → ANSI text converter.

- **State machine**: Tracks code blocks, tables, partial lines
- **Code blocks**: Box-drawing borders, Pygments syntax highlighting
- **Tables**: Full box-drawing table rendering with alignment
- **Headers**: ANSI colors from theme (h1, h2, h3)
- **Inline**: Bold, italic, inline code, links via regex
- **Streaming**: Emits partial lines immediately for real-time display
- **Color system**: Theme-aware hex→ANSI 24-bit color conversion

### AnsiBuffer (`ansi_buffer.py`, 306 LOC)

Parses ANSI-escaped text into structured `StyledSpan` objects.

- **SGR support**: Reset, bold, dim, italic, underline, disable variants
- **24-bit color**: Foreground `38;2;R;G;B`, background `48;2;R;G;B`
- **Cursor control**: Carriage return `\r`, clear-to-EOL `\033[K`
- **Dirty tracking**: `dirty_lines` set for incremental repainting
- **Overwrite**: Character-level replacement at cursor position

### MarkdownFormatter (`markdown_formatter.py`, 193 LOC)

Applies markdown formatting to `GtkTextBuffer` (used for non-streaming contexts like DevPad).

- Creates TextTags for bold, italic, code, headers, links
- Theme-aware colors for code blocks and headings
- Inline pattern regex for `**bold**`, `*italic*`, `` `code` ``, `[links](url)`

---

## Process Management

### AiProcessTracker (`ai_process_tracker.py`, 187 LOC)

Tracks and cleans up spawned AI CLI processes.

- **Storage**: PID files in `~/.zen_ide/ai_pids/{instance_pid}.pids`
- **Register/unregister**: `register_pid()`, `unregister_pid()`
- **Cleanup**: `cleanup_all()` kills all PIDs for current IDE instance
- **Orphan cleanup**: `cleanup_orphans()` kills PIDs from dead IDE instances at startup
- **Platform-aware**: macOS uses `libproc` ctypes, Linux reads `/proc/{pid}/comm`
- **Kill strategy**: `os.killpg()` (process group) → fallback `os.kill()` (single PID)

### DockBadge (`dock_badge.py`, 63 LOC)

macOS dock icon badge for active AI process count.

- `set_ai_badge()` increments counter, updates dock
- `clear_ai_badge()` decrements counter, clears badge at zero
- Platform-safe: no-op on non-macOS

---

## Tab Title Inference

### TabTitleInferrer (`tab_title_inferrer.py`, 535 LOC)

Generates meaningful tab titles from the first user message.

- **Semantic patterns**: Regex matching for comparison, debugging, implementation, testing, etc.
- **Word processing**: Removes filler words, applies abbreviations (database→db)
- **Max length**: 30 characters
- **Examples**: "Can you explain lambda functions?" → `"Explain Lambda"`

---

## Utilities

### Spinner (`spinner.py`, 19 LOC)

Braille-dot animation: `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`, cycled every 80ms via `GLib.timeout_add`.

---

## Key Settings

| Setting | Default | Purpose |
|---------|---------|---------|
| `ai.provider` | auto-detect | `"copilot"` or `"claude_cli"` |
| `ai.model` | provider default | Model name (per provider) |
| `ai.yolo_mode` | `True` | Skip tool permission prompts |
| `behavior.ai_chat_on_vertical_stack` | `False` | Vertical vs horizontal tab layout |
| `wide_cursor` | `False` | Block cursor in input field |
| `cursor_blink` | `False` | Cursor blink animation |

---

## Integration Points

- **Keybindings**: AI chat toggle, new session, model switching
- **Workspace context**: `get_workspace_folders()`, `get_current_file()` callbacks
- **Focus management**: `ComponentFocusManager` with `"ai_chat"` component ID
- **Theme system**: Colors propagated via `_on_theme_change()` and `update_colors()`
- **Font settings**: Per-component font config via `get_font_settings("ai_chat")`

---

## File Reference

| File | LOC | Class/Function | Role |
|------|-----|----------------|------|
| `__init__.py` | 49 | `_LAZY_IMPORTS` | Lazy import facade |
| `ai_chat_tabs.py` | 1,384 | `AIChatTabs`, `AITabButton` | Multi-session management |
| `ai_chat_terminal.py` | 2,614 | `AIChatTerminalView` | Main chat window |
| `ai_process_tracker.py` | 187 | `register_pid()`, `cleanup_all()` | PID tracking/cleanup |
| `ansi_buffer.py` | 306 | `AnsiBuffer`, `StyledSpan` | ANSI parsing |
| `block_cursor_text_view.py` | 89 | `BlockCursorTextView` | Input field with block cursor |
| `chat_canvas.py` | 794 | `ChatCanvas` | GtkSnapshot-based output canvas |
| `claude_cli_provider.py` | 473 | `ClaudeCLIProvider` | Claude JSON stream provider |
| `copilot_cli_provider.py` | 145 | `CopilotCLIProvider` | Copilot CLI path/model detection |
| `dock_badge.py` | 63 | `set_ai_badge()`, `clear_ai_badge()` | macOS dock badge |
| `markdown_formatter.py` | 193 | `apply_markdown()` | GtkTextBuffer markdown |
| `pty_cli_provider.py` | 334 | `PTYCLIProvider`, `PTYScreen` | PTY-based CLI execution |
| `spinner.py` | 19 | `Spinner` | Braille animation |
| `system_tag_stripper.py` | 114 | `SystemTagStripper` | XML tag removal |
| `tab_title_inferrer.py` | 535 | `infer_title()` | Smart tab title generation |
| `terminal_markdown_renderer.py` | 741 | `TerminalMarkdownRenderer` | Streaming markdown→ANSI |
