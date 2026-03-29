"""Default settings for Zen IDE."""

import sys

_IS_MACOS = sys.platform == "darwin"
# macOS CoreText renders text thinner, Linux with subpixel rendering is fine at "normal".
_DEFAULT_FONT_WEIGHT = "medium" if _IS_MACOS else "normal"

_DEFAULT_FONT = "Source Code Pro"

DEFAULT_SETTINGS = {
    "theme": "aura_dark",
    "cursor_blink": False,
    "wide_cursor": True,
    "editor": {
        "tab_size": 4,
        "insert_spaces": True,
        "show_line_numbers": True,
        "highlight_current_line": True,
        "word_wrap": False,
        "letter_spacing": 0,
        "font_ligatures": False,
        "show_indent_guides": True,
        "indent_guide_color": "",  # Override theme indent guide color (hex, e.g. "#ff0000"); empty = use theme
        "indent_guide_alpha": 0.6,  # Override indent guide opacity (0.0-1.0); -1 = use default
        "show_minimap": True,
        "scroll_past_end": True,
        "show_whitespace": False,
        "whitespace_color": "",  # Override whitespace dot/arrow color (hex); empty = use theme fg_dim
        "whitespace_alpha": 0.5,  # Whitespace dot/arrow opacity (0.0-1.0); -1 = fully opaque
        "auto_close_brackets": True,
        "auto_complete_on_type": False,
        "format_on_save": True,
    },
    "terminal": {
        "scrollback_lines": 10000,
        "shell": "",
    },
    "ai": {
        "is_enabled": True,  # Master toggle — when False, hides AI chat and disables inline suggestions
        "provider": "",  # "", "claude_cli", "copilot_cli" — empty means auto-detect (prefers claude)
        "model": "",  # CLI model override — e.g. "opus", "sonnet", "haiku" for claude_cli; empty means CLI default
        "show_inline_suggestions": True,  # Enable AI ghost text inline suggestions
        "yolo_mode": True,  # When True: no tool-use limit (unlimited iterations). When False: stops after 25 tool calls and asks to continue.
        "inline_completion": {
            "trigger_delay_ms": 500,  # Debounce delay before requesting a completion
            "model": "gpt-4.1-mini",  # Model for inline completions — use cheapest capable model
        },
    },
    "treeview": {
        "line_spacing": 12,  # Total vertical spacing (px) split evenly above/below each row
    },
    "status_bar": {
        "show_full_path": True,
        "item_spacing": 0,
        "inner_spacing": 4,
    },
    "layout": {
        "main_splitter": 250,
        "right_splitter": -250,
        "bottom_splitter": 0,
        "window_width": 1400,
        "window_height": 900,
    },
    "workspace": {
        "folders": [],
        "last_file": "",
        "open_files": [],
        "workspace_file": "",
        "dev_pad_open": False,
    },
    "popup": {
        "border_radius": 0,  # Border radius for popup windows (0 = sharp corners)
    },
    "dev_pad": {
        "max_activities": 500,  # Maximum number of activities displayed in the Dev Pad
    },
    "behavior": {
        "auto_show_dev_pad_when_empty": True,  # Show dev pad when no files are open
        "is_nvim_emulation_enabled": True,
        "terminal_follow_file": True,  # cd terminal to file's repo when switching files
        "auto_expand_terminals": True,  # Reset terminals to default size when opening a file after all tabs were closed
        "terminals_on_vertical_stack": True,  # True = vertically stacked panes, False = horizontal tab bar
        "ai_chat_on_vertical_stack": False,  # True = vertically stacked panes, False = horizontal tab bar
    },
    "formatters": {
        ".py": [
            "ruff check --select I --fix --stdin-filename {file}",
            "ruff format --stdin-filename {file}",
        ],
        ".json": "builtin",
    },
    "diagnostics": {
        ".py": {
            "command": "ruff check --output-format json --no-fix {file}",
            "format": "ruff",
        },
    },
    "fonts": {
        "editor": {"family": _DEFAULT_FONT, "size": 14, "weight": _DEFAULT_FONT_WEIGHT},
        "terminal": {"family": _DEFAULT_FONT, "size": 14, "weight": _DEFAULT_FONT_WEIGHT},
        "explorer": {"family": _DEFAULT_FONT, "size": 14, "weight": _DEFAULT_FONT_WEIGHT},
        "ai_chat": {"family": _DEFAULT_FONT, "size": 14, "weight": _DEFAULT_FONT_WEIGHT},
        "markdown_preview": {"family": _DEFAULT_FONT, "size": 14, "weight": _DEFAULT_FONT_WEIGHT},
    },
    "debugger": {
        "configurations": [],
        "adapters": {
            "codelldb": {
                "command": ["codelldb", "--port", "stdin"],
                "launch_args_key": "program",
            },
            "rdbg": {
                "command": ["rdbg", "--open", "--command", "--"],
                "launch_args_key": "script",
                "extra_launch_args": {"command": "ruby"},
            },
        },
        "file_types": {
            ".py": "python",
            ".c": "cppdbg",
            ".cpp": "cppdbg",
            ".cc": "cppdbg",
            ".cxx": "cppdbg",
            ".c++": "cppdbg",
            ".h": "cppdbg",
            ".hpp": "cppdbg",
            ".js": "node",
            ".mjs": "node",
            ".cjs": "node",
            ".jsx": "node",
            ".ts": "node",
            ".mts": "node",
            ".cts": "node",
            ".tsx": "node",
            ".rs": "codelldb",
            ".rb": "rdbg",
        },
    },
    "font_rendering": {
        # Pango text rendering backend: "auto", "coretext", "freetype".
        # "auto" uses the platform default (CoreText on macOS, FreeType on Linux).
        # "freetype" on macOS forces FontConfig+FreeType2 (Linux-style rendering),
        # which enables the antialias/hinting/subpixel settings below.
        # Requires restart to take effect.
        "pango_backend": "freetype",
        # Antialias/hinting/subpixel settings apply on Linux always, and on macOS
        # only when pango_backend is "freetype".
        "antialias": True,
        "hinting": True,
        "hintstyle": "hintslight",  # "hintnone", "hintslight", "hintmedium", "hintfull"
        "subpixel_order": "rgb",  # "none", "rgb", "bgr", "vrgb", "vbgr"
        # Cross-platform — snaps glyph metrics to pixel grid for crisper text.
        "hint_font_metrics": True,
    },
}
