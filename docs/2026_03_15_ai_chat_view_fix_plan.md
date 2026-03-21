# AI Chat View — Fix Plan

**Created_at:** 2026-03-15  
**Updated_at:** 2026-03-15  
**Status:** Superseded — old chat view replaced by VTE terminal, see [2026_03_21_ai_terminal.md](2026_03_21_ai_terminal.md)
**Goal:** Structured plan to fix all bugs, regressions, and UX issues identified in the AI chat view analysis
**Scope:** `src/ai/ai_chat_terminal.py`, `src/ai/ai_chat_tabs.py`, `src/ai/chat_canvas.py`, `src/ai/ansi_buffer.py`, `src/ai/terminal_markdown_renderer.py`  

---

## Overview

This plan prioritises fixes from the [AI Chat View Analysis](2026_03_15_ai_chat_view_analysis.md) into four phases, ordered by impact and dependency. Each phase is designed to be independently shippable — later phases build on earlier ones but don't block them.

**Total estimated effort:** ~6 hours across all phases.

---

## Phase 1 — Crash & Data-Corruption Fixes

**Goal:** Eliminate crashes and data-integrity bugs so the chat is reliably usable.  
**Effort:** ~45 min  

| ID | Task | File | Est. |
|----|------|------|------|
| ISSUE-9 | Define `_clear_session()` — clear terminal, empty messages, reset display name, delete chat file | `ai_chat_tabs.py` | 15 min |
| ISSUE-10 | Fix `new_session()` call on last-tab close — replace with terminal reset + message clear | `ai_chat_tabs.py` | 10 min |
| BUG-5 | Don't append user message to history until CLI availability is confirmed; on failure append an error assistant message | `ai_chat_terminal.py` | 15 min |
| BUG-3 | Call `_stop_spinner()` before appending the timeout message in the no-data timeout handler | `ai_chat_terminal.py` | 5 min |

### Acceptance criteria
- "Close All AI Tabs" with one session remaining doesn't crash
- Closing the last tab doesn't crash
- When Claude CLI is not installed, sending a message shows an error and doesn't pollute history
- No-data timeout stops the spinner before showing `[Timed out]`

---

## Phase 2 — Scroll & Tab-Switch Regressions

**Goal:** Fix the most visible perceived regression: scroll jumps.  
**Effort:** ~70 min  

| ID | Task | File | Est. |
|----|------|------|------|
| BUG-1 | Remove the duplicate `schedule_activation_scroll_to_bottom` call (lines 682–688). `ensure_restored()` already handles bottom scroll via `restore_scroll_mode="bottom"` | `ai_chat_tabs.py` | 10 min |
| BUG-4 | Implement Phase 6 from `docs/2026_03_07_ai_chat_scroll_stability_plan.md`: clear `_pending_restore_scroll_mode = "none"` at `ensure_restored()` start; funnel all scroll writes through a single authority path; verify the generation token is checked in all retry paths | `ai_chat_terminal.py` | 60 min |

### Acceptance criteria
- Switching between chat tabs preserves scroll position without any visible flash or jump
- Resizing the panel while scrolled to a mid-conversation position doesn't change the visible content
- Programmatic scroll-to-bottom during streaming still works correctly

### Testing approach
1. Open 3+ chat sessions with varying content lengths
2. Scroll to middle of conversation in session A
3. Switch to session B, then back to A — scroll position should be unchanged
4. While streaming a response in session C, drag-resize the panel — no scroll jumps

---

## Phase 3 — Resource Leaks & Performance

**Goal:** Eliminate CPU waste and memory leaks in long-running sessions.  
**Effort:** ~50 min  

| ID | Task | File | Est. |
|----|------|------|------|
| ISSUE-6 | Replace 100ms `_poll_column_count()` timer with a GTK `notify::default-width` signal on the toplevel window; fall back to 500ms polling if signal isn't reliable | `ai_chat_terminal.py` | 20 min |
| ISSUE-8 | Store `CssProvider` on `self` and reuse it via `load_from_data()` on theme changes instead of creating and adding new ones | `ai_chat_terminal.py`, `ai_chat_tabs.py` | 15 min |
| ISSUE-7 | Increase stored-response truncation limit from 10K to 100K characters; if still truncated, show a visible `[Response truncated for storage — X chars omitted]` indicator in the rendered output | `ai_chat_terminal.py` | 10 min |
| ISSUE-11 | Add `ChatCanvas.replace_lines(start, end, new_lines)` public method that internally marks affected lines as dirty; update thinking-block collapse to use it | `chat_canvas.py`, `ai_chat_terminal.py` | 30 min |

### Acceptance criteria
- `_poll_column_count` timer is not running when the chat panel is hidden or no sessions exist
- After 10 theme switches, only 1 CSS provider exists per component (not 10)
- A 50K-character AI response is stored in full and restored correctly on IDE restart
- Collapsing a thinking block redraws cleanly without stale lines

---

## Phase 4 — UX Improvements

**Goal:** Polish the interaction model to feel responsive and forgiving.  
**Effort:** ~2.5 hours  

| ID | Task | File | Est. |
|----|------|------|------|
| BUG-2 | Keep the input box visible but disabled during processing; show inline "Press Esc to stop" hint text; ensure the Esc keybinding actually stops the current request | `ai_chat_terminal.py` | 30 min |
| UX-1 | Show a subtle "Sending..." label immediately on send (before spinner starts); clear it when the first token arrives | `ai_chat_terminal.py` | 15 min |
| UX-5 | Fetch available models asynchronously in a background thread; cache results; show "Loading models..." in dropdown while fetching | `ai_chat_terminal.py` | 30 min |
| UX-4 | Set cursor to `GDK_TEXT` when hovering over chat content in the `ChatCanvas` | `chat_canvas.py` | 10 min |
| UX-3 | Add a "Retry" affordance on failed/stopped/timed-out messages — re-send the last user message | `ai_chat_terminal.py` | 45 min |
| UX-2 | Make thinking block summary clickable to expand/collapse; store thinking text instead of discarding it | `ai_chat_terminal.py`, `chat_canvas.py` | 60 min |

### Acceptance criteria
- During AI processing, user sees a disabled input with "Press Esc to stop" text
- Pressing Esc during processing kills the subprocess and restores the input
- On send, "Sending..." appears within 1 frame; spinner replaces it when first token arrives
- Model dropdown shows "Loading models..." and populates asynchronously (never blocks UI)
- Hovering over chat text shows text cursor
- On timeout/error, a clickable "Retry" element appears; clicking it re-sends the last user message
- Thinking block summary is clickable; clicking expands to show full thinking text; clicking again collapses

---

## Dependency Graph

```
Phase 1 (crashes)
    └─▶ Phase 2 (scroll)
            └─▶ Phase 3 (performance)
                    └─▶ Phase 4 (UX)
```

Phases are sequential because:
- Phase 2 touches scroll code that Phase 1's `_clear_session` fix must not regress
- Phase 3's `replace_lines()` API is needed by Phase 4's expandable thinking blocks
- Phase 4's input-box changes build on Phase 1's spinner fix

---

## Validation Strategy

After each phase:
1. `make tests` — all existing tests pass
2. `make lint` — no new warnings
3. `make run` — manual smoke test of the specific scenarios listed in acceptance criteria
4. `make startup-time` — no regression (phases 1–3 should not affect startup; phase 4's async model fetch should improve it)
