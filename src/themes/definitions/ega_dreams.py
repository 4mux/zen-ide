"""EGA Dreams theme — a nostalgic tribute to the Enhanced Graphics Adapter's 16-color palette."""

from themes.theme_model import Theme

EGA_DREAMS = Theme(
    name="ega_dreams",
    display_name="EGA Dreams",
    # Base — dark black background
    main_bg="#0e0e0e",
    panel_bg="#141414",
    fg_color="#aaaaaa",
    fg_dim="#555555",
    # Selection — EGA dark magenta band
    selection_bg="#aa00aa",
    hover_bg="#1a1a1a",
    # Editor
    line_number_bg="#0e0e0e",
    line_number_fg="#555555",
    caret_fg="#ffff55",
    indent_guide="#222222",
    # Tabs — dark with EGA blue active glow
    tab_bg="#141414",
    tab_active_bg="#0000aa",
    tab_fg="#555555",
    tab_active_fg="#55ffff",
    # Tree — dark with EGA light gray text
    tree_bg="#141414",
    tree_fg="#aaaaaa",
    tree_selected_bg="#0000aa",
    tree_modified_fg="#ffff55",
    tree_ignored_fg="#555555",
    # Terminal
    term_bg="#141414",
    term_fg="#aaaaaa",
    # Accent — EGA light cyan, the signature color
    accent_color="#55ffff",
    # Borders — subtle dark lines with EGA cyan focus
    border_color="#1a1a1a",
    border_focus="#55ffff",
    # Sash
    sash_color="#0e0e0e",
    # AI / Chat
    term_cyan="#55ffff",
    # Search — EGA yellow highlight
    search_match_bg="#aa5500",
    search_current_bg="#ffff55",
    # Syntax — drawn from the classic EGA 16-color palette
    syntax_keyword="#5555ff",
    syntax_string="#55ff55",
    syntax_comment="#00aaaa",
    syntax_number="#ffff55",
    syntax_function="#55ffff",
    syntax_class="#ff55ff",
    syntax_operator="#aaaaaa",
    # Extended syntax
    syntax_keyword_control="#0000aa",
    syntax_variable="#aaaaaa",
    syntax_string_escape="#00aa00",
    syntax_regex="#55ff55",
    syntax_doc_comment="#00aaaa",
    syntax_constant="#ff5555",
    syntax_boolean="#ff55ff",
    # Git status — EGA green/yellow/red
    git_added="#55ff55",
    git_modified="#ffff55",
    git_deleted="#ff5555",
    # Terminal ANSI — faithful EGA bright palette
    term_black="#0e0e0e",
    term_red="#ff5555",
    term_green="#55ff55",
    term_yellow="#ffff55",
    term_blue="#5555ff",
    term_magenta="#ff55ff",
    term_white="#aaaaaa",
    syntax_parameter="#ffff55",
    is_dark=True,
    warning_color="#f0d050",
)
