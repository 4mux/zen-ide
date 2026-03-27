# Debugging — Design Document

**Created_at:** 2026-03-03
**Updated_at:** 2026-03-27
**Status:** Ready for implementation
**Goal:** Implement Debug Adapter Protocol (DAP) support for multi-language debugging
**Scope:** `src/debugger/`, language-independent DAP integration (C, C++, Python, Rust, JavaScript)

---

## Overview

Zen IDE debugging integration via the **Debug Adapter Protocol (DAP)** — the same open standard used by Neovim (nvim-dap), Emacs, and other modern editors. DAP decouples the IDE UI from language-specific debuggers, so one implementation unlocks debugging for C, C++, Python, Rust, JavaScript, and any language with a DAP adapter.

> **Note:** `src/debug/` is already used by the widget inspector (GTK DevTools-like inspect mode). Debugger code lives in `src/debugger/`.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                        Zen IDE                           │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │  Breakpoint  │  │  Debug Panel │  │ Editor Gutter │  │
│  │  Manager     │  │  (variables, │  │ (breakpoint   │  │
│  │              │  │   call stack, │  │  markers,     │  │
│  │              │  │   watches,    │  │  current line │  │
│  │              │  │   output)     │  │  highlight)   │  │
│  └──────┬───────┘  └──────┬───────┘  └───────┬───────┘  │
│         │                 │                   │          │
│         └─────────┬───────┘───────────────────┘          │
│                   │                                      │
│          ┌────────▼────────┐                             │
│          │   DAP Client    │   JSON messages over stdio  │
│          │ (dap_client.py) │◄───────────────────────┐    │
│          └────────┬────────┘                        │    │
│                   │                                 │    │
└───────────────────┼─────────────────────────────────┼────┘
                    │ subprocess (stdio)              │
           ┌────────▼───────────────────────────────────┐
           │            Debug Adapter                    │
           │  (debugpy, codelldb, cppdbg, js-debug)     │
           └────────┬───────────────────────────────────┘
                    │
           ┌────────▼────────┐
           │   Debuggee      │
           │  (user program) │
           └─────────────────┘
```

### Why DAP?

| Approach | Pros | Cons |
|----------|------|------|
| **DAP (chosen)** | Multi-language, battle-tested protocol, reuse existing adapters | Moderate implementation effort |
| Direct subprocess/pdb | Simple, Python-only | Single language, brittle parsing |
| GDB/MI protocol | Powerful for C/C++/Rust | Not language-agnostic, complex |

DAP gives us language-independent debugging through a single UI — the same protocol layer supports Python (`debugpy`), C/C++ (`cppdbg` / `codelldb`), Rust (`codelldb`), and JavaScript (`js-debug`).

## Components

### 1. DAP Client (`src/debugger/dap_client.py`)

The protocol layer. Communicates with debug adapters via JSON over stdio.

**Responsibilities:**
- Launch debug adapter as subprocess
- Send DAP requests (initialize, setBreakpoints, launch, continue, stepIn, etc.)
- Parse DAP responses and events
- Emit signals to UI components via callbacks

**Key classes:**

```python
class DAPClient:
    """Manages communication with a debug adapter subprocess."""

    def __init__(self, adapter_command: list[str], on_event: Callable):
        self._process: subprocess.Popen | None = None
        self._seq = 0
        self._pending: dict[int, Future] = {}
        self._on_event = on_event  # callback for DAP events

    # Lifecycle
    def start(self) -> None: ...       # Launch adapter subprocess
    def stop(self) -> None: ...        # Terminate adapter

    # DAP Requests
    def initialize(self) -> dict: ...
    def launch(self, program: str, **kwargs) -> dict: ...
    def attach(self, port: int) -> dict: ...
    def set_breakpoints(self, source: str, lines: list[int]) -> dict: ...
    def continue_(self, thread_id: int) -> dict: ...
    def next(self, thread_id: int) -> dict: ...       # Step over
    def step_in(self, thread_id: int) -> dict: ...
    def step_out(self, thread_id: int) -> dict: ...
    def pause(self, thread_id: int) -> dict: ...
    def disconnect(self) -> dict: ...

    # Inspection
    def stack_trace(self, thread_id: int) -> list[StackFrame]: ...
    def scopes(self, frame_id: int) -> list[Scope]: ...
    def variables(self, ref: int) -> list[Variable]: ...
    def evaluate(self, expression: str, frame_id: int) -> str: ...
```

**Transport protocol** — DAP uses HTTP-like headers over stdio:

```
Content-Length: 119\r\n
\r\n
{"seq":1,"type":"request","command":"initialize","arguments":{"adapterID":"python","clientID":"zen-ide",...}}
```

**Threading model:**
- Reader thread reads adapter stdout continuously, parses JSON messages
- Responses matched to pending requests by `seq` / `request_seq`
- Events dispatched to main GTK thread via `main_thread_call()` (from `shared.main_thread`) — same pattern used by `GutterDiffRenderer` and `DiagnosticsManager`
- All UI updates happen on main thread (GTK requirement)

### 2. Debug Session Manager (`src/debugger/debug_session.py`)

Orchestrates the debug lifecycle. Sits between UI and DAP client.

```python
class DebugSession:
    """Manages a single debug session lifecycle."""

    class State(Enum):
        IDLE = "idle"
        INITIALIZING = "initializing"
        RUNNING = "running"
        STOPPED = "stopped"       # Hit breakpoint / step completed
        TERMINATED = "terminated"

    def __init__(self, config: DebugConfig):
        self.state = State.IDLE
        self._client: DAPClient | None = None
        self._config = config
        self._threads: dict[int, ThreadInfo] = {}
        self._stopped_thread_id: int | None = None

    # Lifecycle
    def start(self) -> None: ...
    def stop(self) -> None: ...

    # Execution control
    def continue_(self) -> None: ...
    def step_over(self) -> None: ...
    def step_into(self) -> None: ...
    def step_out(self) -> None: ...
    def pause(self) -> None: ...
    def restart(self) -> None: ...

    # Inspection (fetches from adapter, caches)
    def get_call_stack(self) -> list[StackFrame]: ...
    def get_variables(self, scope: str) -> list[Variable]: ...
    def evaluate(self, expr: str) -> str: ...

    # DAP event handlers
    def _on_stopped(self, event: dict) -> None: ...
    def _on_terminated(self, event: dict) -> None: ...
    def _on_output(self, event: dict) -> None: ...
```

### 3. Breakpoint Manager (`src/debugger/breakpoint_manager.py`)

Persistent breakpoint tracking, independent of debug sessions.

```python
class BreakpointManager:
    """Manages breakpoints across files. Persists to ~/.zen_ide/breakpoints.json (SETTINGS_DIR)."""

    def toggle(self, file_path: str, line: int) -> bool: ...
    def add(self, file_path: str, line: int, condition: str = "") -> Breakpoint: ...
    def remove(self, file_path: str, line: int) -> None: ...
    def get_for_file(self, file_path: str) -> list[Breakpoint]: ...
    def get_all(self) -> dict[str, list[Breakpoint]]: ...
    def clear_file(self, file_path: str) -> None: ...
    def clear_all(self) -> None: ...

    # Persistence
    def save(self) -> None: ...
    def load(self) -> None: ...

    # Change notification
    def subscribe(self, callback: Callable) -> None: ...
```

**Breakpoint types (phased):**

| Type | Phase | Description |
|------|-------|-------------|
| Line breakpoint | Phase 1 | Break at line N |
| Conditional breakpoint | Phase 2 | Break when expression is true |
| Logpoint | Phase 2 | Log message instead of breaking |
| Exception breakpoint | Phase 3 | Break on raised/uncaught exceptions |
| Function breakpoint | Phase 3 | Break when function is entered |

### 4. Debug Panel (`src/debugger/debug_panel.py`)

Bottom panel UI showing debug state. Registered via `SplitPanelManager` — same pattern as `diff_view` and `system_monitor` (see `window_panels.py`).

```
+------------------------------------------------------+
| > Continue | >> Step Over | v Step In | ^ Step Out | Stop | Restart |
+----------------------+-------------------------------+
| CALL STACK           | VARIABLES                     |
|                      |                               |
| > main()     line 42 | > Locals                      |
|   foo()      line 17 |   x = 42                      |
|   bar()      line 8  |   name = "hello"              |
|                      |   items = [1, 2, 3]           |
|                      | > Globals                     |
|                      |   __name__ = "__main__"       |
+----------------------+-------------------------------+
| BREAKPOINTS          | DEBUG CONSOLE                 |
|                      |                               |
| * main.py:42         | > print(x)                   |
| * utils.py:17        | 42                            |
| o test.py:8 (disabled| > len(items)                  |
|                      | 3                              |
+----------------------+-------------------------------+
```

**Sub-panels:**

| Panel | Content | Interaction |
|-------|---------|-------------|
| **Call Stack** | Stack frames with file:line | Click to navigate to frame |
| **Variables** | Expandable tree: locals, globals, closures | Expand objects, hover for type info |
| **Breakpoints** | All breakpoints with enable/disable toggles | Click to navigate, checkbox to toggle |
| **Debug Console** | Program output + REPL for evaluating expressions | Type expression, Enter to evaluate |

**Integration — lazy `@property` in `ZenIDEWindow`** (same pattern as `diff_view`, `system_monitor`, `dev_pad`):

```python
# In ZenIDEWindow (zen_ide.py)
@property
def debug_panel(self):
    if self._debug_panel is None:
        from debugger.debug_panel import DebugPanel
        self._debug_panel = DebugPanel(self)
        self._debug_panel.set_visible(False)
        self.split_panels.register("debug", self._debug_panel, ...)
    return self._debug_panel
```

### 5. Breakpoint Gutter Renderer (`src/debugger/breakpoint_renderer.py`)

Visual breakpoint markers in the editor gutter. Follows the `GutterDiffRenderer` overlay pattern — draws into the `ZenSourceView.do_snapshot()` pipeline alongside diff bars, color previews, and diagnostics (see `source_view.py:_do_custom_snapshot`).

```python
class BreakpointRenderer:
    """Draws breakpoint markers and current-line highlight in the editor gutter."""

    def __init__(self, view: GtkSource.View, breakpoint_mgr: BreakpointManager):
        self._view = view
        self._breakpoint_mgr = breakpoint_mgr
        self._current_line: int | None = None  # execution pointer

    def draw(self, snapshot, vis_range):
        """Called from ZenSourceView._do_custom_snapshot(). Draws:
        - Red circles for breakpoints
        - Yellow arrow for current execution line
        - Yellow background highlight on current line
        vis_range is (start_line, end_line) tuple, pre-computed by source_view.
        """
        ...

    def set_current_line(self, line: int | None):
        """Set/clear the current execution pointer."""
        self._current_line = line
        self._view.queue_draw()
```

**Snapshot integration** — add to `_do_custom_snapshot` in `source_view.py`:

```python
# After gutter_diff_renderer draw, before diagnostics
if self._breakpoint_renderer:
    self._breakpoint_renderer.draw(snapshot, vis_range)
```

**Click-to-toggle breakpoints** — extend existing click handler in `input.py` (alongside diagnostic click detection):

```python
# In ZenSourceViewInputMixin._on_click — before diagnostic check
# Gutter area click detection (left of line numbers)
if n_press == 1 and x < GUTTER_BREAKPOINT_AREA_WIDTH:
    bx, by = self.view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
    _, it = self.view.get_iter_at_location(bx, by)
    line = it.get_line() + 1
    self._breakpoint_mgr.toggle(self.file_path, line)
    gesture.set_state(Gtk.EventSequenceState.CLAIMED)
    return True
```

### 6. Debug Configuration (`src/debugger/debug_config.py`)

Launch configurations stored per-workspace in `.zen/launch.json`.

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Python: Current File",
      "type": "python",
      "request": "launch",
      "program": "${file}",
      "console": "integratedTerminal"
    },
    {
      "name": "C/C++: Build and Debug",
      "type": "cppdbg",
      "request": "launch",
      "program": "${workspaceFolder}/build/${fileBasenameNoExtension}",
      "preLaunchTask": "make"
    },
    {
      "name": "Rust: Current Project",
      "type": "codelldb",
      "request": "launch",
      "cargo": { "args": ["build"] },
      "program": "${workspaceFolder}/target/debug/${workspaceFolderBasename}"
    },
    {
      "name": "Node.js: Current File",
      "type": "node",
      "request": "launch",
      "program": "${file}"
    }
  ]
}
```

**Built-in adapter registry:**

| Language | Adapter | Command | Auto-detect |
|----------|---------|---------|-------------|
| Python | debugpy | `python -m debugpy --listen 0 --wait-for-client {program}` | `*.py` files |
| C | cppdbg / CodeLLDB | `codelldb --port 0` or GDB via cppdbg | `*.c`, `Makefile` |
| C++ | cppdbg / CodeLLDB | `codelldb --port 0` or GDB via cppdbg | `*.cpp`, `*.cc`, `CMakeLists.txt` |
| Rust | CodeLLDB | `codelldb --port 0` | `*.rs`, `Cargo.toml` present |
| JavaScript/TypeScript | js-debug | `node js-debug-adapter` | `*.js`, `*.ts` |

**Zero-config mode:** When no `launch.json` exists, Zen auto-detects the language from the current file (using the same detection as `language_detect.py`) and generates a default configuration. User just presses F5.

## UI Integration

### Keybindings

Registered via `ActionManager.bind_shortcuts()` in `_bind_shortcuts()` (`zen_ide.py`), using `mod`/`mod_shift` for platform-appropriate modifier keys.

| Action | macOS | Linux | Rationale |
|--------|-------|-------|-----------|
| Start/Continue debugging | `F5` | `F5` | Universal debugger convention |
| Stop debugging | `Shift+F5` | `Shift+F5` | Standard |
| Step Over | `F10` | `F10` | Universal debugger convention |
| Step Into | `F11` | `F11` | Universal |
| Step Out | `Shift+F11` | `Shift+F11` | Universal |
| Toggle Breakpoint | `F9` | `F9` | Universal |
| Toggle Debug Panel | `Cmd+Shift+B` | `Ctrl+Shift+B` | — |

> **Note:** `Cmd+Shift+D` / `Ctrl+Shift+D` is already bound to Sketch Pad (`open_sketch_pad`). Debug panel uses `Ctrl+Shift+B` instead. No other conflicts with existing shortcuts in `_bind_shortcuts()`.

### Editor Decorations

When a debug session is active and stopped at a breakpoint:

```
   1  │ def calculate(x, y):
   2  │     result = x + y
 ● 3  │     if result > 10:        ← breakpoint (red dot in gutter)
 → 4  │         print("big!")      ← current line (yellow arrow + highlight)
   5  │     return result
```

- **Red dot (●):** Breakpoint set at this line
- **Yellow arrow (→):** Current execution position
- **Line highlight:** Subtle yellow background on the current execution line
- **Grayed dot (○):** Disabled breakpoint

### Status Bar Integration

The `StatusBar` (`status_bar.py`) already shows diagnostics and cursor position. During an active debug session, extend the right section to show debug state:

```
[Debugging: main.py] [Stopped at line 42] [Thread 1]
```

### Dev Pad Integration

The Dev Pad (`dev_pad.py`) tracks user activities in `~/.zen_ide/dev_pad.json`. Debug sessions logged as activities:

```
Debug session started — main.py (Python)
Breakpoint hit — main.py:42
Debug session ended — 2m 34s
```

## File Structure

```
src/debugger/
├── __init__.py
├── dap_client.py           # DAP protocol transport + message handling
├── debug_session.py         # Session lifecycle orchestration
├── debug_config.py          # Launch configuration loading + adapter registry
├── breakpoint_manager.py    # Breakpoint state + persistence
├── debug_panel.py           # Bottom panel UI (call stack, variables, console)
├── breakpoint_renderer.py   # Gutter overlay for breakpoint markers (snapshot pipeline)
└── debug_console.py         # REPL-style expression evaluator widget
```

> `src/debug/` remains the widget inspector (`widget_inspector.py`, `inspect_popup.py`).

## Implementation Phases

### Phase 1 — Foundation (MVP)

**Goal:** Language-independent DAP core + Python debugging with breakpoints, stepping, variable inspection.

| Task | Description |
|------|-------------|
| DAP Client | JSON/stdio transport, request/response/event handling |
| Debug Session Manager | Lifecycle, state machine, thread management |
| Breakpoint Manager | Toggle/persist breakpoints, change notifications |
| Breakpoint Gutter Renderer | Red dots in gutter via snapshot pipeline, click to toggle |
| Current Line Highlight | Yellow arrow + line highlight during stopped state |
| Debug Panel (basic) | Call stack + variables tree + toolbar (register with `split_panels`) |
| Keybindings | F5, F9, F10, F11, Shift+F11, Ctrl+Shift+B |
| Python adapter integration | debugpy launch, zero-config for `*.py` |

**Phase 1 delivers:** Click gutter to set breakpoint, F5 to debug, step through code, see variables and call stack.

### Phase 2 — Core Languages

**Goal:** Extend to C, C++, Rust, JavaScript — the DAP core is language-independent, so this is adapter configuration + testing.

| Task | Description |
|------|-------------|
| C/C++ adapter (cppdbg / CodeLLDB) | GDB/LLDB-backed debugging via DAP, zero-config for `*.c`, `*.cpp` |
| Rust adapter (CodeLLDB) | CodeLLDB integration, zero-config for `Cargo.toml` projects |
| JavaScript/TypeScript adapter (js-debug) | js-debug integration, zero-config for `*.js`, `*.ts` |
| `launch.json` support | Load/save configurations, config picker |
| Debug Console (REPL) | Evaluate expressions while stopped |

### Phase 3 — Polish

| Task | Description |
|------|-------------|
| Conditional breakpoints | Right-click breakpoint, add condition |
| Logpoints | Log messages without stopping |
| Hover variable inspection | Hover over variable in editor, tooltip with value |
| Exception breakpoints | Break on caught/uncaught exceptions |
| Status bar integration | Debug state in `StatusBar` |
| Dev Pad logging | Log debug session activities |
| Watch expressions panel | Persistent expression watches |

### Phase 4 — Advanced

| Task | Description |
|------|-------------|
| Go adapter (Delve) | `dlv dap` integration |
| Multi-thread debugging | Thread picker, per-thread stepping |
| Remote debugging | Attach to remote processes (SSH tunnel) |
| Debug configurations UI | Visual editor for `launch.json` |
| Inline variable values | Show variable values inline after statements |
| Data breakpoints | Break when a variable's value changes |
| Disassembly view | Low-level view for C/C++/Rust |

## Startup Impact

**Zero impact on startup.** All debug code is lazily loaded — same strategy as `diff_view`, `system_monitor`, `dev_pad`:

- No module-level imports of `src/debugger/` anywhere in the startup path
- Debug panel created only on first F5 press or Ctrl+Shift+B (lazy `@property`)
- `BreakpointRenderer` attached only when a file with breakpoints is opened
- DAP client subprocess spawned only when debugging starts

**Verification:** Run `make startup-time` before and after — numbers must not change.

## Dependencies

| Package | Purpose | Install |
|---------|---------|---------|
| (none for Phase 1) | DAP client is pure Python — just JSON over stdio | — |
| `debugpy` | Python debug adapter (user must install) | `pip install debugpy` |

The DAP client itself requires **no additional dependencies** — it's pure Python using `subprocess`, `json`, `threading`, and `socket` from the standard library. Debug adapters are external tools the user installs per-language.

## Configuration Files

| File | Purpose | Location |
|------|---------|----------|
| `launch.json` | Debug launch configs | `.zen/launch.json` in workspace root |
| `breakpoints.json` | Persisted breakpoints | `~/.zen_ide/breakpoints.json` (alongside `settings.json`, `dev_pad.json`) |

## Integration Points Summary

| Component | File | How to integrate |
|-----------|------|------------------|
| Snapshot pipeline | `source_view.py:_do_custom_snapshot` | Add `breakpoint_renderer.draw(snapshot, vis_range)` |
| Gutter click | `input.py:_on_click` | Add breakpoint toggle before diagnostic check |
| Lazy init | `zen_ide.py` | Add `debug_panel` `@property` alongside `diff_view`, `dev_pad` |
| Panel registration | `window_panels.py` | `self.split_panels.register("debug", ...)` |
| Keybindings | `zen_ide.py:_bind_shortcuts` | Add F5, F9, F10, F11, Ctrl+Shift+B |
| Actions | `zen_ide.py:_create_actions` | Add `debug_start`, `debug_stop`, `toggle_breakpoint`, etc. |
| Threading | `shared/main_thread.py` | Use `main_thread_call()` for DAP event dispatch |

## Decisions

1. **Panel placement:** Right split panel via `SplitPanelManager` — consistent with diff view and system monitor. Debug panel needs horizontal space for variables + call stack side by side.

2. **Adapter installation:** Prompt the user to install on first use with clear instructions. No auto-install.

3. **Terminal integration:** Program stdout/stderr goes to Debug Console panel by default; `"console": "integratedTerminal"` option redirects to the existing `TerminalView` instead.

4. **Directory naming:** `src/debugger/` (not `src/debug/`) since `src/debug/` is the widget inspector.
