"""Aurora Borealis theme — inspired by the northern lights."""

from themes.theme_model import Theme

AURORA_BOREALIS = Theme(
    name="aurora_borealis",
    display_name="Aurora Borealis",
    # Base colors — deep arctic night sky
    main_bg="#0b0e14",
    panel_bg="#0f1219",
    fg_color="#c7d5e0",
    fg_dim="#6b7d8e",
    # Selection
    selection_bg="#1a3a4a",
    hover_bg="#131923",
    # Editor
    line_number_bg="#0d1017",
    line_number_fg="#3d5065",
    caret_fg="#7fefbd",
    indent_guide="#1e2a38",
    # Tabs
    tab_bg="#0f1219",
    tab_active_bg="#0f1219",
    tab_fg="#6b7d8e",
    tab_active_fg="#c7d5e0",
    # Tree
    tree_bg="#0f1219",
    tree_fg="#c7d5e0",
    tree_selected_bg="#1a3a4a",
    tree_modified_fg="#5ccfe6",
    tree_ignored_fg="#3d5065",
    # Terminal
    term_bg="#0f1219",
    term_fg="#c7d5e0",
    # Accent — aurora green
    accent_color="#7fefbd",
    # Borders
    border_color="#1a2332",
    border_focus="#7fefbd",
    # Sash
    sash_color="#0b0e14",
    # AI / Chat
    term_cyan="#5ccfe6",
    # Search
    search_match_bg="#2a4a3a",
    search_current_bg="#3a6a4a",
    # Syntax — northern lights palette
    syntax_keyword="#c594ff",
    syntax_string="#7fefbd",
    syntax_comment="#4a6070",
    syntax_number="#ffad66",
    syntax_function="#5ccfe6",
    syntax_class="#f29e74",
    syntax_operator="#f0c674",
    # Extended syntax
    syntax_keyword_control="#d4a0ff",
    syntax_variable="#c7d5e0",
    syntax_string_escape="#95e6cb",
    syntax_regex="#f28779",
    syntax_doc_comment="#5c7a8a",
    syntax_constant="#ffad66",
    syntax_boolean="#ff8f40",
    # Git status
    git_added="#7fefbd",
    git_modified="#f0c674",
    git_deleted="#f07178",
    # Terminal ANSI
    term_black="#0b0e14",
    term_red="#f07178",
    term_green="#7fefbd",
    term_yellow="#f0c674",
    term_blue="#5ccfe6",
    term_magenta="#c594ff",
    term_white="#c7d5e0",
    syntax_parameter="#ffad66",
    is_dark=True,
    warning_color="#f0d050",
)
