# Debugging — Design Document

**Created_at:** 2026-03-03
**Updated_at:** 2026-03-27
**Status:** Implemented (Phase 1)
**Goal:** Python debugging via `bdb` (stdlib) — zero external dependencies
**Scope:** `src/debugger/`, pure Python `bdb.Bdb`-based debugger

---

## Overview

Zen IDE debugging uses Python's built-in `bdb.Bdb` debugger class. The debuggee runs in a subprocess with a `bdb.Bdb` subclass (`_BdbBridge`) that communicates with the IDE via JSON lines over stdin/stdout. No external dependencies are required — everything uses the Python standard library.

> **Note:** `src/debug/` is already used by the widget inspector (GTK DevTools-like inspect mode). Debugger code lives in `src/debugger/`.

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                        Zen IDE                        │
│                                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │  Breakpoint  │  │  Debug Panel │  │ Editor      │ │
│  │  Manager     │  │  (variables, │  │ Gutter      │ │
│  │              │  │   call stack, │  │ (breakpoint │ │
│  │              │  │   console)   │  │  markers,   │ │
│  │              │  │              │  │  exec line) │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬──────┘ │
│         │                 │                  │        │
│         └─────────┬───────┘──────────────────┘        │
│                   │                                   │
│          ┌────────▼─────────┐                         │
│          │   BdbClient      │  JSON lines over stdio  │
│          │ (bdb_debugger.py)│◄──────────────────┐     │
│          └────────┬─────────┘                   │     │
│                   │                             │     │
└───────────────────┼─────────────────────────────┼─────┘
                    │ subprocess (stdio)          │
           ┌────────▼─────────────────────────────┐
           │         _BdbBridge                    │
           │   (bdb.Bdb subclass in subprocess)    │
           │                                       │
           │   Runs user script with tracing,      │
           │   stops at breakpoints, sends events   │
           └───────────────────────────────────────┘
```

### Why bdb?

| Approach | Pros | Cons |
|----------|------|------|
| **bdb (chosen)** | Zero dependencies, stdlib, simple protocol | Python-only |
| DAP + debugpy | Multi-language, battle-tested protocol | External dependency, complex |
| Direct pdb | Simple | Brittle text parsing, limited API |

`bdb.Bdb` gives us full debugging capabilities (breakpoints, stepping, variable inspection, expression evaluation) with zero external dependencies — everything ships with Python.

## Components

### 1. BdbClient + BdbBridge (`src/debugger/bdb_debugger.py`)

Two components in one file:

**BdbClient** (IDE side) — manages the debugger subprocess:
- Launches `bdb_debugger.py` as a subprocess with the user's script
- Sends JSON commands via stdin (set_break, continue, step_over, get_stack, etc.)
- Reads JSON events/responses from stdout on a reader thread
- Dispatches events to main GTK thread via `main_thread_call()`
- Request/response pattern using `concurrent.futures.Future` for inspection queries

**_BdbBridge** (subprocess side) — `bdb.Bdb` subclass:
- Inherits from `bdb.Bdb` at runtime (dynamic class creation to avoid importing bdb in IDE)
- Overrides `user_line()`, `user_exception()`, `dispatch_line()`, `break_here()`
- Captures user stdout/stderr via `_OutputRedirector` and forwards as protocol events
- Enters `_command_loop()` when stopped — blocks reading commands until resume
- Handles inspection requests: `get_stack`, `get_scopes`, `get_variables`, `evaluate`

**Protocol** — JSON lines over stdio:
```
IDE → subprocess (stdin):  {"cmd": "set_break", "file": "/path/to/file.py", "line": 10}
IDE → subprocess (stdin):  {"cmd": "run", "stop_on_entry": false}
subprocess → IDE (stdout): {"event": "stopped", "file": "/path/to/file.py", "line": 10, "reason": "breakpoint"}
IDE → subprocess (stdin):  {"cmd": "get_stack", "id": 1}
subprocess → IDE (stdout): {"event": "response", "id": 1, "frames": [...]}
```

### 2. Debug Session Manager (`src/debugger/debug_session.py`)

Orchestrates the debug lifecycle. Sits between UI and BdbClient.

```python
class DebugSession:
    class State(Enum):
        IDLE, INITIALIZING, RUNNING, STOPPED, TERMINATED

    def start(file_path, workspace) -> None  # Launch subprocess, sync breakpoints, run
    def stop() -> None                       # Terminate subprocess
    def continue_() -> None                  # Resume execution
    def step_over/step_into/step_out()       # Stepping commands
    def get_call_stack() -> list[StackFrame] # Fetch stack from subprocess (blocking Future)
    def get_scopes() -> list[Scope]          # Fetch scope references
    def get_variables(ref) -> list[Variable] # Expand variable reference
    def evaluate(expr) -> str                # Eval expression in current frame
```

### 3. Breakpoint Manager (`src/debugger/breakpoint_manager.py`)

Persistent breakpoint tracking, independent of debug sessions. Persists to `~/.zen_ide/breakpoints.json`.

### 4. Debug Panel (`src/debugger/debug_panel.py`)

Right split panel UI (via `SplitPanelManager`). Contains:
- **Toolbar:** Continue, Step Over, Step In, Step Out, Restart, Stop buttons
- **Call Stack:** Clickable stack frames with file:line
- **Variables:** Expandable tree (Locals, Globals) with lazy-load children
- **Breakpoints:** List with enable/disable checkboxes
- **Debug Console:** REPL for evaluating expressions while stopped

### 5. Breakpoint Gutter Renderer (`src/debugger/breakpoint_renderer.py`)

Draws into `ZenSourceView.do_snapshot()` pipeline:
- Red circles for breakpoints (orange for conditional, green for logpoints)
- Yellow arrow + line highlight for current execution position

### 6. Debug Configuration (`src/debugger/debug_config.py`)

Python-only configuration. Supports `.zen/launch.json` or zero-config (auto-detect `.py` files).

## UI Integration

### Keybindings

Function keys handled in capture-phase key handler (`_on_global_key_pressed`) by both keyval and hardware keycode (for laptops where F-row sends media keys without Fn). Also registered via `ActionManager.bind_shortcuts()`.

| Action | Shortcut |
|--------|----------|
| Start/Continue debugging | F5 |
| Stop debugging | Shift+F5 |
| Step Over | F10 |
| Step Into | F11 |
| Step Out | Shift+F11 |
| Toggle Breakpoint | F9 |
| Toggle Debug Panel | Ctrl+Shift+B / Cmd+Shift+B |

A play button (▶) in the header bar also starts debugging.

### Editor Decorations

```
   1  │ def calculate(x, y):
   2  │     result = x + y
 ● 3  │     if result > 10:        ← breakpoint (red dot in gutter)
 → 4  │         print("big!")      ← current line (yellow arrow + highlight)
   5  │     return result
```

Decorations clear automatically when execution resumes or the session ends.

## File Structure

```
src/debugger/
├── __init__.py
├── bdb_debugger.py           # BdbClient (IDE) + _BdbBridge (subprocess)
├── debug_session.py          # Session lifecycle orchestration
├── debug_config.py           # Launch configuration (Python-only)
├── breakpoint_manager.py     # Breakpoint state + persistence
├── debug_panel.py            # Split panel UI (call stack, variables, console)
├── breakpoint_renderer.py    # Gutter overlay for breakpoint markers
└── debug_console.py          # REPL-style expression evaluator widget
```

## Startup Impact

**Zero impact on startup.** All debug code is lazily loaded:
- No module-level imports of `src/debugger/` in the startup path
- Debug panel created only on first use (lazy `@property`)
- Subprocess spawned only when debugging starts

## Dependencies

None. The debugger is pure Python stdlib (`bdb`, `json`, `subprocess`, `threading`).
