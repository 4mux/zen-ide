# Zen IDE — Settings Reference

**Created_at:** 2026-02-12  
**Updated_at:** 2026-03-21  
**Status:** Active  
**Goal:** Document all settings in `~/.zen_ide/settings.json` with types, defaults, and descriptions  
**Scope:** `src/shared/settings_manager.py`, `~/.zen_ide/settings.json`  

---

All settings are persisted in `~/.zen_ide/settings.json` and managed by `SettingsManager` (`src/settings_manager.py`).

Settings marked with ⚙️ are configurable from the Settings dialog (`Ctrl+,`). Others are managed programmatically (e.g., layout positions saved on window resize).

---

## Window

| Setting | Default | ⚙️ | Description |
|---------|---------|---|-------------|

---

## Theme

| Setting | Default | ⚙️ | Description |
|---------|---------|---|-------------|
| `theme` | `"zen_dark"` | ⚙️ | Active color theme. Options include `zen_dark`, `monokai`, `github_dark`, and others defined in the themes module. |

---

## Cursor

| Setting | Default | ⚙️ | Description |
|---------|---------|---|-------------|
| `cursor_blink` | `true` | ⚙️ | Enable cursor blink globally (editor, terminal, tree view, AI chat inputs). Uses native GTK caret. |
| `wide_cursor` | `false` | ⚙️ | Use a wide block cursor instead of the thin GTK caret. Applies to editor, terminal, and AI chat inputs. |

---

## Editor

| Setting | Default | ⚙️ | Description |
|---------|---------|---|-------------|
| `editor.tab_size` | `4` | ⚙️ | Number of spaces per tab stop. |
| `editor.insert_spaces` | `true` | ⚙️ | When enabled, pressing Tab inserts spaces instead of a tab character. |
| `editor.show_line_numbers` | `true` | ⚙️ | Show the line number gutter on the left side of the editor. |
| `editor.highlight_current_line` | `true` | ⚙️ | Highlight the line where the cursor is positioned. |
| `editor.word_wrap` | `false` | ⚙️ | Wrap long lines instead of horizontal scrolling. |
| `editor.letter_spacing` | `0.3` (macOS) / `0` | ⚙️ | Extra letter spacing in pixels. Improves readability on macOS where CoreText renders thinner text. |
| `editor.show_indent_guides` | `true` | | Display vertical indent guide lines in the editor. |
| `editor.indent_guide_color` | `""` | | Override indent guide color (hex, e.g. `"#ff0000"`). Empty = use theme default. |
| `editor.indent_guide_alpha` | `-1` | | Override indent guide opacity (`0.0`–`1.0`). `-1` = use default. |
| `editor.show_minimap` | `true` | | Show a minimap overview on the right side of the editor. |
| `editor.scroll_past_end` | `true` | | Allow scrolling past the end of the file for elastic/kinetic bounce. |
| `editor.auto_close_brackets` | `true` | ⚙️ | Automatically insert closing brackets, quotes, and backticks (`()`, `[]`, `{}`, `""`, `''`, `` `` ``) when typing the opening character. |
| `editor.auto_complete_on_type` | `false` | ⚙️ | Auto-trigger completions while typing (after 3+ characters). When disabled, use `Ctrl+Space` to trigger manually. |
| `editor.format_on_save` | `true` | ⚙️ | Auto-format files on save using the configured formatter for the file extension (see **Formatters** section). |
| `editor.font_ligatures` | `false` | ⚙️ | Enable OpenType font ligatures (`liga`, `calt`) for combined glyphs like `=>`, `!=`, `==`. Requires a ligature-capable font (e.g., SauceCodePro, Fira Code, JetBrains Mono). |

---

## Tree View

| Setting | Default | ⚙️ | Description |
|---------|---------|---|-------------|
| `treeview.line_spacing` | `10` | ⚙️ | Total vertical spacing in pixels, split evenly above and below each row (e.g., `10` → 5px above, 5px below). |

---

## Terminal

| Setting | Default | ⚙️ | Description |
|---------|---------|---|-------------|
| `terminal.scrollback_lines` | `10000` | ⚙️ | Number of lines to keep in the terminal scrollback buffer. |
| `terminal.shell` | `""` (auto-detect) | | Shell executable path. Empty string auto-detects the user's default shell. |

---

## Fonts

All font settings are centralized under the `fonts` key. Each component has `family`, `size`, and `weight` sub-keys.

| Setting | Default | ⚙️ | Description |
|---------|---------|---|-------------|
| `fonts.editor.family` | `"SauceCodePro Nerd Font"` | ⚙️ | Font family for the code editor. Empty string uses the system monospace font. |
| `fonts.editor.size` | `16` | ⚙️ | Font size in points (range: 8–36). Also adjustable with `Ctrl++` / `Ctrl+-`. |
| `fonts.editor.weight` | `"normal"` | | Font weight for editor text (e.g., `"normal"`, `"bold"`). |
| `fonts.terminal.family` | `""` (system default) | ⚙️ | Font family for the integrated terminal. |
| `fonts.terminal.size` | `16` | ⚙️ | Font size in points for the terminal. |
| `fonts.terminal.weight` | `"normal"` | | Font weight for terminal text. |
| `fonts.explorer.family` | `""` (system default) | | Font family for the file explorer tree view. |
| `fonts.explorer.size` | `16` | | Font size for the file explorer. |
| `fonts.explorer.weight` | `"normal"` | | Font weight for explorer text. |
| `fonts.ai_chat.family` | `""` (system default) | | Font family for the AI chat panel. |
| `fonts.ai_chat.size` | `16` | | Font size for AI chat text. |
| `fonts.ai_chat.weight` | `"normal"` | | Font weight for AI chat text. |
| `fonts.markdown_preview.family` | `""` (editor font) | ⚙️ | Font family for markdown preview body text. Code blocks always use the editor font. |
| `fonts.markdown_preview.size` | `14` | ⚙️ | Font size in points for markdown preview body text. |
| `fonts.markdown_preview.weight` | `"normal"` | | Font weight for markdown preview body text. |

> **Migration note:** If your settings file still has `editor.font_family`, `editor.font_size`, or `editor.font_weight`, they will be automatically migrated to `fonts.editor` on the next launch.

---

## Font Rendering

Controls text rendering quality. Platform-specific behaviour:

- **Linux**: All settings apply via X11/fontconfig (`gtk-xft-*` properties).
- **macOS**: By default, CoreText handles rendering and only `hint_font_metrics` applies. Set `pango_backend` to `"freetype"` to use the Linux rendering stack, which enables all xft settings on macOS too.

| Setting | Default | Platform | Description |
|---------|---------|----------|-------------|
| `font_rendering.pango_backend` | `"auto"` | All | Text rendering backend: `"auto"` (platform default), `"coretext"` (macOS native), `"freetype"` (FontConfig+FreeType2). **Requires restart.** |
| `font_rendering.antialias` | `true` | Linux / macOS+freetype | Enable font antialiasing (smoothing). |
| `font_rendering.hinting` | `true` | Linux / macOS+freetype | Enable font hinting (align glyphs to pixel grid). |
| `font_rendering.hintstyle` | `"hintfull"` | Linux / macOS+freetype | Hinting intensity: `"hintnone"`, `"hintslight"`, `"hintmedium"`, `"hintfull"`. |
| `font_rendering.subpixel_order` | `"rgb"` | Linux / macOS+freetype | Subpixel layout for LCD: `"none"`, `"rgb"`, `"bgr"`, `"vrgb"`, `"vbgr"`. |
| `font_rendering.hint_font_metrics` | `true` | All | Snap glyph metrics to pixel grid for crisper text. |

---

## AI

| Setting | Default | ⚙️ | Description |
|---------|---------|---|-------------|
| `ai.is_enabled` | `true` | | Master toggle for AI features. When `false`, hides the AI chat panel and the terminal expands to fill the bottom area. |
| `ai.provider` | `""` (auto-detect) | | Active AI provider. Values: `"copilot_api"`, `"anthropic_api"`, `"openai_api"`, or `""` for auto-detection. |
| `ai.show_inline_suggestions` | `true` | ⚙️ | Show AI-powered inline code completion suggestions (ghost text). |
| `ai.yolo_mode` | `true` | | Unlimited tool calls per message (up to `ai.max_tool_rounds` safety ceiling). When `false`, stops after 25 tool calls and asks to continue. |
| `ai.max_tool_rounds` | `25` | | Hard ceiling on tool-use rounds in yolo mode. Prevents runaway loops from burning tokens. |
| `ai.context_truncation` | `true` | | Truncate old tool results in long agentic sessions to reduce token cost. |
| `ai.max_context_chars` | `80000` | | Hard cap on total serialised conversation size (chars). ~20K tokens. |
| `ai.context_injection.current_file` | `true` | | Include current file contents in the AI system prompt (saves tool calls). |
| `ai.context_injection.open_tabs` | `true` | | Include list of open editor tabs in the AI system prompt. |
| `ai.context_injection.git_info` | `true` | | Include git branch, status, and diff stat in the AI system prompt. |
| `ai.context_injection.diagnostics` | `true` | | Include current errors and warnings in the AI system prompt. |
| `ai.context_injection.workspace_tree` | `false` | | Include workspace directory structure in the AI system prompt. Disabled by default (can be large). |
| `ai.model.copilot_api` | `"claude-sonnet-4"` | | Selected model when using the Copilot API provider. |
| `ai.model.anthropic_api` | `"claude-sonnet-4-20250514"` | | Selected model when using the Anthropic API provider. |
| `ai.model.openai_api` | `"gpt-4.1"` | | Selected model when using the OpenAI API provider. |
| `ai.inline_completion.trigger_delay_ms` | `200` | | Debounce delay (ms) before requesting an inline completion after typing stops. |
| `ai.inline_completion.model` | `"gpt-4.1"` | | Model for inline completions — defaults to fastest available. |
| `ai.auto_scroll_on_output` | `true` | ⚙️ | Auto-scroll the AI chat to the bottom while the AI streams a response. Only scrolls if the user is already at the bottom; scrolling up disables follow until the next response. |

---

## Status Bar

| Setting | Default | ⚙️ | Description |
|---------|---------|---|-------------|
| `status_bar.show_full_path` | `true` | ⚙️ | Show the full file path in the status bar. When disabled, only the filename is shown. |
| `status_bar.item_spacing` | `12` | ⚙️ | Pixels of spacing between right-side status bar items (e.g., between diagnostics and encoding). |
| `status_bar.inner_spacing` | `10` | ⚙️ | Pixels of spacing within composite status bar items (e.g., between file icon and file type text). |

---

## Layout

These settings are saved automatically when the user resizes panels or the window.

| Setting | Default | Description |
|---------|---------|-------------|
| `layout.main_splitter` | `250` | Width of the file explorer sidebar in pixels. |
| `layout.right_splitter` | `-250` | Width of the right panel (AI chat / Dev Pad) in pixels. Negative value indicates offset from window edge. |
| `layout.bottom_splitter` | `0` | Height of the bottom panel (terminal) in pixels. `0` means collapsed. |
| `layout.window_width` | `1400` | Main window width in pixels. |
| `layout.window_height` | `900` | Main window height in pixels. |

---

## Popup

| Setting | Default | ⚙️ | Description |
|---------|---------|---|-------------|
| `popup.border_radius` | `0` | ⚙️ | Border radius in pixels for popup windows (0 = sharp corners). |

---

## Workspace

These settings track the current workspace state and are saved/restored between sessions.

| Setting | Default | Description |
|---------|---------|-------------|
| `workspace.folders` | `[]` | List of open workspace folder paths. |
| `workspace.last_file` | `""` | Path of the last active file (restored on startup). |
| `workspace.open_files` | `[]` | List of all currently open file tab paths. |

---

## Dev Pad

| Setting | Default | ⚙️ | Description |
|---------|---------|---|-------------|
| `dev_pad.max_activities` | `500` | ⚙️ | Maximum number of activities displayed in the Dev Pad panel. Increase to see older history; decrease for faster rendering. |

---

## Behavior

| Setting | Default | ⚙️ | Description |
|---------|---------|---|-------------|
| `behavior.auto_show_dev_pad_when_empty` | `true` | ⚙️ | Automatically show the Dev Pad panel when no files are open. |
| `behavior.is_nvim_emulation_enabled` | `true` | ⚙️ | Enable vim-style command line (`:w`, `:q`, `:wq`, etc.) at the bottom of the editor. |
| `behavior.auto_expand_terminals` | `true` | ⚙️ | Reset terminals to default size when opening a file after all tabs were closed. |
| `behavior.terminals_on_vertical_stack` | `true` | ⚙️ | `true` = terminals stack vertically (split panes, all visible). `false` = horizontal tab bar (one visible at a time, like AI chat). |
| `behavior.ai_chat_on_vertical_stack` | `false` | ⚙️ | `true` = AI chat sessions stack vertically (split panes, all visible). `false` = horizontal tab bar (one visible at a time, default). |

---

## Formatters

Configure auto-format commands per file extension. Each entry maps a file extension to a shell command that reads **stdin** and writes formatted output to **stdout**. Formatting runs on save when `editor.format_on_save` is `true`.

| Setting | Default | ⚙️ | Description |
|---------|---------|---|-------------|
| `formatters.{ext}` | `{ ".py": "ruff format ...", ".json": "builtin" }` | ⚙️ | Formatter command per file extension. Use `"builtin"` for built-in formatters (JSON pretty-print). |

**`{file}`** in the command is replaced with the file path (so formatters can infer language/config).

The command receives file content via **stdin** and must write formatted content to **stdout**. If the formatter exits with a non-zero code, the original content is saved unchanged.

**Built-in formatters:**

| Extension | Behavior |
|-----------|----------|
| `.json` | Pretty-print with 2-space indent |

**Examples:**

```json
{
  "formatters": {
    ".py": "ruff format --stdin-filename {file} -",
    ".js": "prettier --stdin-filepath {file}",
    ".ts": "prettier --stdin-filepath {file}",
    ".go": "gofmt",
    ".json": "builtin"
  }
}
```

---

## Diagnostics

Configure linter commands per file extension. Each entry maps a file extension to a command and output format.

| Setting | Default | ⚙️ | Description |
|---------|---------|---|-------------|
| `diagnostics.{ext}` | `{ ".py": { "command": "ruff check ...", "format": "ruff" } }` | ⚙️ | Linter config per file extension. Each value is an object with `command` and `format`, or a plain command string (defaults to `"line"` format). |

**`{file}`** in the command is replaced with the absolute file path being linted.

**Supported formats:**

| Format | Description | Compatible tools |
|--------|-------------|-----------------|
| `"ruff"` | Ruff JSON output | `ruff` |
| `"line"` | Generic `file:line:col: message` | `mypy`, `flake8`, `pylint`, `gcc`, `rustc`, `eslint --format unix`, etc. |

**Examples:**

```json
{
  "diagnostics": {
    ".py": {
      "command": "ruff check --output-format json --no-fix {file}",
      "format": "ruff"
    },
    ".js": {
      "command": "eslint --format unix {file}",
      "format": "line"
    },
    ".rs": {
      "command": "clippy-driver {file}",
      "format": "line"
    },
    ".rb": "rubocop --format emacs {file}"
  }
}
```

To use **mypy** instead of ruff for Python:
```json
{
  "diagnostics": {
    ".py": {
      "command": "mypy --no-color-output --show-column-numbers --no-error-summary {file}",
      "format": "line"
    }
  }
}
```

---

## Navigation

| Setting | Default | ⚙️ | Description |
|---------|---------|---|-------------|
| `navigation.provider` | `"custom"` | ⚙️ | Code navigation backend for Go to Definition (`Cmd+Click`). `"custom"` uses regex/import parsing. |

---

## Settings File Location

Settings are stored at:

```
~/.zen_ide/settings.json
```

The file is created automatically on first run with default values and updated whenever a setting changes.

## Programmatic Access

```python
from shared.settings import get_setting, set_setting

# Read a setting
tab_size = get_setting("editor.tab_size", 4)

# Write a setting (auto-saves)
set_setting("editor.tab_size", 2)

# Font settings — use the FontManager API
from fonts import get_font_settings, set_font_settings

editor_font = get_font_settings("editor")  # {"family": "...", "size": 16, "weight": "normal"}
set_font_settings("editor", size=18)

# Layout helpers
from shared.settings import save_layout, get_layout

layout = get_layout()

# Workspace helpers
from shared.settings import save_workspace, get_workspace

workspace = get_workspace()
```
