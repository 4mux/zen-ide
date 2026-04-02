# AGENTS instructions

## Project

Zen is an IDE for general purpose code development. Goals are:

- minimalist
- performant
- easy to be used

## Tech Stack

- Python 3.13
- GUI framework: **GTK4** (via PyGObject)
- Editor component: **GtkSourceView 5**
- Terminal: **VTE**
- All commands driven by `Makefile`

### How to run:
```bash
make run          # Run the IDE
make install      # Install dependencies with uv
```

## Features

- tree workspace explorer
- tab system to open multiple files at the same time
- key shortcuts
- saved files appear on the tree
- integrated terminal unix like
- markdown files open in split view with live preview
- AI inline autosuggestion (ghost text completions)\n- AI context injection — injects current file, open tabs, git info, diagnostics into AI system prompt (configurable via `ai.context_injection.*`)
- Active file state exported for external AI tools
- Dev Pad - activity tracking panel with split view alongside editor (Cmd+.)
- Sketch Pad - ASCII drawing tool, opens .zen_sketch files in editor (Cmd+Shift+D) (see [docs/2026_02_15_sketch_pad.md](docs/2026_02_15_sketch_pad.md))
- Welcome Screen - branded landing view with version (from pyproject.toml) and shortcut reference (see [docs/2026_03_17_welcome_screen.md](docs/2026_03_17_welcome_screen.md))

## Makefile Commands

| Command | Description |
|---------|-------------|
| `make install` | Install dependencies with uv |
| `make install-system-deps` | Install GTK4 system dependencies (brew/apt) |
| `make install-cli` | Install `code` command to open Zen IDE from terminal |
| `make install-desktop` | Install .desktop file and icon (Linux) |
| `make run` | Run IDE |
| `make startup-time` | Measure startup time |
| `make tests` | Run tests with pytest |
| `make lint` | Run ruff linter and formatter |
| `make clean` | Remove build artifacts and caches |
| `make dist` | Build standalone app bundle (macOS) |

## Structure

### Source Code
- `src/` - **Main source code**:
  - `src/zen_ide_window.py` - Main application entry point
  - `src/editor/editor_view.py` - GtkSourceView-based editor
  - `src/tree_view.py` - File explorer tree
  - `src/terminal_view.py` - VTE terminal integration
  - `src/keybindings.py` - Central keyboard shortcut definitions
  - `src/constants.py` - Shared constants
  - `src/ai/` - AI chat: HTTP providers (Anthropic, OpenAI, Copilot), tool use, ChatCanvas rendering
  - `src/editor/` - Editor components (editor, diff view, dev pad, markdown/openapi preview)
  - `src/popups/` - Dialogs and floating windows (NvimPopup base class)
  - `src/navigation/` - Code navigation (go to definition via Tree-sitter AST queries)
  - `src/sketch_pad/` - ASCII drawing tool
  - `src/icons/` - Centralised icon definitions and rendering helpers
  - `src/fonts/` - Font management
  - `src/themes/` - Theme definitions and manager
  - `src/editor/langs/` - Language specs (.lang files) and language detection

### Shared Utilities (GUI-agnostic)
- `src/shared/` - **GUI-agnostic utilities**:
  - `src/shared/git_manager.py` - Git operations facade
  - `src/shared/git_ignore_utils.py` - Gitignore pattern matching
  - `src/shared/settings_manager.py` - User preferences manager

### Other
- `tests/` - Test files (all tests must be placed here, not in root)
- `tools/` - Support tools (generating offline resources, etc.)
- `docs/` - Feature documentation and design docs (see [Documentation Reference](#documentation-reference) below)

## Code Style

One class per file, `snake_case` filenames, `PascalCase` class names matching the file. See [docs/standards/code_style.md](docs/standards/code_style.md).

## AI Restrictions

**AI agents must NEVER run `git commit` or any git command that modifies history — only humans commit.** AI must never kill the host IDE. Never hardcode AI model lists — fetch dynamically from CLIs. **Never add `Co-authored-by` trailers** to commit messages. **Never create unrequested files** (temp notes, snapshots, exploration dumps) in the repo — use session-scoped storage instead. **Never write absolute paths** (`/Users/...`, `/home/...`) or expose third-party/employer names in code or docs — use relative paths from repo root. See [docs/standards/ai_agents.md](docs/standards/ai_agents.md).

### No Cairo — Use GtkSnapshot

**Never use `cairo` or `PangoCairo` in new code.** Use the GTK4 `GtkSnapshot` API. See [docs/standards/rendering.md](docs/standards/rendering.md).

### IconsManager - Use the Icon Manager

**All icons via `from icons import IconsManager`.** Prefer Nerd Font icons. See [docs/standards/icons.md](docs/standards/icons.md).

## Development Guidelines

### Makefile is the Source of Truth

**All commands must go through the Makefile.** Run `make run` to validate breaking changes. See [docs/standards/build_workflow.md](docs/standards/build_workflow.md).

### Continuous Documentation Alignment

**Align docs whenever changes affect behavior.** Update all relevant surfaces: `README.md` (concise, links wiki only), `AGENTS.md` (links `docs/`), `docs/` (exhaustive technical reference), and `docs/wiki/` (user-facing details). New project docs belong under `docs/`, non-standard docs must use a `YYYY_MM_DD_` filename prefix, and all docs must follow [docs/standards/spec_format.md](docs/standards/spec_format.md). See [docs/standards/documentation.md](docs/standards/documentation.md) for full scoping rules.

### Startup Performance — Zero Regression Policy

**Vim-level startup speed required.** First paint < 80ms, interactive < 90ms. Run `make startup-time` before merging startup-path changes. See [docs/standards/startup_performance.md](docs/standards/startup_performance.md).

### Centralization — No Hardcoding

**Never hardcode values, git calls, or utility functions in components.** Use `src/constants.py`, `git_manager.py`, `git_ignore_utils.py`, `shared/utils.py`. See [docs/standards/centralization.md](docs/standards/centralization.md).

### Popups - Inherit from `NvimPopup` (No Exceptions)

**All popup windows MUST inherit from `NvimPopup`.** See [docs/standards/popups.md](docs/standards/popups.md) for the full rule, API, and popup reference table.

## Documentation Reference

All feature documentation lives in `docs/`. Read the relevant doc before working on that area.

**Every doc must follow the standard format defined in [`docs/standards/spec_format.md`](docs/standards/spec_format.md).** New project docs must live under `docs/`; non-standard docs must use a `YYYY_MM_DD_` filename prefix; and all docs require frontmatter with **Created_at**, **Updated_at**, **Status**, **Goal**, and **Scope** fields. When creating or updating docs, follow this format — see the spec for field definitions, status values, and examples.

### Standards
| Doc | Description |
|-----|-------------|
| [docs/standards/spec_format.md](docs/standards/spec_format.md) | **Required format for all docs** — frontmatter fields, status values, and template |
| [docs/standards/code_style.md](docs/standards/code_style.md) | File/class naming conventions — one class per file, snake_case/PascalCase |
| [docs/standards/ai_agents.md](docs/standards/ai_agents.md) | AI agent restrictions — no commits, no killing host, no co-authored-by, dynamic model fetching |
| [docs/standards/rendering.md](docs/standards/rendering.md) | Rendering standard — no Cairo, use GtkSnapshot |
| [docs/standards/icons.md](docs/standards/icons.md) | Icon management — centralised constants, Nerd Font preference |
| [docs/standards/build_workflow.md](docs/standards/build_workflow.md) | Build workflow — Makefile source of truth, validate breaking changes |
| [docs/standards/documentation.md](docs/standards/documentation.md) | Documentation alignment — keep docs in sync with code changes |
| [docs/standards/startup_performance.md](docs/standards/startup_performance.md) | Startup performance — zero regression policy, hard limits |
| [docs/standards/centralization.md](docs/standards/centralization.md) | Centralization — no hardcoding, git_manager, gitignore, shared/utils |
| [docs/standards/popups.md](docs/standards/popups.md) | Popup standard — NvimPopup inheritance, popup reference table |
| [docs/standards/dist_packaging.md](docs/standards/dist_packaging.md) | Dist packaging — PyInstaller pipeline, dependency checklist, ICU trimming, macOS quirks |

### Formats & Compatibility
| Doc | Description |
|-----|-------------|
| [docs/2026_02_20_supported_formats.md](docs/2026_02_20_supported_formats.md) | All supported file types, languages, viewers, and feature levels |

### Architecture & Design
| Doc | Description |
|-----|-------------|
| [docs/2026_02_15_arc.md](docs/2026_02_15_arc.md) | Architecture analysis and overview |
| [docs/2026_02_27_startup.md](docs/2026_02_27_startup.md) | Startup architecture, phases, and performance targets |
| [docs/2026_03_03_compilation_startup.md](docs/2026_03_03_compilation_startup.md) | Analysis of AOT compilation impact on startup performance |
| [docs/2026_02_17_filesystem_centralisation.md](docs/2026_02_17_filesystem_centralisation.md) | Filesystem access centralisation strategy |
| [docs/2026_02_08_focus_manager.md](docs/2026_02_08_focus_manager.md) | Centralized focus state management system |
| [docs/2026_03_03_zen_ide_user_directory.md](docs/2026_03_03_zen_ide_user_directory.md) | User directory (`~/.zen_ide/`) structure and purpose |
| [docs/2026_03_03_zen_ide_user_directory.md](docs/2026_03_03_zen_ide_user_directory.md) | Detailed `~/.zen_ide/` directory contents and config files |
| [docs/2026_03_05_codebase_audit.md](docs/2026_03_05_codebase_audit.md) | Full codebase audit (~100 issues: threading, data loss, performance, API misuse) |
| [docs/2026_03_05_visual_glitch_analysis.md](docs/2026_03_05_visual_glitch_analysis.md) | Visual glitch root causes (scrolling, flicker, artifacts, refresh — 30 issues) |
| [docs/2026_03_06_cairo_migration.md](docs/2026_03_06_cairo_migration.md) | Cairo → GtkSnapshot migration plan, inventory, and patterns |
| [docs/2026_03_03_polling_mechanisms.md](docs/2026_03_03_polling_mechanisms.md) | Catalog of all polling and timer mechanisms in the IDE |
| [docs/2026_03_12_plugin_architecture.md](docs/2026_03_12_plugin_architecture.md) | Current extensibility architecture and proposed Python plugin system design |

### Theming
| Doc | Description |
|-----|-------------|
| [docs/2026_03_03_custom_themes.md](docs/2026_03_03_custom_themes.md) | Custom user-defined JSON themes |

### Editor & Editing
| Doc | Description |
|-----|-------------|
| [docs/2026_02_20_syntax_highlighting.md](docs/2026_02_20_syntax_highlighting.md) | Dynamic style scheme generation and syntax highlighting layers |
| [docs/2026_02_08_gtk_editor_roadmap.md](docs/2026_02_08_gtk_editor_roadmap.md) | GTK editor roadmap and current state |
| [docs/2026_02_08_diff_view.md](docs/2026_02_08_diff_view.md) | Split diff view for git comparisons |
| [docs/2026_03_03_incremental_edit.md](docs/2026_03_03_incremental_edit.md) | Incremental text edits for format-on-save (preserves scroll/cursor) |
| [docs/2026_02_19_indent_system.md](docs/2026_02_19_indent_system.md) | Indentation editing, smart indent, and indent guides |
| [docs/2026_02_08_dialog_system.md](docs/2026_02_08_dialog_system.md) | Neovim-style floating dialog system |
| [docs/2026_02_12_settings_reference.md](docs/2026_02_12_settings_reference.md) | All settings in `~/.zen_ide/settings.json` |

### AI Integration
| Doc | Description |
|-----|-------------|
| [docs/2026_03_21_ai_terminal.md](docs/2026_03_21_ai_terminal.md) | **Current AI system** — VTE terminal, CLI providers, context injection, inline completions, debug logging |
| [docs/2026_01_25_ai_setup_guide.md](docs/2026_01_25_ai_setup_guide.md) | AI provider setup instructions |
| [docs/2026_01_22_ai_strategy.md](docs/2026_01_22_ai_strategy.md) | How Zen integrates AI capabilities |
| [docs/2026_03_04_ai_inline_completion.md](docs/2026_03_04_ai_inline_completion.md) | Inline ghost text AI code completion system |
| [docs/2026_03_08_inline_completion_comparison.md](docs/2026_03_08_inline_completion_comparison.md) | Inline completion architecture comparison |
| [docs/2026_03_10_inline_completion_comprehensive_reference.md](docs/2026_03_10_inline_completion_comprehensive_reference.md) | Inline completion technical reference: lifecycle, providers, rendering, caching, edge cases |
| [docs/2026_03_07_ai_chat_scroll_stability_plan.md](docs/2026_03_07_ai_chat_scroll_stability_plan.md) | AI chat scroll stability fix plan |

### Navigation & Code Intelligence
| Doc | Description |
|-----|-------------|
| [docs/2026_01_22_navigation.md](docs/2026_01_22_navigation.md) | Code navigation (Cmd+Click / Go-to-Definition) |
| [docs/2026_02_08_intellisense.md](docs/2026_02_08_intellisense.md) | Autocomplete, signature hints, hover highlighting |

### UI Components
| Doc | Description |
|-----|-------------|
| [docs/2026_03_09_icons_system.md](docs/2026_03_09_icons_system.md) | Centralised icon management, file-type mapping, Nerd Font rendering |
| [docs/2026_02_20_tree_view.md](docs/2026_02_20_tree_view.md) | File explorer tree with keyboard navigation and git integration |
| [docs/2026_02_08_dev_pad.md](docs/2026_02_08_dev_pad.md) | Activity tracking panel (Cmd+.) |
| [docs/2026_02_15_sketch_pad.md](docs/2026_02_15_sketch_pad.md) | ASCII drawing tool with box/arrow/text tools |
| [docs/2026_03_03_debugging.md](docs/2026_03_03_debugging.md) | Debugging feature design (DAP-based, multi-language) |
| [docs/2026_02_08_neovim_themes.md](docs/2026_02_08_neovim_themes.md) | Neovim colorscheme integration strategy |
| [docs/2026_02_20_status_bar.md](docs/2026_02_20_status_bar.md) | Nvim-style status bar segments, theming, and API |
| [docs/2026_02_20_terminal.md](docs/2026_02_20_terminal.md) | Integrated VTE terminal: architecture, shortcuts, file navigation, theming |
| [docs/2026_02_18_terminal_aliases.md](docs/2026_02_18_terminal_aliases.md) | Built-in shell aliases in the integrated terminal |
| [docs/2026_03_04_ui_testing.md](docs/2026_03_04_ui_testing.md) | UI testing framework: fixtures, helpers, and patterns |
| [docs/2026_03_17_welcome_screen.md](docs/2026_03_17_welcome_screen.md) | Welcome screen: ASCII logo, version from pyproject.toml, keyboard shortcuts |
| [docs/2026_03_17_widget_inspector.md](docs/2026_03_17_widget_inspector.md) | Widget inspector: DevTools-like inspect mode, AI chat block & color inspection |
| [docs/2026_01_18_unicode.md](docs/2026_01_18_unicode.md) | Unicode box-drawing character reference |