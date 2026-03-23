"""Tests for indent guide level computation (no GTK required)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from editor.indent_guide_levels import compute_guide_levels, compute_indent_step, detect_indent_width


class TestBracketScopeJSON(unittest.TestCase):
    """JSON / bracket-based languages: JetBrains-style guides on content only."""

    def test_simple_json_object(self):
        lines = [
            "{",
            '    "key": "val",',
            '    "num": 42',
            "}",
        ]
        levels = compute_guide_levels(lines, indent_step=4, tab_width=4, lang_id="json")
        # JetBrains-style: guides only between braces, not on brace lines
        self.assertEqual(levels[0], 0)  # { → no guide
        self.assertEqual(levels[1], 1)  # "key"
        self.assertEqual(levels[2], 1)  # "num"
        self.assertEqual(levels[3], 0)  # } → no guide

    def test_nested_json(self):
        lines = [
            "{",
            '    "editor": {',
            '        "font_size": 18,',
            '        "theme": "dark"',
            "    },",
            '    "terminal": {',
            '        "shell": "/bin/zsh"',
            "    }",
            "}",
        ]
        levels = compute_guide_levels(lines, indent_step=4, tab_width=4, lang_id="json")
        self.assertEqual(levels[0], 0)  # { → no guide
        self.assertEqual(levels[1], 1)  # "editor": { → guide at col 0
        self.assertEqual(levels[2], 2)  # "font_size"
        self.assertEqual(levels[3], 2)  # "theme"
        self.assertEqual(levels[4], 1)  # }, → guide at col 0
        self.assertEqual(levels[5], 1)  # "terminal": { → guide at col 0
        self.assertEqual(levels[6], 2)  # "shell"
        self.assertEqual(levels[7], 1)  # } → guide at col 0
        self.assertEqual(levels[8], 0)  # } → no guide

    def test_json_array(self):
        lines = [
            "{",
            '    "items": [',
            "        1,",
            "        2",
            "    ]",
            "}",
        ]
        levels = compute_guide_levels(lines, indent_step=4, tab_width=4, lang_id="json")
        self.assertEqual(levels[0], 0)  # {
        self.assertEqual(levels[1], 1)  # "items": [
        self.assertEqual(levels[2], 2)  # 1,
        self.assertEqual(levels[3], 2)  # 2
        self.assertEqual(levels[4], 1)  # ]
        self.assertEqual(levels[5], 0)  # }

    def test_blank_line_interpolation_json(self):
        lines = [
            "{",
            '    "a": 1,',
            "",
            '    "b": 2',
            "}",
        ]
        levels = compute_guide_levels(lines, indent_step=4, tab_width=4, lang_id="json")
        self.assertEqual(levels[0], 0)  # { → no guide
        self.assertEqual(levels[1], 1)
        self.assertEqual(levels[2], 1)  # blank line interpolated
        self.assertEqual(levels[3], 1)
        self.assertEqual(levels[4], 0)  # } → no guide


class TestPythonIndentation(unittest.TestCase):
    """Python: pure indentation-based guides, no bracket extension."""

    def test_python_function(self):
        lines = [
            "def foo():",
            "    x = 1",
            "    if True:",
            "        y = 2",
            "    return x",
        ]
        levels = compute_guide_levels(lines, indent_step=4, tab_width=4, lang_id="python")
        self.assertEqual(levels[0], 0)  # def → level 0, no guide
        self.assertEqual(levels[1], 1)
        self.assertEqual(levels[2], 1)
        self.assertEqual(levels[3], 2)
        self.assertEqual(levels[4], 1)

    def test_python_nested_class(self):
        lines = [
            "class Foo:",
            "    def bar(self):",
            "        pass",
            "",
            "    def baz(self):",
            "        return 1",
        ]
        levels = compute_guide_levels(lines, indent_step=4, tab_width=4, lang_id="python")
        self.assertEqual(levels[0], 0)  # class → no guide
        self.assertEqual(levels[1], 1)
        self.assertEqual(levels[2], 2)
        self.assertEqual(levels[3], 1)  # blank → interpolated min(2, 1) = 1
        self.assertEqual(levels[4], 1)
        self.assertEqual(levels[5], 2)

    def test_python_dict_not_extended(self):
        """Python dict literals should NOT get bracket scope extension."""
        lines = [
            "data = {",
            '    "key": "val",',
            "}",
        ]
        levels = compute_guide_levels(lines, indent_step=4, tab_width=4, lang_id="python")
        # Python is NOT in BRACKET_SCOPE_LANGS, so no extension
        self.assertEqual(levels[0], 0)  # data = { at indent 0
        self.assertEqual(levels[1], 1)
        self.assertEqual(levels[2], 0)  # } at indent 0


class TestJavaScriptBrackets(unittest.TestCase):
    """JavaScript: JetBrains-style guides on content between braces."""

    def test_js_function(self):
        lines = [
            "function foo() {",
            "    const x = 1;",
            "    if (true) {",
            "        console.log(x);",
            "    }",
            "}",
        ]
        levels = compute_guide_levels(lines, indent_step=4, tab_width=4, lang_id="javascript")
        self.assertEqual(levels[0], 0)  # function { → no guide (indent 0)
        self.assertEqual(levels[1], 1)
        self.assertEqual(levels[2], 1)  # if { → guide at col 0
        self.assertEqual(levels[3], 2)
        self.assertEqual(levels[4], 1)  # } → guide at col 0
        self.assertEqual(levels[5], 0)  # } → no guide

    def test_js_else_block(self):
        lines = [
            "if (x) {",
            "    a();",
            "} else {",
            "    b();",
            "}",
        ]
        levels = compute_guide_levels(lines, indent_step=4, tab_width=4, lang_id="javascript")
        self.assertEqual(levels[0], 0)  # if { → indent 0
        self.assertEqual(levels[1], 1)
        self.assertEqual(levels[2], 0)  # } else { → indent 0
        self.assertEqual(levels[3], 1)
        self.assertEqual(levels[4], 0)  # }


class TestTabIndentation(unittest.TestCase):
    """Test with tab characters."""

    def test_tab_indented_json(self):
        lines = [
            "{",
            '\t"key": "val"',
            "}",
        ]
        levels = compute_guide_levels(lines, indent_step=4, tab_width=4, lang_id="json")
        self.assertEqual(levels[0], 0)  # { → no guide
        self.assertEqual(levels[1], 1)
        self.assertEqual(levels[2], 0)  # } → no guide


class TestTwoSpaceIndent(unittest.TestCase):
    """Test with 2-space indentation."""

    def test_two_space_json(self):
        lines = [
            "{",
            '  "key": {',
            '    "nested": true',
            "  }",
            "}",
        ]
        levels = compute_guide_levels(lines, indent_step=2, tab_width=2, lang_id="json")
        self.assertEqual(levels[0], 0)  # { → no guide
        self.assertEqual(levels[1], 1)  # "key": { → guide at col 0
        self.assertEqual(levels[2], 2)
        self.assertEqual(levels[3], 1)  # } → guide at col 0
        self.assertEqual(levels[4], 0)  # } → no guide


class TestNoLanguage(unittest.TestCase):
    """When lang_id is None, no bracket extension (safe default)."""

    def test_no_lang(self):
        lines = [
            "{",
            "    content",
            "}",
        ]
        levels = compute_guide_levels(lines, indent_step=4, tab_width=4, lang_id=None)
        self.assertEqual(levels[0], 0)  # no extension
        self.assertEqual(levels[1], 1)
        self.assertEqual(levels[2], 0)  # no extension


class TestEdgeCases(unittest.TestCase):
    """Edge cases for robustness."""

    def test_empty_input(self):
        levels = compute_guide_levels([], indent_step=4, tab_width=4)
        self.assertEqual(levels, [])

    def test_single_blank_line(self):
        levels = compute_guide_levels([""], indent_step=4, tab_width=4)
        self.assertEqual(levels, [0])

    def test_all_blank_lines(self):
        levels = compute_guide_levels(["", "", ""], indent_step=4, tab_width=4)
        self.assertEqual(levels, [0, 0, 0])

    def test_single_content_line(self):
        levels = compute_guide_levels(["    hello"], indent_step=4, tab_width=4)
        self.assertEqual(levels, [1])


class TestComputeIndentStep(unittest.TestCase):
    """Tests for the indent step detection heuristic."""

    def test_two_space_json_with_tab_width_4(self):
        """2-space JSON file with tab_size=4 should detect step=2."""
        # Simulates settings.json: many lines at indent 2/4/6
        non_zero = [2] * 23 + [4] * 50 + [6] * 17
        self.assertEqual(compute_indent_step(non_zero, tab_width=4), 2)

    def test_four_space_python_with_one_odd_line(self):
        """4-space Python file with one continuation line should detect step=4."""
        non_zero = [4] * 30 + [8] * 15 + [12] * 5 + [2]
        self.assertEqual(compute_indent_step(non_zero, tab_width=4), 4)

    def test_four_space_file_no_misaligned(self):
        """Pure 4-space file should detect step=4."""
        non_zero = [4, 4, 8, 8, 4, 12]
        self.assertEqual(compute_indent_step(non_zero, tab_width=4), 4)

    def test_two_space_file_tab_width_2(self):
        """2-space file with tab_width=2 should detect step=2."""
        non_zero = [2, 2, 4, 4, 2]
        self.assertEqual(compute_indent_step(non_zero, tab_width=2), 2)

    def test_empty_indents(self):
        """No indented lines should return tab_width."""
        self.assertEqual(compute_indent_step([], tab_width=4), 4)

    def test_minimum_step_is_2(self):
        """Step should never be less than 2."""
        non_zero = [1, 2, 3]
        self.assertEqual(compute_indent_step(non_zero, tab_width=4), 2)


class TestTwoSpaceJSONWithTabWidth4(unittest.TestCase):
    """End-to-end: 2-space JSON file opened with tab_size=4."""

    def test_settings_json_like(self):
        """Simulates real settings.json content with 2-space indent."""
        lines = [
            "{",
            '  "theme": "aura_dark",',
            '  "editor": {',
            '    "font_size": 18,',
            '    "tab_size": 4',
            "  },",
            '  "terminal": {',
            '    "shell": ""',
            "  }",
            "}",
        ]
        # First verify indent step detection
        non_zero = []
        for text in lines:
            if not text.strip():
                continue

            # proper indent counting
            ind = 0
            for ch in text:
                if ch == " ":
                    ind += 1
                else:
                    break
            if ind > 0:
                non_zero.append(ind)
        step = compute_indent_step(non_zero, tab_width=4)
        self.assertEqual(step, 2)

        # Now verify guide levels — JetBrains-style: no guides on brace lines
        levels = compute_guide_levels(lines, indent_step=2, tab_width=4, lang_id="json")
        self.assertEqual(levels[0], 0)  # { → no guide
        self.assertEqual(levels[1], 1)  # "theme"
        self.assertEqual(levels[2], 1)  # "editor": { → guide at col 0
        self.assertEqual(levels[3], 2)  # "font_size"
        self.assertEqual(levels[4], 2)  # "tab_size"
        self.assertEqual(levels[5], 1)  # }, → guide at col 0
        self.assertEqual(levels[6], 1)  # "terminal": { → guide at col 0
        self.assertEqual(levels[7], 2)  # "shell"
        self.assertEqual(levels[8], 1)  # } → guide at col 0
        self.assertEqual(levels[9], 0)  # } → no guide


class TestDetectIndentWidth(unittest.TestCase):
    """Tests for detect_indent_width — auto-detect from file content."""

    def test_two_space_js(self):
        text = "function foo() {\n  const x = 1;\n  if (true) {\n    bar();\n  }\n}\n"
        self.assertEqual(detect_indent_width(text, fallback=4), 2)

    def test_four_space_python(self):
        text = "def foo():\n    x = 1\n    if True:\n        y = 2\n    return x\n"
        self.assertEqual(detect_indent_width(text, fallback=4), 4)

    def test_fallback_on_no_indentation(self):
        text = "hello\nworld\n"
        self.assertEqual(detect_indent_width(text, fallback=4), 4)

    def test_fallback_on_too_few_lines(self):
        text = '{\n  "key": 1\n}\n'
        # Only 1 indented line — not enough signal
        self.assertEqual(detect_indent_width(text, fallback=4), 4)

    def test_mixed_but_mostly_two(self):
        text = "{\n  a: 1,\n  b: 2,\n  c: {\n    d: 3\n  }\n}\n"
        self.assertEqual(detect_indent_width(text, fallback=4), 2)

    def test_empty_file(self):
        self.assertEqual(detect_indent_width("", fallback=4), 4)

    def test_tabs_ignored(self):
        """Tab-indented lines are skipped (first char is tab, not space)."""
        text = "{\n\tkey: 1,\n\tval: 2,\n\tfoo: 3\n}\n"
        self.assertEqual(detect_indent_width(text, fallback=4), 4)

    def test_whitespace_only_lines_ignored(self):
        """Blank lines with trailing spaces must not corrupt the GCD."""
        text = "def foo():\n    x = 1\n    y = 2\n  \n    z = 3\n    return x\n"
        self.assertEqual(detect_indent_width(text, fallback=4), 4)

    def test_single_space_blank_line_ignored(self):
        """A blank line with a single space must not reduce GCD to 1."""
        text = "def foo():\n    a = 1\n    b = 2\n \n    c = 3\n    return a\n"
        self.assertEqual(detect_indent_width(text, fallback=4), 4)


if __name__ == "__main__":
    unittest.main()
