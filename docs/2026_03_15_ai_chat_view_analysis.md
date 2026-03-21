# AI Chat View — Bug & Regression Analysis

**Created_at:** 2026-03-15  
**Updated_at:** 2026-03-15  
**Status:** Superseded — old chat view replaced by VTE terminal, see [2026_03_21_ai_terminal.md](2026_03_21_ai_terminal.md)
**Goal:** Identify and catalog all bugs, regressions, and UX issues in the AI chat view
**Scope:** `src/ai/ai_chat_terminal.py`, `src/ai/ai_chat_tabs.py`, `src/ai/chat_canvas.py`, `src/ai/ansi_buffer.py`, `src/ai/terminal_markdown_renderer.py`, `src/ai/system_tag_stripper.py`  

---

## Architecture Overview

The AI chat system is a **multi-session, DrawingArea-based chat** with two layout modes (horizontal tabs or vertical stack). Key components:

| Component | File | Lines | Role |
|-----------|------|-------|------|
| `AIChatTabs` | `ai_chat_tabs.py` | 1386 | Multi-session manager, tab/stack layout, session persistence |
| `AIChatTerminalView` | `ai_chat_terminal.py` | 2253 | Single chat session: PTY streaming, markdown rendering, scroll |
| `ChatCanvas` | `chat_canvas.py` | 794 | Custom `Gtk.DrawingArea` renderer using GtkSnapshot + Pango |
| `AnsiBuffer` | `ansi_buffer.py` | 306 | ANSI text parser → styled spans for DrawingArea rendering |
| `TerminalMarkdownRenderer` | `terminal_markdown_renderer.py` | 741 | Streaming markdown→ANSI converter with Pygments highlighting |
| `SystemTagStripper` | `system_tag_stripper.py` | 114 | Strips XML tags from Claude CLI output stream |

**Streaming pipeline:** PTY → SystemTagStripper / CopilotStreamParser → TerminalMarkdownRenderer → ChatCanvas.feed() → AnsiBuffer

---

## Critical Bugs

### BUG-1: Duplicate Scroll Restoration Causes Jump-to-Top on Tab Switch

**Severity:** 🔴 Critical  
**Location:** `ai_chat_tabs.py` lines 674–688  
**Symptoms:** Visible scroll jump to top when switching between chat tabs  

**Root cause:** Two independent scroll-to-bottom paths race when switching tabs:

```python
# Path 1 (line 678): restore triggers bottom scroll
GLib.idle_add(chat.ensure_restored, restore_scroll_mode)  # scroll_mode = "bottom"

# Path 2 (lines 682-688): DUPLICATE bottom scroll, different timing
if session_changed and not getattr(chat, '_pending_restore', False):
    if hasattr(chat, 'schedule_activation_scroll_to_bottom'):
        GLib.idle_add(chat.schedule_activation_scroll_to_bottom)
```

Both schedule independent `idle_add` scroll actions. The first one scrolls to bottom, the layout hasn't fully settled, then the second fires and either scrolls to top (stale upper bound) or causes a visible flash.

**Fix:** Remove lines 682–688 entirely. `ensure_restored()` already handles bottom scroll via `restore_scroll_mode="bottom"`. The second path is redundant.

---

### BUG-2: Input Box Hidden During Processing Blocks All Interaction

**Severity:** 🔴 Critical  
**Location:** `ai_chat_terminal.py` line 1169  
**Symptoms:** User can't type anything while AI is responding; no visual cue about how to interrupt  

When processing starts:
```python
self.input_box.set_visible(False)  # line 1169
```

The input completely disappears. The stop button exists in the header but is easy to miss (especially in vertical mode where the header may be scrolled away). If the AI hangs or produces a very long response, the user has no obvious way to interact.

**Fix:** Keep the input box visible but disabled (dimmed). Show a prominent inline "Stop" button or hint text like "Press Esc to stop" directly where the input was.

---

### BUG-3: No-Data Timeout Doesn't Stop Spinner

**Severity:** 🟠 High  
**Location:** `ai_chat_terminal.py` lines 1485–1507  
**Symptoms:** Spinner animation continues indefinitely after timeout kills the process  

The no-data timeout code kills the process and shows `[Timed out]` but never calls `_stop_spinner()`:

```python
if elapsed > AI_CHAT_NO_DATA_TIMEOUT:
    os.killpg(...)
    self._cleanup_pty()
    self._response_buffer = []
    timeout_msg = f"[Timed out — no response for {timeout_s}s]"
    self._append_text(f"\n{timeout_msg}\n")
    # BUG: _stop_spinner() never called here!
    self.messages.append(...)
    self._finish_processing()  # calls _stop_spinner() but AFTER append_text
```

`_finish_processing()` does call `_stop_spinner()`, but the spinner was still animating when the timeout message was appended — the spinner text and timeout message overlap momentarily.

**Fix:** Call `self._stop_spinner()` before appending the timeout message.

---

### BUG-4: Scroll State Corrupted During Resize (Documented but Unfixed)

**Severity:** 🟠 High  
**Location:** `ai_chat_terminal.py` lines 849–932, 1991–2093  
**Ref:** `docs/2026_03_07_ai_chat_scroll_stability_plan.md`  
**Symptoms:** User's manually-adjusted scroll position jumps unexpectedly during panel resize  

`_pending_restore_scroll_mode` is global mutable state shared across multiple async operations:
- `ensure_restored()` sets it to `"bottom"`
- `_rerender_on_resize()` captures and restores scroll state independently
- Both can run concurrently via `idle_add` / `timeout_add`

The scroll stability plan documents this as a known issue (Phases 1–4 partially done, Phase 6 not done). The generation token system (`_scroll_generation`) was added but isn't fully utilized — retry logic in `_restore_scroll_state()` doesn't always check the generation.

**Fix:** Implement Phase 6 from the scroll stability plan: clear `_pending_restore_scroll_mode = "none"` at the start of `ensure_restored()`, and ensure all scroll writes go through a single authority path.

---

### BUG-5: CLI Not Found Leaves UI in Half-Initialized State

**Severity:** 🟠 High  
**Location:** `ai_chat_terminal.py` lines 1113–1136  
**Symptoms:** After a "CLI not found" error, subsequent messages may fail silently  

When the CLI isn't found, the method returns early but has already modified state:
```python
def _run_ai_cli(self, message):
    ...
    if self._current_provider == self.PROVIDER_CLAUDE_CLI:
        cli_path = find_cli("claude")
        if not cli_path:
            self._append_text("\n[Error: Claude CLI not found]\n")
            return  # Returns without cleanup
    ...
    # These never execute:
    self._is_processing = True
    self.input_box.set_visible(False)
```

The message was already appended to `self.messages` (line 1037) and saved (line 1040), so chat history records a user message with no assistant response. The next call to `_build_prompt_with_context()` includes this orphaned message in history.

**Fix:** Don't append/save the message until CLI availability is confirmed. Or append an error assistant message: `self.messages.append({"role": "assistant", "content": "[Error: CLI not found]"})`.

---

## Medium-Priority Issues

### ISSUE-6: 100ms Resize Polling Timer Always Active

**Severity:** 🟡 Medium  
**Location:** `ai_chat_terminal.py` lines 815–847  
**Impact:** Unnecessary CPU usage; battery drain on laptops  

`_start_resize_polling()` fires every 100ms when the terminal is mapped, calling `_poll_column_count()`. This runs even when no chat is active or the panel is hidden behind another tab.

**Fix:** Use GTK's `notify::default-width` on the toplevel window or `notify::width-request` on the scrolled window instead of polling. Alternatively, increase the poll interval to 500ms (column changes are rare).

---

### ISSUE-7: Response Truncation at 10K Characters Without User Notice

**Severity:** 🟡 Medium  
**Location:** `ai_chat_terminal.py` lines 1600–1602  

```python
if len(text) > 10000:
    text = text[:10000] + "...[truncated]"
```

Long assistant responses are silently truncated in the stored message history. The user sees the full response rendered on screen but the saved version is incomplete. If they restart the IDE, the restored chat shows a truncated response.

**Fix:** Either increase the limit significantly (AI responses are routinely 20–50K), or show a visible "[Response truncated for storage]" indicator in the rendered output so the user knows what happened.

---

### ISSUE-8: CSS Provider Leaks on Every Theme Change

**Severity:** 🟡 Medium  
**Location:** `ai_chat_terminal.py` lines 956–959, `ai_chat_tabs.py` lines 425–431  

Both `_apply_theme()` and `_apply_base_css()` call `Gtk.StyleContext.add_provider_for_display()` every time. GTK doesn't deduplicate providers — each call adds another provider to the global display. Over many theme changes, hundreds of providers accumulate.

**Fix:** Store the `CssProvider` instance on `self` and call `load_from_data()` on the existing provider instead of creating a new one each time.

---

### ISSUE-9: `_clear_session` Method Called but Never Defined

**Severity:** 🟡 Medium  
**Location:** `ai_chat_tabs.py` line 983  

```python
if len(self.sessions) == 1:
    self._clear_session(self.sessions[0]["session_id"])
```

The method `_clear_session` is never defined in `AIChatTabs`. This path triggers when "Close All AI Tabs" is selected and only one session remains.

**Fix:** Define `_clear_session()` that clears the terminal, empties messages, resets the display name, and deletes the chat file. Or call `chat.terminal.reset()` and `chat.messages.clear()` inline.

---

### ISSUE-10: `new_session()` Called on Single Chat Causes Crash

**Severity:** 🟡 Medium  
**Location:** `ai_chat_tabs.py` lines 836–839  

```python
if len(self.sessions) <= 1:
    self.sessions[0]["chat"].new_session()  # AIChatTerminalView has no new_session()!
    return
```

`AIChatTerminalView` doesn't have a `new_session()` method. This code runs when trying to close the last remaining session.

**Fix:** Replace with terminal clear logic: `self.sessions[0]["chat"].terminal.reset()` and `self.sessions[0]["chat"].messages.clear()`.

---

### ISSUE-11: Thinking Block Collapse Accesses Private `_buffer` Directly

**Severity:** 🟡 Medium  
**Location:** `ai_chat_terminal.py` lines 1825, 1861, 1890  

`AIChatTerminalView` reaches into `self.terminal._buffer` (the `AnsiBuffer` internals):

```python
self._thinking_line_start = self.terminal._buffer.get_line_count()  # line 1825
buf = self.terminal._buffer  # line 1861
buf.lines[start:] = [[summary_span], []]  # line 1890 — direct mutation!
```

This violates encapsulation. Direct `lines` mutation bypasses dirty-line tracking, meaning the collapsed thinking block may not redraw properly on the next frame.

**Fix:** Add a `ChatCanvas.replace_lines(start, end, new_lines)` public API that handles dirty tracking internally.

---

## UX Improvement Opportunities

### UX-1: No Visual Feedback Between Send and First Token

When the user sends a message, there's a 30ms delay (`GLib.timeout_add(30, self._do_launch_cli)`) before the CLI even starts, plus time for the spinner to appear. During this gap there's no feedback — the input just clears.

**Suggestion:** Show a subtle "Sending..." indicator immediately on send, before the spinner starts.

### UX-2: Thinking Block Collapsed Too Aggressively

The thinking block collapses into a single summary line ("💭 Thought for 2.3s — 15 lines") as soon as content starts streaming. Users can't expand it to see what the AI was thinking.

**Suggestion:** Make the collapsed thinking block clickable to expand/collapse. Store the thinking text rather than discarding it.

### UX-3: No Way to Retry a Failed Message

If the AI response times out, errors out, or is stopped, the user has no "Retry" button. They must retype or copy-paste their original message.

**Suggestion:** Add a "Retry" button on failed/stopped messages that re-sends the last user message.

### UX-4: User Messages Not Selectable/Copyable

User messages are rendered with the blockquote bar style (`▎ message`) into the ChatCanvas. They can be selected via drag, but there's no visual affordance (no cursor change, no hover highlight) suggesting they're selectable.

**Suggestion:** Change cursor to text cursor when hovering over chat content.

### UX-5: Model Fetching Blocks UI on First Settings Open

`_available_models` is a `@property` that calls `provider.get_available_models()` synchronously, which runs `subprocess.run([cli, "--help"], timeout=10)`. This blocks the main thread for up to 10 seconds on the first click of the AI settings button.

**Location:** `ai_chat_terminal.py` lines 2228–2237

**Suggestion:** Fetch models asynchronously in a background thread on startup. Cache results. Show "Loading models..." in the dropdown while fetching.

---

## Summary Table

| ID | Type | Severity | Effort | Description |
|----|------|----------|--------|-------------|
| BUG-1 | Bug | 🔴 Critical | 10 min | Duplicate scroll restoration causes jump on tab switch |
| BUG-2 | Bug | 🔴 Critical | 30 min | Input hidden during processing; no obvious stop affordance |
| BUG-3 | Bug | 🟠 High | 5 min | Spinner continues after no-data timeout |
| BUG-4 | Bug | 🟠 High | 60 min | Scroll state corrupted during resize (documented unfixed) |
| BUG-5 | Bug | 🟠 High | 15 min | CLI not found leaves orphaned user message in history |
| ISSUE-6 | Perf | 🟡 Medium | 20 min | 100ms resize polling always active |
| ISSUE-7 | Data | 🟡 Medium | 10 min | 10K char truncation without user notice |
| ISSUE-8 | Leak | 🟡 Medium | 15 min | CSS providers accumulate on theme changes |
| ISSUE-9 | Crash | 🟡 Medium | 15 min | `_clear_session()` method never defined |
| ISSUE-10 | Crash | 🟡 Medium | 10 min | `new_session()` called on wrong class |
| ISSUE-11 | Arch | 🟡 Medium | 30 min | Direct `_buffer.lines` mutation bypasses dirty tracking |
| UX-1 | UX | 🟢 Low | 15 min | No feedback between send and first token |
| UX-2 | UX | 🟢 Low | 60 min | Thinking block not expandable |
| UX-3 | UX | 🟢 Low | 45 min | No retry button on failed messages |
| UX-4 | UX | 🟢 Low | 10 min | No text cursor on chat content hover |
| UX-5 | UX | 🟡 Medium | 30 min | Model fetching blocks UI thread |

---

## Recommended Fix Order

1. **ISSUE-9 + ISSUE-10** — `_clear_session` / `new_session` crashes (immediate, blocks basic usage)
2. **BUG-1** — Duplicate scroll restoration (10 min, biggest perceived regression)
3. **BUG-3** — Spinner after timeout (5 min, easy win)
4. **BUG-5** — CLI not found cleanup (15 min)
5. **BUG-2** — Hidden input UX (30 min, significant UX improvement)
6. **ISSUE-8** — CSS provider leak (15 min)
7. **BUG-4** — Scroll stability (60 min, follow the existing plan doc)
8. **UX-5** — Async model fetching (30 min)
9. Everything else in priority order
