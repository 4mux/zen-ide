# Filename ↔ Class Alignment Plan

**Created_at:** 2026-03-27
**Updated_at:** 2026-03-27
**Status:** Planned
**Goal:** Rename every file so its snake_case name exactly matches its PascalCase class
**Scope:** All 20 violations in `src/`

---

## How to execute each rename

1. `git mv` the file
2. Update every import that references the old module name
3. Update `__init__.py` re-exports if applicable
4. `make run` — verify the app starts
5. Commit

---

## Batch 1 — Zero or one import site (low risk)

These files are imported in at most one place, so each rename is a single-commit, < 5 min task.

| # | Old file | Class | New file | Importers |
|---|----------|-------|----------|-----------|
| 1 | `popups/path_breadcrumb.py` | `SystemContextMenu` | `popups/system_context_menu.py` | `popups/system_dialogs.py` |
| 2 | `popups/recent_items.py` | `SystemSelectionDialog` | `popups/system_selection_dialog.py` | `popups/system_dialogs.py` |
| 3 | `editor/fold_gutter.py` | `LineNumberFoldRenderer` | `editor/line_number_fold_renderer.py` | `editor/fold_manager.py` |
| 4 | `shared/cursor_blink.py` | `CursorBlinker` | `shared/cursor_blinker.py` | `treeview/tree_panel.py` |
| 5 | `shared/debounce.py` | `Debouncer` | `shared/debouncer.py` | `shared/debounce.py` (docstring), `main/window_state.py` |
| 6 | `editor/nav_highlight.py` | `NavigationHighlight` | `editor/navigation_highlight.py` | `navigation/code_navigation.py` |
| 7 | `terminal/terminal_jog_wheel.py` | `JogWheelScrollbarMixin` | `terminal/jog_wheel_scrollbar.py` | `ai/ai_terminal_view.py` |
| 8 | `editor/editor_view/source_view.py` | `ZenSourceView` | `editor/editor_view/zen_source_view.py` | `editor/editor_view/__init__.py`, `editor/editor_view/editor_tab.py` |
| 9 | `shared/system_monitor.py` | `SystemMonitorPanel` | `shared/system_monitor_panel.py` | `zen_ide.py`, `popups/system_monitor_dialog.py` |
| 10 | `editor/tree_sitter_buffer.py` | `TreeSitterBufferCache` | `editor/tree_sitter_buffer_cache.py` | `editor/semantic_highlight.py`, `editor/fold_manager.py`, `editor/editor_view/editor_tab.py` |

- [x] Status: not started

---

## Batch 2 — Multiple import sites (medium risk)

More importers to update. Still straightforward — just more lines to touch.

| # | Old file | Class | New file | Import count |
|---|----------|-------|----------|--------------|
| 11 | `icons/icon_manager.py` | `Icons` | `icons/icons.py` | 1 (`icons/__init__.py`) |
| 12 | `treeview/tree_panel.py` | `CustomTreePanel` | `treeview/custom_tree_panel.py` | 2 (`treeview/__init__.py`, `treeview/tree_view.py`) |
| 13 | `shared/focus_manager.py` | `ComponentFocusManager` | `shared/component_focus_manager.py` | ~15 files across `ai/`, `shared/`, `treeview/`, `main/`, `terminal/`, `editor/` |
| 14 | `themes/theme_model.py` | `Theme` | `themes/theme.py` | ~40 theme definition files + `themes/__init__.py`, `themes/theme_manager.py` |
| 15 | `themes/theme_manager.py` | `ThemeAwareMixin` | `themes/theme_aware.py` | `themes/__init__.py`, 3 preview files |

- [x] Status: not started

---

## Batch 3 — Structural / high-touch (needs care)

These touch entry points, `__init__.py` packages, or require a file split.

| # | Old file | Class | New file | Notes |
|---|----------|-------|----------|-------|
| 16 | `app_modules.py` | `ZenIDEApp` | `zen_ide_app.py` | Imported in `zen_ide.py`; circular-import comment — test carefully |
| 17 | `zen_ide.py` | `ZenIDEWindow` | `zen_ide_window.py` | Main entry point. Also registers itself as `zen_ide` in `sys.modules` (line 14). Multiple lazy `import zen_ide` across codebase. Rename the file **and** update the `sys.modules` alias. |
| 18 | `editor/preview/markdown_canvas/core.py` | `MarkdownCanvas` | `editor/preview/markdown_canvas/markdown_canvas.py` | Re-exported in `__init__.py` |
| 19 | `sketch_pad/canvas/core.py` | `SketchCanvas` | `sketch_pad/canvas/sketch_canvas.py` | Re-exported in `__init__.py`; also imported in `keyboard.py` |
| 20 | `ai/cli/cli_manager.py` | `CLIProvider` + `CLIManager` | Split → `ai/cli/cli_provider.py` + `ai/cli/cli_manager.py` | Two classes violate one-class-per-file. `CLIProvider` (ABC) is imported by `claude_cli.py`, `copilot_cli.py`. `CLIManager` is imported everywhere via `cli_manager` singleton. Split `CLIProvider` out first, then the file naturally keeps `CLIManager`. |

- [x] Status: not started

---

## Notes

- **No functional changes** — only file renames, import updates, and `__init__.py` adjustments.
- Each rename is one commit so any breakage is easy to bisect and revert.
- Run `make run` after every commit to catch import errors immediately.
- Standard updated: `docs/standards/code_style.md` (2026-03-27) now explicitly
  requires filename = class name, no exceptions.
