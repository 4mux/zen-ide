"""
Context gatherer for inline AI completions.

Builds Fill-in-Middle (FIM) context from the editor buffer:
prefix (code before cursor), suffix (code after cursor),
file path, language identifier, and related file snippets.
"""

import os
import re
from dataclasses import dataclass, field


@dataclass
class RelatedSnippet:
    """A snippet from a related file to provide cross-file context."""

    file_path: str
    content: str
    relevance: str  # "import", "open_tab", "same_dir"


@dataclass
class CompletionContext:
    """Context for an inline completion request."""

    prefix: str
    suffix: str
    file_path: str
    language: str
    cursor_line: int
    cursor_col: int
    related_snippets: list[RelatedSnippet] = field(default_factory=list)


# Max characters to include in prefix/suffix — large enough for FIM context
_MAX_PREFIX_CHARS = 1500
_MAX_SUFFIX_CHARS = 500

# Cross-file context limits
_MAX_SNIPPET_CHARS = 300
_MAX_IMPORT_SNIPPET_CHARS = 200
_MAX_RELATED_SNIPPETS = 10


def gather_context(editor_tab) -> CompletionContext:
    """Gather completion context from an EditorTab.

    Extracts prefix/suffix text around the cursor, metadata,
    and cross-file context from open tabs and imports.
    """
    buf = editor_tab.buffer
    cursor_mark = buf.get_insert()
    cursor_iter = buf.get_iter_at_mark(cursor_mark)

    # Text before cursor (prefix)
    start_iter = buf.get_start_iter()
    prefix = buf.get_text(start_iter, cursor_iter, False)
    if len(prefix) > _MAX_PREFIX_CHARS:
        prefix = prefix[-_MAX_PREFIX_CHARS:]

    # Text after cursor (suffix)
    end_iter = buf.get_end_iter()
    suffix = buf.get_text(cursor_iter, end_iter, False)
    if len(suffix) > _MAX_SUFFIX_CHARS:
        suffix = suffix[:_MAX_SUFFIX_CHARS]

    # Language from GtkSourceView language id
    lang = buf.get_language()
    language = lang.get_id() if lang else ""
    if language in ("python3",):
        language = "python"

    file_path = editor_tab.file_path or ""

    # Gather cross-file context from open tabs and imports
    related = _gather_cross_file_context(editor_tab, file_path)

    return CompletionContext(
        prefix=prefix,
        suffix=suffix,
        file_path=file_path,
        language=language,
        cursor_line=cursor_iter.get_line() + 1,
        cursor_col=cursor_iter.get_line_offset(),
        related_snippets=related,
    )


def _gather_cross_file_context(editor_tab, current_file: str) -> list[RelatedSnippet]:
    """Gather context snippets from related files (open tabs, imports)."""
    snippets: list[RelatedSnippet] = []

    try:
        # Get the EditorView via the root window
        window = editor_tab.view.get_root()
        if window is None:
            return snippets

        editor_view = getattr(window, "_editor_view", None)
        if editor_view is None:
            return snippets

        tabs = getattr(editor_view, "tabs", {})

        # 1. Open tabs — user is actively working with these files
        for _tab_id, tab in tabs.items():
            if tab is editor_tab:
                continue
            tab_path = getattr(tab, "file_path", None)
            if not tab_path:
                continue
            content = _extract_header(tab.buffer, _MAX_SNIPPET_CHARS)
            if content:
                snippets.append(
                    RelatedSnippet(
                        file_path=tab_path,
                        content=content,
                        relevance="open_tab",
                    )
                )

        # 2. Imports — parse current file and resolve to file paths
        if current_file:
            full_text = editor_tab.buffer.get_text(
                editor_tab.buffer.get_start_iter(),
                editor_tab.buffer.get_end_iter(),
                False,
            )
            import_paths = _parse_imports(full_text, current_file)
            # Only add imports not already covered by open tabs
            open_paths = {s.file_path for s in snippets}
            for imp_path in import_paths[:5]:
                if imp_path in open_paths:
                    continue
                content = _read_file_header(imp_path, _MAX_IMPORT_SNIPPET_CHARS)
                if content:
                    snippets.append(
                        RelatedSnippet(
                            file_path=imp_path,
                            content=content,
                            relevance="import",
                        )
                    )

    except Exception:
        pass

    return snippets[:_MAX_RELATED_SNIPPETS]


# Regex patterns for Python import statements
_IMPORT_RE = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.MULTILINE)


def _parse_imports(source: str, current_file: str) -> list[str]:
    """Parse import statements and resolve them to file paths."""
    base_dir = os.path.dirname(current_file)
    resolved: list[str] = []

    for match in _IMPORT_RE.finditer(source):
        module = match.group(1) or match.group(2)
        if not module:
            continue
        # Convert dotted module to relative path
        parts = module.split(".")
        # Try as a .py file in the same tree
        candidate = os.path.join(base_dir, *parts) + ".py"
        if os.path.isfile(candidate):
            resolved.append(candidate)
            continue
        # Try as __init__.py in a package
        candidate = os.path.join(base_dir, *parts, "__init__.py")
        if os.path.isfile(candidate):
            resolved.append(candidate)

    return resolved


def _extract_header(buffer, max_chars: int) -> str:
    """Extract the first max_chars of a GtkSourceBuffer (signatures, classes)."""
    try:
        start = buffer.get_start_iter()
        end = buffer.get_end_iter()
        text = buffer.get_text(start, end, False)
        if not text:
            return ""
        return text[:max_chars]
    except Exception:
        return ""


def _read_file_header(file_path: str, max_chars: int) -> str:
    """Read the first max_chars of a file from disk."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(max_chars)
    except Exception:
        return ""
