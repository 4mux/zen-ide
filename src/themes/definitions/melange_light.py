"""Melange Light theme — warm, earthy light colorscheme by savq/melange-nvim."""

from themes.theme_model import Theme

MELANGE_LIGHT = Theme(
    name="melange_light",
    display_name="Melange Light",
    is_dark=False,
    # Base
    main_bg="#F1F1F1",
    panel_bg="#E9E1DB",
    fg_color="#54433A",
    fg_dim="#7D6658",
    # Selection
    selection_bg="#D9D3CE",
    hover_bg="#E9E1DB",
    # Editor
    line_number_bg="#F1F1F1",
    line_number_fg="#A98A78",
    caret_fg="#54433A",
    indent_guide="#A98A78",
    # Tabs
    tab_bg="#E9E1DB",
    tab_active_bg="#F1F1F1",
    tab_fg="#7D6658",
    tab_active_fg="#54433A",
    # Tree / sidebar
    tree_bg="#E9E1DB",
    tree_fg="#54433A",
    tree_selected_bg="#D9D3CE",
    tree_modified_fg="#BC5C00",
    tree_ignored_fg="#A98A78",
    # Terminal
    term_bg="#F1F1F1",
    term_fg="#54433A",
    term_black="#E9E1DB",
    term_red="#C77B8B",
    term_green="#6E9B72",
    term_yellow="#BC5C00",
    term_blue="#7892BD",
    term_magenta="#BE79BB",
    term_cyan="#739797",
    term_white="#7D6658",
    # Accents / borders
    accent_color="#BC5C00",
    border_color="#A98A78",
    border_focus="#BC5C00",
    sash_color="#F1F1F1",
    # AI / chat
    # Search
    search_match_bg="#CCA478",
    search_current_bg="#A06D00",
    # Git
    git_added="#3A684A",
    git_modified="#A06D00",
    git_deleted="#BF0021",
    # Warning
    warning_color="#A06D00",
    # Syntax — core 7
    syntax_keyword="#BC5C00",
    syntax_string="#465AA4",
    syntax_comment="#7D6658",
    syntax_number="#904180",
    syntax_function="#A06D00",
    syntax_class="#739797",
    syntax_operator="#BF0021",
    # Syntax — extended
    syntax_keyword_control="#3A684A",
    syntax_variable="#54433A",
    syntax_string_escape="#7892BD",
    syntax_regex="#465AA4",
    syntax_doc_comment="#7D6658",
    syntax_constant="#BE79BB",
    syntax_boolean="#904180",
    syntax_parameter="#54433A",
)
