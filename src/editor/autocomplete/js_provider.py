"""
JavaScript/TypeScript completion provider for Zen IDE autocomplete.

Provides JS/TS-specific completions: keywords, globals, imports, and symbols.
"""

import re

from editor.autocomplete import CompletionItem, CompletionKind

# JavaScript/TypeScript keywords and globals
JS_KEYWORDS = [
    "async",
    "await",
    "break",
    "case",
    "catch",
    "class",
    "const",
    "continue",
    "debugger",
    "default",
    "delete",
    "do",
    "else",
    "enum",
    "export",
    "extends",
    "false",
    "finally",
    "for",
    "function",
    "if",
    "implements",
    "import",
    "in",
    "instanceof",
    "interface",
    "let",
    "new",
    "null",
    "package",
    "private",
    "protected",
    "public",
    "return",
    "static",
    "super",
    "switch",
    "this",
    "throw",
    "true",
    "try",
    "typeof",
    "undefined",
    "var",
    "void",
    "while",
    "with",
    "yield",
    "console",
    "document",
    "window",
    "process",
    "module",
    "require",
    "exports",
    "global",
    "Buffer",
    "Promise",
    "Array",
    "Object",
    "String",
    "Number",
    "Boolean",
    "Symbol",
    "Map",
    "Set",
    "WeakMap",
    "WeakSet",
    "Date",
    "RegExp",
    "Error",
    "JSON",
    "Math",
]


class JsCompletionProvider:
    """JavaScript/TypeScript-specific completion provider."""

    def get_completions(self, buffer_text):
        """Get JS/TS keyword, import, and symbol completions."""
        completions = []
        completions.extend(CompletionItem(kw, CompletionKind.KEYWORD) for kw in JS_KEYWORDS)
        completions.extend(self._get_imports(buffer_text))
        completions.extend(self._get_symbols(buffer_text))
        return completions

    def _get_imports(self, text):
        """Extract imported symbol names from JS/TS code."""
        imports = []

        for m in re.finditer(r"import\s*\{([^}]+)\}\s*from", text):
            for name_part in m.group(1).split(","):
                name_part = name_part.strip()
                parts = name_part.split(" as ")
                alias = parts[1].strip() if len(parts) > 1 else parts[0].strip()
                if alias:
                    imports.append(CompletionItem(alias, CompletionKind.VARIABLE))

        for m in re.finditer(r"import\s+(\w+)\s+from", text):
            imports.append(CompletionItem(m.group(1), CompletionKind.VARIABLE))

        for m in re.finditer(r"import\s*\*\s*as\s+(\w+)\s+from", text):
            imports.append(CompletionItem(m.group(1), CompletionKind.VARIABLE))

        return imports

    def _get_symbols(self, text):
        """Extract local symbol definitions from JS/TS code."""
        symbols = []

        for m in re.finditer(r"class\s+(\w+)", text):
            symbols.append(CompletionItem(m.group(1), CompletionKind.PROPERTY))
        for m in re.finditer(r"function\s+(\w+)", text):
            doc = self._extract_jsdoc_at(text, m.start())
            symbols.append(CompletionItem(m.group(1), CompletionKind.FUNCTION, docstring=doc))
        for m in re.finditer(r"(?:const|let|var)\s+(\w+)", text):
            symbols.append(CompletionItem(m.group(1), CompletionKind.VARIABLE))
        for m in re.finditer(r"interface\s+(\w+)", text):
            symbols.append(CompletionItem(m.group(1), CompletionKind.PROPERTY))
        for m in re.finditer(r"type\s+(\w+)\s*=", text):
            symbols.append(CompletionItem(m.group(1), CompletionKind.PROPERTY))

        return symbols

    @staticmethod
    def _extract_jsdoc_at(text, def_start_pos):
        """Extract first description line from a JSDoc comment preceding a definition."""
        before = text[:def_start_pos].rstrip()
        if not before.endswith("*/"):
            return ""
        start = before.rfind("/**")
        if start == -1:
            return ""
        comment = before[start + 3 : -2].strip()
        for line in comment.split("\n"):
            line = line.strip().lstrip("* ").strip()
            if line and not line.startswith("@"):
                return line[:120]
        return ""
