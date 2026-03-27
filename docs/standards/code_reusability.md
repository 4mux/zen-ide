# Code Reusability

**Created_at:** 2026-03-27  
**Updated_at:** 2026-03-27  
**Status:** Active  
**Goal:** Enforce reuse of shared utilities and prevent duplication across modules  
**Scope:** All files in `src/`  

---

## Principle

Be sensible about reusing code. Before writing a new helper, check if `src/shared/` already provides one. Duplicating logic across modules creates maintenance debt and divergent behavior.

## Rules

- Always check `src/shared/utils.py` and `src/shared/` before writing local helpers for common operations (color conversion, event handling, file operations, etc.).
- If a utility is needed in two or more modules, it belongs in `src/shared/`.
- Do not copy-paste helper functions between files — extract to shared and import.
- When adding a new shared utility, add tests in `tests/shared/`.

## Shared Utilities Reference

Key modules in `src/shared/`:

| Module | Purpose |
|---|---|
| `utils.py` | Color conversion (`hex_to_rgba`, `hex_to_gdk_rgba`, `tuple_to_gdk_rgba`, `hex_to_rgba_css`, `blend_hex_colors`), text helpers, path utilities |
| `gtk_event_utils.py` | GTK pointer/click hit-test helpers (`is_button_click`, `is_click_inside_widget`) |
| `focus_border_mixin.py` | Shared focus/click border behavior for panels |
| `settings.py` | Centralized settings access (`get_setting`) |
| `git_manager.py` | Git operations singleton |
| `main_thread.py` | Thread-safe GTK main thread dispatch |
