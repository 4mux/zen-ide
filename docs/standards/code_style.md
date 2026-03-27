# Code Style

**Created_at:** 2026-01-16  
**Updated_at:** 2026-03-27
**Status:** Active  
**Goal:** Define naming conventions and file structure rules for all source code  
**Scope:** All files in `src/`  

---

## One Class Per File

Each class should be in its own standalone file — no nested or multiple classes per file.

## Naming Conventions

- File names use `snake_case`
- **Every file must be named after its class — no exceptions.** The snake_case
  filename must be the exact conversion of the PascalCase class name:
  - `git_manager.py` → `GitManager`
  - `git_ignore_utils.py` → `GitIgnoreUtils`
  - `diff_view.py` → `DiffView`
- **Mixin files** follow the same rule but drop the `Mixin` suffix from the
  filename: `window_layout.py` → `WindowLayoutMixin`
- When renaming a file, rename the class to match (and vice versa)
- Do not use generic names like `core.py`, `utils.py` (in non-shared dirs),
  `base.py`, or `helpers.py` — name the file after the class it contains

## File Length Limit

No single file should exceed **500 lines**. When a file grows beyond this limit,
split it by responsibility into a package or sibling modules. Use `__init__.py`
re-exports to preserve the public API.

See [`docs/2026_03_26_500_line_limit_plan.md`](../2026_03_26_500_line_limit_plan.md)
for the full reorganisation plan covering existing files that exceed this limit.

## Function Locality

Keep related logic local when it is not reused.

- Do not split a function into multiple files or distant helpers if the extracted parts are not shared.
- If a function is still reasonably small and readable, prefer keeping it together in one place.
- Extract helpers only when they improve clarity **and** have clear reuse or a strong separation-of-concerns reason.
