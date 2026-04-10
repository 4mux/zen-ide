# GTK Logging Customisation

## Problem

GTK4 and GLib emit warnings/criticals at runtime that pollute the console.
Many originate from upstream bugs or system theme files — unfixable in our codebase.
Without filtering, the terminal output becomes noisy and real issues get buried.

## GLib Logging Architecture

GLib has two logging paths:

### 1. Legacy log handlers (`GLib.log_set_handler`)

- Per-domain (e.g. `"Gtk"`, `"Gdk"`, `"GLib-GIO"`).
- Receives `(domain, level, message, user_data)`.
- Return nothing to suppress; call `GLib.log_default_handler(...)` to forward.
- Only catches messages emitted via `g_log()` — **not** structured logs.

### 2. Structured log writer (`GLib.log_set_writer_func`)

- Global — one per process, must be set before any logging occurs.
- Receives `(level, fields, n_fields, user_data)` in PyGObject.
- `GLib.log_writer_default(level, fields, user_data)` to forward (note: no `n_fields`).
- Return `GLib.LogWriterOutput.HANDLED` to suppress.
- Catches **all** `g_log_structured()` messages.

### 3. fd-level stderr filter (what we use)

GTK4 emits some warnings (notably CSS theme parser errors) through code paths
that bypass both of the above in PyGObject. These write directly to stderr at
the C level. The only reliable way to catch them is filtering at the file
descriptor level:

```
fd 2 (stderr) ──> pipe(write end) ──> pump thread ──> original fd 2
                                        │
                                        └── drops lines matching needles
```

## Current Implementation

Location: `src/zen_ide_window.py`, installed before `Gtk.init()`.

### Per-domain handlers

| Domain      | Level    | Filter                                         | Reason                                           |
|-------------|----------|-------------------------------------------------|--------------------------------------------------|
| `Gtk`       | WARNING  | `"Broken accounting of active state"`           | GNOME bug #3356, #6442                           |
| `Gtk`       | WARNING  | `"Theme parser error"`                          | System theme CSS (e.g. gtk-dark.css)             |
| `Gdk`       | CRITICAL | `"gdk_display_link_source_pause"`               | macOS display-link race condition                |
| `GLib-GIO`  | CRITICAL | `"g_list_store_remove"`                         | GTK list-store internal error                    |
| `GLib`      | WARNING  | `"poll(2) failed due to: Resource temporarily"` | macOS EAGAIN from non-blocking fd in event loop  |

### Stderr pipe filter

Suppresses any line containing substrings from `_SUPPRESSED_SUBSTRINGS`:

- `"Theme parser error"` — system theme CSS errors outside our control.
- `"Broken accounting of active state"` — upstream GTK4 bug.

The pump thread also collapses the blank line GLib prints before each warning
(`\n(prog:pid): ...\n` pattern), preventing orphaned empty lines.

## Adding a New Filter

1. **Identify the source**: run with `G_MESSAGES_DEBUG=all` to see domain/level.
2. **Try a per-domain handler first** — simplest approach, works for `g_log()` messages.
3. **If it still leaks through**, add the substring to `_SUPPRESSED_SUBSTRINGS` — the stderr pipe will catch it.
4. **Document** the filter in the table above with the upstream bug reference.

## Why Not Just `2>/dev/null`

Blanket suppression hides real errors — segfaults, assertion failures, actual
bugs in our code. The goal is surgical: drop known-unfixable noise, keep
everything else visible.
