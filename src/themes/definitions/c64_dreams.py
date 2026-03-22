"""64 Basic Dreams — Commodore 64 inspired palette."""

from themes.theme_model import Theme

C64_DREAMS = Theme(
    name="c64_dreams",
    display_name="64 Basic Dreams",
    # backgrounds — deep C64 purple-blue
    main_bg="#2b2063",
    panel_bg="#221a54",
    fg_color="#d0c8ff",
    fg_dim="#8a82b8",
    selection_bg="#4a3d8a",
    hover_bg="#3a2f78",
    # editor
    line_number_bg="#2b2063",
    line_number_fg="#6a60a0",
    caret_fg="#bfce72",
    indent_guide="#3a2f78",
    # tabs
    tab_bg="#221a54",
    tab_active_bg="#2b2063",
    tab_fg="#8a82b8",
    tab_active_fg="#d0c8ff",
    # tree
    tree_bg="#221a54",
    tree_fg="#d0c8ff",
    tree_selected_bg="#4a3d8a",
    tree_modified_fg="#bfce72",
    tree_ignored_fg="#6a60a0",
    # terminal
    term_bg="#2b2063",
    term_fg="#d0c8ff",
    # accents — C64 light blue
    accent_color="#6abfc6",
    border_color="#4a3d8a",
    border_focus="#6abfc6",
    sash_color="#4a3d8a",
    # chat
    term_cyan="#6abfc6",
    # syntax — full C64 16-color palette for variety
    syntax_keyword="#cb7e75",
    syntax_string="#bfce72",
    syntax_comment="#6a60a0",
    syntax_number="#6abfc6",
    syntax_function="#d0c8ff",
    syntax_class="#9ae29b",
    syntax_operator="#cb7e75",
    # ANSI terminal colors — C64 palette mapped
    term_black="#221a54",
    term_red="#cb7e75",
    term_green="#9ae29b",
    term_yellow="#c9d487",
    term_blue="#6abfc6",
    term_magenta="#a057a3",
    term_white="#d0c8ff",
    syntax_keyword_control="#cb7e75",
    syntax_variable="#d0c8ff",
    syntax_string_escape="#bfce72",
    syntax_regex="#bfce72",
    syntax_doc_comment="#6a60a0",
    syntax_constant="#9ae29b",
    syntax_boolean="#cb7e75",
    syntax_parameter="#6abfc6",
    search_match_bg="#515c6a",
    search_current_bg="#61afef",
    is_dark=True,
    git_added="#98c379",
    git_modified="#e5c07b",
    git_deleted="#e06c75",
    warning_color="#f0d050",
)
