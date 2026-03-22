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
    )
    defaults.update(overrides)
    return Theme(**defaults)


class TestThemeGetSyntaxColor:
    """Test get_syntax_color fallback resolution."""

    def test_direct_value(self):
        """Returns direct value when set."""
        t = _make_theme(syntax_keyword="#ff0000")
        assert t.get_syntax_color("syntax_keyword") == "#ff0000"

    def test_fallback_keyword_control_to_keyword(self):
        """syntax_keyword_control falls back to syntax_keyword."""
        t = _make_theme(syntax_keyword="#569cd6")
        assert t.get_syntax_color("syntax_keyword_control") == "#569cd6"

    def test_fallback_variable_to_fg_color(self):
        """syntax_variable falls back to fg_color."""
        t = _make_theme(fg_color="#d4d4d4")
        assert t.get_syntax_color("syntax_variable") == "#d4d4d4"

    def test_fallback_string_escape_to_string(self):
        """syntax_string_escape falls back to syntax_string."""
        t = _make_theme(syntax_string="#ce9178")
        assert t.get_syntax_color("syntax_string_escape") == "#ce9178"

    def test_fallback_regex_to_string(self):
        """syntax_regex falls back to syntax_string."""
        t = _make_theme(syntax_string="#aabbcc")
        assert t.get_syntax_color("syntax_regex") == "#aabbcc"

    def test_fallback_doc_comment_to_comment(self):
        """syntax_doc_comment falls back to syntax_comment."""
        t = _make_theme(syntax_comment="#6a9955")
        assert t.get_syntax_color("syntax_doc_comment") == "#6a9955"

    def test_fallback_constant_to_class(self):
        """syntax_constant falls back to syntax_class."""
        t = _make_theme(syntax_class="#4ec9b0")
        assert t.get_syntax_color("syntax_constant") == "#4ec9b0"

    def test_fallback_boolean_to_keyword(self):
        """syntax_boolean falls back to syntax_keyword."""
        t = _make_theme(syntax_keyword="#569cd6")
        assert t.get_syntax_color("syntax_boolean") == "#569cd6"

    def test_unknown_attr_returns_default(self):
        """Unknown attribute returns default color."""
        t = _make_theme()
        assert t.get_syntax_color("syntax_nonexistent") == "#d4d4d4"

    def test_extended_value_when_set(self):
        """Returns extended color when explicitly set."""
        t = _make_theme(syntax_keyword_control="#ff0000")
        assert t.get_syntax_color("syntax_keyword_control") == "#ff0000"


class TestThemeProperties:
    """Test computed properties."""

    def test_editor_bg(self):
        """editor_bg maps to main_bg."""
        t = _make_theme(main_bg="#111111")
        assert t.editor_bg == "#111111"

    def test_terminal_bg(self):
        """terminal_bg maps to term_bg."""
        t = _make_theme(term_bg="#222222")
        assert t.terminal_bg == "#222222"


class TestThemeDefaults:
    """Test default field values."""

    def test_git_added_default(self):
        t = _make_theme()
        assert t.git_added == "#98c379"

    def test_git_modified_default(self):
        t = _make_theme()
        assert t.git_modified == "#e5c07b"

    def test_git_deleted_default(self):
        t = _make_theme()
        assert t.git_deleted == "#e06c75"

    def test_tree_ignored_fg_default(self):
        t = _make_theme()
        assert t.tree_ignored_fg == "#6c6c6c"
