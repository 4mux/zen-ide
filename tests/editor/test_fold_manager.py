"""Tests for code folding logic (fold_manager.py).

Tests the pure-logic parts: fold region detection via tree-sitter,
state management (collapsed tracking), and FOLD_NODE_TYPES coverage.
GTK rendering is not tested here.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from editor.fold_manager import FOLD_NODE_TYPES

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_node(node_type, start_line, end_line, children=None):
    """Create a mock tree-sitter node."""
    node = MagicMock()
    node.type = node_type
    node.start_point = (start_line, 0)
    node.end_point = (end_line, 0)
    node.children = children or []
    return node


def _collect(root, lang_id):
    """Run _collect_fold_regions on a mock tree and return the regions dict."""
    from editor.fold_manager import FOLD_NODE_TYPES

    def walk(node, regions):
        foldable = FOLD_NODE_TYPES.get(lang_id, set())
        if node.type in foldable:
            sl = node.start_point[0]
            el = node.end_point[0]
            if el > sl:
                regions[sl] = el
        for child in node.children:
            walk(child, regions)

    regions = {}
    walk(root, regions)
    return regions


# ---------------------------------------------------------------------------
# FOLD_NODE_TYPES coverage
# ---------------------------------------------------------------------------


class TestFoldNodeTypes(unittest.TestCase):
    """Verify FOLD_NODE_TYPES has expected languages and key node types."""

    def test_python_has_core_types(self):
        py = FOLD_NODE_TYPES["python"]
        for t in ("function_definition", "class_definition", "if_statement", "for_statement"):
            self.assertIn(t, py)

    def test_javascript_has_core_types(self):
        js = FOLD_NODE_TYPES["javascript"]
        for t in ("function_declaration", "class_declaration", "if_statement", "arrow_function"):
            self.assertIn(t, js)

    def test_typescript_has_ts_specifics(self):
        ts = FOLD_NODE_TYPES["typescript"]
        for t in ("interface_declaration", "type_alias_declaration", "enum_declaration"):
            self.assertIn(t, ts)

    def test_tsx_matches_typescript(self):
        """TSX should have the same types as TypeScript."""
        self.assertEqual(FOLD_NODE_TYPES["tsx"], FOLD_NODE_TYPES["typescript"])

    def test_unknown_language_returns_empty(self):
        self.assertEqual(FOLD_NODE_TYPES.get("cobol", set()), set())


# ---------------------------------------------------------------------------
# Fold region detection (_collect_fold_regions)
# ---------------------------------------------------------------------------


class TestCollectFoldRegions(unittest.TestCase):
    """Test _collect_fold_regions on mock AST nodes."""

    def test_single_function(self):
        root = _make_mock_node(
            "module",
            0,
            5,
            children=[_make_mock_node("function_definition", 0, 5)],
        )
        regions = _collect(root, "python")
        self.assertEqual(regions, {0: 5})

    def test_single_line_node_ignored(self):
        """Nodes where start_line == end_line should not produce a fold."""
        root = _make_mock_node(
            "module",
            0,
            0,
            children=[_make_mock_node("function_definition", 3, 3)],
        )
        regions = _collect(root, "python")
        self.assertEqual(regions, {})

    def test_nested_folds(self):
        inner = _make_mock_node("if_statement", 2, 4)
        outer = _make_mock_node("function_definition", 0, 5, children=[inner])
        root = _make_mock_node("module", 0, 5, children=[outer])
        regions = _collect(root, "python")
        self.assertIn(0, regions)  # function
        self.assertIn(2, regions)  # if

    def test_non_foldable_type_ignored(self):
        root = _make_mock_node(
            "module",
            0,
            5,
            children=[_make_mock_node("comment", 0, 3)],
        )
        regions = _collect(root, "python")
        self.assertEqual(regions, {})

    def test_multiple_siblings(self):
        fn1 = _make_mock_node("function_definition", 0, 5)
        fn2 = _make_mock_node("function_definition", 7, 12)
        cls = _make_mock_node("class_definition", 14, 20)
        root = _make_mock_node("module", 0, 20, children=[fn1, fn2, cls])
        regions = _collect(root, "python")
        self.assertEqual(regions, {0: 5, 7: 12, 14: 20})

    def test_javascript_arrow_function(self):
        arrow = _make_mock_node("arrow_function", 1, 4)
        root = _make_mock_node("program", 0, 5, children=[arrow])
        regions = _collect(root, "javascript")
        self.assertEqual(regions, {1: 4})

    def test_wrong_language_skips_types(self):
        """Python node types should not match in JavaScript context."""
        node = _make_mock_node("decorated_definition", 0, 5)
        root = _make_mock_node("program", 0, 5, children=[node])
        regions = _collect(root, "javascript")
        self.assertEqual(regions, {})


# ---------------------------------------------------------------------------
# State management (collapsed tracking, toggle logic)
# ---------------------------------------------------------------------------


class TestFoldStateManagement(unittest.TestCase):
    """Test toggle/collapse/expand state logic using a mock view+buffer."""

    def _make_fm(self):
        """Create a FoldManager with mocked GTK objects."""
        mock_buf = MagicMock()
        mock_buf.get_line_count.return_value = 50
        mock_buf.get_insert.return_value = MagicMock()

        # get_iter_at_mark returns an iter on line 0 (safe line)
        mock_iter = MagicMock()
        mock_iter.get_line.return_value = 0
        mock_buf.get_iter_at_mark.return_value = mock_iter

        # get_iter_at_line returns (True, mock_iter) with working compare
        def make_iter():
            it = MagicMock()
            it.compare.return_value = -1  # start < end
            it.ends_line.return_value = False
            it.get_line.return_value = 0
            return it

        mock_buf.get_iter_at_line.side_effect = lambda l: (True, make_iter())
        mock_buf.get_end_iter.side_effect = make_iter

        # fold tag setup
        tag_table = MagicMock()
        tag_table.lookup.return_value = MagicMock()  # existing fold-hidden tag
        mock_buf.get_tag_table.return_value = tag_table

        mock_view = MagicMock()
        mock_view.get_buffer.return_value = mock_buf
        mock_view.get_pango_context.return_value = MagicMock()

        # Patch GLib and gutter to avoid real GTK calls
        with patch("editor.fold_manager.GLib"):
            with patch.object(mock_view, "get_gutter", return_value=MagicMock()):
                from editor.fold_manager import FoldManager

                fm = FoldManager(mock_view, MagicMock())

        fm._fold_regions = {0: 5, 7: 12, 14: 20}
        return fm

    def test_toggle_collapse(self):
        fm = self._make_fm()
        result = fm.toggle_fold(0)
        self.assertTrue(result)
        self.assertIn(0, fm._collapsed)
        self.assertEqual(fm._collapsed[0], 5)

    def test_toggle_expand(self):
        fm = self._make_fm()
        fm.toggle_fold(0)  # collapse
        fm.toggle_fold(0)  # expand
        self.assertNotIn(0, fm._collapsed)

    def test_toggle_unknown_line(self):
        fm = self._make_fm()
        result = fm.toggle_fold(99)
        self.assertFalse(result)

    def test_collapse_all(self):
        fm = self._make_fm()
        fm.collapse_all()
        self.assertEqual(set(fm._collapsed.keys()), {0, 7, 14})

    def test_expand_all(self):
        fm = self._make_fm()
        fm.collapse_all()
        fm.expand_all()
        self.assertEqual(fm._collapsed, {})

    def test_toggle_at_cursor_on_fold_line(self):
        fm = self._make_fm()
        # Place cursor on fold header line 7
        buf = fm._view.get_buffer()
        cursor_iter = MagicMock()
        cursor_iter.get_line.return_value = 7
        buf.get_iter_at_mark.return_value = cursor_iter
        result = fm.toggle_fold_at_cursor()
        self.assertTrue(result)
        self.assertIn(7, fm._collapsed)

    def test_toggle_at_cursor_inside_fold(self):
        fm = self._make_fm()
        # Place cursor on line 10 (inside fold 7-12)
        buf = fm._view.get_buffer()
        cursor_iter = MagicMock()
        cursor_iter.get_line.return_value = 10
        buf.get_iter_at_mark.return_value = cursor_iter
        result = fm.toggle_fold_at_cursor()
        self.assertTrue(result)
        self.assertIn(7, fm._collapsed)

    def test_toggle_at_cursor_no_fold(self):
        fm = self._make_fm()
        buf = fm._view.get_buffer()
        cursor_iter = MagicMock()
        cursor_iter.get_line.return_value = 6  # between folds
        buf.get_iter_at_mark.return_value = cursor_iter
        result = fm.toggle_fold_at_cursor()
        self.assertFalse(result)

    def test_debounce_flag(self):
        fm = self._make_fm()
        self.assertFalse(fm._toggle_pending)
        fm._toggle_pending = True
        fm._clear_toggle_pending()
        self.assertFalse(fm._toggle_pending)


# ---------------------------------------------------------------------------
# Brace fold detection (JSON and other non-tree-sitter languages)
# ---------------------------------------------------------------------------


class TestBraceFoldRegions(unittest.TestCase):
    """Test _collect_brace_fold_regions for JSON-style files."""

    def _collect(self, content):
        from editor.fold_manager import FoldManager

        regions = {}
        FoldManager._collect_brace_fold_regions(content, regions)
        return regions

    def test_simple_json_object(self):
        content = '{\n  "key": "val"\n}'
        regions = self._collect(content)
        self.assertEqual(regions, {0: 2})

    def test_nested_objects(self):
        content = '{\n  "a": {\n    "b": 1\n  }\n}'
        regions = self._collect(content)
        self.assertIn(0, regions)  # outer {}
        self.assertIn(1, regions)  # inner {}

    def test_array(self):
        content = '[\n  1,\n  2,\n  3\n]'
        regions = self._collect(content)
        self.assertEqual(regions, {0: 4})

    def test_single_line_braces_no_fold(self):
        content = '{"key": "val"}'
        regions = self._collect(content)
        self.assertEqual(regions, {})

    def test_strings_with_braces_ignored(self):
        content = '{\n  "x": "{ not a brace }"\n}'
        regions = self._collect(content)
        # Only the outer {} should fold, braces inside strings ignored
        self.assertEqual(regions, {0: 2})

    def test_empty_content(self):
        regions = self._collect("")
        self.assertEqual(regions, {})

    def test_mixed_braces_and_brackets(self):
        content = '{\n  "arr": [\n    1,\n    2\n  ]\n}'
        regions = self._collect(content)
        self.assertIn(0, regions)  # outer {}
        self.assertIn(1, regions)  # inner []


# ---------------------------------------------------------------------------
# Chevron glyph constants
# ---------------------------------------------------------------------------


class TestChevronGlyphs(unittest.TestCase):
    """Verify the chevron Unicode escapes are single codepoints."""

    def test_collapsed_glyph_is_single_char(self):
        self.assertEqual(len("\U000f0142"), 1)
        self.assertEqual(ord("\U000f0142"), 0xF0142)

    def test_expanded_glyph_is_single_char(self):
        self.assertEqual(len("\U000f0140"), 1)
        self.assertEqual(ord("\U000f0140"), 0xF0140)

    def test_wrong_escape_produces_two_chars(self):
        """Guard against the \\uf0142 vs \\U000f0142 mistake."""
        self.assertEqual(len("\uf0142"), 2, "\\uf0142 is TWO chars, not one — use \\U000f0142")


if __name__ == "__main__":
    unittest.main()
