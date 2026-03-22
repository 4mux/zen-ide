"""
Keybindings for Zen IDE.
Provides keyboard shortcut definitions.
"""

import sys

# Keyboard shortcuts using GTK/Gdk naming convention
# Note: GTK4 on macOS doesn't properly map <Primary> to Cmd
# We use <Meta> on macOS (Cmd key) and <Control> elsewhere
_MOD = "<Meta>" if sys.platform == "darwin" else "<Control>"
_MOD_SHIFT = f"{_MOD}<Shift>"


class KeyBindings:
    """Central keybindings registry for Zen IDE."""

    # File operations
    NEW_FILE = f"{_MOD}n"
    OPEN_FILE = f"{_MOD}o"
    OPEN_WORKSPACE = f"{_MOD_SHIFT}o"
    SAVE_FILE = f"{_MOD}s"
    SAVE_AS = f"{_MOD_SHIFT}s"
    CLOSE_TAB = f"{_MOD}w"
    QUIT = f"{_MOD}q"

    # Edit operations
    UNDO = f"{_MOD}z"
    REDO = f"{_MOD_SHIFT}z"
    CUT = f"{_MOD}x"
    COPY = f"{_MOD}c"
    PASTE = f"{_MOD}v"
    SELECT_ALL = f"{_MOD}a"
    FIND = f"{_MOD}f"
    FIND_NEXT = f"{_MOD}g"
    FIND_PREV = f"{_MOD_SHIFT}g"
    GLOBAL_SEARCH = f"{_MOD_SHIFT}f"
    TOGGLE_COMMENT = f"{_MOD}slash"
    INDENT = f"{_MOD}bracketright"
    UNINDENT = f"{_MOD}bracketleft"

    # View operations
    FOCUS_EXPLORER = f"{_MOD_SHIFT}e"
    QUICK_OPEN = f"{_MOD}p"
    REFRESH = f"{_MOD}r"
    CLEAR_TERMINAL = f"{_MOD}k"
    ZOOM_IN = f"{_MOD}equal"
    ZOOM_OUT = f"{_MOD}minus"
    ZOOM_RESET = f"{_MOD}0"
    TOGGLE_DEV_PAD = f"{_MOD}period"
    OPEN_SKETCH_PAD = f"{_MOD_SHIFT}d"
    THEME_PICKER = f"{_MOD_SHIFT}t"
    TOGGLE_DARK_LIGHT = f"{_MOD_SHIFT}l"

    # Code
    AUTOCOMPLETE = f"{_MOD}space"  # Cmd+Space on macOS, Ctrl+Space elsewhere

    # AI operations
    AI_HISTORY = f"{_MOD}h"

    # Maximize focused panel (editor, terminal, ai_chat, or tree)
    MAXIMIZE_FOCUSED = f"{_MOD_SHIFT}backslash"

    # Reset layout to default positions
    RESET_LAYOUT = f"{_MOD_SHIFT}0"

    # Cycle focus between panels
    CYCLE_FOCUS_RIGHT = "<Control><Shift>Right"
    CYCLE_FOCUS_LEFT = "<Control><Shift>Left"
    CYCLE_FOCUS_UP = "<Control><Shift>Up"
    CYCLE_FOCUS_DOWN = "<Control><Shift>Down"

    # Toggle all UI panels (tree, terminal, etc.)
    SHOW_UI = f"{_MOD_SHIFT}u"

    # Toggle widget inspect mode (browser DevTools-like)
    TOGGLE_INSPECT = f"{_MOD_SHIFT}i"

    # Open app menu
    OPEN_MENU = "F10"

    @classmethod
    def get_shortcut_categories(cls) -> list:
        """Get all shortcuts as structured data: list of (category, [(name, key), ...]).

        This is the single source of truth for shortcut display across the app
        (welcome screen, shortcuts popup, formatted text output).
        """
        mod = "Cmd" if sys.platform == "darwin" else "Ctrl"
        word_mod = "Opt" if sys.platform == "darwin" else "Ctrl"

        return [
            (
                "File Operations",
                [
                    ("New File", f"{mod}+N"),
                    ("Open File", f"{mod}+O"),
                    ("Open Workspace", f"{mod}+Shift+O"),
                    ("Save File", f"{mod}+S"),
                    ("Close Tab", f"{mod}+W"),
                    ("Quit", f"{mod}+Q"),
                    ("Copy Item (Tree)", f"{mod}+C"),
                    ("Paste Item (Tree)", f"{mod}+V"),
                ],
            ),
            (
                "Edit",
                [
                    ("Undo", f"{mod}+Z"),
                    ("Redo", f"{mod}+Shift+Z"),
                    ("Find", f"{mod}+F"),
                    ("Find Next", f"{mod}+G"),
                    ("Find Previous", f"{mod}+Shift+G"),
                    ("Search in Files", f"{mod}+Shift+F"),
                    ("Toggle Comment", f"{mod}+/"),
                    ("Indent", f"{mod}+]"),
                    ("Unindent", f"{mod}+["),
                ],
            ),
            (
                "View",
                [
                    ("Quick Open", f"{mod}+P"),
                    ("Focus Explorer", f"{mod}+Shift+E"),
                    ("Toggle Dev Pad", f"{mod}+."),
                    ("Sketch Pad", f"{mod}+Shift+D"),
                    ("Reload IDE", f"{mod}+R"),
                    ("Clear Terminal", f"{mod}+K"),
                    ("Zoom In", f"{mod}++"),
                    ("Zoom Out", f"{mod}+-"),
                    ("Reset Zoom", f"{mod}+0"),
                    ("Theme Picker", f"{mod}+Shift+T"),
                    ("Toggle Dark/Light", f"{mod}+Shift+L"),
                ],
            ),
            (
                "Code & Navigation",
                [
                    ("Autocomplete", f"{mod}+Space"),
                    ("Go to Definition", f"{mod}+Click"),
                    ("Word Navigation", f"{word_mod}+Left/Right"),
                    ("Accept AI Suggestion", "Tab"),
                    ("Accept Word", f"{mod}+Right"),
                    ("Dismiss Suggestion", "Escape"),
                    ("Next Suggestion", "Alt+]"),
                    ("Prev Suggestion", "Alt+["),
                ],
            ),
            (
                "Terminal",
                [
                    ("Line Start", f"{mod}+Left"),
                    ("Line End", f"{mod}+Right"),
                    ("Clear Terminal", f"{mod}+K"),
                    ("Interrupt Command", "Ctrl+C"),
                ],
            ),
            (
                "AI & Panels",
                [
                    ("AI History", f"{mod}+H"),
                    ("Focus Next Panel", "Ctrl+Shift+Right"),
                    ("Focus Prev Panel", "Ctrl+Shift+Left"),
                    ("Focus Editor (Up)", "Ctrl+Shift+Up"),
                    ("Focus Bottom (Down)", "Ctrl+Shift+Down"),
                    ("Maximize Focused Panel", f"{mod}+Shift+\\"),
                    ("Maximize Window", f"{mod}+Shift+0"),
                    ("Widget Inspector", f"{mod}+Shift+I"),
                    ("Open Menu", "F10"),
                    ("Keyboard Shortcuts", f"{mod}+Shift+/"),
                ],
            ),
        ]
