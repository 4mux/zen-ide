"""Laserwave theme - based on LaserWave by Eric Eldredge and Jared Jones."""

from themes.theme_model import Theme

LASERWAVE = Theme(
    name="laserwave",
    display_name="Laserwave",
    # Base colors
    main_bg="#27212e",
    panel_bg="#201b26",
    fg_color="#ffffff",
    fg_dim="#91889b",
    # Selection
    selection_bg="#3d3348",
    hover_bg="#3d3348",
    # Editor
    line_number_bg="#27212e",
    line_number_fg="#7b6995",
    caret_fg="#ffffff",
    indent_guide="#3d3550",
    # Tabs
    tab_bg="#201b26",
    tab_active_bg="#27212e",
    tab_fg="#7b6995",
    tab_active_fg="#ffffff",
    # Tree
    tree_bg="#201b26",
    tree_fg="#ffffff",
    tree_selected_bg="#3d3348",
    tree_modified_fg="#ffe261",
    tree_ignored_fg="#7b6995",
    # Terminal
    term_bg="#27212e",
    term_fg="#ffffff",
    # Accent
    accent_color="#eb64b9",
    # Borders
    border_color="#3d3348",
    border_focus="#eb64b9",
    sash_color="#3d3348",
    # AI Chat
    term_cyan="#b4dce7",
    # Syntax
    syntax_keyword="#74dfc4",
    syntax_string="#b4dce7",
    syntax_comment="#91889b",
    syntax_number="#b381c5",
    syntax_function="#eb64b9",
    syntax_class="#b381c5",
    syntax_operator="#40b4c4",
    # Extended syntax
    syntax_keyword_control="#74dfc4",
    syntax_variable="#ffffff",
    syntax_string_escape="#74dfc4",
    syntax_constant="#ffe261",
    syntax_boolean="#ffe261",
    syntax_doc_comment="#91889b",
    syntax_regex="#b4dce7",
    # Git status
    git_added="#74dfc4",
    git_modified="#ffe261",
    git_deleted="#ff3e7b",
    # Terminal ANSI
    term_black="#201b26",
    term_red="#eb64b9",
    term_green="#74dfc4",
    term_yellow="#ffe261",
    term_blue="#40b4c4",
    term_magenta="#b381c5",
    term_white="#ffffff",
    syntax_parameter="#b381c5",
    search_match_bg="#515c6a",
    search_current_bg="#61afef",
    is_dark=True,
    warning_color="#f0d050",
)
