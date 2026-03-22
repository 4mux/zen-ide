"""ZX Dreams — ZX Spectrum inspired palette."""

from themes.theme_model import Theme

ZX_DREAMS = Theme(
    name="zx_dreams",
    display_name="ZX Dreams",
    # backgrounds — deep Spectrum black/dark blue
    main_bg="#0d0d1a",
    panel_bg="#080812",
    fg_color="#d7d7d7",
    fg_dim="#7a7a9c",
    selection_bg="#0000c5",
    hover_bg="#1a1a3a",
    # editor
    line_number_bg="#0d0d1a",
    line_number_fg="#4a4a70",
    caret_fg="#d7d700",
    indent_guide="#1a1a3a",
    # tabs
    tab_bg="#080812",
    tab_active_bg="#0d0d1a",
    tab_fg="#7a7a9c",
    tab_active_fg="#d7d7d7",
    # tree
    tree_bg="#080812",
    tree_fg="#d7d7d7",
    tree_selected_bg="#0000c5",
    tree_modified_fg="#d7d700",
    tree_ignored_fg="#4a4a70",
    # terminal
    term_bg="#0d0d1a",
    term_fg="#d7d7d7",
    # accents — Spectrum bright cyan
    accent_color="#00d7d7",
    border_color="#0000c5",
    border_focus="#00d7d7",
    sash_color="#0000c5",
    # chat
    term_cyan="#00d7d7",
    # AI processing
    # search
    search_match_bg="#0000c5",
    search_current_bg="#00d700",
    # syntax — ZX Spectrum 8 bright colors
    syntax_keyword="#d700d7",
    syntax_string="#00d700",
    syntax_comment="#4a4a70",
    syntax_number="#00d7d7",
    syntax_function="#d7d7ff",
    syntax_class="#d7d700",
    syntax_operator="#d70000",
    # extended syntax
    syntax_keyword_control="#ff00ff",
    syntax_variable="#d7d7d7",
    syntax_string_escape="#00ff00",
    syntax_regex="#00d7d7",
    syntax_doc_comment="#5a5a80",
    syntax_constant="#d7d700",
    syntax_boolean="#ff00ff",
    # git
    git_added="#00d700",
    git_modified="#d7d700",
    git_deleted="#d70000",
    # ANSI terminal colors — ZX Spectrum palette
    term_black="#0d0d1a",
    term_red="#d70000",
    term_green="#00d700",
    term_yellow="#d7d700",
    term_blue="#0000d7",
    term_magenta="#d700d7",
    term_white="#d7d7d7",
    syntax_parameter="#00d7d7",
    is_dark=True,
    warning_color="#f0d050",
)
