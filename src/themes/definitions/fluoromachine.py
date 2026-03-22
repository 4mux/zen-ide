"""Fluoromachine theme - Neon retro-futuristic with heavy magenta/cyan."""

from themes.theme_model import Theme

FLUOROMACHINE = Theme(
    name="fluoromachine",
    display_name="Fluoromachine",
    # Base colors - deep purple-dark
    main_bg="#241b2f",
    panel_bg="#1b1425",
    fg_color="#8b8da3",
    fg_dim="#544863",
    # Selection
    selection_bg="#3c2a4d",
    hover_bg="#2e2240",
    # Editor
    line_number_bg="#241b2f",
    line_number_fg="#544863",
    caret_fg="#fc199a",
    indent_guide="#2e2240",
    # Tabs
    tab_bg="#1b1425",
    tab_active_bg="#241b2f",
    tab_fg="#544863",
    tab_active_fg="#8b8da3",
    # Tree
    tree_bg="#1b1425",
    tree_fg="#8b8da3",
    tree_selected_bg="#3c2a4d",
    tree_modified_fg="#fce566",
    tree_ignored_fg="#544863",
    # Terminal
    term_bg="#241b2f",
    term_fg="#8b8da3",
    # Accent - hot magenta
    accent_color="#fc199a",
    # Borders
    border_color="#2e2240",
    border_focus="#fc199a",
    sash_color="#2e2240",
    # AI Chat
    term_cyan="#61e2ff",
    # Syntax - neon retro-futuristic
    syntax_keyword="#fc199a",
    syntax_string="#72f1b8",
    syntax_comment="#544863",
    syntax_number="#fce566",
    syntax_function="#61e2ff",
    syntax_class="#9d7dce",
    syntax_operator="#8b8da3",
    # Extended syntax
    syntax_keyword_control="#9d7dce",
    syntax_variable="#ff2afc",
    syntax_string_escape="#61e2ff",
    syntax_constant="#fce566",
    syntax_boolean="#fc199a",
    syntax_doc_comment="#544863",
    syntax_regex="#72f1b8",
    # Git status
    git_added="#72f1b8",
    git_modified="#fce566",
    git_deleted="#fc199a",
    # Terminal ANSI - neon retro
    term_black="#1b1425",
    term_red="#fc199a",
    term_green="#72f1b8",
    term_yellow="#fce566",
    term_blue="#61e2ff",
    term_magenta="#9d7dce",
    term_white="#8b8da3",
    syntax_parameter="#fce566",
    search_match_bg="#515c6a",
    search_current_bg="#61afef",
    is_dark=True,
    warning_color="#f0d050",
)
