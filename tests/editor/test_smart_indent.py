"""Regression tests for smart indentation and BRACKET_SCOPE_LANGS correctness.

Covers:
- _strip_python_comment / _strip_line_comment helpers
- Smart indent decision logic (indent after openers, dedent after closers)
- BRACKET_SCOPE_LANGS matching actual GtkSourceView lang IDs
- detect_indent_width ignoring whitespace-only lines
"""

import unittest

from constants import BRACKET_SCOPE_LANGS, LANG_INDENT_WIDTH
from editor.editor_view import EditorTab
from editor.indent_guide_levels import detect_indent_width
from editor.langs.language_detect import detect_language

# ---------------------------------------------------------------------------
# Pure helpers — no GTK buffer needed
# ---------------------------------------------------------------------------


class TestStripPythonComment(unittest.TestCase):
    """EditorView._strip_python_comment static method."""

    strip = staticmethod(EditorTab._strip_python_comment)

    def test_no_comment(self):
        self.assertEqual(self.strip("x = 1"), "x = 1")

    def test_trailing_comment(self):
        self.assertEqual(self.strip("x = 1  # assign"), "x = 1")

    def test_hash_inside_string(self):
        self.assertEqual(self.strip('url = "http://x#y"'), 'url = "http://x#y"')

    def test_colon_with_comment(self):
        self.assertEqual(self.strip("if True:  # check"), "if True:")

    def test_empty(self):
        self.assertEqual(self.strip(""), "")


class TestStripLineComment(unittest.TestCase):
    """EditorTab._strip_line_comment static method."""

    strip = staticmethod(EditorTab._strip_line_comment)

    def test_no_comment(self):
        self.assertEqual(self.strip("const x = 1;"), "const x = 1;")

    def test_trailing_comment(self):
        self.assertEqual(self.strip("const x = 1; // init"), "const x = 1;")

    def test_slash_inside_string(self):
        self.assertEqual(self.strip('url = "http://example.com"'), 'url = "http://example.com"')

    def test_slash_inside_template_literal(self):
        self.assertEqual(self.strip("`http://x`"), "`http://x`")

    def test_brace_with_comment(self):
        self.assertEqual(self.strip("function foo() { // start"), "function foo() {")

    def test_empty(self):
        self.assertEqual(self.strip(""), "")


# ---------------------------------------------------------------------------
# Smart indent decision logic — simulate what _handle_smart_indent computes
# without needing a live GtkSourceView buffer.
# ---------------------------------------------------------------------------


def _compute_smart_indent(line_text, indent_width, is_python):
    """Replicate the indent decision from _handle_smart_indent.

    Returns the new indentation string, or None when GtkSourceView's
    default auto-indent should handle it.
    """
    stripped = line_text.lstrip()
    indent_len = len(line_text) - len(stripped)
    indent_str = line_text[:indent_len]
    one_level = " " * indent_width

    if is_python:
        code = EditorTab._strip_python_comment(stripped)
        if code.endswith(":") or code.endswith(("(", "[", "{")):
            return indent_str + one_level
        first_word = code.split()[0] if code else ""
        if first_word in EditorTab._DEDENT_KEYWORDS:
            if indent_len >= indent_width:
                return indent_str[:-indent_width]
            return ""
        return None
    else:
        code = EditorTab._strip_line_comment(stripped)
        if code.endswith(("{", "(", "[")):
            return indent_str + one_level
        if code in ("}", "},", "});", ");", "]", "],", "]);"):
            if indent_len >= indent_width:
                return indent_str[:-indent_width]
            return ""
        return None


class TestSmartIndentPython(unittest.TestCase):
    """Python indent/dedent decisions."""

    def test_indent_after_colon(self):
        self.assertEqual(_compute_smart_indent("    if True:", 4, True), "        ")

    def test_indent_after_open_brace(self):
        self.assertEqual(_compute_smart_indent("    data = {", 4, True), "        ")

    def test_indent_after_open_paren(self):
        self.assertEqual(_compute_smart_indent("    foo(", 4, True), "        ")

    def test_indent_after_open_bracket(self):
        self.assertEqual(_compute_smart_indent("    items = [", 4, True), "        ")

    def test_dedent_after_return(self):
        self.assertEqual(_compute_smart_indent("        return x", 4, True), "    ")

    def test_dedent_after_pass(self):
        self.assertEqual(_compute_smart_indent("    pass", 4, True), "")

    def test_dedent_after_break(self):
        self.assertEqual(_compute_smart_indent("        break", 4, True), "    ")

    def test_no_action_plain_line(self):
        self.assertIsNone(_compute_smart_indent("    x = 1", 4, True))

    def test_colon_with_comment(self):
        self.assertEqual(_compute_smart_indent("    for x in xs:  # iterate", 4, True), "        ")

    def test_dedent_from_zero_indent(self):
        self.assertEqual(_compute_smart_indent("return", 4, True), "")


class TestSmartIndentBrace(unittest.TestCase):
    """Brace-based language indent/dedent decisions."""

    def test_indent_after_open_brace(self):
        # TSX: `  const foo = () => {` → 4 spaces
        self.assertEqual(_compute_smart_indent("  const foo = () => {", 2, False), "    ")

    def test_indent_after_open_brace_4space(self):
        self.assertEqual(_compute_smart_indent("    if (x) {", 4, False), "        ")

    def test_indent_after_open_paren(self):
        self.assertEqual(_compute_smart_indent("    foo(", 4, False), "        ")

    def test_indent_after_open_bracket(self):
        self.assertEqual(_compute_smart_indent("    const arr = [", 4, False), "        ")

    def test_dedent_close_brace(self):
        self.assertEqual(_compute_smart_indent("    }", 4, False), "")

    def test_dedent_close_brace_comma(self):
        self.assertEqual(_compute_smart_indent("        },", 4, False), "    ")

    def test_dedent_close_brace_paren_semi(self):
        self.assertEqual(_compute_smart_indent("    });", 4, False), "")

    def test_dedent_close_paren_semi(self):
        self.assertEqual(_compute_smart_indent("        );", 4, False), "    ")

    def test_dedent_close_bracket(self):
        self.assertEqual(_compute_smart_indent("    ]", 4, False), "")

    def test_dedent_close_bracket_comma(self):
        self.assertEqual(_compute_smart_indent("        ],", 4, False), "    ")

    def test_no_action_plain_statement(self):
        self.assertIsNone(_compute_smart_indent("    const x = 1;", 4, False))

    def test_no_action_assignment(self):
        self.assertIsNone(_compute_smart_indent("  return foo;", 2, False))

    def test_brace_with_comment(self):
        self.assertEqual(_compute_smart_indent("  if (x) { // check", 2, False), "    ")

    def test_dedent_from_zero_indent(self):
        self.assertEqual(_compute_smart_indent("}", 4, False), "")

    def test_tsx_arrow_function_regression(self):
        """Regression: TSX arrow fn ending with { must indent +1 level (2-space file)."""
        line = "  const repaymentTermsChanged = () => {"
        result = _compute_smart_indent(line, 2, False)
        self.assertEqual(result, "    ")
        self.assertEqual(len(result) + 1, 5, "cursor should land at col 5")


# ---------------------------------------------------------------------------
# BRACKET_SCOPE_LANGS must match actual GtkSourceView lang IDs
# ---------------------------------------------------------------------------


class TestBracketScopeLangsCorrectness(unittest.TestCase):
    """Every ID in BRACKET_SCOPE_LANGS must be a real GtkSourceView language."""

    def test_all_ids_are_valid(self):
        from gi.repository import GtkSource

        mgr = GtkSource.LanguageManager.get_default()
        missing = []
        for lid in BRACKET_SCOPE_LANGS:
            if mgr.get_language(lid) is None:
                missing.append(lid)
        self.assertEqual(missing, [], f"Invalid lang IDs in BRACKET_SCOPE_LANGS: {missing}")

    def test_common_extensions_are_covered(self):
        """Common brace-lang extensions must resolve to an ID in BRACKET_SCOPE_LANGS."""
        extensions = [".js", ".jsx", ".ts", ".tsx", ".java", ".c", ".cpp", ".go", ".rs", ".css", ".json"]
        uncovered = []
        for ext in extensions:
            lang = detect_language(f"test{ext}")
            if lang is None:
                uncovered.append(ext)
                continue
            if lang.get_id() not in BRACKET_SCOPE_LANGS:
                uncovered.append(f"{ext} -> {lang.get_id()}")
        self.assertEqual(uncovered, [], f"Extensions not in BRACKET_SCOPE_LANGS: {uncovered}")


# ---------------------------------------------------------------------------
# LANG_INDENT_WIDTH must use real GtkSourceView lang IDs
# ---------------------------------------------------------------------------


class TestLangIndentWidthCorrectness(unittest.TestCase):
    """Non-extension keys in LANG_INDENT_WIDTH must be valid GtkSourceView lang IDs."""

    def test_lang_ids_are_valid(self):
        from gi.repository import GtkSource

        mgr = GtkSource.LanguageManager.get_default()
        missing = []
        for lid in LANG_INDENT_WIDTH:
            if lid.startswith("."):
                continue  # extension-based key, not a lang ID
            if mgr.get_language(lid) is None:
                missing.append(lid)
        self.assertEqual(missing, [], f"Invalid lang IDs in LANG_INDENT_WIDTH: {missing}")


# ---------------------------------------------------------------------------
# detect_indent_width — whitespace-only line regression
# ---------------------------------------------------------------------------


class TestDetectIndentWidthWhitespaceRegression(unittest.TestCase):
    """Whitespace-only blank lines must not corrupt the indent width GCD."""

    def test_trailing_spaces_ignored(self):
        text = "def foo():\n    x = 1\n    y = 2\n  \n    z = 3\n    return x\n"
        self.assertEqual(detect_indent_width(text, 4), 4)

    def test_single_trailing_space_ignored(self):
        text = "def foo():\n    a = 1\n    b = 2\n \n    c = 3\n    return a\n"
        self.assertEqual(detect_indent_width(text, 4), 4)

    def test_tab_trailing_space_mixed(self):
        text = "{\n  a: 1,\n  b: 2,\n   \n  c: 3,\n  d: 4\n}\n"
        self.assertEqual(detect_indent_width(text, 4), 2)

    def test_all_blank_lines_with_spaces(self):
        text = "  \n    \n      \n"
        # No real content lines → fallback
        self.assertEqual(detect_indent_width(text, 4), 4)


if __name__ == "__main__":
    unittest.main()
