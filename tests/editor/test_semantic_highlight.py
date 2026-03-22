"""Tests for editor/semantic_highlight.py — tag constants, source-safety,
and tree-sitter integration smoke tests.

The regex-based patterns have been replaced by tree-sitter AST extraction.
Detailed token-extraction tests live in test_tree_sitter_semantic.py.
"""

import inspect

from editor.semantic_highlight import (
    TAG_CLASS_USAGE,
    TAG_FUNC_CALL,
    TAG_PARAM,
    TAG_PROPERTY,
    TAG_SELF,
    _apply_semantic_tags,
)

# ---------------------------------------------------------------------------
# Tag constant tests
# ---------------------------------------------------------------------------


class TestTagNames:
    """Test tag name constants."""

    def test_class_tag(self):
        assert TAG_CLASS_USAGE == "zen-class-usage"

    def test_func_tag(self):
        assert TAG_FUNC_CALL == "zen-func-call"

    def test_param_tag(self):
        assert TAG_PARAM == "zen-param"

    def test_self_tag(self):
        assert TAG_SELF == "zen-self"

    def test_property_tag(self):
        assert TAG_PROPERTY == "zen-property"


# ---------------------------------------------------------------------------
# Source-safety regression tests
# ---------------------------------------------------------------------------


class TestNoToggleAPIUsage:
    """Ensure iter_forward_to_context_class_toggle is never called.

    This API triggers lazy re-highlighting inside GtkSourceView that
    invalidates iterators mid-call, producing GTK warnings that cannot
    be fixed from Python.  Only iter_has_context_class should be used.
    """

    def test_source_does_not_call_toggle_api(self):
        """The module source must not contain any call to the toggle API."""
        import editor.semantic_highlight as mod

        source = inspect.getsource(mod)
        lines = source.splitlines()
        code_lines = [
            ln
            for ln in lines
            if not ln.lstrip().startswith("#") and not ln.lstrip().startswith('"""') and not ln.lstrip().startswith("``")
        ]
        code_text = "\n".join(code_lines)
        assert "iter_forward_to_context_class_toggle" not in code_text, (
            "iter_forward_to_context_class_toggle must not be called — it triggers stale-iterator GTK warnings"
        )


class TestNoRegexImport:
    """Verify that the ``re`` module is no longer imported."""

    def test_no_re_import(self):
        import editor.semantic_highlight as mod

        source = inspect.getsource(mod)
        lines = source.splitlines()
        for ln in lines:
            stripped = ln.strip()
            if stripped.startswith("#"):
                continue
            assert not stripped.startswith("import re"), "semantic_highlight should not import re"


# ---------------------------------------------------------------------------
# Fake GTK objects for integration smoke tests
# ---------------------------------------------------------------------------


class _FakeIter:
    def __init__(self, text, offset):
        self._text = text
        self._offset = max(0, min(len(text), offset))

    def get_offset(self):
        return self._offset


class _FakeTag:
    def __init__(self, name):
        self.name = name


class _FakeTagTable:
    def __init__(self, tags):
        self._tags = {t.name: t for t in tags}

    def lookup(self, name):
        return self._tags.get(name)

    def get_size(self):
        return len(self._tags)


class _FakeLanguage:
    def __init__(self, lang_id):
        self._id = lang_id

    def get_id(self):
        return self._id


class _FakeBuffer:
    def __init__(self, text, *, lang_id="python3"):
        self.text = text
        self._lang_id = lang_id
        self._tags = [
            _FakeTag(TAG_CLASS_USAGE),
            _FakeTag(TAG_FUNC_CALL),
            _FakeTag(TAG_PARAM),
            _FakeTag(TAG_SELF),
            _FakeTag(TAG_PROPERTY),
        ]
        self._tag_table = _FakeTagTable(self._tags)
        self.applied_tags = []

    def get_iter_at_offset(self, offset):
        return (True, _FakeIter(self.text, offset))

    def get_start_iter(self):
        return _FakeIter(self.text, 0)

    def get_end_iter(self):
        return _FakeIter(self.text, len(self.text))

    def get_text(self, start_iter, end_iter, _include_hidden):
        return self.text[start_iter.get_offset() : end_iter.get_offset()]

    def get_tag_table(self):
        return self._tag_table

    def apply_tag(self, tag, start_iter, end_iter):
        self.applied_tags.append((tag.name, start_iter.get_offset(), end_iter.get_offset()))

    def remove_tag_by_name(self, _name, _start, _end):
        pass

    def get_language(self):
        return _FakeLanguage(self._lang_id)


# ---------------------------------------------------------------------------
# Integration: _apply_semantic_tags early-exit paths
# ---------------------------------------------------------------------------


class TestApplySemanticTagsEdgeCases:
    def test_no_language_returns_early(self):
        buf = _FakeBuffer("MyClass()\n")
        buf.get_language = lambda: None
        _apply_semantic_tags(buf)
        assert buf.applied_tags == []

    def test_unsupported_language_returns_early(self):
        buf = _FakeBuffer("MyClass()\n", lang_id="markdown")
        _apply_semantic_tags(buf)
        assert buf.applied_tags == []

    def test_no_tab_returns_early(self):
        """Without a tab (no tree-sitter cache), nothing is highlighted."""
        buf = _FakeBuffer("x = MyClass()\n")
        _apply_semantic_tags(buf, tab=None)
        assert buf.applied_tags == []
