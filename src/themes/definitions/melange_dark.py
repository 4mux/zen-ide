"""Melange Dark theme — warm, earthy dark colorscheme by savq/melange-nvim."""

from themes.theme_model import Theme

MELANGE_DARK = Theme(
    name="melange_dark",
    display_name="Melange Dark",
    is_dark=True,
    # Base
    main_bg="#292522",
    panel_bg="#34302C",
    fg_color="#ECE1D7",
    fg_dim="#C1A78E",
    # Selection
    selection_bg="#403A36",
    hover_bg="#34302C",
    # Editor
    line_number_bg="#292522",
    line_number_fg="#867462",
    caret_fg="#ECE1D7",
    indent_guide="#867462",
    # Tabs
    tab_bg="#34302C",
    tab_active_bg="#292522",
    tab_fg="#C1A78E",
    tab_active_fg="#ECE1D7",
    # Tree / sidebar
    tree_bg="#34302C",
    tree_fg="#ECE1D7",
    tree_selected_bg="#403A36",
    tree_modified_fg="#E49B5D",
    tree_ignored_fg="#867462",
    # Terminal
    term_bg="#292522",
    term_fg="#ECE1D7",
    term_black="#34302C",
    term_red="#BD8183",
    term_green="#78997A",
    term_yellow="#E49B5D",
    term_blue="#7F91B2",
    term_magenta="#B380B0",
    term_cyan="#7B9695",
    term_white="#C1A78E",
    # Accents / borders
    accent_color="#E49B5D",
    border_color="#867462",
    border_focus="#E49B5D",
    sash_color="#292522",
    # AI / chat
    # Search
    search_match_bg="#8B7449",
    search_current_bg="#EBC06D",
    # Git
    git_added="#85B695",
    git_modified="#EBC06D",
    git_deleted="#D47766",
    # Warning
    warning_color="#EBC06D",
    # Syntax — core 7
    syntax_keyword="#E49B5D",
    syntax_string="#A3A9CE",
    syntax_comment="#C1A78E",
    syntax_number="#CF9BC2",
    syntax_function="#EBC06D",
    syntax_class="#7B9695",
    syntax_operator="#D47766",
    # Syntax — extended
    syntax_keyword_control="#85B695",
    syntax_variable="#ECE1D7",
    syntax_string_escape="#7F91B2",
    syntax_regex="#A3A9CE",
    syntax_doc_comment="#C1A78E",
    syntax_constant="#B380B0",
    syntax_boolean="#CF9BC2",
    syntax_parameter="#ECE1D7",
)
