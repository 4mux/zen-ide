# Settings Reference

All settings are stored in `~/.zen_ide/settings.json`. Edit this file directly or use the in-app settings UI where available (marked with ⚙️).

## Theme

| Setting | Default | Type | Description |
|---|---|---|---|
| `theme` | `"zen_dark"` | string | Active colour theme |

## Cursor

| Setting | Default | Type | ⚙️ | Description |
|---|---|---|---|---|
| `cursor_blink` | `true` | bool | ⚙️ | Cursor blink animation |
| `wide_cursor` | `false` | bool | ⚙️ | Block cursor instead of thin caret |

## Editor

| Setting | Default | Type | ⚙️ | Description |
|---|---|---|---|---|
| `editor.tab_size` | `4` | int | ⚙️ | Spaces per tab stop |
| `editor.insert_spaces` | `true` | bool | ⚙️ | Spaces instead of tabs |
| `editor.show_line_numbers` | `true` | bool | ⚙️ | Line number gutter |
| `editor.highlight_current_line` | `true` | bool | ⚙️ | Highlight cursor line |
| `editor.word_wrap` | `false` | bool | ⚙️ | Wrap long lines |
| `editor.letter_spacing` | `0.3` / `0` | float | ⚙️ | Extra letter spacing (px). macOS=0.3, Linux=0 |
| `editor.show_indent_guides` | `true` | bool | | Vertical indent lines |
| `editor.indent_guide_color` | `""` | hex | | Override indent guide colour |
| `editor.indent_guide_alpha` | `-1` | 0.0–1.0 | | Override indent guide opacity (-1 = theme) |
| `editor.show_minimap` | `true` | bool | | Code minimap on right |
| `editor.scroll_past_end` | `true` | bool | | Scroll past last line |
| `editor.auto_close_brackets` | `true` | bool | ⚙️ | Auto-insert closing brackets/quotes |
| `editor.auto_complete_on_type` | `false` | bool | ⚙️ | Auto-trigger completions after 3+ chars |
| `editor.format_on_save` | `true` | bool | ⚙️ | Format file on save |
| `editor.font_ligatures` | `false` | bool | ⚙️ | OpenType ligatures |

## Fonts

Each font component has `family`, `size`, and `weight` sub-keys:

| Setting | Default | Type | ⚙️ | Description |
|---|---|---|---|---|
| `fonts.editor.family` | `"SauceCodePro Nerd Font"` | string | ⚙️ | Editor font |
| `fonts.editor.size` | `16` | int (8–36) | ⚙️ | Editor font size |
| `fonts.editor.weight` | `"normal"` | string | | Editor font weight |
| `fonts.terminal.family` | `""` | string | ⚙️ | Terminal font (empty = system) |
| `fonts.terminal.size` | `16` | int | ⚙️ | Terminal font size |
| `fonts.terminal.weight` | `"normal"` | string | | Terminal font weight |
| `fonts.explorer.family` | `""` | string | | Tree view font |
| `fonts.explorer.size` | `16` | int | | Tree view font size |
| `fonts.explorer.weight` | `"normal"` | string | | Tree view font weight |
| `fonts.ai_chat.family` | `""` | string | | AI chat font |
| `fonts.ai_chat.size` | `16` | int | | AI chat font size |
| `fonts.ai_chat.weight` | `"normal"` | string | | AI chat font weight |
| `fonts.markdown_preview.family` | `""` | string | ⚙️ | Preview font (empty = editor font) |
| `fonts.markdown_preview.size` | `14` | int | ⚙️ | Preview font size |
| `fonts.markdown_preview.weight` | `"normal"` | string | | Preview font weight |

## Font Rendering

| Setting | Default | Type | Description |
|---|---|---|---|
| `font_rendering.pango_backend` | `"auto"` | string | `"auto"`, `"coretext"`, `"freetype"` (restart required) |
| `font_rendering.antialias` | `true` | bool | Font anti-aliasing |
| `font_rendering.hinting` | `true` | bool | Font hinting |
| `font_rendering.hintstyle` | `"hintfull"` | string | `"hintnone"`, `"hintslight"`, `"hintmedium"`, `"hintfull"` |
| `font_rendering.subpixel_order` | `"rgb"` | string | `"none"`, `"rgb"`, `"bgr"`, `"vrgb"`, `"vbgr"` |
| `font_rendering.hint_font_metrics` | `true` | bool | Snap glyph metrics to pixel grid |

## Tree View

| Setting | Default | Type | ⚙️ | Description |
|---|---|---|---|---|
| `treeview.line_spacing` | `10` | int | ⚙️ | Vertical row spacing (px) |

## Terminal

| Setting | Default | Type | ⚙️ | Description |
|---|---|---|---|---|
| `terminal.scrollback_lines` | `10000` | int | ⚙️ | Scrollback buffer size |
| `terminal.shell` | `""` | string | | Shell path (empty = auto-detect) |

## AI

| Setting | Default | Type | ⚙️ | Description |
|---|---|---|---|---|
| `ai.is_enabled` | `true` | bool | | Master AI toggle |
| `ai.provider` | `""` | string | | `""`, `"claude_cli"`, or `"copilot_cli"` (`""` = auto-detect, prefers Claude) |
| `ai.model` | `""` | string | | Optional chat CLI model override; empty uses the CLI default |
| `ai.show_inline_suggestions` | `true` | bool | ⚙️ | Ghost text inline completions |
| `ai.yolo_mode` | `true` | bool | | Skip AI tool-use confirmations |
| `ai.inline_completion.trigger_delay_ms` | `500` | int | | Completion request debounce (ms) |
| `ai.inline_completion.model` | `"gpt-4.1-mini"` | string | | Inline completion model |

## Status Bar

| Setting | Default | Type | ⚙️ | Description |
|---|---|---|---|---|
| `status_bar.show_full_path` | `true` | bool | ⚙️ | Full path vs filename only |
| `status_bar.item_spacing` | `12` | int | ⚙️ | Spacing between right-side items (px) |
| `status_bar.inner_spacing` | `10` | int | ⚙️ | Spacing within composite items (px) |

## Layout (auto-saved)

| Setting | Default | Type | Description |
|---|---|---|---|
| `layout.main_splitter` | `250` | int | Tree sidebar width |
| `layout.right_splitter` | `-250` | int | Right panel width (negative = from edge) |
| `layout.bottom_splitter` | `0` | int | Terminal height (0 = collapsed) |
| `layout.window_width` | `1400` | int | Window width |
| `layout.window_height` | `900` | int | Window height |

## Popup

| Setting | Default | Type | ⚙️ | Description |
|---|---|---|---|---|
| `popup.border_radius` | `0` | int | ⚙️ | Popup window corner radius (px) |

## Workspace (auto-saved)

| Setting | Default | Type | Description |
|---|---|---|---|
| `workspace.workspace_file` | `""` | string | Path to the loaded `.zen-workspace` file |
| `workspace.folders` | `[]` | list | Open workspace folder paths |
| `workspace.last_file` | `""` | string | Last active file (for restore) |
| `workspace.open_files` | `[]` | list | Currently open tabs |

## Behaviour

| Setting | Default | Type | ⚙️ | Description |
|---|---|---|---|---|
| `behavior.auto_show_dev_pad_when_empty` | `true` | bool | ⚙️ | Show Dev Pad when no files open |
| `behavior.is_nvim_emulation_enabled` | `true` | bool | ⚙️ | Vim-style `:w`, `:q`, `:wq` commands |
| `behavior.auto_expand_terminals` | `true` | bool | ⚙️ | Reset terminal size on file open |
| `behavior.terminals_on_vertical_stack` | `true` | bool | ⚙️ | Terminal layout: vertical stack vs tabs |
| `behavior.ai_chat_on_vertical_stack` | `false` | bool | ⚙️ | AI chat layout: vertical stack vs tabs |
| `behavior.terminal_follow_file` | `true` | bool | | Terminal cd follows active editor file |

## Formatters

Configure per-extension formatters for format-on-save:

```json
{
  "formatters": {
    ".py": "ruff format --stdin-filename {file} -",
    ".js": "prettier --stdin-filepath {file}",
    ".ts": "prettier --stdin-filepath {file}",
    ".json": "builtin",
    ".css": "prettier --stdin-filepath {file}"
  }
}
```

- `{file}` is replaced with the file path
- Formatters read stdin and write formatted output to stdout
- `"builtin"` uses the built-in JSON formatter (2-space indent)

## Diagnostics (Linters)

Configure per-extension linters:

```json
{
  "diagnostics": {
    ".py": {
      "command": "ruff check --output-format json {file}",
      "format": "ruff"
    },
    ".js": {
      "command": "eslint --format unix {file}",
      "format": "line"
    }
  }
}
```

Supported formats:
- `"ruff"` — Ruff JSON output
- `"line"` — Generic `file:line:col: message` format

## Navigation

| Setting | Default | Type | ⚙️ | Description |
|---|---|---|---|---|
| `navigation.provider` | `"custom"` | string | ⚙️ | Code navigation backend |
