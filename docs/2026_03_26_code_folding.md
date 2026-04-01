# Code Folding

**Created_at:** 2026-03-26  
**Updated_at:** 2026-03-27   
**Status:** Implemented   
**Goal:** Implement code folding (collapse/expand) for the editor   
**Scope:** `src/editor/fold_manager.py`, `src/editor/editor_view.py`  

---

## Overview

Code folding allows users to collapse multi-line blocks (functions, classes, loops, objects, braces, etc.) down to a single header line. The fold header line remains visible with a chevron indicating the collapsed state.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                       FoldManager                            │
│                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────┐  │
│  │ Fold Region      │  │ LineNumberFold   │  │ Invisible  │  │
│  │ Detection        │  │ Renderer         │  │ Tag        │  │
│  │ (tree-sitter +   │  │ (custom gutter)  │  │ Manager    │  │
│  │  brace matching) │  │                  │  │            │  │
│  └──────┬──────────┘  └──────┬───────────┘  └─────┬──────┘  │
│         │                    │                     │         │
│         ▼                    ▼                     ▼         │
│  TreeSitterBuffer       GtkSource.              GtkTextTag   │
│  Cache + brace scan     GutterRenderer          "fold-hidden"│
└──────────────────────────────────────────────────────────────┘
```

### Components

| Component | Responsibility |
|-----------|---------------|
| **FoldManager** | Central coordinator: owns fold state, computes regions, toggles folds, respects `show_line_numbers` setting |
| **LineNumberFoldRenderer** | Custom `GtkSource.GutterRenderer` that replaces built-in line numbers; draws both line numbers and fold chevrons in a single gutter column |
| **Fold region detection** | Tree-sitter AST for Python/JS/TS/TSX; brace/bracket matching for JSON and other languages |
| **Invisible tag manager** | Applies/removes `invisible` text tags on complete lines to hide/show folded content |

---

## Fold Region Detection

### Tree-sitter (Python, JavaScript, TypeScript, TSX)

Foldable regions are identified by walking the tree-sitter AST and collecting nodes whose type is in the foldable set and that span 2+ lines:

```python
FOLD_NODE_TYPES = {
    "python": {"function_definition", "class_definition", "if_statement", ...},
    "javascript": {"function_declaration", "arrow_function", "object", ...},
    "typescript": {# javascript + "interface_declaration", "enum_declaration", ...},
    "tsx": {# same as typescript},
}
```

### Brace/bracket matching (JSON and all other languages)

For languages without tree-sitter support, fold regions are detected by matching `{}`/`[]` pairs across lines. The parser correctly ignores braces inside string literals.

### Recomputation

- Recomputed on buffer change, debounced at 500ms
- Initial computation 200ms after FoldManager creation
- Collapsed state preserved across recomputation by proximity matching (within +/-2 lines)

---

## Line Hiding Mechanism

### Complete-line invisible tags

The invisible tag is applied to **complete lines only** — from the start of `(start_line+1)` to the start of `(end_line+1)`. The fold header line is never touched by the invisible tag. This avoids Pango byte-index corruption that occurs when a line is partially invisible.

### Cursor safety

Before collapsing, if the cursor is inside the fold region, it is moved to the fold header line to prevent GTK's internal cursor rendering from crashing on invisible text.

### Auto-expand

When the cursor enters a collapsed region (via find, go-to-line, etc.), the fold auto-expands via a deferred `GLib.idle_add` callback on the `mark-set` signal.

---

## Gutter Renderer: LineNumberFoldRenderer

A single custom `GtkSource.GutterRenderer` replaces the built-in line number renderer. It draws:

1. **Line numbers** — right-aligned, with current-line highlight
2. **Fold chevrons** — right of numbers, using ZenIcons font glyphs:
   - `\U000f0142` (chevron-right) for collapsed folds
   - `\U000f0140` (chevron-down) for expanded folds

### Visibility

- **Hover-to-reveal**: Chevrons fade in when the mouse enters the gutter, fade out on leave (~200ms animation via timed opacity interpolation)
- **Collapsed chevrons** always visible at full opacity regardless of hover state
- Font size: 1.2x editor font, bold weight
- Color: `theme.line_number_fg` at 0.7 opacity

### Settings integration

Controlled by `editor.show_line_numbers` setting — hides/shows the entire custom gutter column. Responds to live setting changes via `subscribe_settings_change`.

---

## Crash Prevention (Pango byte-index safety)

GTK4's `get_iter_location()` and `get_cursor_locations()` crash with a fatal C-level abort when called on iters within invisible-tagged regions. All snapshot-pipeline code is guarded:

| Code path | Guard |
|-----------|-------|
| `_do_custom_snapshot` | Builds `_fold_unsafe_lines` set (hidden lines inside folds) |
| `draw_block_cursor` | Skipped if cursor is on a fold-unsafe line |
| `_draw_diagnostic_waves` | Skips fold-unsafe lines |
| `_draw_indent_guides_snapshot` | Skips fold-unsafe lines |
| `color_preview_renderer.draw` | Accepts `fold_unsafe` set, skips affected lines |
| `ghost_text_renderer.draw` | Skipped if cursor is on fold-unsafe line |
| `ghost_text_renderer._apply_spacing` | Skipped if cursor is on fold-unsafe line |
| `autocomplete popup positioning` | Skipped if cursor is on fold-unsafe line |
| `gutter_diff_renderer.draw` | Skips fold-unsafe lines |

### Click debounce

Gutter clicks are debounced (`_toggle_pending` flag + 150ms cooldown) and deferred via `GLib.timeout_add(30ms)` to ensure GTK finishes event processing before buffer modification.

---

## Testing

31 tests in `tests/editor/test_fold_manager.py`:

| Category | Tests |
|----------|-------|
| `FOLD_NODE_TYPES` coverage | 5 (Python, JS, TS, TSX core types, unknown language) |
| Tree-sitter region detection | 7 (single/nested/sibling nodes, single-line skip, non-foldable, cross-language) |
| Brace fold detection | 7 (JSON objects, arrays, nested, single-line, strings, empty, mixed) |
| State management | 9 (toggle, collapse/expand all, cursor targeting, debounce) |
| Chevron glyph safety | 3 (single codepoint verification, `\uf0142` vs `\U000f0142` guard) |

---

## Files

| File | Role |
|------|------|
| `src/editor/fold_manager.py` | FoldManager + LineNumberFoldRenderer |
| `src/editor/editor_view.py` | Snapshot pipeline guards, fold-unsafe line tracking |
| `src/editor/color_preview_renderer.py` | Accepts fold_unsafe parameter |
| `src/editor/gutter_diff_renderer.py` | Skips fold-unsafe lines |
| `src/editor/inline_completion/ghost_text_renderer.py` | fold-unsafe guard |
| `src/editor/autocomplete/autocomplete.py` | fold-unsafe guard |
| `tests/editor/test_fold_manager.py` | 31 tests |
