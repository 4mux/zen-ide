# FAQ & Tips

## Frequently Asked Questions

### How do I open a project/folder?

Use `Cmd+Shift+O` (Open Workspace) or launch from the terminal:
```bash
code ~/my-project
```

### How do I change the theme?

Press `Cmd+Shift+T` to open the theme picker. Browse 41 themes with live preview. Press `Enter` to confirm or `Escape` to cancel.

### How do I change the font?

Open the Font Picker from the **View** menu. You can set different fonts for the editor, terminal, tree view, AI chat, and markdown preview.

For quick size changes, use `Cmd++` / `Cmd+-` / `Cmd+0`.

### How do I set up AI features?

Zen IDE AI chat is not API-based anymore. It runs the `claude` or `copilot` CLI inside the integrated AI Terminal:

- **Claude CLI** — install `claude` and run `claude login`
- **Copilot CLI** — install `copilot` and run `copilot auth`

Inline ghost text suggestions still use Copilot-backed auth from your machine.

Open AI chat → click provider selector → choose Claude or Copilot. See [AI Setup](AI-Setup) for details.

### How do I disable AI suggestions?

To disable inline ghost text but keep AI chat:
```json
{ "ai.show_inline_suggestions": false }
```

To disable all AI features:
```json
{ "ai.is_enabled": false }
```

### How do I configure format on save?

See [Formatters & Linters](Formatters-and-Linters). The default formatters are ruff (Python) and prettier (JS/TS).

To disable: set `editor.format_on_save` to `false`.

### Where are settings stored?

All settings live in `~/.zen_ide/settings.json`. See [Settings Reference](Settings) for every option.

### How do I reset settings?

Delete the settings file:
```bash
rm ~/.zen_ide/settings.json
```
Zen IDE recreates it with defaults on next launch.

### How do I add custom shell aliases?

Add them to `~/.zen_ide/aliases`:
```bash
alias gco='git checkout'
alias gp='git push'
```

### Can I use vim keybindings?

Zen IDE has Neovim-style emulation with `:w`, `:q`, and `:wq` commands. This is enabled by default via `behavior.is_nvim_emulation_enabled`.

The tree view also uses vim-style `j`/`k`/`h`/`l` navigation, and all popups support `j`/`k` for movement.

### How do I create a new file?

- `Cmd+N` — New file in the editor
- Right-click a folder in the tree → **New File** — create with a specific name/location

### How do I split the terminal?

Click the **+** button in the terminal header to add a new terminal pane.

### How do I create a workspace file?

Use **File → New Workspace...** from the menu. This opens a Save dialog where you choose where to store the `.zen-workspace` file. The file is pre-populated with a template:

```json
{
  "folders": [
    {
      "name": "my-project",
      "path": "."
    }
  ]
}
```

Each folder entry has a `name` (display name in the tree) and a `path` (absolute or relative to the workspace file). After saving, the file opens in the editor for you to customise, and you're asked whether to load the workspace immediately.

### Can I use multiple workspaces?

Yes! Multiple workspace roots are supported. Add folders to your `.zen-workspace` file, use `Cmd+Shift+O`, or edit `workspace.folders` in settings.

---

## Tips & Tricks

### Navigation
- **`Cmd+P` is your best friend** — Quick open is the fastest way to navigate large projects
- **`Cmd+Click` on imports** — Jump directly to the source of any import
- **`Cmd+Click` in the terminal** — Click on file paths in compiler/linter output to open them

### Productivity
- **Multiple AI chat sessions** — Keep one for your current task and another for general questions
- **Dev Pad notes** — Leave breadcrumbs while debugging; they persist across sessions
- **Sketch Pad for design** — Draw architecture diagrams without leaving the IDE

### Performance
- Zen IDE targets **< 80ms** first paint — it should feel instant
- Heavy features (terminal, AI chat) are deferred after first paint
- The tree view uses virtual scrolling — it handles large projects efficiently

### Theme Development
- Use `Cmd+Shift+I` (Widget Inspector) to see which theme colours are applied
- Create a `~/.zen_ide/custom_theme.json` with your custom colours
- The theme picker shows live previews — iterate quickly

### Terminal
- The terminal inherits your system bash configuration plus Zen-specific settings
- Use `gst` alias for quick git status
- Click the **TERMINAL** header label to quickly `cd` into a workspace folder
