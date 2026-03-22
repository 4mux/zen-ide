"""Tests for editor/autocomplete/autocomplete.py - Autocomplete behaviours.

Covers:
- _extract_params: function parameter extraction for auto-insertion
- No popup on deletion: auto-trigger only fires on character insertions
- No popup in comments: auto-trigger skips comment context
- No popup on exact match: suppressed when only suggestion matches typed word
- Auto-dismiss on exact match: live-filtering hides popup when sole match = typed word
- Dot-trigger: typing '.' after an identifier triggers completions
"""

from unittest.mock import MagicMock, patch

from editor.autocomplete.autocomplete import Autocomplete, CompletionItem, CompletionKind

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_autocomplete(**overrides):
    """Create an Autocomplete with mocked GTK dependencies for unit testing."""
    with patch.object(Autocomplete, "__init__", lambda self, *a, **kw: None):
        ac = Autocomplete.__new__(Autocomplete)

    ac._completions = []
    ac._filtered = []
    ac._selected_idx = 0
    ac._word_start_offset = 0
    ac._inserting = False
    ac._auto_trigger_timer = None
    ac._last_buffer_len = 0
    ac._changed_handler = None
    ac._dismiss_guard = False
    ac._dismiss_guard_timer = None
    ac._focus_suppress_idle = None

    ac._buffer = MagicMock()
    ac._view = MagicMock()
    ac._popup = MagicMock()
    ac._listbox = MagicMock()
    ac._sig_box = MagicMock()
    ac._sig_sep = MagicMock()
    ac._sig_buffer = MagicMock()
    ac._sig_view = MagicMock()
    ac._hbox = MagicMock()
    ac._tab = MagicMock()
    ac._python_provider = MagicMock()
    ac._js_provider = MagicMock()
    ac._terraform_provider = MagicMock()
    ac._css_provider = None

    for k, v in overrides.items():
        setattr(ac, k, v)
    return ac


def _mock_buffer(char_count, *, in_comment=False, cursor_offset=0, dot_before=False, char_before_dot="_"):
    """Build a mock GtkSource.Buffer for _on_auto_trigger_change tests."""
    buf = MagicMock()
    buf.get_char_count.return_value = char_count
    buf.get_insert.return_value = MagicMock()

    cursor_iter = MagicMock()
    cursor_iter.get_offset.return_value = cursor_offset
    buf.get_iter_at_mark.return_value = cursor_iter
    buf.iter_has_context_class.return_value = in_comment

    if dot_before:
        # cursor_iter.copy() for dot_iter, then backward_char gets '.'
        dot_iter = MagicMock()
        dot_iter.get_char.return_value = "."
        before_dot = MagicMock()
        before_dot.get_char.return_value = char_before_dot
        dot_iter.copy.return_value = before_dot
        cursor_iter.copy.return_value = dot_iter
    return buf


# ---------------------------------------------------------------------------
# _extract_params
# ---------------------------------------------------------------------------


class TestExtractParams:
    """Test _extract_params for function parameter auto-insertion."""

    def test_simple_params(self):
        assert Autocomplete._extract_params("func(a, b, c)") == "a, b, c"

    def test_strips_self(self):
        assert Autocomplete._extract_params("method(self, x, y)") == "x, y"

    def test_strips_cls(self):
        assert Autocomplete._extract_params("create(cls, name)") == "name"

    def test_strips_type_annotations(self):
        assert Autocomplete._extract_params("func(a: int, b: str) → bool") == "a, b"

    def test_preserves_default_values(self):
        assert Autocomplete._extract_params("func(a=1, b='hello')") == "a=1, b='hello'"

    def test_empty_params(self):
        assert Autocomplete._extract_params("func()") == ""

    def test_no_signature(self):
        assert Autocomplete._extract_params("") == ""

    def test_no_parens(self):
        assert Autocomplete._extract_params("my_variable") == ""

    def test_self_only(self):
        assert Autocomplete._extract_params("method(self)") == ""

    def test_complex_signature(self):
        sig = "process(self, name: str, count: int = 0, verbose: bool = False) → list"
        assert Autocomplete._extract_params(sig) == "name, count=0, verbose=False"

    def test_cls_with_annotations(self):
        assert Autocomplete._extract_params("from_config(cls, config: dict) → MyClass") == "config"

    def test_mixed_self_and_defaults(self):
        sig = "run(self, path: str = '/tmp', dry: bool = True)"
        assert Autocomplete._extract_params(sig) == "path='/tmp', dry=True"


# ---------------------------------------------------------------------------
# No popup on deletion
# ---------------------------------------------------------------------------


class TestNoPopupOnDeletion:
    """Auto-trigger should only fire when characters are inserted, not deleted."""

    def test_deletion_does_not_trigger(self):
        ac = _make_autocomplete(_last_buffer_len=20)
        buf = _mock_buffer(19)  # deletion: 20 → 19
        ac._popup.get_visible.return_value = False

        with patch("editor.autocomplete.autocomplete.get_setting", return_value=True):
            ac._on_auto_trigger_change(buf)

        assert ac._last_buffer_len == 19
        assert ac._auto_trigger_timer is None

    def test_same_length_does_not_trigger(self):
        ac = _make_autocomplete(_last_buffer_len=10)
        buf = _mock_buffer(10)  # replace, same length
        ac._popup.get_visible.return_value = False

        with patch("editor.autocomplete.autocomplete.get_setting", return_value=True):
            ac._on_auto_trigger_change(buf)

        assert ac._auto_trigger_timer is None

    def test_insertion_updates_buffer_len(self):
        ac = _make_autocomplete(_last_buffer_len=10)
        buf = _mock_buffer(11, cursor_offset=11)
        ac._popup.get_visible.return_value = False
        ac._get_word_at_cursor = MagicMock(return_value="ab")  # below threshold

        with patch("editor.autocomplete.autocomplete.get_setting", return_value=True):
            ac._on_auto_trigger_change(buf)

        assert ac._last_buffer_len == 11

    def test_bulk_insertion_does_not_trigger(self):
        """File load / paste of many chars should not trigger autocomplete."""
        ac = _make_autocomplete(_last_buffer_len=0)
        buf = _mock_buffer(500, cursor_offset=500)  # e.g. opening a file
        ac._popup.get_visible.return_value = False

        with patch("editor.autocomplete.autocomplete.get_setting", return_value=True):
            ac._on_auto_trigger_change(buf)

        assert ac._last_buffer_len == 500
        assert ac._auto_trigger_timer is None


# ---------------------------------------------------------------------------
# No popup in comments
# ---------------------------------------------------------------------------


class TestNoPopupInComments:
    """Auto-trigger should skip when cursor is inside a comment."""

    def test_comment_context_skips_trigger(self):
        ac = _make_autocomplete(_last_buffer_len=10)
        buf = _mock_buffer(11, in_comment=True)  # insertion inside comment
        ac._popup.get_visible.return_value = False

        with patch("editor.autocomplete.autocomplete.get_setting", return_value=True):
            ac._on_auto_trigger_change(buf)

        assert ac._auto_trigger_timer is None

    def test_non_comment_allows_trigger(self):
        ac = _make_autocomplete(_last_buffer_len=10)
        buf = _mock_buffer(11, in_comment=False, cursor_offset=11)
        ac._popup.get_visible.return_value = False
        ac._get_word_at_cursor = MagicMock(return_value="onboarding")  # >= 3 chars

        with (
            patch("editor.autocomplete.autocomplete.get_setting", return_value=True),
            patch("editor.autocomplete.autocomplete.GLib") as mock_glib,
        ):
            mock_glib.timeout_add.return_value = 42
            mock_glib.source_remove = MagicMock()
            ac._on_auto_trigger_change(buf)

        assert ac._auto_trigger_timer == 42


# ---------------------------------------------------------------------------
# Dot-trigger
# ---------------------------------------------------------------------------


class TestDotTrigger:
    """Typing '.' after an identifier should schedule auto-trigger."""

    def test_dot_after_identifier_triggers(self):
        ac = _make_autocomplete(_last_buffer_len=15)
        buf = _mock_buffer(16, in_comment=False, cursor_offset=16, dot_before=True, char_before_dot="t")
        ac._popup.get_visible.return_value = False
        ac._get_word_at_cursor = MagicMock(return_value="")  # empty after dot

        with (
            patch("editor.autocomplete.autocomplete.get_setting", return_value=True),
            patch("editor.autocomplete.autocomplete.GLib") as mock_glib,
        ):
            mock_glib.timeout_add.return_value = 99
            mock_glib.source_remove = MagicMock()
            ac._on_auto_trigger_change(buf)

        assert ac._auto_trigger_timer == 99

    def test_dot_after_space_no_trigger(self):
        ac = _make_autocomplete(_last_buffer_len=5)
        buf = _mock_buffer(6, in_comment=False, cursor_offset=6, dot_before=True, char_before_dot=" ")
        ac._popup.get_visible.return_value = False
        ac._get_word_at_cursor = MagicMock(return_value="")

        with patch("editor.autocomplete.autocomplete.get_setting", return_value=True):
            ac._on_auto_trigger_change(buf)

        assert ac._auto_trigger_timer is None

    def test_dot_after_number_triggers(self):
        """Dot after digit (e.g. dict or numeric attr) should also trigger."""
        ac = _make_autocomplete(_last_buffer_len=5)
        buf = _mock_buffer(6, in_comment=False, cursor_offset=6, dot_before=True, char_before_dot="3")
        ac._popup.get_visible.return_value = False
        ac._get_word_at_cursor = MagicMock(return_value="")

        with (
            patch("editor.autocomplete.autocomplete.get_setting", return_value=True),
            patch("editor.autocomplete.autocomplete.GLib") as mock_glib,
        ):
            mock_glib.timeout_add.return_value = 77
            mock_glib.source_remove = MagicMock()
            ac._on_auto_trigger_change(buf)

        assert ac._auto_trigger_timer == 77


# ---------------------------------------------------------------------------
# Skip exact match on show
# ---------------------------------------------------------------------------


class TestSkipExactMatchOnShow:
    """Popup should not appear if the only suggestion is an exact match of typed text."""

    def test_single_exact_match_suppresses_popup(self):
        ac = _make_autocomplete()

        # Simulate what show() does: set completions, run _update_filter, check
        ac._completions = [CompletionItem("onboarding_client", CompletionKind.VARIABLE)]
        ac._update_filter("onboarding_client")

        assert len(ac._filtered) == 1
        assert ac._filtered[0].name == "onboarding_client"
        # This is the condition in show() that suppresses the popup
        should_skip = len(ac._filtered) == 1 and ac._filtered[0].name == "onboarding_client"
        assert should_skip

    def test_partial_match_does_not_suppress(self):
        ac = _make_autocomplete()
        ac._completions = [
            CompletionItem("onboarding_client", CompletionKind.VARIABLE),
            CompletionItem("onboarding_config", CompletionKind.VARIABLE),
        ]
        ac._update_filter("onboarding")

        assert len(ac._filtered) == 2
        should_skip = len(ac._filtered) == 1 and ac._filtered[0].name == "onboarding"
        assert not should_skip

    def test_single_non_exact_match_does_not_suppress(self):
        ac = _make_autocomplete()
        ac._completions = [CompletionItem("onboarding_client", CompletionKind.VARIABLE)]
        ac._update_filter("onboarding")

        assert len(ac._filtered) == 1
        should_skip = len(ac._filtered) == 1 and ac._filtered[0].name == "onboarding"
        assert not should_skip


# ---------------------------------------------------------------------------
# Auto-dismiss on exact match during live filtering
# ---------------------------------------------------------------------------


class TestAutoDismissOnExactMatch:
    """Popup should auto-dismiss when live-filtering leaves only an exact match."""

    def _setup_buffer_changed(self, ac, partial):
        """Configure mocks for _on_buffer_changed with a given partial word."""
        cursor_iter = MagicMock()
        cursor_iter.get_offset.return_value = ac._word_start_offset + len(partial)

        word_start_iter = MagicMock()
        ac._buffer.get_iter_at_mark.return_value = cursor_iter
        ac._buffer.get_iter_at_offset.return_value = word_start_iter
        ac._buffer.get_text.return_value = partial
        ac._buffer.get_char_count.return_value = ac._word_start_offset + len(partial)

    def test_exact_match_dismisses(self):
        ac = _make_autocomplete(_word_start_offset=0)
        ac._completions = [CompletionItem("onboarding_client", CompletionKind.VARIABLE)]
        ac._popup.get_visible.return_value = True

        self._setup_buffer_changed(ac, "onboarding_client")

        with patch("editor.autocomplete.autocomplete.get_theme"):
            ac._on_buffer_changed(ac._buffer)

        ac._popup.popdown.assert_called()

    def test_partial_does_not_dismiss(self):
        ac = _make_autocomplete(_word_start_offset=0)
        ac._completions = [
            CompletionItem("onboarding_client", CompletionKind.VARIABLE),
            CompletionItem("onboarding_config", CompletionKind.VARIABLE),
        ]
        ac._popup.get_visible.return_value = True

        self._setup_buffer_changed(ac, "onboarding")

        with patch("editor.autocomplete.autocomplete.get_theme"):
            ac._on_buffer_changed(ac._buffer)

        ac._popup.popdown.assert_not_called()

    def test_no_matches_hides_popup(self):
        ac = _make_autocomplete(_word_start_offset=0)
        ac._completions = [CompletionItem("foo", CompletionKind.VARIABLE)]
        ac._popup.get_visible.return_value = True

        self._setup_buffer_changed(ac, "bar")

        with patch("editor.autocomplete.autocomplete.get_theme"):
            ac._on_buffer_changed(ac._buffer)

        # hide() is called which calls popdown
        ac._popup.popdown.assert_called()


# ---------------------------------------------------------------------------
# _update_filter
# ---------------------------------------------------------------------------


class TestUpdateFilter:
    """Test that _update_filter correctly filters completions."""

    def test_filters_by_prefix(self):
        ac = _make_autocomplete()
        ac._completions = [
            CompletionItem("process", CompletionKind.FUNCTION),
            CompletionItem("print", CompletionKind.BUILTIN),
            CompletionItem("open", CompletionKind.BUILTIN),
        ]

        with patch("editor.autocomplete.autocomplete.get_theme"):
            ac._update_filter("pr")

        names = [c.name for c in ac._filtered]
        assert "process" in names
        assert "print" in names
        assert "open" not in names

    def test_empty_partial_returns_all(self):
        ac = _make_autocomplete()
        ac._completions = [
            CompletionItem("foo", CompletionKind.VARIABLE),
            CompletionItem("bar", CompletionKind.VARIABLE),
        ]

        with patch("editor.autocomplete.autocomplete.get_theme"):
            ac._update_filter("")

        assert len(ac._filtered) == 2

    def test_case_insensitive_filter(self):
        ac = _make_autocomplete()
        ac._completions = [CompletionItem("MyClass", CompletionKind.VARIABLE)]

        with patch("editor.autocomplete.autocomplete.get_theme"):
            ac._update_filter("myc")

        assert len(ac._filtered) == 1
        assert ac._filtered[0].name == "MyClass"

    def test_respects_max_items(self):
        from constants import AUTOCOMPLETE_MAX_ITEMS

        ac = _make_autocomplete()
        ac._completions = [CompletionItem(f"item_{i}", CompletionKind.VARIABLE) for i in range(50)]

        with patch("editor.autocomplete.autocomplete.get_theme"):
            ac._update_filter("item")

        assert len(ac._filtered) == AUTOCOMPLETE_MAX_ITEMS


# ---------------------------------------------------------------------------
# Docstring in signature preview
# ---------------------------------------------------------------------------


class TestSignaturePreviewDocstring:
    """Test that _update_signature_preview shows docstrings."""

    def test_signature_only(self):
        ac = _make_autocomplete()
        ac._popup.get_visible = MagicMock(return_value=True)
        ac._sig_box.get_visible = MagicMock(return_value=False)
        ac._filtered = [CompletionItem("foo", CompletionKind.FUNCTION, "foo(x, y)")]
        ac._selected_idx = 0
        ac._update_signature_preview()
        ac._sig_buffer.set_text.assert_called_with("foo(x, y)")
        ac._sig_box.set_visible.assert_called_with(True)
        ac._sig_sep.set_visible.assert_called_with(True)

    def test_signature_and_docstring(self):
        ac = _make_autocomplete()
        ac._popup.get_visible = MagicMock(return_value=True)
        ac._sig_box.get_visible = MagicMock(return_value=False)
        ac._filtered = [CompletionItem("foo", CompletionKind.FUNCTION, "foo(x)", "Do something")]
        ac._selected_idx = 0
        ac._update_signature_preview()
        ac._sig_buffer.set_text.assert_called_with("foo(x)\n# Do something")
        ac._sig_box.set_visible.assert_called_with(True)

    def test_docstring_only_no_signature(self):
        ac = _make_autocomplete()
        ac._popup.get_visible = MagicMock(return_value=True)
        ac._sig_box.get_visible = MagicMock(return_value=False)
        ac._filtered = [CompletionItem("MyClass", CompletionKind.PROPERTY, "", "A useful class")]
        ac._selected_idx = 0
        ac._update_signature_preview()
        ac._sig_buffer.set_text.assert_called_with("# A useful class")
        ac._sig_box.set_visible.assert_called_with(True)

    def test_no_signature_no_docstring(self):
        ac = _make_autocomplete()
        ac._popup.get_visible = MagicMock(return_value=True)
        ac._sig_box.get_visible = MagicMock(return_value=True)
        ac._filtered = [CompletionItem("x", CompletionKind.VARIABLE)]
        ac._selected_idx = 0
        ac._update_signature_preview()
        ac._sig_box.set_visible.assert_called_with(False)
        ac._sig_sep.set_visible.assert_called_with(False)


# ---------------------------------------------------------------------------
# Python docstring extraction
# ---------------------------------------------------------------------------


class TestPythonDocstringExtraction:
    """Test docstring extraction from Python code."""

    def setup_method(self):
        from editor.autocomplete.tree_sitter_provider import (
            _parse,
            py_extract_class_members,
            py_extract_definitions,
            py_extract_self_members,
        )

        self._parse = _parse
        self._defs = py_extract_definitions
        self._members = py_extract_class_members
        self._self_members = py_extract_self_members

    def _py(self, text):
        source, tree = self._parse(text, "python")
        assert tree is not None
        return source, tree

    def test_get_symbols_extracts_function_docstring(self):
        text = 'def greet(name: str):\n    """Say hello to someone."""\n    pass\n'
        source, tree = self._py(text)
        symbols = self._defs(source, tree)
        func = next(s for s in symbols if s.name == "greet")
        assert func.docstring == "Say hello to someone."

    def test_get_symbols_extracts_class_docstring(self):
        text = 'class MyService:\n    """Handles business logic."""\n    pass\n'
        source, tree = self._py(text)
        symbols = self._defs(source, tree)
        cls = next(s for s in symbols if s.name == "MyService")
        assert cls.docstring == "Handles business logic."

    def test_get_symbols_no_docstring(self):
        text = "def process(x):\n    return x + 1\n"
        source, tree = self._py(text)
        symbols = self._defs(source, tree)
        func = next(s for s in symbols if s.name == "process")
        assert func.docstring == ""

    def test_multiline_docstring_takes_first_line(self):
        text = 'def foo():\n    """First line.\n\n    More details here.\n    """\n    pass\n'
        source, tree = self._py(text)
        symbols = self._defs(source, tree)
        func = next(s for s in symbols if s.name == "foo")
        assert func.docstring == "First line."

    def test_single_quote_docstring(self):
        text = "def bar():\n    '''Single-quoted docstring.'''\n    pass\n"
        source, tree = self._py(text)
        symbols = self._defs(source, tree)
        func = next(s for s in symbols if s.name == "bar")
        assert func.docstring == "Single-quoted docstring."

    def test_extract_docstring_at_position(self):
        text = 'def hello():\n    """Greets the user."""\n    pass'
        source, tree = self._py(text)
        symbols = self._defs(source, tree)
        func = next(s for s in symbols if s.name == "hello")
        assert func.docstring == "Greets the user."

    def test_peek_docstring_single_line(self):
        text = 'def foo():\n    """A short docstring."""\n    pass'
        source, tree = self._py(text)
        symbols = self._defs(source, tree)
        func = next(s for s in symbols if s.name == "foo")
        assert func.docstring == "A short docstring."

    def test_peek_docstring_multiline(self):
        text = 'def foo():\n    """\n    The actual description.\n    """\n    pass'
        source, tree = self._py(text)
        symbols = self._defs(source, tree)
        func = next(s for s in symbols if s.name == "foo")
        assert func.docstring == "The actual description."

    def test_peek_docstring_content_after_opening_quote(self):
        text = 'def foo():\n    """Description starts here.\n    """\n    pass'
        source, tree = self._py(text)
        symbols = self._defs(source, tree)
        func = next(s for s in symbols if s.name == "foo")
        assert func.docstring == "Description starts here."

    def test_peek_docstring_no_docstring(self):
        text = "def foo():\n    return 42"
        source, tree = self._py(text)
        symbols = self._defs(source, tree)
        func = next(s for s in symbols if s.name == "foo")
        assert func.docstring == ""

    def test_extract_class_members_with_docstrings(self):
        text = (
            "class Calculator:\n"
            "    def add(self, a, b):\n"
            '        """Add two numbers."""\n'
            "        return a + b\n"
            "    def multiply(self, a, b):\n"
            "        return a * b\n"
        )
        source, tree = self._py(text)
        members = self._members(source, tree, "Calculator")
        add_item = next(m for m in members if m.name == "add")
        mul_item = next(m for m in members if m.name == "multiply")
        assert add_item.docstring == "Add two numbers."
        assert mul_item.docstring == ""

    def test_self_completions_with_docstrings(self):
        text = (
            "class Greeter:\n"
            "    def greet(self, name):\n"
            '        """Greet someone by name."""\n'
            "        pass\n"
            "    def farewell(self):\n"
            "        pass\n"
        )
        source, tree = self._py(text)
        members = self._self_members(source, tree, "Greeter")
        greet = next(m for m in members if m.name == "greet")
        farewell = next(m for m in members if m.name == "farewell")
        assert greet.docstring == "Greet someone by name."
        assert farewell.docstring == ""


# ---------------------------------------------------------------------------
# JS JSDoc extraction
# ---------------------------------------------------------------------------


class TestJsDocExtraction:
    """Test JSDoc comment extraction for JS/TS completions."""

    def setup_method(self):
        from editor.autocomplete.js_provider import JsCompletionProvider

        self.provider = JsCompletionProvider()

    def test_jsdoc_before_function(self):
        text = "/** Fetches user data from the API. */\nfunction fetchUser(id) {}\n"
        symbols = self.provider._get_symbols(text)
        func = next(s for s in symbols if s.name == "fetchUser")
        assert func.docstring == "Fetches user data from the API."

    def test_multiline_jsdoc(self):
        text = (
            "/**\n"
            " * Calculate the sum of two numbers.\n"
            " * @param {number} a\n"
            " * @param {number} b\n"
            " */\n"
            "function sum(a, b) { return a + b; }\n"
        )
        symbols = self.provider._get_symbols(text)
        func = next(s for s in symbols if s.name == "sum")
        assert func.docstring == "Calculate the sum of two numbers."

    def test_no_jsdoc(self):
        text = "function plain() {}\n"
        symbols = self.provider._get_symbols(text)
        func = next(s for s in symbols if s.name == "plain")
        assert func.docstring == ""

    def test_regular_comment_not_jsdoc(self):
        text = "// This is not a JSDoc\nfunction notDoc() {}\n"
        symbols = self.provider._get_symbols(text)
        func = next(s for s in symbols if s.name == "notDoc")
        assert func.docstring == ""
