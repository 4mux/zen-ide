# Quick Start Guide

Get productive with Zen IDE in five minutes.

## 1. Open a Project

```bash
make run                # Launch Zen IDE
# or, if you installed the CLI:
code ~/my-project       # Open a folder
code file.py            # Open a single file
```

You can also use **File → Open Workspace** (`Cmd+Shift+O`) from inside the IDE, or create a new workspace with **File → New Workspace...**.

## 2. Navigate Files

| Action | How |
|---|---|
| **Quick open** | `Cmd+P` — fuzzy file finder; start typing a filename |
| **Tree explorer** | `Cmd+Shift+E` — focus the left sidebar, then `j`/`k` to navigate, `Enter` to open |
| **Global search** | `Cmd+Shift+F` — search across all workspace files |

## 3. Edit Code

| Action | How |
|---|---|
| Find & replace | `Cmd+F` (supports regex) |
| Toggle comment | `Cmd+/` |
| Indent / Unindent | `Cmd+]` / `Cmd+[` |
| Go to definition | `Cmd+Click` on a symbol |
| Autocomplete | `Cmd+Space` |
| Accept AI suggestion | `Tab` (ghost text appears automatically) |

## 4. Use the Terminal

Press `` Cmd+` `` to focus the terminal. It's a full bash shell with:
- Git-aware prompt showing your current branch
- `Cmd+Click` on file paths to open them in the editor
- Built-in aliases like `gst` (git status)

Split terminals with the **+** button in the terminal header.

## 5. AI Chat

Click the AI chat panel on the right, or look for the AI tab. Start typing your question. Zen supports:
- **Copilot API** — auto-detected if you use GitHub Copilot (zero setup)
- **Anthropic API** — paste your API key in the provider setup
- **OpenAI API** — paste your API key in the provider setup

The AI provider is auto-detected. Switch providers via the dropdown in the chat header.

## 6. Customise

| What | How |
|---|---|
| Switch theme | `Cmd+Shift+T` — browse 41 themes with live preview |
| Change font | Use the Font Picker from the View menu |
| Toggle dark/light | `Cmd+Shift+L` |
| Edit settings | Open `~/.zen_ide/settings.json` — all options listed in [Settings Reference](Settings) |

## 7. Key Shortcuts to Memorise

| Shortcut | Action |
|---|---|
| `Cmd+P` | Quick open file |
| `Cmd+Shift+F` | Search in all files |
| `Cmd+/` | Toggle comment |
| `` Cmd+` `` | Focus terminal |
| `Cmd+.` | Toggle Dev Pad |
| `Cmd+Shift+T` | Theme picker |
| `Cmd+Shift+/` | Show all shortcuts |
| `Cmd+W` | Close tab |
| `Cmd+S` | Save |

> **Full reference:** See [Keyboard Shortcuts](Keyboard-Shortcuts) for the complete list.
