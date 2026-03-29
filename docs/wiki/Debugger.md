# Debugger

Zen IDE includes a built-in debugger for Python, C/C++, and JavaScript/TypeScript. Set breakpoints, inspect variables, step through code, and evaluate expressions — all without leaving the editor.

## Supported Languages

| Language | Adapter | Notes |
|---|---|---|
| **Python** | `bdb` (standard library) | No extra installs needed |
| **C / C++** | GDB (Machine Interface) | Requires `gdb` installed; auto-compiles with debug flags |
| **JavaScript** | Node.js V8 Inspector | Requires `node` in PATH |
| **TypeScript** | Node.js V8 Inspector | Best with `tsx` installed (`npm i -g tsx`) |

## Quick Start

1. Open a Python, C/C++, JavaScript, or TypeScript file
2. Click the gutter (left of line numbers) to set a breakpoint
3. Press **F5** to start debugging
4. The debug panel opens automatically when execution hits a breakpoint

That's it — no configuration file required for single-file debugging.

## Keyboard Shortcuts

| Action | macOS | Linux |
|---|---|---|
| Start / Continue | `F5` | `F5` |
| Stop | `Shift+F5` | `Shift+F5` |
| Step Over | `F10` | `F10` |
| Step Into | `F11` | `F11` |
| Step Out | `Shift+F11` | `Shift+F11` |
| Toggle Breakpoint | `F9` | `F9` |
| Toggle Debug Panel | `Cmd+Shift+B` | `Ctrl+Shift+B` |

## Breakpoints

### Types

| Type | Gutter Colour | Description |
|---|---|---|
| Line breakpoint | Red | Pause execution at this line |
| Conditional breakpoint | Orange | Pause only when a condition is true |
| Logpoint | Green | Print a message without pausing |
| Disabled breakpoint | Grey | Breakpoint is set but inactive |

### Setting Breakpoints

- **Click** the gutter area to the left of a line number to toggle a line breakpoint.
- A faint dot preview appears on hover before you click.

### Conditional Breakpoints & Logpoints

Conditional breakpoints pause execution only when a given expression evaluates to true. Logpoints print a message to the debug console without stopping.

### Persistence

Breakpoints are saved to `~/.zen_ide/breakpoints.json` and survive IDE restarts. Breakpoints for deleted files are automatically cleaned up on load.

## The Debug Panel

When a debug session starts, the debug panel appears alongside the editor. It has five sections:

```
┌──────────────────────────────────────────┐
│  [▶] [⤳] [↓] [↑] [⟳] [■]              │  ← toolbar
├──────────────────────────────────────────┤
│  CALL STACK                              │
│    main          main.py:42             │
│    process       utils.py:18            │
├──────────────────────────────────────────┤
│  VARIABLES                               │
│    Name        Value          Type       │
│  ▸ data        [1, 2, 3]     list       │
│    count       3              int        │
├──────────────────────────────────────────┤
│  BREAKPOINTS                             │
│  ☑ main.py:10                            │
│  ☐ utils.py:25  (disabled)               │
├──────────────────────────────────────────┤
│  DEBUG CONSOLE                           │
│  > x + y                                 │
│  47                                      │
└──────────────────────────────────────────┘
```

### Toolbar

Six buttons control execution flow:

| Button | Action |
|---|---|
| **Continue** | Resume until the next breakpoint or program exit |
| **Step Over** | Execute the current line without entering function calls |
| **Step Into** | Step into the function call on the current line |
| **Step Out** | Run until the current function returns |
| **Restart** | Stop and re-launch the debug session |
| **Stop** | Terminate the session |

### Call Stack

Shows the chain of function calls that led to the current pause point. Each frame displays:
- Function name
- Source file (basename)
- Line number

Click a frame to navigate the editor to that location and switch the variable inspection context to that frame.

### Variables

Displays local and global variables for the selected stack frame.

- **Locals** — variables in the current function scope
- **Globals** — module-level variables (filters out dunder attributes)
- **Expandable** — click the arrow on objects, lists, and dicts to inspect their contents (loaded lazily on demand, up to 200 items)
- **Type column** — shows the Python/C type of each variable

### Breakpoints List

Lists all breakpoints across all files with enable/disable checkboxes. Quickly toggle breakpoints without navigating to each file.

### Debug Console

A REPL-style console for evaluating expressions in the context of the current stack frame while paused.

- Type any expression and press Enter to evaluate it
- Use **Up/Down** arrow keys to navigate input history
- Output is colour-coded:
  - **White** — program stdout
  - **Red** — stderr or evaluation errors
  - **Accent colour** — expression results

Program output (`print()` statements, etc.) also appears here in real time.

## Editor Integration

### Gutter Indicators

| Indicator | Meaning |
|---|---|
| Red dot | Active line breakpoint |
| Orange dot | Conditional breakpoint |
| Green dot | Logpoint |
| Grey dot | Disabled breakpoint |
| Yellow highlight + arrow | Current execution line |

When execution pauses, the editor auto-scrolls to the current line and highlights it. The highlight clears when you resume.

### Play Button

The editor tab bar includes a **Play button** (triangle icon) that starts debugging the current file. It is only visible for supported file types.

### Status Bar

The status bar shows the current debug state: *Not debugging*, *Starting...*, *Running*, or *Paused*.

## Launch Configuration

### Zero-Config Mode

For simple cases, just press F5 — Zen IDE auto-detects the file type and launches the appropriate debugger:
- `.py` files use the Python bdb adapter
- `.c`, `.cpp`, `.cc`, `.cxx`, `.c++` files use GDB (auto-compiled with `-g -O0` debug flags)
- `.js`, `.mjs`, `.cjs`, `.jsx` files use Node.js V8 Inspector
- `.ts`, `.mts`, `.cts`, `.tsx` files use Node.js V8 Inspector (via `tsx` if available)

### Custom Configuration (`.zen/launch.json`)

For projects that need arguments, environment variables, or a specific Python interpreter, create a `.zen/launch.json` in your workspace root:

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Python: Current File",
      "type": "python",
      "program": "${file}",
      "args": ["--verbose", "--port", "8080"],
      "cwd": "${workspaceFolder}",
      "python": "/usr/bin/python3.11",
      "env": { "DEBUG": "1" },
      "stopOnEntry": false
    },
    {
      "name": "C++: Debug Main",
      "type": "cppdbg",
      "program": "src/main.cpp",
      "cwd": "${workspaceFolder}"
    },
    {
      "name": "Node: Server",
      "type": "node",
      "program": "src/server.js",
      "args": ["--port", "3000"],
      "cwd": "${workspaceFolder}",
      "env": { "NODE_ENV": "development" }
    }
  ]
}
```

### Configuration Properties

| Property | Description |
|---|---|
| `name` | Display name shown in the launcher |
| `type` | `"python"`, `"cppdbg"`, or `"node"` |
| `program` | File to debug |
| `args` | Command-line arguments (list of strings) |
| `cwd` | Working directory for the debugged program |
| `python` | Path to Python interpreter (Python only) |
| `env` | Environment variables (key-value object) |
| `stopOnEntry` | Pause on the first line of the program (default: `false`) |

### Variable Substitutions

Use these placeholders in any configuration value:

| Variable | Expands To |
|---|---|
| `${file}` | Full path to the current file |
| `${fileBasename}` | Filename only (e.g., `main.py`) |
| `${fileBasenameNoExtension}` | Filename without extension (e.g., `main`) |
| `${fileDirname}` | Directory of the current file |
| `${fileExtname}` | File extension (e.g., `.py`) |
| `${workspaceFolder}` | Workspace root directory |
| `${workspaceFolderBasename}` | Workspace folder name |

## C/C++ Auto-Compilation

When debugging C/C++ files, Zen IDE automatically compiles the source with debug symbols before launching GDB:

1. Looks for a `Makefile` in the source directory (and parent directories)
2. If found, runs `make` with debug flags
3. Otherwise, falls back to direct `gcc`/`g++` compilation with `-g -O0`

## JavaScript / TypeScript Debugging

Node.js debugging uses the V8 Inspector protocol (Chrome DevTools Protocol) over WebSocket. Zen IDE launches `node --inspect-brk` and connects automatically.

### Requirements

- **JavaScript**: `node` must be in your PATH
- **TypeScript**: Install [`tsx`](https://github.com/privatenumber/tsx) globally for the best experience:
  ```bash
  npm install -g tsx
  ```
  If `tsx` is not found, Zen falls back to plain `node` (which won't handle `.ts` files without a loader).

### How It Works

1. A free port is selected automatically
2. Node.js is launched with `--inspect-brk=127.0.0.1:<port>`
3. Zen connects to the V8 Inspector WebSocket endpoint
4. Breakpoints, stepping, and variable inspection work via the Debugger and Runtime CDP domains

### Console Output

`console.log()` and other console methods appear in the debug console in real time. Errors and warnings are highlighted in red.

## Tips

- **F5 is context-aware** — if already paused, it resumes; if already running, it does nothing; if terminated, it starts a new session.
- **Breakpoints work across sessions** — set them before starting the debugger and they'll be active when the session begins.
- **Frame switching** — click different call stack frames to inspect variables at any level of the call chain, not just the current function.
- **Expression evaluation** — use the debug console to test fixes or inspect complex expressions before modifying code.
