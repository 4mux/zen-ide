"""
Theme dataclass definition for Zen IDE.
"""

from dataclasses import dataclass


@dataclass
class Theme:
    """Color theme definition used by GTK themes."""

    name: str
    display_name: str

    # Base colors
    main_bg: str
    panel_bg: str
    fg_color: str
    fg_dim: str

    # Selection
    selection_bg: str
    hover_bg: str

    # Editor
    line_number_bg: str
    line_number_fg: str
    caret_fg: str
    indent_guide: str

    # Tabs
    tab_bg: str
    tab_active_bg: str
    tab_fg: str
    tab_active_fg: str

    # Tree
    tree_bg: str
    tree_fg: str
    tree_selected_bg: str
    tree_modified_fg: str

    # Terminal
    term_bg: str
    term_fg: str

    # Accent
    accent_color: str

    # Borders
    border_color: str
    border_focus: str

    # Syntax colors
    syntax_keyword: str
    syntax_string: str
    syntax_comment: str
    syntax_number: str
    syntax_function: str
    syntax_class: str
    syntax_operator: str

    # Extended syntax colors
    syntax_keyword_control: str = ""
    syntax_variable: str = ""
    syntax_string_escape: str = ""
    syntax_regex: str = ""
    syntax_doc_comment: str = ""
    syntax_constant: str = ""
    syntax_boolean: str = ""
    syntax_parameter: str = ""

    # Sash (splitter)
    sash_color: str = "#3e3e42"

    # AI processing color (purple for thinking indicator)
    ai_processing_color: str = "#c678dd"

    # Terminal cyan (used for user labels in AI chat)
    term_cyan: str = "#56b6c2"

    # AI Chat colors
    chat_user_fg: str = "#61afef"
    chat_assistant_fg: str = "#98c379"

    # Search/Find colors
    search_match_bg: str = "#515c6a"
    search_current_bg: str = "#61afef"

    # Dark/light mode flag
    is_dark: bool = True

    # Tree ignored (gitignored items)
    tree_ignored_fg: str = "#6c6c6c"

    # Git status colors
    git_added: str = "#98c379"
    git_modified: str = "#e5c07b"
    git_deleted: str = "#e06c75"

    # Diagnostic colors
    warning_color: str = "#f0d050"

    # Terminal ANSI colors
    term_black: str = "#282c34"
    term_red: str = "#e06c75"
    term_green: str = "#98c379"
    term_yellow: str = "#e5c07b"
    term_blue: str = "#61afef"
    term_magenta: str = "#c678dd"
    term_white: str = "#abb2bf"

    def get_syntax_color(self, attr: str) -> str:
        """Get a syntax color with fallback resolution for extended colors."""
        val = getattr(self, attr, "")
        if val:
            return val
        fallbacks = {
            "syntax_keyword_control": "syntax_keyword",
            "syntax_variable": "fg_color",
            "syntax_string_escape": "syntax_string",
            "syntax_regex": "syntax_string",
            "syntax_doc_comment": "syntax_comment",
            "syntax_constant": "syntax_class",
            "syntax_boolean": "syntax_keyword",
            "syntax_parameter": "syntax_number",
        }
        fallback_attr = fallbacks.get(attr)
        if fallback_attr:
            return getattr(self, fallback_attr, "#d4d4d4")
        return "#d4d4d4"

    def get_color(self, attr: str) -> str:
        """Safely get any theme color with fallback to prevent empty values."""
        val = getattr(self, attr, "")
        if val:
            return val

        # Common fallbacks for different color types
        if "bg" in attr:
            return self.main_bg or "#1e1e1e"
        elif "fg" in attr:
            return self.fg_color or "#d4d4d4"
        elif attr.startswith("syntax_"):
            return self.get_syntax_color(attr)
        else:
            # Generic fallback for any other color
            return "#606060"

    # Computed properties for compatibility
    @property
    def editor_bg(self) -> str:
        """Editor background - maps to main_bg."""
        return self.main_bg

    @property
    def terminal_bg(self) -> str:
        """Terminal background - maps to term_bg."""
        return self.term_bg
