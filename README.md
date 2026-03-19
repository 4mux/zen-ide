# Zen IDE

<img src="zen_icon.png" width="64" height="64"/>

A minimalist and opinionated IDE built with Python and [GTK4](https://gitlab.gnome.org/GNOME/gtk).


## Screenshots

<table>
  <tr>
    <td colspan="2"><img src="screenshots/splash1.png" width="100%"/></td>
  </tr>
  <tr>
    <td><img src="screenshots/splash2.png"/></td>
    <td><img src="screenshots/splash3.png"/></td>
  </tr>
</table>

## Features

- **Editor** — GtkSourceView 5 with syntax highlighting, semantic highlighting, minimap, autocomplete, find & replace, indent guides, color preview
- **File Explorer** — Custom GtkSnapshot-rendered tree with Nerd Font icons, git status badges, drag & drop, vim-style navigation, multi-root workspaces
- **Search** — Quick Open (`Cmd+P`), Global Search (`Cmd+Shift+F`), Go to Definition (`Cmd+Click`)
- **File Previews** — Markdown, HTML, OpenAPI/Swagger, images, hex viewer
- **Git** — Gutter diff markers, side-by-side diff view, commit history navigation, inline revert
- **AI Chat** — GitHub Copilot and Anthropic via direct HTTP API with parallel sessions, inline ghost text, streaming responses
- **Terminal** — VTE with 256-color support, file path linking, shell aliases, workspace folder picker
- **Dev Pad** (`Cmd+.`) — Activity tracking, notes, quick resume links
- **Sketch Pad** (`Cmd+Shift+D`) — ASCII/Unicode diagram editor, opens `.zen_sketch` files in editor with box-drawing shapes, arrows, export to PNG
- **38 Themes** — Zen Dark/Light, Dracula, Gruvbox, Tokyo Night, Catppuccin, and more
- **Vim-Style UI** — Neovim-style floating popups, j/k navigation, context menus
- **Session Restore** — Reopens last files, layout, and panel positions on startup

## Quick Start

```bash
make install   # installs everything: GTK4 system deps, Python venv, dev tools, and the 'zen' CLI command
make run       # launch Zen IDE
```

After install you can also open Zen from any terminal:

```bash
zen .                                 # open current directory
zen file.py                           # open a file
zen ~/projects/my-app.zen-workspace   # open a workspace
```

> If `~/.local/bin` is not in your PATH, add it:
> ```bash
> export PATH="$HOME/.local/bin:$PATH"
> ```

### Platform Support

- **macOS** — ✅ Officially supported
- **Linux** — 🚧 Coming soon

### Requirements

- Python 3.14+, [uv](https://docs.astral.sh/uv/getting-started/installation), macOS (Homebrew)

## Supported Languages

Syntax highlighting via GtkSourceView built-in specs (100+ languages). Smart features (autocomplete, semantic highlighting) for Python, JavaScript/TypeScript, and Terraform.

> See [`docs/2026_02_20_supported_formats.md`](docs/2026_02_20_supported_formats.md) for the full reference including viewer modes, file detection, and feature levels.

## AI Setup

Zen IDE uses direct HTTP API calls for AI — no CLI tools or Node.js needed.

- **Copilot API** — auto-detected if you use GitHub Copilot in any editor (zero setup)
- **Anthropic API** — paste your API key in the IDE

Open AI chat → click provider dropdown → select a provider. See [`docs/wiki/AI-Setup.md`](docs/wiki/AI-Setup.md) for details.

## Makefile Commands

Run `make` to see all available targets. Key ones:

```bash
make install        # Install everything (system deps + venv + dev tools + CLI)
make run            # Run the IDE
make tests          # Run tests
make lint           # Run linter and formatter
make dist           # Build standalone app bundle (macOS)
make clean          # Remove build artifacts
```

## Keyboard Shortcuts

Press `Ctrl+?` inside the IDE to see all shortcuts.

## Configuration

Settings are stored in `~/.zen_ide/settings.json`. See `docs/2026_02_12_settings_reference.md` for details.

## License

[MIT License](LICENSE)

### Third-Party Notices

Zen IDE bundles **ZenIcons.ttf**, a subset font derived from [Nerd Fonts](https://www.nerdfonts.com/). 
It includes glyphs from Devicons, Font Awesome Free, Material Design Icons, Codicons, Octicons, and Powerline — each under their respective open-source licenses. See [THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES) for full details.
