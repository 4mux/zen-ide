"""Editor View package for Zen IDE.

Re-exports public names so external code using
``from editor.editor_view import EditorView, EditorTab``
continues to work unchanged.
"""

MD_EXTENSIONS = {".md", ".markdown"}
OPENAPI_EXTENSIONS = {".yaml", ".yml", ".json"}
SKETCH_EXTENSION = ".zen_sketch"

from .core import (
    _iter_at_line,
    _iter_at_line_offset,
    _iter_at_offset,
)
from .editor_tab import EditorTab
from .editor_view import EditorView
from .highlighting import _SCHEME_DIR, _cursor_scheme_fg, _generate_style_scheme
from .zen_source_view import ZenSourceView

__all__ = [
    "EditorView",
    "EditorTab",
    "ZenSourceView",
    "MD_EXTENSIONS",
    "OPENAPI_EXTENSIONS",
    "SKETCH_EXTENSION",
    "_generate_style_scheme",
    "_SCHEME_DIR",
    "_cursor_scheme_fg",
    "_iter_at_line",
    "_iter_at_line_offset",
    "_iter_at_offset",
]
