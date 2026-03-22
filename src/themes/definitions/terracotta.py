"""
Terracotta — a warm, earthy dark theme inspired by sun-baked clay,
Mediterranean pottery, and desert landscapes.
"""

from themes.theme_model import Theme

TERRACOTTA = Theme(
    name="terracotta",
    display_name="Terracotta",
    # Base — deep warm charcoal-brown
    main_bg="#1e1916",
    panel_bg="#261f1b",
    fg_color="#e8ddd0",
    fg_dim="#9a8b7c",
    # Selection
    selection_bg="#3d2e26",
    hover_bg="#332821",
    # Editor
    line_number_bg="#1e1916",
    line_number_fg="#6b5d52",
    caret_fg="#d4845a",
    indent_guide="#362c25",
    # Tabs
    tab_bg="#1e1916",
    tab_active_bg="#2f2520",
    tab_fg="#9a8b7c",
    tab_active_fg="#e8ddd0",
    # Tree
    tree_bg="#1a1513",
    tree_fg="#c4b5a5",
    tree_selected_bg="#3d2e26",
    tree_modified_fg="#c9a84c",
    # Terminal
    term_bg="#1a1513",
    term_fg="#e8ddd0",
    # Accent — terracotta orange
    accent_color="#d4845a",
    # Borders
    border_color="#362c25",
    border_focus="#d4845a",
    # Syntax — dusty rose keywords, sage strings, honey functions
    syntax_keyword="#c27a8e",
    syntax_string="#8fa67a",
    syntax_comment="#706052",
    syntax_number="#e0956e",
    syntax_function="#c9a84c",
    syntax_class="#d4a05a",
    syntax_operator="#b8a692",
    # Extended syntax
    syntax_keyword_control="#d68a9e",
    syntax_variable="#d4bfa8",
    syntax_string_escape="#a8bf8a",
    syntax_regex="#b0c28a",
    syntax_doc_comment="#8a7564",
    syntax_constant="#d4a05a",
    syntax_boolean="#c27a8e",
    # UI extras
    sash_color="#362c25",
    term_cyan="#7ab0a6",
    search_match_bg="#4d3a2c",
    search_current_bg="#5a4232",
    is_dark=True,
    tree_ignored_fg="#5e5047",
    # Git
    git_added="#8fa67a",
    git_modified="#c9a84c",
    git_deleted="#c25a5a",
    # Terminal ANSI
    term_black="#1e1916",
    term_red="#c25a5a",
    term_green="#8fa67a",
    term_yellow="#c9a84c",
    term_blue="#7a8fa6",
    term_magenta="#c27a8e",
    term_white="#e8ddd0",
    syntax_parameter="#e0956e",
    warning_color="#f0d050",
)
