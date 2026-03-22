"""Tests for Theme model dataclass."""

from themes.theme_model import Theme


def _make_theme(**overrides):
    """Create a minimal Theme for testing."""
    defaults = dict(
        name="test",
        display_name="Test Theme",
        main_bg="#1e1e1e",
        panel_bg="#252525",
        fg_color="#d4d4d4",
        fg_dim="#808080",
        selection_bg="#264f78",
        hover_bg="#2a2d2e",
        line_number_bg="#1e1e1e",
        line_number_fg="#858585",
        caret_fg="#ffffff",
        indent_guide="#404040",
        tab_bg="#2d2d2d",
        tab_active_bg="#1e1e1e",
        tab_fg="#969696",
        tab_active_fg="#ffffff",
        tree_bg="#252525",
        tree_fg="#cccccc",
        tree_selected_bg="#37373d",
        tree_modified_fg="#e2c08d",
        term_bg="#1e1e1e",
        term_fg="#cccccc",
        accent_color="#007acc",
        border_color="#333333",
        border_focus="#007acc",
        syntax_keyword="#569cd6",
        syntax_string="#ce9178",
        syntax_comment="#6a9955",
        syntax_number="#b5cea8",
        syntax_function="#dcdcaa",
        syntax_class="#4ec9b0",
        syntax_operator="#d4d4d4",
        syntax_keyword_control="#569cd6",
        syntax_variable="#d4d4d4",
        syntax_string_escape="#ce9178",
        syntax_regex="#ce9178",
        syntax_doc_comment="#6a9955",
        syntax_constant="#4ec9b0",
        syntax_boolean="#569cd6",
        syntax_parameter="#b5cea8",
        sash_color="#3e3e42",
        term_cyan="#56b6c2",
        search_match_bg="#515c6a",
        search_current_bg="#61afef",
        is_dark=True,
        tree_ignored_fg="#6c6c6c",
        git_added="#98c379",
        git_modified="#e5c07b",
        git_deleted="#e06c75",
        warning_color="#f0d050",
        term_black="#282c34",
        term_red="#e06c75",
        term_green="#98c379",
        term_yellow="#e5c07b",
        term_blue="#61afef",
        term_magenta="#c678dd",
        term_white="#abb2bf",
    )
    defaults.update(overrides)
    return Theme(**defaults)


class TestThemeGetSyntaxColor:
    """Test get_syntax_color returns attribute values."""

    def test_direct_value(self):
        """Returns direct value when set."""
        t = _make_theme(syntax_keyword="#ff0000")
        assert t.get_syntax_color("syntax_keyword") == "#ff0000"

    def test_extended_value(self):
        """Returns extended color value."""
        t = _make_theme(syntax_keyword_control="#ff0000")
        assert t.get_syntax_color("syntax_keyword_control") == "#ff0000"
