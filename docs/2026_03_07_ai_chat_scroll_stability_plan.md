# AI Chat Scroll Stability Plan

**Created_at:** 2026-03-07  
**Updated_at:** 2026-03-08  
**Status:** Superseded — ChatCanvas replaced by VTE terminal, see [2026_03_21_ai_terminal.md](2026_03_21_ai_terminal.md)
**Goal:** Stabilize AI chat scroll behavior by centralizing scroll authority and improving resize handling
**Scope:** `src/ai/chat_canvas.py`, `src/ai/ai_chat_terminal.py`, `src/ai/ai_chat_tabs.py`, `src/ai/terminal_markdown_renderer.py`  

---

## Summary

The new AI chat canvas already looks better than the old VTE-based output, but scroll ownership is still unstable. The current implementation has several independent code paths that all try to "help" the viewport after resize, restore, focus, and tab activation, and those paths occasionally fight each other.

The visible result is the jump users are noticing:

- resize the AI panel from outside
- maximize / restore the panel
- switch back to a chat tab
- click inside the rendered chat

In each of those cases, the UI can briefly move to the wrong position, then snap again, or jump all the way to the top.

## What is happening today

### 1. Chat output height depends on reflow

`ChatCanvas` is a `Gtk.DrawingArea` inside a `Gtk.ScrolledWindow`.

- `get_column_count()` derives wrapping width from the visible viewport width
- content is rendered line-by-line from `AnsiBuffer`
- `_update_content_height()` sets the drawing area height from `line_count * line_height`

That means panel width changes are not cosmetic. A width change changes wrap width, which changes total line count, which changes content height, which changes the vertical adjustment range.

So after any external resize, the previous scroll position is no longer a stable absolute number.

### 2. Scroll restoration currently happens in multiple places

`AIChatTerminalView` currently has several separate mechanisms that can mutate the vertical adjustment:

- `_restore_scroll_position()` after focusing the chat canvas
- `_restore_scroll_state()` after resize-triggered re-render
- `_do_restore_messages(..., scroll_mode=...)` after message restoration
- `scroll_to_bottom()` after restore or tab activation
- `AIChatTabs.switch_to_session()` auto-scroll on session change

Each individual piece is understandable, but together they create overlapping authority over the same adjustment.

### 3. Focus can trigger a viewport correction

When the user clicks inside the output area, `_on_panel_click()` calls `_focus_terminal_preserving_scroll()`, which:

1. reads the current `vadjustment` value
2. calls `self.terminal.grab_focus()`
3. schedules repeated idle restores of the old scroll value

This is meant to protect against GTK scrolling the focused widget into view. The problem is that this happens immediately after resize/reflow periods where the adjustment upper bound may still be changing.

So the click path can race against pending resize/layout changes and restore to a stale target.

### 4. Restore and auto-scroll policy are mixed together

The intended UX is:

- when a hidden AI tab becomes visible, it may auto-scroll to the end once
- once the chat is visible and the user is interacting with it, the viewport should be left alone

The current flow gets close to this, but not fully:

- `ensure_restored()` schedules asynchronous restore work when a session becomes visible
- `_do_restore_messages()` still defaults to bottom scrolling unless explicitly told to preserve state
- `switch_to_session()` also schedules a bottom scroll when `session_changed`

That means restoration policy and tab-activation policy are still coupled through delayed callbacks instead of one explicit source of truth.

### 5. Fraction-based restore is only partially stable

`_capture_scroll_state()` stores:

- absolute value
- max value
- fraction
- whether the user was at bottom

This is better than restoring only the raw absolute value, but it is still weak when line wrapping changes significantly.

Example:

- the user is reading a paragraph in the middle of a long assistant response
- panel width increases
- wrapped lines collapse
- the same semantic location is no longer at the same fraction of the whole document

The restore logic may land near the old proportional position, but not at the same content anchor.

## Why the jump to the top happens

The jump-to-top symptom is likely a compound effect, not one isolated bug.

Most likely sequence:

1. the user is near the bottom of the chat
2. panel width changes from maximize/restore or external splitter movement
3. reflow changes content height and therefore the adjustment bounds
4. a delayed restore, bottom scroll, or focus-preserving restore is still pending
5. the user clicks the chat canvas
6. GTK focus behavior and our own restore logic both touch the adjustment while the layout is still settling

If one of those restores runs against an outdated `max_value`, or runs before the final post-reflow geometry is stable, the viewport can be clamped to an unintended position. In practice that can look like a snap to the top, a bounce, or a visible rewind then settle.

## Root causes

### Root cause A — too many scroll writers

The viewport currently has no single owner. Resize recovery, focus recovery, restore-from-history, and tab activation can all write to the same adjustment.

### Root cause B — scroll targets are decided too early

Several callbacks capture a target before the layout is fully stable, then replay that target later through `GLib.idle_add()` or `GLib.timeout_add()`.

### Root cause C — restore is value-based instead of content-anchored

Preserving a numeric adjustment works only when the document shape is mostly unchanged. Rewrap-heavy content needs a semantic anchor, not just a number.

### Root cause D — activation-time behavior and visible-time behavior are not clearly separated

A hidden tab becoming visible is one phase. A visible, user-controlled chat is another. The code still allows delayed activation logic to leak into the second phase.

## Desired behavior

This should be the rule set:

1. **Tab activation**
   - If a different AI tab becomes visible, scroll to bottom once.
   - If the tab is being restored from saved messages, do the restore first and apply the activation target once at the end.

2. **Visible chat**
   - Once visible, do not modify scroll position because of clicks, focus churn, or late restore callbacks.
   - Resizing should preserve the current viewport unless the user was already pinned to bottom.

3. **Bottom-follow mode**
   - While streaming, auto-follow only if the user is already at bottom.
   - If the user has scrolled up, new output must not yank them back down.

4. **Resize / maximize / restore**
   - If the user was at bottom before reflow, keep them at bottom after reflow.
   - Otherwise preserve the same visible content anchor, not just the same adjustment fraction.

## Improvement plan

### Phase 1 — establish a single scroll authority

Introduce one small scroll state model inside the AI chat view, for example:

- `activation-scroll`
- `restore-scroll`
- `resize-preserve`
- `stream-follow`
- `user-controlled`

Only one path should be allowed to commit a scroll mutation at a time. All other code should request an intent instead of calling `vadjustment.set_value()` directly.

Practical outcome:

- `switch_to_session()` should request an activation policy
- `_do_restore_messages()` should apply the policy it is handed, not decide one implicitly
- click handling should not start an independent scroll-repair loop if another policy is already active

### Phase 2 — separate restore from post-restore scroll policy

Refactor the restore flow into two explicit steps:

1. rebuild visual content
2. apply a single post-restore scroll target

That target should be passed in explicitly:

- `"bottom"`
- `"preserve"`
- `"none"`

The important part is that `_do_restore_messages()` must stop defaulting to bottom scrolling just because no explicit preserve state was provided.

### Phase 3 — replace repeated idle retries with a resize settle point

The current approach retries with `GLib.idle_add()` and `GLib.timeout_add()` several times. That keeps the code resilient, but it also creates delayed scroll writes that may outlive the event that triggered them.

Instead, prefer a single "resize settled" application point:

- detect width change
- capture scroll intent before reflow
- wait until the canvas/content height is updated for the new width
- apply one restoration

This can be implemented with a debounced width-change handler or a generation token that invalidates old pending restore callbacks.

### Phase 4 — preserve a content anchor, not just a numeric adjustment

For non-bottom resize preservation, restore against content identity:

- top visible line index plus intra-line pixel offset, or
- a message index plus line offset within that message

This is more robust than restoring by raw value or global fraction after wrap changes.

The right long-term anchor is probably message-based, because the chat is already structured as user/assistant message blocks and resize reflow mostly changes wrapping inside those blocks.

### Phase 5 — reduce focus side effects ✅ DONE

ChatCanvas is now non-focusable (`set_can_focus(False)`, `set_focusable(False)`).
This eliminates the root cause: GTK4's `scroll_child_into_view` no longer fires
on click because the DrawingArea never receives focus.

- Text selection works via `GestureDrag` (no focus needed)
- Copy shortcut (Cmd+C) moved to panel-level CAPTURE-phase key controller
- `_focus_terminal_preserving_scroll()` removed entirely

### Phase 6 — make "visible means user-owned" explicit

Once a chat is visible and restoration has completed:

- clear pending activation intents
- ignore late bottom-scroll callbacks
- ignore late preserve-scroll callbacks from an older layout generation

This is the behavior the user asked for: auto-scroll when swapped in, but do not keep touching scroll once the chat is on screen.

## Suggested implementation order

1. **Introduce a scroll generation token**
   - Every resize / restore / activation increments a generation.
   - Delayed callbacks must check the token and abort if stale.

2. **Centralize scroll application**
   - Create one helper that applies bottom/preserve/none.
   - Route existing callers through it.

3. **Refactor restore flow**
   - `ensure_restored()` should schedule restore with an explicit target.
   - `_do_restore_messages()` should not self-decide bottom scrolling.

4. **Debounce width-change preservation**
   - Capture state once per resize burst, not once per callback.

5. **Make focus restoration one-shot**
   - Only restore if `grab_focus()` actually moved the adjustment.

6. **Upgrade preservation anchor**
   - Start with bottom vs fraction.
   - Then move to line/message anchored restore for true stability.

## Validation plan

### Automated tests

Add or extend tests around:

- tab switch triggers one bottom scroll only when a different session becomes visible
- visible resize preserves scroll and does not queue a later bottom scroll
- click after resize does not write a new scroll target unless focus changed the adjustment
- stale delayed callbacks are ignored after a newer resize/restore generation
- bottom-follow works only when the user is already at bottom

### Manual checks

Run these scenarios in the UI:

1. Scroll to the bottom, maximize AI panel, restore it, click inside output.
   - Expected: no jump to top, no rewind.

2. Scroll to the middle of a long assistant response, resize wider and narrower.
   - Expected: same content stays in view.

3. Switch from chat A to chat B.
   - Expected: B opens at the end once.

4. After B is visible, click, select text, resize slightly.
   - Expected: no automatic repositioning unless the user was pinned to bottom.

5. Start streaming, then scroll up during output.
   - Expected: auto-follow stops immediately.

## Short-term recommendation

The fastest safe improvement is:

1. add a scroll generation token
2. centralize all delayed scroll writes behind one helper
3. remove implicit bottom scrolling from `_do_restore_messages()`
4. make focus-preserving restore one-shot and generation-aware

That should eliminate most of the visible jumps without redesigning the whole rendering pipeline.

## Long-term recommendation

Move the AI chat to a proper "scroll intent + content anchor" model:

- one owner for viewport mutations
- explicit activation vs user-controlled phases
- message-anchored preservation during rewrap

That will make the new canvas feel stable enough to match the quality of the component's visual design.
