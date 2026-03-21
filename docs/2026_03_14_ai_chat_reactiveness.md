# AI Chat Reactiveness Improvement Plan

**Created_at:** 2026-03-14  
**Updated_at:** 2026-03-15  
**Status:** Superseded — custom rendering replaced by VTE terminal, see [2026_03_21_ai_terminal.md](2026_03_21_ai_terminal.md)
**Goal:** Reduce perceived and actual latency in AI chat streaming to match terminal/CLI responsiveness
**Scope:** `src/ai/ai_chat_terminal.py`, `src/ai/chat_canvas.py`, `src/ai/terminal_markdown_renderer.py`, `src/ai/system_tag_stripper.py`, `src/ai/ansi_buffer.py`  

---

## Problem

The AI chat in Zen IDE feels noticeably slower than using the same AI providers via the terminal or Copilot CLI. Two specific observations:

1. **Dead air during thinking** — the CLI shows thinking text streaming in real time; Zen shows a spinner with no visible progress.
2. **Slower first visible token** — the CLI writes directly to the terminal emulator with zero overhead; Zen routes output through a 3-stage filter chain (tag stripping → markdown rendering → ANSI buffer → ChatCanvas DrawingArea), each adding latency.

---

## Current Architecture

```
PTY Output (8192 bytes, polled every 16ms)
  → SystemTagStripper.feed()      strips XML tags, buffers partials (up to 64KB)
  → TerminalMarkdownRenderer.feed()  markdown → ANSI, buffers code blocks & tables
  → ChatCanvas.feed()             ANSI → StyledSpans, GLib.idle_add redraw
  → ChatCanvas.do_snapshot()      GtkSnapshot render (visible lines only)
```

For Copilot CLI, Zen now consumes JSON streaming events (`assistant.reasoning_delta`, `assistant.message_delta`) and feeds reasoning deltas into the existing thinking renderer so users see intermediate progress similar to terminal usage.

### Key Timings

| Component | Mechanism | Interval |
|-----------|-----------|----------|
| PTY poll | `GLib.timeout_add` | 16ms |
| Canvas redraw | `GLib.idle_add` | next idle (variable) |
| Spinner | `GLib.timeout_add` | 80ms |
| Subprocess check | `GLib.timeout_add` | 500ms |

### Buffering Points

- **SystemTagStripper**: holds partial XML tags up to 64KB before flushing
- **TerminalMarkdownRenderer**: buffers entire code blocks until closing ` ``` `, tables until separator row
- **ChatCanvas**: coalesces redraws via idle_add (only one queued at a time)

---

## Opportunities

### Phase 1 — Perceived Latency (High Impact, Low Risk)

#### 1.1 Live Thinking Text Display

**Problem:** Thinking tokens stream in but render as indistinct dimmed text. Users perceive "nothing happening."

**Solution:** Render thinking output in a visually distinct collapsible block:
- Detect thinking tokens (zero-width space `\u200b` prefix from Claude CLI provider)
- Display them in a dedicated "Thinking…" section with:
  - Dimmed/italic styling, slightly indented
  - Collapsible toggle (collapsed by default, expandable on click)
  - Live-updating text so users see the AI reasoning in real time
- When thinking ends and response begins, auto-collapse the thinking block

**Files:** `ai_chat_terminal.py` (thinking detection), `chat_canvas.py` (rendering), `claude_cli_provider.py` (token tagging)

#### 1.2 Elapsed Timer During Thinking

**Problem:** No indication of how long the AI has been processing.

**Solution:** Show an elapsed time counter next to the spinner: `⠋ Thinking... (3.2s)`
- Start timer when message is sent
- Stop timer when first content token appears
- Minimal cost: reuse existing spinner timer (80ms)

**Files:** `ai_chat_terminal.py` (`_start_spinner`, `_update_spinner`)

#### 1.3 First-Token Priority

**Problem:** The very first content token goes through the same batching path as all subsequent tokens, adding unnecessary latency to the most perceptually important moment.

**Solution:** On first non-thinking token:
- Immediately stop spinner (no 80ms wait for next frame)
- Force synchronous redraw (bypass `idle_add` coalescing)
- This makes the transition from "thinking" to "responding" feel instant

**Files:** `ai_chat_terminal.py` (line ~1257), `chat_canvas.py` (`_schedule_redraw`)

---

### Phase 2 — Actual Latency (Medium Impact, Medium Risk)

#### 2.1 Incremental Code Block Rendering

**Problem:** Code blocks are fully buffered until the closing ` ``` ` fence appears. For long code blocks, this means several seconds of no visible output.

**Solution:** Emit code block lines incrementally:
- Start rendering code block lines as they arrive (with syntax highlighting)
- On closing fence, finalize (no re-render needed since lines were already correct)
- Trade-off: slightly more redraws, but dramatically better perceived speed

**Files:** `terminal_markdown_renderer.py` (lines ~165-187, `_in_code_block` path)

#### 2.2 Reduce Tag Stripper Buffering

**Problem:** The tag stripper holds up to 64KB of data when it encounters a partial XML tag.

**Solution:**
- Lower the buffer threshold to 4KB (most system tags are <1KB)
- Add a time-based flush: if partial tag buffer hasn't closed within 200ms, flush as plain text
- This prevents a single unclosed `<` from stalling the entire pipeline

**Files:** `system_tag_stripper.py`

#### 2.3 Streaming Markdown — Partial Line Emission

**Problem:** The markdown renderer only emits complete lines. During slow token-by-token streaming, this means the current line is invisible until the next newline.

**Solution:** Emit partial lines with a "dirty" flag:
- Feed current partial line to ChatCanvas immediately
- On next token, update the partial line in-place (overwrite last line in AnsiBuffer)
- On newline, finalize the line (clear dirty flag)
- This matches how the terminal works: characters appear as they arrive

**Files:** `terminal_markdown_renderer.py`, `ansi_buffer.py` (partial line support), `chat_canvas.py`

---

### Phase 3 — Architecture (Lower Priority, Higher Risk)

#### 3.1 Event-Driven PTY Reading

**Problem:** 16ms polling means up to 16ms latency before data is even read, regardless of when it arrives.

**Solution:** Use `GLib.io_add_watch()` instead of timeout polling:
- Register PTY fd for `G_IO_IN` events
- Callback fires immediately when data is available (0ms latency vs 0-16ms)
- **macOS caveat:** PTY fd causes `ESRCH` poll errors after child exits — needs guard:
  - Catch the error and fall back to drain + close
  - Or switch to timeout polling only after detecting process exit

**Files:** `ai_chat_terminal.py` (lines ~1210-1283)

#### 3.2 Dirty-Line Rendering

**Problem:** `queue_draw()` invalidates the entire widget; `do_snapshot()` re-renders all visible lines even if only the last line changed.

**Solution:** Track which lines changed since last render:
- Maintain a `dirty_lines: set[int]` in AnsiBuffer
- In `do_snapshot()`, only re-layout and re-draw dirty lines
- Cache Pango layouts for unchanged lines
- Expected: ~10x fewer layout calculations during streaming

**Files:** `chat_canvas.py`, `ansi_buffer.py`

---

## Priority & Effort Matrix

| Item | Impact | Effort | Risk | Priority |
|------|--------|--------|------|----------|
| 1.1 Live thinking text | ★★★★★ | Medium | Low | **P0** |
| 1.2 Elapsed timer | ★★★☆☆ | Small | None | **P0** |
| 1.3 First-token priority | ★★★★☆ | Small | Low | **P0** |
| 2.1 Incremental code blocks | ★★★★☆ | Medium | Low | **P1** |
| 2.2 Reduce tag buffer | ★★☆☆☆ | Small | Low | **P1** |
| 2.3 Partial line emission | ★★★★★ | Large | Medium | **P1** |
| 3.1 Event-driven PTY | ★★★☆☆ | Medium | Medium | **P2** |
| 3.2 Dirty-line rendering | ★★☆☆☆ | Large | Medium | **P2** |

---

## Success Criteria

- **Thinking phase**: user sees live AI reasoning text streaming (not just a spinner)
- **First token to screen**: ≤ 20ms from PTY data arrival to pixel on screen
- **Code blocks**: lines appear as they stream, not after block closes
- **Partial lines**: characters appear in real time, matching terminal behavior
- **No regressions**: scroll stability, selection, copy/paste all still work

---

## Non-Goals

- Changing the AI provider protocol or API
- Modifying the PTY-based architecture (it works well, just needs tuning)
- Adding a separate terminal emulator widget (ChatCanvas approach is correct for our needs)
