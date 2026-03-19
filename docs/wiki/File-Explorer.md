# File Explorer (Tree View)

The file explorer is a custom-rendered tree with Nerd Font icons, git status badges, drag-and-drop, and vim-style keyboard navigation.

## Opening the Tree

| Action | Shortcut |
|---|---|
| Focus tree | `Cmd+Shift+E` |
| Quick open (fuzzy finder) | `Cmd+P` |
| Open workspace | `Cmd+Shift+O` |

## Keyboard Navigation

The tree supports vim-style navigation:

| Key | Action |
|---|---|
| `↓` or `j` | Move selection down |
| `↑` or `k` | Move selection up |
| `→` or `l` or `Enter` | Expand folder / Open file |
| `←` or `h` | Collapse folder / Go to parent |
| `Cmd+Click` | Toggle multi-select |
| `Shift+Click` | Select range |
| `Cmd+A` | Select all visible items |
| `Cmd+Delete` | Delete selected items |
| `Cmd+C` | Copy selected items |
| `Cmd+V` | Paste copied items |

## File Icons

Over 50 file types display unique Nerd Font icons with distinct colours:

| Extension | Icon Colour | Language |
|---|---|---|
| `.py` | Yellow (#ffbc03) | Python |
| `.ts` | Blue (#3178c6) | TypeScript |
| `.js` | Yellow (#f1e05a) | JavaScript |
| `.rs` | Orange (#dea584) | Rust |
| `.go` | Cyan (#00add8) | Go |
| `.html` | Orange (#e44d26) | HTML |
| `.css` | Purple (#563d7c) | CSS |
| `.md` | Blue (#519aba) | Markdown |
| `.json` | Yellow | JSON |
| `.yaml` | Red | YAML |
| `Dockerfile` | Blue (#2496ed) | Docker |
| `.tf` | Purple (#7b42bc) | Terraform |

If no Nerd Font is detected on first run, emoji fallbacks are used. The detection result is cached in `~/.zen_ide/font_cache.txt`.

## Git Status Indicators

Each file shows its git status as a coloured badge:

| Badge | Colour | Meaning |
|---|---|---|
| `M` | Yellow (#e5c07b) | Modified |
| `A` | Green (#98c379) | Staged / Added |
| `D` | Red (#e06c75) | Deleted |
| `R` | Blue (#61afef) | Renamed |
| `?` | Bright green (#73c991) | Untracked |
| `I` | Dim grey | Gitignored |

Parent directories inherit the modified colour when any child is modified.

## Context Menu (Right-Click)

### File Actions
- **Open** — Open in editor
- **Show in Finder** — Reveal in system file manager
- **Copy Path** — Copy full path to clipboard
- **Rename** — Inline rename (extension preserved)
- **Delete** — Delete with confirmation dialog
- **Discard Local Changes** — Git revert to HEAD (only shown for modified files)

### Folder Actions
- **New File** — Create file with inline naming
- **New Folder** — Create folder with inline naming
- **Show in Finder** — Open in system file manager
- **Copy Path** — Copy full path to clipboard
- **Rename** — Inline rename
- **Delete** — Recursive deletion with confirmation

## Inline Editing

| Action | How |
|---|---|
| Create new file | Right-click folder → New File → type name → `Enter` |
| Create new folder | Right-click folder → New Folder → type name → `Enter` |
| Rename | Right-click → Rename → edit name → `Enter` |
| Cancel | `Escape` |

Newly created files are automatically opened in the editor.

## Drag & Drop

Move files and folders by dragging them in the tree:

| Drop Zone | Action |
|---|---|
| Middle of folder (50%) | Move item into that folder |
| Top/bottom of item (25%) | Reorder at that position |

Validation prevents dropping a folder into its own descendants, onto itself, or creating name conflicts.

## Gitignore Filtering

The tree automatically hides files matching `.gitignore` patterns. Both workspace-level and global gitignore patterns are respected. Patterns are compiled to regex and cached for performance.

## Indent Guides

Neovim-style indent guides show tree depth:
- `│` continuation lines
- `└` corner connectors
- 16px per depth level

## Multiple Workspace Roots

Multiple folders can be open simultaneously. You can manage workspaces in several ways:

### Creating a Workspace File

Use **File → New Workspace...** to create a `.zen-workspace` file. The format is:

```json
{
  "folders": [
    {
      "name": "frontend",
      "path": "/Users/you/projects/frontend"
    },
    {
      "name": "backend",
      "path": "../backend"
    }
  ]
}
```

Each entry has a `name` (display label in the tree) and a `path` (absolute, or relative to the workspace file location). After saving, you're prompted to load it immediately.

### Other Ways to Add Folders

- **File → Open Workspace...** (`Cmd+Shift+O`) — open an existing `.zen-workspace` or `.code-workspace` file
- **File → Edit Workspace...** — edit the current workspace file directly in the editor
- Edit `workspace.folders` in `~/.zen_ide/settings.json`

The tree preserves expanded state, selection, and scroll position across refreshes.

## Settings

| Setting | Default | Description |
|---|---|---|
| `treeview.line_spacing` | `10` | Vertical spacing between rows (pixels) |
