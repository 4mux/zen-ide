"""Cyberdream theme - High-contrast cyan/magenta/green on near-black."""

from themes.theme_model import Theme

CYBERDREAM = Theme(
    name="cyberdream",
    display_name="Cyberdream",
    # Base colors - near-black with white text
    main_bg="#16181a",
    panel_bg="#0e1012",
    fg_color="#ffffff",
    fg_dim="#7b8496",
    # Selection
    selection_bg="#293244",
    hover_bg="#1e2028",
    # Editor
    line_number_bg="#16181a",
    line_number_fg="#3c4048",
    caret_fg="#5ef1ff",
    indent_guide="#1e2028",
    # Tabs
    tab_bg="#0e1012",
    tab_active_bg="#16181a",
    tab_fg="#3c4048",
    tab_active_fg="#ffffff",
    # Tree
    tree_bg="#0e1012",
    tree_fg="#ffffff",
    tree_selected_bg="#293244",
    tree_modified_fg="#f1ff5e",
    tree_ignored_fg="#3c4048",
    # Terminal
    term_bg="#16181a",
    term_fg="#ffffff",
    # Accent - electric cyan
    accent_color="#5ef1ff",
    # Borders
    border_color="#1e2028",
    border_focus="#5ef1ff",
    sash_color="#1e2028",
    # AI Chat
    term_cyan="#5ef1ff",
    # Syntax - vivid neon on black
    syntax_keyword="#ff5ef1",
    syntax_string="#5eff6c",
    syntax_comment="#7b8496",
    syntax_number="#ffbd5e",
    syntax_function="#5ef1ff",
    syntax_class="#ff5ef1",
    syntax_operator="#ffffff",
    # Extended syntax
    syntax_keyword_control="#bd5eff",
    syntax_variable="#ffffff",
    syntax_string_escape="#5ef1ff",
    syntax_constant="#ffbd5e",
    syntax_boolean="#ff5ef1",
    syntax_doc_comment="#7b8496",
    syntax_regex="#5eff6c",
    # Git status
    git_added="#5eff6c",
    git_modified="#f1ff5e",
    git_deleted="#ff6e5e",
    # Terminal ANSI - high-contrast neon
    term_black="#0e1012",
    term_red="#ff6e5e",
    term_green="#5eff6c",
    term_yellow="#f1ff5e",
    term_blue="#5ea1ff",
    term_magenta="#ff5ef1",
    term_white="#ffffff",
    syntax_parameter="#ffbd5e",
    search_match_bg="#515c6a",
    search_current_bg="#61afef",
    is_dark=True,
    warning_color="#f0d050",
)
