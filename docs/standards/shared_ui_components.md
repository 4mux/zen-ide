# Shared UI Components

**Created_at:** 2026-03-29
**Updated_at:** 2026-03-29
**Status:** Active
**Goal:** Document reusable UI components in `src/shared/ui/` and track extraction candidates
**Scope:** All UI code in `src/`

---

## Principle

Every UI widget that appears in two or more panels belongs in `src/shared/ui/`. Before building a new widget, check if a shared one exists. Before duplicating a pattern, extract it here.

## Current Components

| Component | File | Purpose |
|-----------|------|---------|
| `ZenTree` | `zen_tree.py` | GtkSnapshot tree widget — selection, hover, keyboard (j/k/h/l), chevrons, indent guides, scroll animation. Subclass and override `_draw_item_row()` for custom rendering. |
| `ZenTreeItem` | `zen_tree.py` | Generic tree data model — name, depth, parent, children, is_expandable, data payload. |
| `ZenButton` | `zen_button.py` | Themed button — variants: flat/primary/danger. Icon, text, or both. Toggle mode. Global CSS. |
| `ZenEntry` | `zen_entry.py` | Themed text entry — auto font/theme subscriptions with cleanup. `font_context` param. |
| `ZenSearchEntry` | `zen_entry.py` | Themed search entry — extends Gtk.SearchEntry. |
| `TabButton` | `tab_button.py` | Base tab widget — click/close handlers, accent underline, hover. |
| `FileTabButton` | `tab_button.py` | File tab — modified dot indicator via Gtk.Stack. |

## Usage Map

- **File explorer** (`treeview/custom_tree_panel.py`): Subclasses `ZenTree`, adds file icons, git status, drag-drop, inline edit
- **Debug variables** (`debugger/debug_panel.py`): Subclasses `ZenTree` as `_DebugVarTree`, adds name:value rendering, lazy child loading
- **All toolbars/panels**: `ZenButton` for consistent buttons
- **All tabs**: `TabButton` / `FileTabButton`
- **Search/input fields**: `ZenEntry` / `ZenSearchEntry`

## Extending ZenTree

```python
class MyTree(ZenTree):
    def _draw_item_row(self, snapshot, layout, item, y, width):
        """Custom row rendering — draw your content here."""

    def _load_item_children(self, item):
        """Lazy-load children when a node is expanded."""

    def _on_item_activated(self, item):
        """Handle click/Enter on leaf items."""
```

Key override points:

| Method | Default | Override when |
|--------|---------|--------------|
| `_draw_item_row` | Chevron + indent guides + name | Custom columns, icons, badges |
| `_load_item_children` | No-op | Lazy loading from filesystem, API, etc. |
| `_on_item_activated` | Calls `self.on_item_activated` callback | Custom activation (open file, navigate, etc.) |
| `_is_item_expandable` | Checks `is_expandable` or `is_dir` | Custom expand logic |
| `_should_suppress_hover` | Returns `False` | Suppress during inline edit, drag, etc. |

## Extraction Candidates

Patterns duplicated across the codebase that should be extracted to `shared/ui/` when next touched.

### High Priority

| Pattern | Locations | Proposed | Notes |
|---------|-----------|----------|-------|
| Scrolled window setup (policy, expand, kinetic) | 23 files | `ZenScrolledWindow` | 5-line boilerplate repeated everywhere |
| Header bar (left label + spacer + right buttons) | 7 files | `ZenHeaderBar` | Already half-extracted in `base_terminal_header.py` |

### Medium Priority

| Pattern | Locations | Proposed | Notes |
|---------|-----------|----------|-------|
| Dim/title/monospace label creation | 20+ files | Factory functions: `create_dim_label()` etc. | Currently scattered in NvimPopup and ad-hoc |
| Margin constants (8, 4, 12 hardcoded) | 254 instances | `MARGIN_SM/MD/LG` in `constants.py` | Trivial win for consistency |
| CSS provider creation + theme subscription | 42 files | `GlobalCssProvider` / `InstanceCssProvider` | ZenButton/ZenEntry already do this well — generalize |
| Tab bar with scroll buttons | 5 files | `ZenTabBar` | Duplicated in terminal, AI, editor tab bars |

### Rule

When modifying a file that contains one of these patterns, extract it to `shared/ui/` first — don't propagate the duplication.

## Architecture Notes

- **Rendering**: Custom widgets use GtkSnapshot (not cairo). `ZenTree` demonstrates the pattern.
- **Mixins**: File explorer layers `TreePanelDragMixin`, `TreePanelInlineEditMixin`, `TreePanelDataMixin` on top of `ZenTree`. Domain-specific logic lives in mixins; generic UI in `ZenTree`.
- **Themes**: `ThemeAwareMixin` + `subscribe_settings_change()` for reactive theming.
- **Fonts**: `get_font_settings(context)` where context is `"editor"`, `"explorer"`, or `"terminal"`.
- **Popups**: All extend `NvimPopup` which provides factory methods (`_create_message_label`, `_create_button_row`, etc.).
