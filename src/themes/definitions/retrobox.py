"""Retrobox theme - CGA/retro terminal inspired, based on Vim's retrobox colorscheme."""

from themes.theme_model import Theme

RETROBOX = Theme(
    name="retrobox",
    display_name="Retrobox",
    # Base colors - classic dark CRT feel
    main_bg="#1c1c1c",
    panel_bg="#121212",
    fg_color="#d0d0d0",
    fg_dim="#6c6c6c",
    # Selection
    selection_bg="#005f5f",
    hover_bg="#303030",
    # Editor
    line_number_bg="#1c1c1c",
    line_number_fg="#585858",
    caret_fg="#ffff00",
    indent_guide="#303030",
    # Tabs
    tab_bg="#121212",
    tab_active_bg="#1c1c1c",
    tab_fg="#6c6c6c",
    tab_active_fg="#d0d0d0",
    # Tree
    tree_bg="#121212",
    tree_fg="#d0d0d0",
    tree_selected_bg="#005f5f",
    tree_modified_fg="#d7af5f",
    tree_ignored_fg="#585858",
    # Terminal
    term_bg="#1c1c1c",
    term_fg="#d0d0d0",
    # Accent - CGA cyan
    accent_color="#00afaf",
    # Borders
    border_color="#303030",
    border_focus="#00afaf",
    sash_color="#303030",
    # AI Chat
    term_cyan="#00afaf",
    # Syntax - classic CGA 4-color palette feel
    syntax_keyword="#d75faf",
    syntax_string="#5faf5f",
    syntax_comment="#585858",
    syntax_number="#d7af5f",
    syntax_function="#00afaf",
    syntax_class="#d75faf",
    syntax_operator="#d0d0d0",
    # Extended syntax
    syntax_keyword_control="#af5fff",
    syntax_variable="#87afaf",
    syntax_string_escape="#5fafaf",
    syntax_constant="#d7af5f",
    syntax_boolean="#d75faf",
    syntax_doc_comment="#6c6c6c",
    syntax_regex="#5faf5f",
    # Git status
    git_added="#5faf5f",
    git_modified="#d7af5f",
    git_deleted="#d75f5f",
    # Terminal ANSI - authentic CGA-ish tones
    term_black="#121212",
    term_red="#d75f5f",
    term_green="#5faf5f",
    term_yellow="#d7af5f",
    term_blue="#5f87af",
    term_magenta="#d75faf",
    term_white="#d0d0d0",
    syntax_parameter="#d7af5f",
    search_match_bg="#515c6a",
    search_current_bg="#61afef",
    is_dark=True,
    warning_color="#f0d050",
)
