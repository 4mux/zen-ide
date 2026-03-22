"""Synthwave '84 theme - Neon magenta, cyan, yellow on dark purple; pure 80s synthwave."""

from themes.theme_model import Theme

SYNTHWAVE84 = Theme(
    name="synthwave84",
    display_name="Synthwave '84",
    # Base colors - deep purple-black
    main_bg="#262335",
    panel_bg="#1e1a2b",
    fg_color="#f0e8ff",
    fg_dim="#848bbd",
    # Selection
    selection_bg="#463465",
    hover_bg="#34294f",
    # Editor
    line_number_bg="#262335",
    line_number_fg="#495495",
    caret_fg="#ff7edb",
    indent_guide="#34294f",
    # Tabs
    tab_bg="#1e1a2b",
    tab_active_bg="#262335",
    tab_fg="#495495",
    tab_active_fg="#f0e8ff",
    # Tree
    tree_bg="#1e1a2b",
    tree_fg="#f0e8ff",
    tree_selected_bg="#463465",
    tree_modified_fg="#fede5d",
    tree_ignored_fg="#495495",
    # Terminal
    term_bg="#262335",
    term_fg="#f0e8ff",
    # Accent - neon pink
    accent_color="#ff7edb",
    # Borders
    border_color="#34294f",
    border_focus="#ff7edb",
    sash_color="#34294f",
    # AI Chat
    term_cyan="#36f9f6",
    # Syntax - full neon palette
    syntax_keyword="#fede5d",
    syntax_string="#ff8b39",
    syntax_comment="#848bbd",
    syntax_number="#f97e72",
    syntax_function="#36f9f6",
    syntax_class="#ff7edb",
    syntax_operator="#fede5d",
    # Extended syntax
    syntax_keyword_control="#c792ea",
    syntax_variable="#ff7edb",
    syntax_string_escape="#72f1b8",
    syntax_constant="#ff7edb",
    syntax_boolean="#f97e72",
    syntax_doc_comment="#6d77b3",
    syntax_regex="#36f9f6",
    # Git status
    git_added="#72f1b8",
    git_modified="#fede5d",
    git_deleted="#f97e72",
    # Terminal ANSI - neon synthwave
    term_black="#1e1a2b",
    term_red="#f97e72",
    term_green="#72f1b8",
    term_yellow="#fede5d",
    term_blue="#36f9f6",
    term_magenta="#ff7edb",
    term_white="#f0e8ff",
    syntax_parameter="#f97e72",
    search_match_bg="#515c6a",
    search_current_bg="#61afef",
    is_dark=True,
    warning_color="#f0d050",
)
