"""
Lazy Tree-sitter parser manager for Zen IDE.

Provides cached Parser and Language instances per language.
All tree-sitter imports are deferred to first use to preserve startup performance.
"""

from typing import Optional


class TreeSitterCore:
    """Manages Tree-sitter parsers with lazy loading and caching."""

    _languages = {}
    _parsers = {}
    _ts_module = None
    _parse_cache = {}
    _PARSE_CACHE_MAX = 128

    _LANG_REGISTRY = {
        "python": ("tree_sitter_python", "language"),
        "javascript": ("tree_sitter_javascript", "language"),
        "typescript": ("tree_sitter_typescript", "language_typescript"),
        "tsx": ("tree_sitter_typescript", "language_tsx"),
        "hcl": ("tree_sitter_hcl", "language"),
    }

    @classmethod
    def _ensure_ts(cls):
        """Lazy-import the tree_sitter module."""
        if cls._ts_module is None:
            import tree_sitter

            cls._ts_module = tree_sitter

    @classmethod
    def get_language(cls, lang: str):
        """Get a cached Language instance for the given language name."""
        if lang in cls._languages:
            return cls._languages[lang]

        if lang not in cls._LANG_REGISTRY:
            return None

        cls._ensure_ts()
        module_name, func_name = cls._LANG_REGISTRY[lang]

        import importlib

        mod = importlib.import_module(module_name)
        lang_fn = getattr(mod, func_name)
        language = cls._ts_module.Language(lang_fn())
        cls._languages[lang] = language
        return language

    @classmethod
    def get_parser(cls, lang: str):
        """Get a cached Parser configured for the given language."""
        if lang in cls._parsers:
            return cls._parsers[lang]

        language = cls.get_language(lang)
        if language is None:
            return None

        parser = cls._ts_module.Parser(language)
        cls._parsers[lang] = parser
        return parser

    @classmethod
    def parse(cls, source: bytes, lang: str, old_tree=None):
        """Parse source bytes and return a Tree, or None if language unsupported.

        Pass *old_tree* (from a previous parse) for incremental re-parsing
        after calling ``old_tree.edit(...)`` with the change coordinates.

        Results are cached by content hash when *old_tree* is None so that
        repeated calls with identical content (e.g. multiple navigation queries
        on the same file) avoid redundant work.
        """
        parser = cls.get_parser(lang)
        if parser is None:
            return None
        if old_tree is not None:
            return parser.parse(source, old_tree=old_tree)

        import hashlib

        key = (lang, hashlib.sha256(source).digest())
        cached = cls._parse_cache.get(key)
        if cached is not None:
            return cached

        tree = parser.parse(source)
        if len(cls._parse_cache) >= cls._PARSE_CACHE_MAX:
            # Evict oldest entry
            cls._parse_cache.pop(next(iter(cls._parse_cache)))
        cls._parse_cache[key] = tree
        return tree

    @classmethod
    def query(cls, lang: str, pattern: str):
        """Create a Query for the given language and pattern string."""
        language = cls.get_language(lang)
        if language is None:
            return None
        return cls._ts_module.Query(language, pattern)

    @classmethod
    def run_query(cls, tree_or_node, query):
        """Execute a query and return matches as [(pattern_idx, {capture_name: [Node]})]."""
        from tree_sitter._binding import QueryCursor

        cursor = QueryCursor(query)
        node = tree_or_node.root_node if hasattr(tree_or_node, "root_node") else tree_or_node
        return cursor.matches(node)

    @classmethod
    def lang_for_ext(cls, ext: str) -> Optional[str]:
        """Map file extension to tree-sitter language name."""
        mapping = {
            ".py": "python",
            ".pyw": "python",
            ".pyi": "python",
            ".js": "javascript",
            ".jsx": "javascript",
            ".ts": "typescript",
            ".tsx": "tsx",
            ".tf": "hcl",
        }
        return mapping.get(ext)

    @classmethod
    def available(cls) -> bool:
        """Check if tree-sitter is importable."""
        try:
            cls._ensure_ts()
            return True
        except ImportError:
            return False
