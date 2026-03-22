# Syntax Highlighting System

**Created_at:** 2026-02-20  
**Updated_at:** 2026-03-08  
**Status:** Active  
**Goal:** Explain syntax highlighting via GtkSourceView language definitions and dynamic CSS generation  
**Scope:** `src/editor/langs/language_detect.py`, `src/editor/langs/`, semantic highlighting  

---

How Zen IDE maps theme colors to syntax tokens across all programming languages.

## Overview

Zen uses [GtkSourceView 5](https://wiki.gnome.org/Projects/GtkSourceView) for syntax highlighting. GtkSourceView ships with **language definitions** (`.lang` files) that tokenize source code via regex, and **style schemes** (`.xml` files) that map token names to colors. Zen does not ship any custom `.lang` or `.xml` files — instead it:

1. Relies on GtkSourceView's **built-in language definitions** for tokenization.
2. **Generates style scheme XML at runtime** from the active Zen theme.
3. Adds an extra **semantic highlight** layer on top for call-site coloring.

```
┌──────────────────────────────────────────────────────────┐
│                     Visible Editor                       │
├──────────────────────────────────────────────────────────┤
│  Layer 3 │ Semantic highlighting (text tags)             │
│          │ PascalCase → class color, func() → func color │
├──────────┼───────────────────────────────────────────────┤
│  Layer 2 │ Dynamic style scheme (generated XML)          │
│          │ def:keyword → theme.syntax_keyword, etc.      │
├──────────┼───────────────────────────────────────────────┤
│  Layer 1 │ GtkSourceView language definitions            │
│          │ Regex tokenizer: .lang files (built-in)       │
└──────────┴───────────────────────────────────────────────┘
```

## Layer 1: Language Detection

**File:** `src/editor/langs/language_detect.py`

When a file is opened, `detect_language()` assigns a GtkSourceView language ID to the buffer using a 3-level fallback:

1. **Content-type guess** — `Gio.content_type_guess()` + `lang_manager.guess_language()`
2. **Filename match** — e.g. `Makefile` → `"makefile"`, `Dockerfile` → `"dockerfile"`
3. **Extension match** — e.g. `.py` → `"python3"`, `.tf` → `"hcl"`, `.rs` → `"rust"`

No custom `.lang` files exist. All tokenization comes from GtkSourceView's built-in library (typically installed at `/usr/share/gtksourceview-5/language-specs/`).

## Layer 2: Dynamic Style Scheme Generation

**File:** `src/editor/editor_view.py` — function `_generate_style_scheme(theme)`

### The Problem

GtkSourceView expects a style scheme **XML file** to map token names (like `def:keyword`, `def:string`) to colors. Normally these are static files. But Zen has a runtime theme system (`src/themes/`) with 20+ themes, and we want all syntax colors driven by theme definitions — not by separate XML files.

### The Solution

At runtime, Zen generates a GtkSourceView-compatible XML style scheme from the active theme's properties:

```
Theme object (e.g. Dracula)          Generated XML
┌─────────────────────────┐     ┌─────────────────────────────────┐
│ syntax_keyword: #ff79c6 │ ──► │ <style name="def:keyword"       │
│ syntax_string:  #f1fa8c │ ──► │         foreground="#ff79c6"/>   │
│ syntax_comment: #6272a4 │ ──► │ <style name="def:string"        │
│ syntax_function:#50fa7b │     │         foreground="#f1fa8c"/>   │
│ syntax_class:   #8be9fd │     │ ...                             │
│ ...                     │     └─────────────────────────────────┘
└─────────────────────────┘
```

### How It Works

1. `_generate_style_scheme(theme)` builds an XML string from `theme.syntax_*` properties.
2. The XML is written to a temp file at `/tmp/zen-ide-schemes/zen-{theme_name}.xml`.
3. The temp directory is registered with `GtkSource.StyleSchemeManager` via `prepend_search_path()`.
4. The scheme ID (e.g. `"zen-dracula"`) is returned.
5. The caller looks up the scheme and applies it: `buffer.set_style_scheme(scheme)`.

### Token Mapping

The generated XML maps these GtkSourceView token families:

| XML style name | Theme property | What it colors |
|---|---|---|
| `def:keyword` | `syntax_keyword` | `if`, `for`, `class`, `import`, etc. |
| `def:type` | `syntax_class` | Type names |
| `def:function` | `syntax_function` | Function names at definition site |
| `def:string` | `syntax_string` | String literals |
| `def:comment` | `syntax_comment` | Comments |
| `def:number` | `syntax_number` | Numeric literals |
| `def:operator` | `syntax_operator` | Operators (`+`, `-`, `=`, etc.) |
| `def:boolean` | `syntax_boolean` ¹ | `True`, `False` |
| `def:constant` | `syntax_constant` ¹ | Constants |
| `def:identifier` | `syntax_variable` ¹ | Variable names |
| `def:special-char` | `syntax_string_escape` ¹ | Escape sequences (`\n`, `\t`) |
| `def:regex` | `syntax_regex` ¹ | Regular expressions |
| `def:doc-comment` | `syntax_doc_comment` ¹ | Docstrings / doc comments |
| `def:statement` | `syntax_keyword_control` ¹ | Control flow keywords |

¹ Extended syntax color — falls back to a base color if not defined by the theme (see `Theme.get_syntax_color()`).

**Python-specific overrides** are also included for `python3:class-name`, `python3:function-name`, `python3:decorator`, `python3:builtin-object`, and `python3:builtin-function`.

### Editor Chrome

The same XML also styles non-syntax editor elements:

| Style | Source |
|---|---|
| `text` (fg/bg) | `theme.fg_color` / `theme.editor_bg` |
| `selection` | `theme.selection_bg` |
| `current-line` | `theme.hover_bg` |
| `line-numbers` | `theme.line_number_fg` / `theme.line_number_bg` |
| `bracket-match` | `theme.fg_color` + `theme.selection_bg` |
| `search-match` | `theme.search_match_bg` |

## Layer 3: Semantic Highlighting

**File:** `src/editor/semantic_highlight.py`

GtkSourceView's regex tokenizer only highlights identifiers at **definition sites** (e.g. `class Foo:`, `def bar(`). It cannot color the same names at **usage sites** (e.g. `Foo()`, `bar()`). Zen adds a semantic highlight layer using GTK text tags applied on top of the GtkSourceView output.

### What It Does

- **PascalCase identifiers** → colored with `theme.syntax_class` (e.g. `MyClass()`, `ServiceProcessor`)
- **Function/method calls** → colored with `theme.syntax_function` (e.g. `.process()`, `len()`)
- Python keywords are excluded to avoid false positives.
- Tokens inside strings/comments are skipped using GtkSourceView's context classes.

### How It Works

1. `setup_semantic_highlight(tab, theme)` creates two text tags: `zen-class-usage` and `zen-func-call`.
2. On every buffer change, a debounced idle callback runs `_apply_semantic_tags()`.
3. The function scans the full buffer text with regex patterns, skips keywords and string/comment contexts, and applies the appropriate tag at each match offset.
4. When the theme changes, `update_semantic_colors()` updates the tag foreground colors.

> **Note:** Semantic highlighting currently only applies to Python files (`python3` / `python` language IDs).

## Theme Integration

### Theme Model

**File:** `src/themes/theme_model.py`

Each theme is a `@dataclass` with syntax color fields:

```python
@dataclass
class Theme:
    # Core syntax colors (required)
    syntax_keyword: str     # e.g. "#ff79c6"
    syntax_string: str
    syntax_comment: str
    syntax_number: str
    syntax_function: str
    syntax_class: str
    syntax_operator: str

    # Extended syntax colors (optional, with fallbacks)
    syntax_keyword_control: str = ""  # falls back to syntax_keyword
    syntax_variable: str = ""         # falls back to fg_color
    syntax_string_escape: str = ""    # falls back to syntax_string
    syntax_regex: str = ""            # falls back to syntax_string
    syntax_doc_comment: str = ""      # falls back to syntax_comment
    syntax_constant: str = ""         # falls back to syntax_class
    syntax_boolean: str = ""          # falls back to syntax_keyword
```

The `get_syntax_color(attr)` method resolves extended colors with automatic fallback so that themes only need to define the 7 core colors — extended colors are optional.

### Theme Change Flow

```
User switches theme
        │
        ▼
EditorTab._apply_theme()              (src/editor/editor_view.py:1233)
        │
        ├─► _generate_style_scheme(theme)   → writes XML, returns scheme ID
        │       │
        │       └─► /tmp/zen-ide-schemes/zen-{name}.xml
        │
        ├─► buffer.set_style_scheme(scheme) → GtkSourceView re-renders tokens
        │
        └─► update_semantic_colors(tab, theme) → updates text tag colors
```

## Adding a New Theme

To add syntax colors for a new theme:

1. Create a theme definition in `src/themes/definitions/` (see existing files for examples).
2. Define at least the 7 core `syntax_*` fields.
3. Optionally define extended syntax colors for finer control.
4. The style scheme XML will be auto-generated — no manual XML needed.

## Adding Language-Specific Overrides

To add syntax overrides for a specific language (like the existing Python overrides):

1. Edit `_generate_style_scheme()` in `src/editor/editor_view.py`.
2. Add `<style name="languageid:token-name" .../>` entries to the XML template.
3. Token names are defined in GtkSourceView's `.lang` files — inspect them at `/usr/share/gtksourceview-5/language-specs/`.
