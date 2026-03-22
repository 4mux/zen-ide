"""CGA Dream theme — a neon hallucination of 1984 CGA, magenta-cyan on black."""

from themes.theme_model import Theme

CGA_DREAM = Theme(
    name="cga_dream",
    display_name="CGA Dream",
    # Base — pitch-black CRT with faint blue static
    main_bg="#000000",
    panel_bg="#06061c",
    fg_color="#d0d8ff",
    fg_dim="#404880",
    # Selection — electric magenta scanline band
    selection_bg="#550055",
    hover_bg="#0c0c28",
    # Editor
    line_number_bg="#000000",
    line_number_fg="#303870",
    caret_fg="#ff55ff",
    indent_guide="#101030",
    # Tabs — black with magenta glow on active
    tab_bg="#06061c",
    tab_active_bg="#1a002a",
    tab_fg="#404880",
    tab_active_fg="#ff55ff",
    # Tree — dark with cyan file names
    tree_bg="#06061c",
    tree_fg="#d0d8ff",
    tree_selected_bg="#1a003a",
    tree_modified_fg="#55ffff",
    tree_ignored_fg="#303870",
    # Terminal
    term_bg="#06061c",
    term_fg="#d0d8ff",
    # Accent — CGA magenta, the showstopper
    accent_color="#ff55ff",
    # Borders — barely-there blue phosphor lines
    border_color="#181840",
    border_focus="#ff55ff",
    # Sash
    sash_color="#000000",
    # AI / Chat
    term_cyan="#55ffff",
    # Search — high-contrast yellow block cursor
    search_match_bg="#555500",
    search_current_bg="#888800",
    # Syntax — pure CGA 4-color: magenta, cyan, white, yellow
    syntax_keyword="#ff55ff",
    syntax_string="#55ffff",
    syntax_comment="#404880",
    syntax_number="#ffff55",
    syntax_function="#ffffff",
    syntax_class="#aa55ff",
    syntax_operator="#8888cc",
    # Extended syntax
    syntax_keyword_control="#dd44dd",
    syntax_variable="#d0d8ff",
    syntax_string_escape="#44dddd",
    syntax_regex="#77bbff",
    syntax_doc_comment="#505890",
    syntax_constant="#ffff55",
    syntax_boolean="#ff88ff",
    # Git status — cyan/yellow/amber, no red
    git_added="#55ffff",
    git_modified="#ffff55",
    git_deleted="#ff8855",
    # Terminal ANSI — full CGA 8-color, no red
    term_black="#000000",
    term_red="#ff8855",
    term_green="#55ff55",
    term_yellow="#ffff55",
    term_blue="#5555ff",
    term_magenta="#ff55ff",
    term_white="#d0d8ff",
    syntax_parameter="#ffff55",
    is_dark=True,
    warning_color="#f0d050",
)
