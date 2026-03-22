"""Centralized language detection for GtkSourceView buffers."""

import os

from gi.repository import Gio, GtkSource

# Register custom language specs (e.g. Clojure) bundled with Zen IDE
_CUSTOM_LANG_DIR = os.path.dirname(__file__)
if os.path.isdir(_CUSTOM_LANG_DIR):
    _lang_mgr = GtkSource.LanguageManager.get_default()
    _search_path = _lang_mgr.get_search_path()
    if _CUSTOM_LANG_DIR not in _search_path:
        _lang_mgr.prepend_search_path(_CUSTOM_LANG_DIR)

# Filename-based language mapping (for files without extensions)
_NAME_TO_LANG = {
    "Makefile": "makefile",
    "makefile": "makefile",
    "GNUmakefile": "makefile",
    "Dockerfile": "dockerfile",
    "CMakeLists.txt": "cmake",
}

# Extension-based language mapping
_EXT_TO_LANG = {
    ".py": "python3",
    ".js": "javascript",
    ".jsx": "jsx",
    ".ts": "typescript",
    ".tsx": "typescript-jsx",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".rs": "rust",
    ".go": "go",
    ".rb": "ruby",
    ".sh": "sh",
    ".bash": "sh",
    ".sql": "sql",
    ".xml": "xml",
    ".plist": "xml",
    ".xsl": "xml",
    ".xslt": "xml",
    ".xsd": "xml",
    ".svg": "xml",
    ".rss": "xml",
    ".wsdl": "xml",
    ".glade": "xml",
    ".toml": "toml",
    ".tf": "hcl",
    ".java": "java",
    ".kt": "kotlin",
    ".swift": "swift",
    ".lua": "lua",
    ".r": "r",
    ".star": "python3",
    ".clj": "clojure",
    ".cljs": "clojure",
    ".cljc": "clojure",
    ".edn": "clojure",
}


def detect_language(file_path: str) -> GtkSource.Language | None:
    """Detect the GtkSourceView language for a file path.

    Uses a 3-level fallback:
    1. content_type + guess_language
    2. Filename-based lookup (Makefile, Dockerfile, etc.)
    3. Extension-based lookup
    """
    lang_manager = GtkSource.LanguageManager.get_default()

    # Try with content type first
    content_type, _ = Gio.content_type_guess(file_path, None)
    if content_type:
        language = lang_manager.guess_language(file_path, content_type)
        if language:
            return language

    # Fallback: match by filename
    basename = os.path.basename(file_path)
    lang_id = _NAME_TO_LANG.get(basename)
    if lang_id:
        language = lang_manager.get_language(lang_id)
        if language:
            return language

    # Fallback: match by extension
    ext = os.path.splitext(file_path)[1].lower()
    lang_id = _EXT_TO_LANG.get(ext)
    if lang_id:
        language = lang_manager.get_language(lang_id)
        if language:
            return language

    return None
