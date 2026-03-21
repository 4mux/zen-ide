# Sleep on AI Completion

**Created_at:** 2026-03-17  
**Updated_at:** 2026-03-17  
**Status:** Planned (needs update — references deleted files)
**Goal:** Put the machine to standby automatically after an AI task finishes
**Scope:** `src/ai/ai_terminal_view.py`, `src/ai/ai_terminal_stack.py`, `src/shared/settings/default_settings.py`, `src/main/status_bar.py`  

---

## Overview

Long-running AI tasks (agentic coding, large refactors) can take minutes to hours. Users often kick off a task and walk away. **Sleep on AI Completion** lets the user arm a one-shot trigger: once the current AI processing finishes, the machine suspends to save power.

---

## Behaviour

1. **Arming** — User presses `Cmd+Shift+Z` (macOS) / `Ctrl+Shift+Z` (Linux) while AI is processing.
2. **Visual indicator** — Status bar shows a 💤 icon to confirm the trigger is armed.
3. **AI completes** — `on_processing_state_change(False)` fires.
4. **Countdown** — A 10-second toast notification appears: _"Sleeping in 10 s — press Esc to cancel"_.
5. **Sleep** — If not cancelled, the machine suspends.
6. **Auto-disarm** — The trigger resets after firing (one-shot). If cancelled, it also disarms.

### Edge Cases

| Scenario | Behaviour |
|----------|-----------|
| User arms while **no** AI task is running | Ignore (no-op). Only armable when `_is_processing is True`. |
| User arms, then sends **another** message before completion | Trigger stays armed; fires after the new task finishes. |
| AI errors out | Treat as completion — fire the trigger (error still means "done"). |
| Multiple chat tabs processing | Fire only when **all** tabs finish processing. |
| Countdown cancelled | Disarm and resume normal operation. |
| IDE closed during countdown | Cancel countdown; do not sleep. |

---

## Setting

```jsonc
// ~/.zen_ide/settings.json
{
  "ai": {
    "sleep_on_completion": false   // persisted arm state (default: false)
  }
}
```

The setting is **not** meant to be permanently enabled — it is toggled on by the keybinding and auto-reset to `false` after firing or cancelling. Persisting it covers the case where the IDE restarts while armed.

---

## Keybinding

| Action | macOS | Linux |
|--------|-------|-------|
| Toggle sleep-on-completion | `Cmd+Shift+Z` | `Ctrl+Shift+Z` |

Add to `KeyBindings` class:

```python
SLEEP_ON_AI_COMPLETION = f"{_MOD_SHIFT}z"
```

The shortcut should be registered in the main window key handler. It toggles the armed state and updates the status bar.

---

## Status Bar Indicator

When armed, append a `💤` segment to the right side of the status bar (after the file-type segment). Remove it when disarmed or after firing.

---

## Countdown Toast

Use an `NvimPopup`-derived overlay anchored to bottom-center of the editor area:

- Text: `"Sleeping in {n} s — press Esc to cancel"`
- Countdown from 10 → 0, updating every second via `GLib.timeout_add(1000, …)`.
- `Esc` key cancels: disarms trigger, hides toast.
- On reaching 0: execute sleep command, then hide toast.

---

## Sleep Command

```python
import subprocess, sys

def suspend_machine():
    if sys.platform == "darwin":
        subprocess.Popen(["pmset", "sleepnow"])
    else:
        subprocess.Popen(["systemctl", "suspend"])
```

Place in `src/shared/utils.py` (or a new `src/shared/power.py` if preferred).

---

## Integration Points

### 1. `AIChatTabs` — completion aggregation

`AIChatTabs` already tracks per-tab processing state. Add a method to check whether **all** tabs have finished:

```python
def _all_tabs_idle(self) -> bool:
    return all(
        not btn.processing
        for btn in self.chat_buttons.values()
    )
```

Wire into each tab's `on_processing_state_change`: when transitioning to `False`, check `_all_tabs_idle()` and, if armed, start the countdown.

### 2. `AIChatTerminalView` — no changes needed

The existing `on_processing_state_change(False)` callback is sufficient. All logic lives in `AIChatTabs` and the countdown overlay.

### 3. Status bar — indicator segment

`StatusBar` reads the armed flag from settings or an in-memory flag and conditionally renders the 💤 segment.

---

## Implementation Checklist

- [ ] Add `ai.sleep_on_completion` to `default_settings.py`
- [ ] Add `SLEEP_ON_AI_COMPLETION` to `KeyBindings`
- [ ] Register keybinding in main window key handler
- [ ] Add 💤 status bar segment (conditional on armed state)
- [ ] Implement countdown toast (`NvimPopup` subclass)
- [ ] Add `suspend_machine()` utility
- [ ] Wire `AIChatTabs` completion aggregation to countdown trigger
- [ ] Auto-disarm after fire or cancel
- [ ] Handle Esc to cancel countdown
- [ ] Test on macOS (`pmset sleepnow`) and Linux (`systemctl suspend`)

---

## Out of Scope

- Hibernate (full disk suspend) — only standby/sleep.
- Scheduled sleep unrelated to AI tasks.
- Wake-on-LAN or remote wake triggers.
- Inline completion (`InlineCompletionProvider`) — only chat tasks.
