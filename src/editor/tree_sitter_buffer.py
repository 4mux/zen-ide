"""
Per-buffer tree-sitter parse tree cache with incremental updates.

Attach one instance per EditorTab.  Tracks buffer edits via
insert-text / delete-range signals and applies them incrementally
on the next ``get_tree()`` call.
"""


class TreeSitterBufferCache:
    """Caches a tree-sitter parse tree for a single GtkSource.Buffer."""

    def __init__(self):
        self._tree = None
        self._lang = None
        self._pending_edits = []
        self._dirty = False

    def get_tree(self, content: str, lang: str):
        """Return the cached tree or re-parse (incrementally when possible)."""
        if self._tree is not None and self._lang == lang and not self._dirty:
            return self._tree

        from navigation.tree_sitter_core import TreeSitterCore

        content_bytes = content.encode("utf-8")

        if self._tree is not None and self._lang == lang and self._pending_edits:
            old_tree = self._tree
            for edit in self._pending_edits:
                old_tree.edit(*edit)
            self._pending_edits.clear()
            tree = TreeSitterCore.parse(content_bytes, lang, old_tree=old_tree)
        else:
            self._pending_edits.clear()
            tree = TreeSitterCore.parse(content_bytes, lang)

        if tree is not None:
            self._tree = tree
            self._lang = lang
            self._dirty = False
        return tree

    def record_insert(self, start_byte, start_point, text_bytes_len, new_end_point):
        """Record a text insertion for incremental parsing."""
        self._pending_edits.append(
            (
                start_byte,
                start_byte,
                start_byte + text_bytes_len,
                start_point,
                start_point,
                new_end_point,
            )
        )
        self._dirty = True

    def record_delete(self, start_byte, start_point, end_byte, end_point):
        """Record a text deletion for incremental parsing."""
        self._pending_edits.append(
            (
                start_byte,
                end_byte,
                start_byte,
                start_point,
                end_point,
                start_point,
            )
        )
        self._dirty = True

    def invalidate(self):
        """Discard the cached tree."""
        self._tree = None
        self._lang = None
        self._pending_edits.clear()
        self._dirty = True


# ---------------------------------------------------------------------------
# GtkSourceView language id → tree-sitter language name
# ---------------------------------------------------------------------------
_LANG_MAP = {
    "python3": "python",
    "python": "python",
    "javascript": "javascript",
    "js": "javascript",
    "typescript": "typescript",
    "jsx": "javascript",
    "typescript-jsx": "tsx",
}


def ts_lang_for_buffer(buf):
    """Return the tree-sitter language name for a buffer, or ``None``."""
    lang = buf.get_language()
    if lang is None:
        return None
    return _LANG_MAP.get(lang.get_id())


# ---------------------------------------------------------------------------
# Signal helpers
# ---------------------------------------------------------------------------


def _iter_to_byte_offset(buf, it):
    """Convert a GtkTextIter to a UTF-8 byte offset."""
    start = buf.get_start_iter()
    text = buf.get_text(start, it, True)
    return len(text.encode("utf-8"))


def _on_insert_text(buf, location, text, _length, cache):
    """Record an insertion for incremental parsing."""
    start_byte = _iter_to_byte_offset(buf, location)
    start_row = location.get_line()
    start_col = location.get_line_offset()
    start_point = (start_row, start_col)

    text_bytes_len = len(text.encode("utf-8"))
    lines = text.split("\n")
    if len(lines) == 1:
        new_end_point = (start_row, start_col + len(lines[0]))
    else:
        new_end_point = (start_row + len(lines) - 1, len(lines[-1]))

    cache.record_insert(start_byte, start_point, text_bytes_len, new_end_point)


def _on_delete_range(buf, start, end, cache):
    """Record a deletion for incremental parsing."""
    start_byte = _iter_to_byte_offset(buf, start)
    end_byte = _iter_to_byte_offset(buf, end)
    start_point = (start.get_line(), start.get_line_offset())
    end_point = (end.get_line(), end.get_line_offset())
    cache.record_delete(start_byte, start_point, end_byte, end_point)


# ---------------------------------------------------------------------------
# Public setup
# ---------------------------------------------------------------------------


def setup_buffer_cache(tab):
    """Attach a tree-sitter buffer cache to an EditorTab and wire signals."""
    cache = TreeSitterBufferCache()
    tab._ts_cache = cache

    buf = tab.buffer
    buf.connect("insert-text", _on_insert_text, cache)
    buf.connect("delete-range", _on_delete_range, cache)
