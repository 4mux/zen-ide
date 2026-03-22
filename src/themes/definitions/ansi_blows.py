"""Ansi Blows theme - based on ansi_blows.vim by Brandon Low."""

from themes.theme_model import Theme

ANSI_BLOWS = Theme(
    name="ansi_blows",
    display_name="Ansi Blows",
    # Base colors
    main_bg="#000000",
    panel_bg="#0a0a0a",
    fg_color="#aaaaaa",
    fg_dim="#555555",
    # Selection
    selection_bg="#1d28d2",
    hover_bg="#1a1a3a",
    # Editor
    line_number_bg="#000000",
    line_number_fg="#ffff44",
    caret_fg="#ffffff",
    indent_guide="#333333",
    # Tabs
    tab_bg="#0a0a0a",
    tab_active_bg="#000000",
    tab_fg="#555555",
    tab_active_fg="#ffffff",
    # Tree
    tree_bg="#0a0a0a",
    tree_fg="#aaaaaa",
    tree_selected_bg="#1d28d2",
    tree_modified_fg="#ffff44",
    tree_ignored_fg="#555555",
    # Terminal
    term_bg="#000000",
    term_fg="#aaaaaa",
    # Accent
    accent_color="#5050ff",
    # Borders
    border_color="#333333",
    border_focus="#5050ff",
    sash_color="#333333",
    # Terminal extras
    term_cyan="#00aaaa",
    # Syntax - mapped from vim highlight groups
    syntax_keyword="#ffff44",  # Statement
    syntax_string="#ff44ff",  # Constant (boldMagenta)
    syntax_comment="#44ffff",  # Comment (boldCyan)
    syntax_number="#ff44ff",  # Constant (boldMagenta)
    syntax_function="#44ffff",  # Identifier (boldCyan)
    syntax_class="#44ff44",  # Type (boldGreen)
    syntax_operator="#dc3244",  # Special (boldRed)
    # Extended syntax
    syntax_keyword_control="#ffff44",
    syntax_variable="#44ffff",
    syntax_string_escape="#dc3244",
    syntax_constant="#ff44ff",
    syntax_boolean="#ff44ff",
    syntax_doc_comment="#00aaaa",
    syntax_regex="#dc3244",
    # Search
    search_match_bg="#aa5500",
    search_current_bg="#cc7700",
    # Git status
    git_added="#00aa00",
    git_modified="#ffff44",
    git_deleted="#b90000",
    # Terminal ANSI colors
    term_black="#000000",
    term_red="#b90000",
    term_green="#00aa00",
    term_yellow="#ffff44",
    term_blue="#1d28d2",
    term_magenta="#aa00aa",
    term_white="#aaaaaa",
    syntax_parameter="#ff44ff",
    is_dark=True,
    warning_color="#f0d050",
)
