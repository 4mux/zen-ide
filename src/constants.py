"""Zen IDE constants.

Centralized configuration values for Zen IDE.
"""

# Window Defaults
DEFAULT_WINDOW_WIDTH = 1400
DEFAULT_WINDOW_HEIGHT = 900

# Layout Defaults
DEFAULT_TREE_WIDTH = 400  # pixels width of tree view sidebar
DEFAULT_TREE_MIN_WIDTH = 0  # minimum width tree view can be resized to
DEFAULT_EDITOR_SPLIT = 500  # initial vertical split position (editor vs bottom panel)
DEFAULT_BOTTOM_PANEL_MIN_HEIGHT = 200  # minimum height for AI chat and terminal

# Font
DEFAULT_FONT_SIZE = 16
MIN_FONT_SIZE = 8
MAX_FONT_SIZE = 36

# Nerd Font Icons
NERD_ICON_SIZE_OFFSET = 3  # extra points added to icon font size vs text size

# Tree View
TREE_ROW_MARGIN_TOP = 5  # pixels above text
TREE_ROW_MARGIN_BOTTOM = 5  # pixels below text
TREE_SCROLL_SPEED = 0.15  # rows per scroll wheel notch (lower = slower)

# Editor Cursor (Vim-style block cursor)
CURSOR_ALPHA = 1.0  # opacity of block cursor (0.0 = transparent, 1.0 = opaque)
CURSOR_BLINK_ON_MS = 530  # milliseconds cursor is visible during blink cycle
CURSOR_BLINK_OFF_MS = 530  # milliseconds cursor is hidden during blink cycle

# Editor Indentation
DEFAULT_INDENT_WIDTH = 4  # default indent width for all languages
# Language-specific indent widths (language ID or file extension → spaces per indent level)
LANG_INDENT_WIDTH = {
    "terraform": 2,  # Terraform (.tf)
    ".tf": 2,  # Terraform by extension
    "clojure": 2,  # Clojure convention
}

# Languages that require real tab characters (not spaces)
TAB_ONLY_LANGS = frozenset({"makefile"})

# Editor Indent Guides
INDENT_GUIDE_ALPHA = 1.00  # opacity of indent guide lines (0.0 = transparent, 1.0 = opaque)
# Language IDs that should NOT show indent guides (non-coding files)
NO_INDENT_GUIDE_LANGS = frozenset({"markdown", "txt", "text", "plain", "restructuredtext", "changelog", "bibtex", "latex"})
# Bracket-based languages: opener/closer lines ({/[/}/]) get scope-extended guides
BRACKET_SCOPE_LANGS = frozenset(
    {
        "json",
        "js",
        "typescript",
        "jsx",
        "typescript-jsx",
        "java",
        "c",
        "cpp",
        "objc",
        "c-sharp",
        "css",
        "scss",
        "less",
        "go",
        "rust",
        "swift",
        "kotlin",
        "dart",
        "php",
        "ruby",
        "perl",
        "lua",
        "r",
        "scala",
        "groovy",
        "terraform",
        "vala",
        "clojure",
    }
)

# Editor Left Padding (spacing between line numbers and code)
EDITOR_LEFT_PADDING = 20  # pixels of left margin between gutter and code text

# Editor Gutter Diff Indicators (vertical bars next to line numbers)
GUTTER_DIFF_WIDTH = 3  # pixels width of diff indicator bar in editor gutter

# Editor Minimap
MINIMAP_WIDTH = 100  # pixels width of code minimap on editor right side
EDITOR_MINIMAP_INDICATOR_WIDTH = 20  # pixels width of git diff/diagnostic indicator strip

# Diff Minimap
DIFF_MINIMAP_WIDTH = EDITOR_MINIMAP_INDICATOR_WIDTH  # pixels width — matches editor scrollbar strip

# AI Chat
AI_CHAT_NO_DATA_TIMEOUT = 300  # seconds with no output before killing stuck AI process
TERMINAL_SCROLLBAR_HIDE_DELAY_MS = 1200  # overlay jog-wheel scrollbar auto-hide delay

# Terminal
TERMINAL_HEADER_MARGIN_TOP = 8  # pixels above terminal header (matches tree view header margin)
TERMINAL_HEADER_MARGIN_BOTTOM = 4  # pixels below terminal header
TERMINAL_TAB_BAR_MARGIN_BOTTOM = 6  # pixels below terminal tab bar

# Tab Buttons (editor, terminal, AI chat)
TAB_BUTTON_HEIGHT = 20  # uniform height for all tab buttons across panels
TAB_BUTTON_FONT_SIZE = 12  # uniform font size (pt) for all tab button labels

# ZenButton (shared UI button)
ZEN_BUTTON_HEIGHT = 25  # uniform height (px) for all ZenButton instances
ZEN_BUTTON_ICON_SIZE = 12  # default icon font-size (px) for ZenButton icons

# Panel Header Buttons (AI chat, terminal)
PANEL_BUTTON_SIZE = ZEN_BUTTON_HEIGHT  # uniform width/height for panel header buttons
PANEL_HEADER_FONT_SIZE = 13  # uniform font size (pt) for panel header labels

# Focus Animation
FOCUS_ANIM_DURATION_MS = 150  # Total animation duration in milliseconds
FOCUS_ANIM_STEPS = 10  # Number of interpolation steps
FOCUS_BORDER_WIDTH = 2  # Border line width in pixels

# Paned Animation (expand/collapse panels)
PANED_ANIM_DURATION_MS = 100  # Default duration for paned slide animations
PANED_ANIM_FRAME_INTERVAL_MS = 16  # ~60fps frame interval

# Autocomplete
AUTOCOMPLETE_MAX_ITEMS = 15  # max visible items in autocomplete popup
AUTOCOMPLETE_AUTO_TRIGGER_CHARS = 3  # min chars before auto-triggering completions
AUTOCOMPLETE_AUTO_TRIGGER_DELAY_MS = 150  # debounce delay for auto-trigger (ms)

# Status Bar
STATUS_BAR_HORIZONTAL_PADDING = 20  # pixels of left/right padding for status bar
STATUS_BAR_ITEM_SPACING = 8  # pixels of spacing between right-side status bar items
STATUS_BAR_FONT_FAMILY = ""  # empty = use editor font family for status bar text

# Sketch Pad Toolbar
SKETCH_TOOL_BTN_SIZE = ZEN_BUTTON_HEIGHT  # pixels width/height of sketch toolbar buttons
SKETCH_TOOL_ICON_SIZE = 18  # font-size (px) for sketch toolbar icons

# Workspace file extensions (Zen native + VSC compatible)
WORKSPACE_EXTENSIONS = (".zen-workspace", ".code-workspace")

# Image file extensions supported for preview
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff", ".tif", ".svg"}
