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
    syntax_keyword_control: str
    syntax_variable: str
    syntax_string_escape: str
    syntax_regex: str
    syntax_doc_comment: str
    syntax_constant: str
    syntax_boolean: str
    syntax_parameter: str

    # Sash (splitter)
    sash_color: str

    # Search/Find colors
    search_match_bg: str
    search_current_bg: str

    # Dark/light mode flag
    is_dark: bool

    # Tree ignored (gitignored items)
    tree_ignored_fg: str

    # Git status colors
    git_added: str
    git_modified: str
    git_deleted: str

    # Diagnostic colors
    warning_color: str

    # Terminal cyan (used for ANSI palette and previews)
    term_cyan: str

    # Terminal ANSI colors
    term_black: str
    term_red: str
    term_green: str
    term_yellow: str
    term_blue: str
    term_magenta: str
    term_white: str

    def get_syntax_color(self, attr: str) -> str:
        """Get a syntax color by attribute name."""
        return getattr(self, attr)
