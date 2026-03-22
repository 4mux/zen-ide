"""64 Dreams — C64 videogame inspired palette. Dark CRT glow with vivid sprite colors."""

from themes.theme_model import Theme

C64_VIDEOGAME_DREAMS = Theme(
    name="c64_videogame_dreams",
    display_name="64 Dreams",
    # backgrounds — near-black with CRT blue tint
    main_bg="#0c0c1e",
    panel_bg="#08081a",
    fg_color="#c8c8d0",
    fg_dim="#6a6a80",
    selection_bg="#2a2a48",
    hover_bg="#1a1a36",
    # editor
    line_number_bg="#0c0c1e",
    line_number_fg="#3a3a58",
    caret_fg="#eeee77",
    indent_guide="#1a1a36",
    # tabs
    tab_bg="#08081a",
    tab_active_bg="#0c0c1e",
    tab_fg="#6a6a80",
    tab_active_fg="#c8c8d0",
    # tree
    tree_bg="#08081a",
    tree_fg="#c8c8d0",
    tree_selected_bg="#2a2a48",
    tree_modified_fg="#aaff66",
    tree_ignored_fg="#3a3a58",
    # terminal
    term_bg="#0c0c1e",
    term_fg="#c8c8d0",
    # accents — classic C64 light blue
    accent_color="#6c9cf6",
    border_color="#2a2a48",
    border_focus="#6c9cf6",
    sash_color="#2a2a48",
    # chat
    term_cyan="#aaffee",
    # syntax — vivid sprite colors
    syntax_keyword="#ff7777",
    syntax_string="#aaff66",
    syntax_comment="#4a4a68",
    syntax_number="#eeee77",
    syntax_function="#aaffee",
    syntax_class="#cc77cc",
    syntax_operator="#dd8855",
    # ANSI terminal colors — C64 game palette
    term_black="#08081a",
    term_red="#ff7777",
    term_green="#aaff66",
    term_yellow="#eeee77",
    term_blue="#6c9cf6",
    term_magenta="#cc77cc",
    term_white="#c8c8d0",
    syntax_keyword_control="#ff7777",
    syntax_variable="#c8c8d0",
    syntax_string_escape="#aaff66",
    syntax_regex="#aaff66",
    syntax_doc_comment="#4a4a68",
    syntax_constant="#cc77cc",
    syntax_boolean="#ff7777",
    syntax_parameter="#eeee77",
    search_match_bg="#515c6a",
    search_current_bg="#61afef",
    is_dark=True,
    git_added="#98c379",
    git_modified="#e5c07b",
    git_deleted="#e06c75",
    warning_color="#f0d050",
)
