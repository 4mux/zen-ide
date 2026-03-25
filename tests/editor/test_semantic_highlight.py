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

    def get_line(self):
        return self._text[: self._offset].count("\n")

    def ends_line(self):
        if self._offset >= len(self._text):
            return True
        return self._text[self._offset] == "\n"

    def forward_to_line_end(self):
        idx = self._text.find("\n", self._offset)
        if idx == -1:
            self._offset = len(self._text)
        else:
            self._offset = idx


class _FakeTag:
    def __init__(self, name):
        self.name = name
        self._priority = 0

    def set_priority(self, p):
        self._priority = p


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
        self.removed_tags = []

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

    def remove_tag_by_name(self, name, _start, _end):
        self.removed_tags.append(name)

    def get_language(self):
        return _FakeLanguage(self._lang_id)

    def get_char_count(self):
        return len(self.text)

    def get_line_count(self):
        return self.text.count("\n") + 1

    def get_iter_at_line(self, line_num):
        offset = 0
        for i, line in enumerate(self.text.split("\n")):
            if i == line_num:
                break
            offset += len(line) + 1
        return (True, _FakeIter(self.text, min(offset, len(self.text))))


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


# ---------------------------------------------------------------------------
# Fake view / tab for first-paint regression tests
# ---------------------------------------------------------------------------

import pytest

try:
    from editor.tree_sitter_buffer import TreeSitterBufferCache

    _HAS_TS = True
except Exception:
    _HAS_TS = False

needs_ts = pytest.mark.skipif(not _HAS_TS, reason="tree-sitter not available")


class _FakeRect:
    def __init__(self, x, y, width, height):
        self.x = x
        self.y = y
        self.width = width
        self.height = height


class _FakeView:
    """Minimal GtkSourceView stand-in for testing visible-range logic."""

    def __init__(self, *, mapped=False, visible_lines=30):
        self._mapped = mapped
        self._visible_lines = visible_lines

    def get_mapped(self):
        return self._mapped

    def get_visible_rect(self):
        return _FakeRect(0, 0, 800, self._visible_lines * 20)

    def get_iter_at_location(self, _x, y):
        line = max(0, int(y / 20))
        return _FakeIter("", 0), _FakeIter.__new__(_FakeIter)

    def get_vadjustment(self):
        return None


class _FakeViewWithLines(_FakeView):
    """View that returns realistic line-based iterators."""

    def __init__(self, text, *, mapped=False, visible_lines=30):
        super().__init__(mapped=mapped, visible_lines=visible_lines)
        self._text = text
        self._line_offsets = [0]
        for i, ch in enumerate(text):
            if ch == "\n":
                self._line_offsets.append(i + 1)

    def get_iter_at_location(self, _x, y):
        line = min(max(0, int(y / 20)), len(self._line_offsets) - 1)
        offset = self._line_offsets[line]
        return (True, _FakeIter(self._text, offset))


class _FakeTab:
    """Minimal EditorTab stand-in."""

    def __init__(self, buf, view):
        self.buffer = buf
        self.view = view
        self._ts_cache = TreeSitterBufferCache() if _HAS_TS else None


# ---------------------------------------------------------------------------
# Regression: first-paint semantic highlighting
# ---------------------------------------------------------------------------


class TestFirstPaintHighlighting:
    """Regression tests for initial file load semantic highlighting.

    These verify the fixes for the "white functions on first open" bug where:
    1. Tokens beyond the visible viewport were missed on initial load.
    2. Tags applied while the view was unmapped didn't trigger display
       invalidation (unmapped→mapped transition).
    """

    @needs_ts
    def test_full_buffer_highlighted_on_first_mapped_pass(self):
        """First mapped call must extract tokens from the ENTIRE buffer,
        not just the visible viewport.

        Regression: method calls like ws_data.get() on line 79 were missed
        because the initial visible range only covered lines 0-70.
        """
        # Build a buffer with a function call far beyond the viewport
        lines = ["# filler\n"] * 100
        lines[5] = "x = time.monotonic()\n"  # line 5 — in viewport
        lines[85] = "y = ws_data.get('key')\n"  # line 85 — beyond viewport
        text = "".join(lines)

        buf = _FakeBuffer(text)
        view = _FakeViewWithLines(text, mapped=True, visible_lines=30)
        tab = _FakeTab(buf, view)

        _apply_semantic_tags(buf, tab)

        # Both lines must have tokens applied
        tagged_offsets = {(t[1], t[2]) for t in buf.applied_tags}
        line_85_start = text.index("ws_data")
        # Verify at least one tag covers text on line 85
        has_line_85_tag = any(s >= line_85_start for s, _e in tagged_offsets)
        assert has_line_85_tag, (
            f"No semantic tags applied beyond viewport. "
            f"Tags at offsets: {sorted(tagged_offsets)}, "
            f"line 85 starts at char {line_85_start}"
        )

    @needs_ts
    def test_subsequent_calls_use_viewport_range(self):
        """After the first mapped pass, subsequent calls should use the
        viewport range (not the entire buffer) for performance."""
        lines = ["# filler\n"] * 200
        lines[5] = "x = time.monotonic()\n"
        lines[180] = "y = ws_data.get('key')\n"
        text = "".join(lines)

        buf = _FakeBuffer(text)
        view = _FakeViewWithLines(text, mapped=True, visible_lines=30)
        tab = _FakeTab(buf, view)

        # First call — full buffer
        _apply_semantic_tags(buf, tab)
        first_pass_tags = list(buf.applied_tags)

        # Second call (same text, view already mapped) — viewport only
        buf.applied_tags.clear()
        _apply_semantic_tags(buf, tab)
        second_pass_tags = list(buf.applied_tags)

        # First pass should have more (or equal) tags than second
        assert len(first_pass_tags) >= len(second_pass_tags)

    @needs_ts
    def test_unmapped_to_mapped_forces_reapply(self):
        """When transitioning from unmapped to mapped, tags must be
        removed and reapplied to trigger display invalidation."""
        text = "x = time.monotonic()\ny = os.path.join('a', 'b')\n"
        buf = _FakeBuffer(text)

        # First call — unmapped
        view_unmapped = _FakeViewWithLines(text, mapped=False)
        tab = _FakeTab(buf, view_unmapped)
        _apply_semantic_tags(buf, tab)
        assert buf.applied_tags, "Should apply tags even when unmapped"

        # Second call — now mapped (simulates view becoming visible)
        buf.applied_tags.clear()
        buf.removed_tags.clear()
        tab.view = _FakeViewWithLines(text, mapped=True)
        _apply_semantic_tags(buf, tab)

        # Must have removed old tags (to trigger display invalidation)
        assert len(buf.removed_tags) > 0, (
            "Unmapped→mapped transition must remove tags to trigger GtkTextView display invalidation"
        )
        # And reapplied them
        assert buf.applied_tags, "Must reapply tags after removal"

    @needs_ts
    def test_same_mapped_state_skips_removal(self):
        """When the view stays mapped and text hasn't changed, tags
        should NOT be removed (avoids flicker from highlight-updated)."""
        text = "x = MyClass()\n"
        buf = _FakeBuffer(text)
        view = _FakeViewWithLines(text, mapped=True)
        tab = _FakeTab(buf, view)

        # First call — initial highlight
        _apply_semantic_tags(buf, tab)
        assert buf.applied_tags

        # Second call — same text, still mapped
        buf.applied_tags.clear()
        buf.removed_tags.clear()
        _apply_semantic_tags(buf, tab)

        assert not buf.removed_tags, "Should not remove tags when text unchanged and view stayed mapped"
