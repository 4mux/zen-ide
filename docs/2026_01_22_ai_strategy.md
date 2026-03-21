# Zen AI Strategy

**Created_at:** 2026-01-22
**Updated_at:** 2026-03-21
**Status:** Superseded
**Goal:** Document how Zen IDE AI chat works — HTTP providers, tool use, safety mechanisms, rendering
**Scope:** `src/ai/`

> **Superseded:** This document describes the old HTTP-streaming architecture which has been fully replaced by the VTE-based AI Terminal. See [2026_03_21_ai_terminal.md](2026_03_21_ai_terminal.md) for the current system. The HTTP providers, custom rendering pipeline, tool executor, and context management described below have all been deleted. The inline completion system (Copilot HTTP API for ghost-text) is still active and documented in the new doc.

---

## Overview (Historical)

Zen IDE's AI chat was an **agentic coding assistant** built into the IDE. It communicated with AI providers via **direct HTTP API calls** (no CLI tools, no subprocesses, no Node.js). The assistant could read/write/edit files, search code, and run shell commands through a tool-use loop.

### Key Design Decisions

- **HTTP-only** — All providers use direct HTTP streaming. No subprocess spawning, no CLI wrappers.
- **Tool use** — The AI has 6 tools (read_file, write_file, edit_file, list_files, search_files, run_command) and executes them in an agentic loop until the task is complete.
- **Yolo mode** — By default, there is no tool call limit (up to a configurable safety ceiling). The AI continues until done.
- **Multiple parallel sessions** — Each chat tab is an independent session with its own history, provider, and model.
- **ChatCanvas rendering** — AI output is rendered on a DrawingArea (GtkSnapshot), not a VTE terminal. Markdown is converted to ANSI-styled text.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Zen IDE                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │                    AI Chat Tabs                            │   │
│  │  Multiple independent chat sessions (vertical stack)      │   │
│  │  Each session: own history, own provider, own model        │   │
│  └───────────────────────────┬───────────────────────────────┘   │
│                              │                                    │
│                              ▼                                    │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │              AIChatTerminalView (per session)              │   │
│  │                                                            │   │
│  │  1. Builds system prompt (workspace dirs, focused file)    │   │
│  │  2. Builds api_messages[] from conversation history        │   │
│  │  3. Context truncation (size cap + tool result trimming)   │   │
│  │  4. Sends to HTTP provider in background thread            │   │
│  │  5. Streams chunks → markdown renderer → ChatCanvas        │   │
│  │  6. On tool_use → executes tool → sends results → loop     │   │
│  └───────────────────────────┬───────────────────────────────┘   │
│                              │                                    │
│              ┌───────────────┴───────────────┐                    │
│              ▼                               ▼                    │
│  ┌────────────────┐              ┌───────────────┐               │
│  │  Anthropic API  │              │  Copilot API  │               │
│  │  (Messages)     │              │  (Chat)       │               │
│  └────────────────┘              └───────────────┘               │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

## How a Message Flows

### 1. User sends a message

`_on_send()` appends `{"role": "user", "content": message}` to `self.messages` and calls `_run_ai_http(message)`.

### 2. System prompt is built

`_run_ai_http()` constructs the system prompt from:

| Source | Content |
|--------|---------|
| Static | "You are a coding assistant integrated into Zen IDE..." |
| `get_workspace_folders()` | Working directories (e.g. `/path/to/project-a, /path/to/project-b`) |
| `get_current_file()` | Currently focused file path in the editor |
| Yolo mode | "You have UNLIMITED tool calls" or "You have a limit of 25 tool calls" |

**Note:** The system prompt does NOT include file contents, terminal output, or editor content. The AI discovers context by using its tools (read_file, search_files, etc.).

### 3. Conversation history is sent as structured API messages

```python
api_messages = []
for msg in self.messages[:-1]:  # All previous messages
    api_messages.append({"role": role, "content": content})
api_messages.append({"role": "user", "content": current_message})
```

Each message is a properly structured `{"role", "content"}` dict — no flattened text, no context duplication.

### 4. Context injection

On the **initial request** (not tool-use continuations), the system prompt is enriched with workspace context gathered by `context_injector.py`. This gives the model the same starting knowledge that VS Code provides to Copilot — avoiding 3-5 tool calls just to orient itself.

Injected context (each individually configurable via `ai.context_injection.*`):

| Source | Setting | Content | Max size |
|--------|---------|---------|----------|
| Current file | `current_file` | Full file contents | 20K chars |
| Open tabs | `open_tabs` | List of open editor file paths | 2K chars |
| Git info | `git_info` | Branch, modified files, `git diff --stat` | 10K chars |
| Diagnostics | `diagnostics` | Current errors and warnings (up to 30) | 3K chars |
| Workspace tree | `workspace_tree` | Directory listing (depth 2) | 5K chars |

**Cost optimisation**: Context injection runs only on the first API request per user message. Tool-use continuation rounds and auto-continue rounds skip it — the model already has the context from round 1.

### 5. Context truncation

Before sending, the conversation passes through `context_truncation.truncate_conversation()`. This is applied on **both** the initial `send_message_stream()` call and every subsequent `continue_with_tool_results()` call — identically for Anthropic and Copilot providers.

The truncation strategy (see [Context Truncation](#context-truncation) below) shortens tool results in the middle of the conversation and enforces a hard size cap, preventing token costs from growing quadratically with conversation length.

### 6. HTTP provider streams the response

The provider (e.g. `AnthropicHTTPProvider`) starts a background thread that:
- POSTs to the API with `stream: True`
- Reads SSE (Server-Sent Events) line by line
- Calls `on_chunk(text)` for each text/thinking delta → scheduled on GTK main thread via `GLib.idle_add()`
- Calls `on_tool_use(tool_calls, text)` if the model requests tool execution
- Calls `on_complete(full_text)` or `on_error(msg)` when done

### 6. Tool use loop (agentic)

When the model requests tools:

1. `_on_tool_use()` receives the tool call list on the main thread
2. Each tool is executed by `ToolExecutor` in a **background thread** (subprocess, file I/O)
3. Results are dispatched back to the main thread via `GLib.idle_add()`
4. `provider.continue_with_tool_results()` sends results back to the API
5. The model generates more text or requests more tools — repeat until `on_complete`

In **yolo mode** (default), the loop runs up to `ai.max_tool_rounds` (default 200). In non-yolo mode, the limit is 25 tool calls. When the limit is reached, the user can send "continue" to resume.

### 7. Rendering pipeline

```
Stream chunk (text)
  → _render_stream_chunk()
    → Split thinking/content markers
    → Thinking: throttled, collapsible block
    → Content: _md_renderer.feed(text) → ANSI-formatted string
      → ChatCanvas.feed(ansi_text) → AnsiBuffer → DrawingArea
```

The `TerminalMarkdownRenderer` converts markdown to ANSI escape codes (bold, italic, colors, code blocks with syntax highlighting via Pygments). The `ChatCanvas` (a `Gtk.DrawingArea`) renders styled text using `GtkSnapshot`.

---

## AI Providers

Both providers implement the same interface: `send_message_stream()`, `continue_with_tool_results()`, `stop()`, `get_available_models()`.

| Provider | Class | API Endpoint | Auth |
|----------|-------|-------------|------|
| Copilot | `CopilotHTTPProvider` | `api.githubcopilot.com/chat/completions` | GitHub OAuth → session token exchange |
| Anthropic | `AnthropicHTTPProvider` | `api.anthropic.com/v1/messages` | API key (`ANTHROPIC_API_KEY` or `~/.zen_ide/api_keys.json`) |

### Provider auto-detection

On startup, providers are checked for availability (API key present). The priority is: Copilot > Anthropic. Users can override via settings or the UI dropdown.

### Model discovery

Each provider fetches models from its API or uses a curated known-good list. Models are never hardcoded in the main application.

### Anthropic provider (`anthropic_http_provider.py`)

- **API**: `POST https://api.anthropic.com/v1/messages` with `stream: True`
- **Auth**: API key via `ANTHROPIC_API_KEY` env var or `~/.zen_ide/api_keys.json` → `{"anthropic": "sk-ant-..."}`
- **SSE events**: `content_block_start`, `content_block_delta` (text, thinking, tool input JSON), `content_block_stop`, `message_delta` (stop reason), `error`
- **Tool use format**: Anthropic-native — tool calls in assistant `content` blocks (type `tool_use`), results in user `content` blocks (type `tool_result`)
- **Extended thinking**: Enabled for Opus/Sonnet models with a budget of `min(max_tokens, 10000)` tokens. Thinking text is prefixed with a zero-width space marker; content text with a zero-width non-joiner marker.
- **Default model**: `claude-sonnet-4-20250514`

### Copilot provider (`copilot_http_provider.py`)

- **API**: `POST {api_base_url}/chat/completions` with `stream: True` (OpenAI-compatible)
- **Auth**: Three-step — (1) find GitHub token from `~/.config/github-copilot/apps.json`, `~/.zen_ide/api_keys.json`, or `GITHUB_TOKEN` env; (2) exchange for session token via `api.github.com/copilot_internal/v2/token`; (3) use session token as Bearer auth
- **Session token caching**: Cached at the class level with expiry tracking. Refreshed 60s before expiry. Lock-based stampede prevention ensures only one thread refreshes at a time. 5s cooldown on failure to avoid hammering the token endpoint.
- **SSE events**: OpenAI-compatible `choices[0].delta` with `content`, `tool_calls`, `finish_reason`
- **Tool use format**: OpenAI-compatible — `tool_calls` array in assistant messages, `role: "tool"` for results
- **OAuth device flow**: Built-in GitHub OAuth device flow for first-time auth — `start_device_flow()` + `poll_device_flow()` with slow-down handling
- **Default model**: `claude-sonnet-4.6`

---

## Safety Mechanisms

### Context Truncation

Implemented in `context_truncation.py`, applied identically by both providers on every API call (initial send and tool-use continuations).

**Strategy** (applied in order):

1. **Protected zones** — System prompt (index 0) and first user message (index 1) are always kept verbatim. The last 8 messages (`_KEEP_RECENT`) are kept verbatim for coherent continuation.
2. **Tool result trimming** — Messages in the middle zone have their tool result content truncated to 200 chars with a `[...truncated for brevity]` marker. This covers `role: "tool"` messages (Copilot/OpenAI format) and `type: "tool_result"` blocks within `role: "user"` messages (Anthropic format).
3. **Hard size cap** — If the total serialised conversation still exceeds `ai.max_context_chars` (default 120,000 chars, ~30K tokens), the oldest middle messages are progressively **dropped** and replaced with a single placeholder: `[Earlier conversation history was truncated to stay within context limits]`.

**When truncation is skipped**: Conversations shorter than 8 messages skip step 1–2 but still enforce the hard size cap (step 3).

### Retry Logic

#### Anthropic provider

| Error type | Max retries | Backoff | Details |
|------------|-------------|---------|---------|
| HTTP 429 (rate limit) | 3 | Exponential: 10s, 20s, 40s (or `retry-after` header) | Resets stream state between retries. User sees `[Rate limited — retrying in Ns...]` |
| Transient (SSL, connection reset, broken pipe, timeout) | 2 | Exponential: 2s, 4s | Detected via `_is_transient_error()`. Applies both during connection and mid-stream |
| HTTP 401 | 0 | — | "Invalid API key" error, no retry |
| HTTP 529 | 0 | — | "API overloaded" error, no retry |
| Other HTTP errors | 0 | — | Logged and surfaced to user |

All retry loops check `_stop_requested` in 1-second sleep increments so the user can cancel at any time.

#### Copilot provider

| Error type | Max retries | Details |
|------------|-------------|---------|
| HTTP 401 | 0 | Clears cached session token, surfaces error |
| HTTP 403 | 0 | "Copilot not enabled on account" |
| HTTP 429 | 0 | Surfaces rate limit error directly |
| All other | 0 | Single attempt, error surfaced to user |

The Copilot provider does not retry HTTP errors. Transient failures surface immediately. This is intentional — Copilot's rate limits are per-seat, and retrying could waste the user's quota.

### Timeout Protection

| Timeout | Value | Location | Purpose |
|---------|-------|----------|---------|
| Socket read timeout | 30s | Both providers | Prevents `readline()` from blocking forever. On timeout, the loop checks `_stop_requested` and continues waiting |
| Connection timeout | 300s (5min) | Both providers | `urlopen(timeout=300)` — covers TCP handshake and TLS negotiation |
| Stale request watchdog | 90s | `ai_chat_terminal.py` | If no data arrives for 90s, the request is cancelled. Runs on main thread via `GLib.timeout_add()` |
| Idle stream timeout | 300s (5min) | Copilot provider only | If the streaming connection receives no data for 5 minutes, it aborts with `idle_timeout` |

### Tool Use Round Limits

| Mode | Limit | Setting | Behaviour at limit |
|------|-------|---------|-------------------|
| Yolo mode (default) | 50 | `ai.max_tool_rounds` | `[Safety limit of N tool rounds reached — send 'continue' to resume]` |
| Non-yolo mode | 25 | `_MAX_TOOL_ITERATIONS` (hardcoded) | `[Tool use limit reached — send 'continue' to resume]` |

The counter (`_tool_iteration_count`) increments by the number of tool calls per round, not the number of API round-trips. This means a single round with 3 parallel tool calls counts as 3.

### Auto-Continue Guard

When the model falsely claims it hit a tool limit in yolo mode (a hallucination), `_auto_continue()` re-sends the conversation with a continuation prompt. This is capped at **3 consecutive auto-continues** (`_MAX_AUTO_CONTINUES`). If the model keeps hallucinating limits after 3 retries, it falls through to normal completion.

### Abnormal Stream Detection

Both providers detect abnormal stream ends: if the stream closes with no `stop_reason`/`finish_reason`, no text response, and no tool calls, the error is surfaced as `"Connection lost — server stopped responding"` rather than silently failing.

---

## Inline Completion Safety

The inline completion system (`src/editor/inline_completion/`) has its own safeguards:

| Mechanism | Details |
|-----------|---------|
| **Adaptive debounce** | 250ms–800ms delay based on typing speed. Fast typing → longer delay (user hasn't paused). Slow typing → shorter delay (user is thinking). |
| **API retry cooldown** | 30s cooldown after API failure before retrying (`_API_RETRY_COOLDOWN_S`) |
| **LRU cache** | 50-entry cache keyed by MD5 of prefix[-200:] + suffix[:100] + language. Prevents duplicate requests for the same context. |
| **Max tokens** | 500 tokens per completion request |
| **Request cancellation** | Pending requests cancelled via `GLib.source_remove()` when new keystrokes arrive |

---

## Settings Reference

| Setting | Default | Purpose |
|---------|---------|---------|
| `ai.provider` | auto-detect | `"copilot_api"` or `"anthropic_api"` |
| `ai.model` | provider default | Model name (per provider) |
| `ai.yolo_mode` | `True` | Unlimited tool calls (up to safety ceiling) |
| `ai.max_tool_rounds` | `50` | Hard ceiling on tool-use rounds in yolo mode |
| `ai.context_truncation` | `True` | Enable conversation truncation to reduce token cost |
| `ai.max_context_chars` | `120000` | Hard cap on total serialised conversation size (chars). ~30K tokens. |
| `ai.context_injection.current_file` | `True` | Include current file contents in system prompt |
| `ai.context_injection.open_tabs` | `True` | Include list of open editor tabs in system prompt |
| `ai.context_injection.git_info` | `True` | Include git branch, status, and diff stat in system prompt |
| `ai.context_injection.diagnostics` | `True` | Include current errors/warnings in system prompt |
| `ai.context_injection.workspace_tree` | `False` | Include workspace directory structure (disabled — can be large) |
| `ai.show_inline_suggestions` | `True` | Enable inline ghost-text completions |
| `ai.auto_scroll_on_output` | `True` | Auto-scroll during streaming |
| `ai.inline_completion.model` | `gpt-4.1` | Model for inline completions |
| `behavior.ai_chat_on_vertical_stack` | `False` | Vertical vs horizontal tab layout |
| `wide_cursor` | `False` | Block cursor in input field |
| `cursor_blink` | `False` | Cursor blink animation |

---

## Tools

Defined in `tool_definitions.py`, executed by `tool_executor.py`:

| Tool | Description |
|------|-------------|
| `read_file` | Read file contents (max 512 KB) |
| `write_file` | Create or overwrite a file |
| `edit_file` | Find-and-replace a unique text match in a file |
| `list_files` | Glob pattern file discovery |
| `search_files` | Regex search in file contents (uses ripgrep/grep) |
| `run_command` | Run a shell command (30s timeout) |

All paths are resolved relative to the workspace root. Path traversal outside the workspace is blocked.

Tool definitions are provider-agnostic and converted to the appropriate format at call time:
- `tools_for_anthropic()` — Anthropic `input_schema` format
- `tools_for_copilot()` — OpenAI `function.parameters` format

---

## Chat Persistence

Each chat session is saved to `~/.zen_ide/ai_chat/chat_{session_id}.json`:

```json
[
  {"role": "user", "content": "Fix the bug in auth.py"},
  {"role": "assistant", "content": "I'll look at the file...", "thinking": "Let me read..."},
  ...
]
```

Sessions are restored on IDE restart. Maximum 100 messages per session.

---

## Auto-Scroll

During streaming, auto-scroll keeps the viewport at the bottom. If the user scrolls away manually, auto-scroll pauses (showing a "Jump to bottom" indicator). Scrolling back near the bottom re-engages auto-scroll.

## Thinking Blocks

For Anthropic models that support extended thinking (Opus, Sonnet), thinking text is:
- Displayed in a dim, collapsible block
- Throttled at 50ms intervals to avoid saturating the main loop
- Collapsed to a single "Thinking..." summary line when content text begins

## Inline Autosuggestion

Separate from the chat system. Provides ghost-text completions in the editor:
- Trigger: after typing pause (adaptive debounce, 250–800ms)
- Provider: Copilot API (FIM endpoint first, chat fallback)
- Accept: Tab key
- Dismiss: Escape key

See `src/editor/inline_completion/` for details.

---

## Files

| File | Purpose |
|------|---------|
| `src/ai/__init__.py` | Module init with lazy imports |
| `src/ai/ai_chat_tabs.py` | Multi-session tab management (vertical stack) |
| `src/ai/ai_chat_terminal.py` | Core chat view: prompt building, HTTP streaming, tool loop, rendering |
| `src/ai/anthropic_http_provider.py` | Anthropic Messages API — streaming, thinking blocks, tool use, retries |
| `src/ai/copilot_http_provider.py` | GitHub Copilot Chat API — OAuth, session tokens, streaming, tool use |
| `src/ai/context_truncation.py` | Conversation truncation — tool result trimming + hard size cap |
| `src/ai/context_injector.py` | Workspace context injection — gathers current file, open tabs, git, diagnostics for system prompt |
| `src/ai/tool_definitions.py` | Provider-agnostic tool schemas with Anthropic/OpenAI converters |
| `src/ai/tool_executor.py` | Executes tool calls (file I/O, grep, shell commands) |
| `src/ai/chat_canvas.py` | DrawingArea renderer for ANSI-styled text (GtkSnapshot) |
| `src/ai/ansi_buffer.py` | Parses ANSI escape codes into styled line spans |
| `src/ai/terminal_markdown_renderer.py` | Streaming markdown → ANSI converter (code highlighting, tables) |
| `src/ai/tab_title_inferrer.py` | Generates short chat tab titles from first user message |
| `src/ai/spinner.py` | Braille-character spinner for loading state |
| `src/ai/block_cursor_text_view.py` | Input text view with block cursor |
| `src/ai/dock_badge.py` | Notification badge for the AI chat dock button |
| `src/ai/markdown_formatter.py` | Markdown formatting utilities |
