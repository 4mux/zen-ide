# Installation & First Launch

## System Requirements

| Requirement | Minimum |
|---|---|
| Python | 3.14+ |
| OS | macOS 13+ or Linux |
| GTK4 | 4.x (via Homebrew or apt) |
| GtkSourceView | 5.x |
| VTE | 0.70+ (terminal emulator) |

## Install System Dependencies

```bash
# macOS
make install-system-deps   # runs: brew install gtk4 gtksourceview5 vte3 libadwaita gobject-introspection pkg-config

# Linux (Debian/Ubuntu)
make install-system-deps   # runs: apt install libgirepository1.0-dev python3-gi python3-gi-cairo
                           #        gir1.2-gtk-4.0 gir1.2-gtksource-5 gir1.2-adw-1
                           #        gir1.2-vte-3.91 gir1.2-webkit2-4.1
```

## Install Zen IDE

```bash
# Clone and install
git clone https://github.com/4mux/zen-ide.git
cd zen-ide

# Option A: Install everything (system deps + venv + dev + build tools + CLI)
make install

# Option B: Step by step
make install-system-deps   # System dependencies (GTK4 stack)
make install-py            # Create venv and install Python dependencies with uv
make install-dev           # (optional) Install dev tools: pytest, ruff
make install-build         # (optional) Install build tools: pyinstaller, nuitka
make install-cli           # (optional) Install the 'zen' CLI command
```

## Running

```bash
make run               # Launch the IDE
```

## Install the `zen` CLI Command

Open Zen IDE from any terminal:

```bash
make install-cli       # Symlinks the 'zen' command to ~/.local/bin/
```

Then from any terminal:

```bash
zen .                  # Open current directory in Zen IDE
zen myfile.py          # Open a specific file
```

> **Note:** Make sure `~/.local/bin` is in your `PATH`. If it isn't, add this to your shell profile:
> ```bash
> export PATH="$HOME/.local/bin:$PATH"
> ```

## Linux Desktop Entry

On Linux, `make dist` installs a `.desktop` file and icon for app launchers:

```bash
make dist              # Install .desktop file and icon (~/.local/share/applications/)
```

## First Launch

On first launch, Zen IDE will:

1. **Create the user directory** at `~/.zen_ide/` with default settings
2. **Detect Nerd Fonts** on your system and cache the result
3. **Show the Welcome Screen** with the ASCII logo and keyboard shortcut reference
4. **Auto-detect AI providers** (GitHub Copilot or Claude Code if installed)

> **Tip:** Press `Cmd+Shift+/` (macOS) or `Ctrl+Shift+/` (Linux) at any time to see all keyboard shortcuts.

## Building a Standalone App (macOS)

```bash
make install-build     # Install PyInstaller/Nuitka
make dist              # Build .app bundle, sign it, and install to /Applications
```
