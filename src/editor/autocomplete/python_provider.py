"""
Python completion provider for Zen IDE autocomplete.

Provides Python-specific completions: keywords, builtins, imports, symbols,
module path resolution, and dot-access member completions.
"""

import glob as glob_module
import keyword
import re
from pathlib import Path

from editor.autocomplete import CompletionItem, CompletionKind

# Python builtins
PYTHON_BUILTINS = [
    "abs",
    "all",
    "any",
    "ascii",
    "bin",
    "bool",
    "breakpoint",
    "bytearray",
    "bytes",
    "callable",
    "chr",
    "classmethod",
    "compile",
    "complex",
    "delattr",
    "dict",
    "dir",
    "divmod",
    "enumerate",
    "eval",
    "exec",
    "filter",
    "float",
    "format",
    "frozenset",
    "getattr",
    "globals",
    "hasattr",
    "hash",
    "help",
    "hex",
    "id",
    "input",
    "int",
    "isinstance",
    "issubclass",
    "iter",
    "len",
    "list",
    "locals",
    "map",
    "max",
    "memoryview",
    "min",
    "next",
    "object",
    "oct",
    "open",
    "ord",
    "pow",
    "print",
    "property",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "setattr",
    "slice",
    "sorted",
    "staticmethod",
    "str",
    "sum",
    "super",
    "tuple",
    "type",
    "vars",
    "zip",
    "__import__",
    "Exception",
    "ValueError",
    "TypeError",
    "KeyError",
    "IndexError",
    "AttributeError",
    "ImportError",
    "RuntimeError",
    "StopIteration",
    "FileNotFoundError",
    "PermissionError",
    "OSError",
    "IOError",
    "None",
    "True",
    "False",
    "Ellipsis",
    "NotImplemented",
]


class PythonCompletionProvider:
    """Python-specific completion provider."""

    def get_completions(self, buffer_text, file_path=None):
        """Get Python keyword, builtin, import, and symbol completions."""
        completions = []
        completions.extend(CompletionItem(kw, CompletionKind.KEYWORD) for kw in keyword.kwlist)
        completions.extend(CompletionItem(b, CompletionKind.BUILTIN) for b in PYTHON_BUILTINS)
        imports = self._get_imports(buffer_text)
        if file_path:
            self._enrich_imports(imports, buffer_text, file_path)
        completions.extend(imports)
        completions.extend(self._get_symbols(buffer_text))
        return completions

    def get_call_parameter_completions(self, buffer, cursor_iter, file_path, buffer_text):
        """Get parameter completions when cursor is inside a function call.

        Detects the enclosing function call, resolves its signature, and returns
        CompletionItems for remaining (unspecified) parameters.
        """
        ctx = self._detect_call_context(buffer, cursor_iter)
        if not ctx:
            return []

        func_chain, specified_kwargs, positional_count = ctx
        cursor_offset = cursor_iter.get_offset()

        sig = self._resolve_function_signature(func_chain, file_path, buffer_text, cursor_offset)
        if not sig:
            return []

        params = self._parse_params_with_defaults(sig)
        if not params:
            return []

        # Skip params covered by positional arguments
        remaining = params[positional_count:]

        # Remove already-specified keyword arguments
        remaining = [(name, default) for name, default in remaining if name not in specified_kwargs]

        completions = []
        for name, default in remaining:
            insert = f"{name}={default}" if default is not None else f"{name}="
            completions.append(
                CompletionItem(
                    name=name,
                    kind=CompletionKind.PARAMETER,
                    signature=sig,
                    insert_text=insert,
                )
            )
        return completions

    def _detect_call_context(self, buffer, cursor_iter):
        """Detect if cursor is inside a function call's parentheses.

        Returns (func_chain, specified_kwargs, positional_count) or None.
        """
        pos = cursor_iter.copy()
        depth = 0
        max_scan = 2000

        # Scan backward to find matching '('
        for _ in range(max_scan):
            if not pos.backward_char():
                return None
            ch = pos.get_char()
            if ch == ")":
                depth += 1
            elif ch == "(":
                if depth == 0:
                    break
                depth -= 1
        else:
            return None

        paren_pos = pos.copy()

        # Extract function name before '('
        func_end = paren_pos.copy()
        func_start = func_end.copy()
        while func_start.backward_char():
            ch = func_start.get_char()
            if not (ch.isalnum() or ch == "_" or ch == "."):
                func_start.forward_char()
                break
        func_chain = buffer.get_text(func_start, func_end, False)

        if not func_chain or not re.match(r"^[A-Za-z_][\w.]*$", func_chain):
            return None

        # Skip control-flow keywords
        first_part = func_chain.split(".")[0]
        skip_keywords = {
            "def",
            "class",
            "if",
            "elif",
            "while",
            "for",
            "with",
            "except",
            "return",
            "yield",
            "assert",
            "lambda",
            "not",
            "and",
            "or",
            "in",
            "is",
            "import",
            "from",
            "raise",
            "del",
            "global",
            "nonlocal",
            "pass",
        }
        if first_part in skip_keywords:
            return None

        # Extract args text between '(' and cursor
        after_paren = paren_pos.copy()
        after_paren.forward_char()
        args_text = buffer.get_text(after_paren, cursor_iter, False)

        # Parse specified arguments
        specified_kwargs = set()
        positional_count = 0
        args = self._split_call_args(args_text)
        for arg in args:
            if not arg:
                continue
            # Check if it's a keyword argument (name=value, but not ==, !=, <=, >=)
            eq_match = re.match(r"^([A-Za-z_]\w*)\s*=(?!=)", arg)
            if eq_match:
                specified_kwargs.add(eq_match.group(1))
            else:
                positional_count += 1

        return func_chain, specified_kwargs, positional_count

    @staticmethod
    def _split_call_args(args_text):
        """Split function call arguments at top-level commas.

        Handles nested parens, brackets, and string literals.
        """
        args = []
        current = []
        depth = 0
        in_string = None
        escape = False

        for ch in args_text:
            if escape:
                current.append(ch)
                escape = False
                continue
            if ch == "\\":
                current.append(ch)
                escape = True
                continue
            if in_string:
                current.append(ch)
                if ch == in_string:
                    in_string = None
                continue
            if ch in ('"', "'"):
                in_string = ch
                current.append(ch)
                continue
            if ch in ("(", "[", "{"):
                depth += 1
                current.append(ch)
                continue
            if ch in (")", "]", "}"):
                depth -= 1
                current.append(ch)
                continue
            if ch == "," and depth == 0:
                args.append("".join(current).strip())
                current = []
                continue
            current.append(ch)

        remaining = "".join(current).strip()
        if remaining:
            args.append(remaining)
        return args

    def _resolve_function_signature(self, func_chain, file_path, buffer_text, cursor_offset=None):
        """Resolve a function/method call chain to its signature string."""
        normalized = self._normalize_multiline_defs(buffer_text)
        parts = func_chain.split(".")

        if len(parts) == 1:
            return self._find_local_or_imported_signature(parts[0], file_path, normalized)

        method_name = parts[-1]
        first = parts[0]

        # Handle self/cls
        if first in ("self", "cls") and cursor_offset is not None:
            class_name = self._find_enclosing_class(buffer_text, cursor_offset)
            if class_name:
                return self._find_method_signature_in_class(normalized, class_name, method_name)
            return None

        # Try resolving variable type (e.g., obj = MyClass() → find MyClass.method)
        resolved_class = self._resolve_variable_type(buffer_text, first)
        if resolved_class:
            sig = self._find_method_signature_in_class(normalized, resolved_class, method_name)
            if sig:
                return sig
            # Try imported class
            sig = self._find_method_in_imported_class(resolved_class, method_name, buffer_text, file_path)
            if sig:
                return sig

        # Try as a direct class reference (e.g., ClassName.method)
        sig = self._find_method_signature_in_class(normalized, first, method_name)
        if sig:
            return sig

        # Try imported class.method
        sig = self._find_method_in_imported_class(first, method_name, buffer_text, file_path)
        if sig:
            return sig

        return None

    def _find_local_or_imported_signature(self, func_name, file_path, normalized_text):
        """Find function signature in local definitions or imports."""
        # Search local definitions
        m = re.search(
            rf"^\s*def\s+{re.escape(func_name)}\s*(\([^)]*\))\s*(?:->\s*(.+?))?\s*:",
            normalized_text,
            re.MULTILINE,
        )
        if m:
            sig = f"{func_name}{m.group(1)}"
            if m.group(2):
                sig += f" → {m.group(2).strip()}"
            return sig

        # Search for class constructor (ClassName())
        if re.search(rf"^class\s+{re.escape(func_name)}\b", normalized_text, re.MULTILINE):
            return self._extract_init_signature(normalized_text, func_name)

        # Search imports
        if not file_path:
            return None
        for im in re.finditer(r"^from\s+([\w.]+)\s+import\s+(.+?)$", normalized_text, re.MULTILINE):
            module_path = im.group(1)
            for name_part in im.group(2).strip("()").split(","):
                name_part = name_part.strip()
                if not name_part or name_part.startswith("#"):
                    continue
                alias_parts = name_part.split(" as ")
                original = alias_parts[0].strip()
                alias = alias_parts[-1].strip()
                if alias == func_name:
                    module_text = self._read_module_text(module_path, file_path)
                    if module_text:
                        module_text = self._normalize_multiline_defs(module_text)
                        sig = self._find_local_or_imported_signature(original, None, module_text)
                        if sig and original != func_name:
                            # Replace original name with alias in signature
                            sig = sig.replace(original, func_name, 1)
                        return sig
        return None

    def _find_method_signature_in_class(self, text, class_name, method_name):
        """Find a method's signature within a class body."""
        body = self._get_class_body_text(text, class_name)
        if not body:
            return None
        body = self._normalize_multiline_defs(body)
        m = re.search(
            rf"def\s+{re.escape(method_name)}\s*(\([^)]*\))\s*(?:->\s*(.+?))?\s*:",
            body,
        )
        if m:
            sig = f"{method_name}{m.group(1)}"
            if m.group(2):
                sig += f" → {m.group(2).strip()}"
            return sig
        return None

    def _find_method_in_imported_class(self, class_name, method_name, buffer_text, file_path):
        """Find a method signature in an imported class."""
        if not file_path:
            return None
        for im in re.finditer(r"^from\s+([\w.]+)\s+import\s+(.+?)$", buffer_text, re.MULTILINE):
            module_path = im.group(1)
            for name_part in im.group(2).strip("()").split(","):
                name_part = name_part.strip()
                if not name_part or name_part.startswith("#"):
                    continue
                alias_parts = name_part.split(" as ")
                original = alias_parts[0].strip()
                alias = alias_parts[-1].strip()
                if alias == class_name:
                    module_text = self._read_module_text(module_path, file_path)
                    if module_text:
                        module_text = self._normalize_multiline_defs(module_text)
                        sig = self._find_method_signature_in_class(module_text, original, method_name)
                        if sig:
                            return sig
                        # Follow re-exports
                        sub_text = self._follow_reexport(module_text, original, module_path, file_path)
                        if sub_text:
                            sub_text = self._normalize_multiline_defs(sub_text)
                            sig = self._find_method_signature_in_class(sub_text, original, method_name)
                            if sig:
                                return sig
        return None

    @staticmethod
    def _parse_params_with_defaults(sig_text):
        """Parse function signature into list of (param_name, default_value_or_None) tuples.

        Strips self/cls, *args, **kwargs, and positional-only markers.
        """
        m = re.search(r"\(([^)]*)\)", sig_text)
        if not m:
            return []
        params_str = m.group(1).strip()
        if not params_str:
            return []

        result = []
        for param in params_str.split(","):
            param = param.strip()
            if not param or param == "/":
                continue

            # Strip leading * or ** for *args/**kwargs
            bare = param.lstrip("*")
            name_part = bare.split(":")[0].split("=")[0].strip()

            if name_part in ("self", "cls", ""):
                continue
            # Skip bare * (keyword-only separator) and *args/**kwargs
            if param.startswith("*"):
                continue

            if "=" in param:
                eq_idx = param.index("=")
                name = param[:eq_idx].split(":")[0].strip()
                default = param[eq_idx + 1 :].strip()
            else:
                name = param.split(":")[0].strip()
                default = None

            if name and re.match(r"^[A-Za-z_]\w*$", name):
                result.append((name, default))
        return result

    def detect_import_context(self, buffer, cursor_iter):
        """Detect if cursor is on a Python from/import line.

        Returns (base_path, from_import) tuple:
        - base_path: dotted module path (e.g., 'lib' for 'from lib.'),
          empty string for top-level, or None if not in import context.
        - from_import: True if in 'from X import' context (need symbols, not submodules).
        Handles indented imports (e.g., inside try/except blocks).
        """
        line_start = cursor_iter.copy()
        line_start.set_line_offset(0)
        line_text = buffer.get_text(line_start, cursor_iter, False)

        # from X import Y: "from lib import " or "from lib.sub import na"
        m = re.match(r"^\s*from\s+([\w.]+)\s+import\s+\w*$", line_text)
        if m:
            return m.group(1), True

        # Dotted path: "from lib." or "from lib.sub.mo" or "import os.pa"
        m = re.match(r"^\s*(?:from|import)\s+((?:[\w]+\.)+)\w*$", line_text)
        if m:
            return m.group(1).rstrip("."), False

        # Top-level: "from " or "from li" or "import " or "import os"
        m = re.match(r"^\s*(?:from|import)\s+\w*$", line_text)
        if m:
            return "", False

        return None, False

    def get_file_symbols(self, module_path, file_path):
        """Extract top-level symbols (classes, functions, constants) from a Python module file.

        Resolves module_path (e.g., 'lib.db_tables') to a .py file by walking
        up parent directories and venv site-packages, then parses it for exportable names.
        """
        if not file_path or not module_path:
            return []

        rel_path = module_path.replace(".", "/")
        py_file = self._find_module_file(rel_path, file_path)
        if py_file:
            return self._parse_symbols(py_file)

        return []

    def detect_dot_access_context(self, buffer, word_start_offset):
        """Detect if cursor is after 'Name.' or 'Name.Sub.' and return the full chain, or None."""
        pos = buffer.get_iter_at_offset(word_start_offset)
        dot_pos = pos.copy()
        if not dot_pos.backward_char():
            return None
        if dot_pos.get_char() != ".":
            return None
        chain_end = dot_pos.copy()
        chain_start = dot_pos.copy()
        while chain_start.backward_char():
            ch = chain_start.get_char()
            if not (ch.isalnum() or ch == "_" or ch == "."):
                chain_start.forward_char()
                break
        chain = buffer.get_text(chain_start, chain_end, False)
        if chain and re.match(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*$", chain):
            return chain
        return None

    def resolve_dot_completions(self, dot_chain, file_path, buffer_text, cursor_offset=None):
        """Resolve dot-access completions for a dotted chain (e.g., DBTables or DBTables.Cards)."""
        if not file_path:
            return []
        parts = dot_chain.split(".")
        first = parts[0]

        # Handle self/cls: resolve to enclosing class
        if first in ("self", "cls") and cursor_offset is not None:
            class_name = self._find_enclosing_class(buffer_text, cursor_offset)
            if class_name:
                if len(parts) == 1:
                    return self._extract_self_completions(buffer_text, class_name)
                else:
                    chain = [class_name] + parts[1:]
                    return self._resolve_chain_in_text(buffer_text, chain)
            return []

        # Try to resolve variable type from assignment (e.g., var = ClassName(...))
        resolved_class = self._resolve_variable_type(buffer_text, first)
        if resolved_class and resolved_class != first:
            resolved_parts = [resolved_class] + parts[1:]
            local = self._resolve_chain_in_text(buffer_text, resolved_parts)
            if local:
                return local
            # Update for import resolution fallback
            first = resolved_class
            parts = resolved_parts

        # Check local classes first (walk chain in current buffer)
        local = self._resolve_chain_in_text(buffer_text, parts)
        if local:
            return local

        # Find module path from imports for the first identifier
        module_path = None
        original_name = first
        for m in re.finditer(r"^from\s+([\w.]+)\s+import\s+(.+?)$", buffer_text, re.MULTILINE):
            for part in m.group(2).strip("()").split(","):
                part = part.strip()
                if not part or part.startswith("#"):
                    continue
                split_parts = part.split(" as ")
                alias = split_parts[-1].strip()
                orig = split_parts[0].strip()
                if alias == first:
                    module_path = m.group(1)
                    original_name = orig
                    break
            if module_path:
                break

        if not module_path:
            return []

        module_text = self._read_module_text(module_path, file_path)
        if not module_text:
            return []

        chain = [original_name] + parts[1:]
        result = self._resolve_chain_in_text(module_text, chain)
        if result:
            return result

        # Follow re-exports in __init__.py (e.g., from .sub import ClassName)
        sub_text = self._follow_reexport(module_text, original_name, module_path, file_path)
        if sub_text:
            return self._resolve_chain_in_text(sub_text, chain)
        return []

    def get_module_completions(self, base_module_path, file_path):
        """Scan filesystem for Python modules/packages at the given import path.

        Walks up every parent directory from the file (stopping at .git root)
        and checks each level for the target module path. This handles projects
        where imports resolve relative to a root that isn't the immediate parent.
        """
        if not file_path:
            return []

        modules = set()
        rel_path = base_module_path.replace(".", "/") if base_module_path else ""
        current = Path(file_path).parent
        searched = set()

        while current != current.parent:
            for root in (current, current / "src"):
                if root in searched or not root.is_dir():
                    continue
                searched.add(root)
                dir_path = root / rel_path if rel_path else root
                if not dir_path.is_dir():
                    continue
                try:
                    for entry in dir_path.iterdir():
                        name = entry.name
                        if name.startswith(".") or name == "__pycache__":
                            continue
                        if entry.is_dir():
                            modules.add(name)
                        elif entry.is_file() and name.endswith(".py") and name != "__init__.py":
                            modules.add(name[:-3])
                except OSError:
                    pass

            if (current / ".git").exists():
                break
            current = current.parent

        # Also search venv site-packages
        if rel_path:
            for sp in self._find_venv_site_packages(file_path):
                dir_path = sp / rel_path
                if not dir_path.is_dir():
                    continue
                try:
                    for entry in dir_path.iterdir():
                        name = entry.name
                        if name.startswith(".") or name == "__pycache__":
                            continue
                        if entry.is_dir():
                            modules.add(name)
                        elif entry.is_file() and name.endswith(".py") and name != "__init__.py":
                            modules.add(name[:-3])
                except OSError:
                    pass

        return sorted([CompletionItem(m, CompletionKind.PROPERTY) for m in modules], key=lambda x: x.name)

    # --- Private helpers ---

    def _extract_init_signature(self, text, class_name):
        """Extract __init__ signature from a class, formatted as ClassName(params).

        For dataclasses (decorated with @dataclass), extracts type-annotated
        fields as constructor parameters since they have no explicit __init__.
        """
        body = self._get_class_body_text(text, class_name)
        if not body:
            return f"{class_name}()"
        body = self._normalize_multiline_defs(body)
        m = re.search(r"def\s+__init__\s*(\([^)]*\))", body)
        if m:
            return f"{class_name}{m.group(1)}"
        # For dataclasses, extract fields as constructor params
        if self._is_dataclass(text, class_name):
            fields = self._extract_dataclass_fields(body)
            if fields:
                return f"{class_name}({', '.join(fields)})"
        return f"{class_name}()"

    @staticmethod
    def _is_dataclass(text, class_name):
        """Check if a class has a @dataclass decorator."""
        m = re.search(rf"^class\s+{re.escape(class_name)}\b", text, re.MULTILINE)
        if not m:
            return False
        before = text[: m.start()].rstrip()
        for line in reversed(before.split("\n")[-5:]):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if re.match(r"@(?:dataclasses?\.)?dataclass\b", stripped):
                return True
            if stripped.startswith("@"):
                continue  # other decorator, keep looking
            break  # non-decorator line, stop
        return False

    @staticmethod
    def _extract_dataclass_fields(body):
        """Extract field names with types from a dataclass body for constructor signature."""
        fields = []
        base_indent = None
        for line in body.split("\n"):
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip())
            if base_indent is None:
                base_indent = indent
            if indent != base_indent:
                continue
            stripped = line.strip()
            # Match type-annotated field: name: Type [= default]
            m = re.match(r"([A-Za-z_]\w*)\s*:\s*", stripped)
            if not m:
                continue
            name = m.group(1)
            rest = stripped[m.end() :]
            # Determine type hint (before any = default)
            eq_idx = rest.find(" = ")
            type_hint = rest[:eq_idx].strip() if eq_idx >= 0 else rest.strip()
            # Skip ClassVar (not an __init__ parameter)
            if type_hint.startswith("ClassVar"):
                continue
            # Skip field(init=False)
            if "field(" in rest and "init=False" in rest:
                continue
            fields.append(f"{name}: {type_hint}")
        return fields

    @staticmethod
    def _extract_docstring_at(text, pos):
        """Extract first line of docstring or comment for a def/class at text position pos.

        Looks for triple-quoted docstring after the definition first, then
        falls back to # comment lines immediately above the definition.
        """
        rest = text[pos:]
        m = re.match(r"[ \t]*\n[ \t]*(\"\"\"|\'{3})", rest)
        if m:
            quote = m.group(1)
            after_quote = m.end()
            end_quote = rest.find(quote, after_quote)
            if end_quote != -1:
                doc = rest[after_quote:end_quote].strip()
                first_line = doc.split("\n")[0].strip()
                if first_line:
                    return first_line[:120]

        # Fall back to # comment above the definition
        before = text[:pos]
        # Walk back to the start of the def/class line
        line_start = before.rfind("\n")
        if line_start == -1:
            line_start = 0
        above = text[:line_start].rstrip()
        for line in reversed(above.split("\n")):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                return stripped.lstrip("# ").strip()[:120]
            break
        return ""

    @staticmethod
    def _peek_docstring(lines, idx):
        """Extract full docstring or comment from lines around a def at idx.

        Looks for triple-quoted docstrings after the def first, then falls back
        to # comment lines immediately above the def.
        """
        # 1. Look for triple-quoted docstring after def
        for j in range(idx + 1, min(idx + 4, len(lines))):
            stripped = lines[j].strip()
            if not stripped:
                continue
            for quote in ('"""', "'''"):
                if stripped.startswith(quote):
                    # Single-line: """docstring"""
                    if stripped.endswith(quote) and len(stripped) > 6:
                        return stripped[3:-3].strip()
                    content = stripped[3:].strip()
                    # Collect all lines until closing quote
                    doc_lines = []
                    if content:
                        if content.endswith(quote):
                            return content[: -len(quote)].strip()
                        doc_lines.append(content)
                    # Read subsequent lines until closing triple quote
                    for k in range(j + 1, min(j + 30, len(lines))):
                        line_k = lines[k].strip()
                        if quote in line_k:
                            before_close = line_k[: line_k.index(quote)].strip()
                            if before_close:
                                doc_lines.append(before_close)
                            break
                        if line_k:
                            doc_lines.append(line_k)
                    return "\n".join(doc_lines) if doc_lines else ""
            break

        # 2. Fall back to # comment block above the def line
        for j in range(idx - 1, max(idx - 6, -1), -1):
            stripped = lines[j].strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                return stripped.lstrip("# ").strip()
            break
        return ""

    def _get_imports(self, text):
        """Extract imported symbol names from Python code."""
        imports = []

        for m in re.finditer(r"^import\s+([\w.]+)(?:\s+as\s+(\w+))?", text, re.MULTILINE):
            alias = m.group(2) or m.group(1).split(".")[-1]
            imports.append(CompletionItem(alias, CompletionKind.VARIABLE))

        for m in re.finditer(r"^from\s+[\w.]+\s+import\s+(.+?)$", text, re.MULTILINE):
            names_str = m.group(1).strip("()")
            for name_part in names_str.split(","):
                name_part = name_part.strip()
                if not name_part or name_part.startswith("#"):
                    continue
                parts = name_part.split(" as ")
                alias = parts[1].strip() if len(parts) > 1 else parts[0].strip()
                if alias:
                    imports.append(CompletionItem(alias, CompletionKind.VARIABLE))

        return imports

    def _enrich_imports(self, imports, buffer_text, file_path):
        """Enrich imported symbols with kind, signature, and docstring from source files."""
        # Build map: module_path → list of imported names
        module_names = {}
        for m in re.finditer(r"^from\s+([\w.]+)\s+import\s+(.+?)$", buffer_text, re.MULTILINE):
            module_path = m.group(1)
            names_str = m.group(2).strip("()")
            for name_part in names_str.split(","):
                name_part = name_part.strip()
                if not name_part or name_part.startswith("#"):
                    continue
                parts = name_part.split(" as ")
                original = parts[0].strip()
                alias = parts[1].strip() if len(parts) > 1 else original
                if alias:
                    module_names.setdefault(module_path, []).append((original, alias))

        # Resolve each module and enrich matching imports
        import_by_alias = {item.name: item for item in imports}
        for module_path, names in module_names.items():
            rel_path = module_path.replace(".", "/")
            py_file = self._find_module_file(rel_path, file_path)
            if not py_file:
                continue
            symbols = self._parse_symbols(py_file)
            sym_map = {item.name: item for item in symbols}
            for original, alias in names:
                if original in sym_map and alias in import_by_alias:
                    src = sym_map[original]
                    item = import_by_alias[alias]
                    item.kind = src.kind
                    item.signature = src.signature
                    item.docstring = src.docstring

    def _get_symbols(self, text):
        """Extract local symbol definitions from Python code."""
        symbols = []

        for m in re.finditer(r"^class\s+(\w+)[^:]*:", text, re.MULTILINE):
            doc = self._extract_docstring_at(text, m.end())
            init_sig = self._extract_init_signature(text, m.group(1))
            symbols.append(CompletionItem(m.group(1), CompletionKind.CLASS, signature=init_sig, docstring=doc))
        for m in re.finditer(r"^\s*def\s+(\w+)\s*(\([^)]*\))\s*(?:->\s*(.+?))?\s*:", text, re.MULTILINE):
            sig = f"{m.group(1)}{m.group(2)}"
            if m.group(3):
                sig += f" → {m.group(3).strip()}"
            doc = self._extract_docstring_at(text, m.end())
            symbols.append(CompletionItem(m.group(1), CompletionKind.FUNCTION, sig, doc))
        for m in re.finditer(r"^(\w+)\s*=", text, re.MULTILINE):
            name = m.group(1)
            if name not in ("_", "__all__", "__version__"):
                symbols.append(CompletionItem(name, CompletionKind.VARIABLE))

        return symbols

    @staticmethod
    def _normalize_multiline_defs(text):
        """Join multi-line def statements into single lines for signature extraction."""
        lines = text.splitlines()
        result = []
        accumulator = None
        paren_depth = 0
        for line in lines:
            if accumulator is not None:
                accumulator += " " + line.strip()
                paren_depth += line.count("(") - line.count(")")
                if paren_depth <= 0:
                    result.append(accumulator)
                    accumulator = None
                    paren_depth = 0
            elif re.match(r"\s*def\s+\w+\s*\(", line):
                paren_depth = line.count("(") - line.count(")")
                if paren_depth <= 0:
                    result.append(line)
                    paren_depth = 0
                else:
                    accumulator = line
            else:
                result.append(line)
        if accumulator:
            result.append(accumulator)
        return "\n".join(result)

    def _parse_symbols(self, py_file):
        """Parse a Python file and extract top-level symbol names.

        For __init__.py files, also follows relative re-exports
        (e.g. 'from .submodule import Name') to resolve symbols from sibling files.
        """
        symbols = {}
        try:
            text = py_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return []

        text = self._normalize_multiline_defs(text)
        lines = text.splitlines()

        # Collect relative re-exports to resolve later (only for __init__.py)
        reexports = {}  # name → relative_module (e.g. "db_item_handler")
        is_init = py_file.name == "__init__.py"

        for i, line in enumerate(lines):
            m = re.match(r"^class\s+(\w+)", line)
            if m:
                doc = self._peek_docstring(lines, i)
                init_sig = self._extract_init_signature(text, m.group(1))
                symbols[m.group(1)] = (init_sig, CompletionKind.CLASS, doc)
                continue
            m = re.match(r"^def\s+(\w+)\s*(\([^)]*\))\s*(?:->\s*(.+?))?\s*:", line)
            if m:
                sig = f"{m.group(1)}{m.group(2)}"
                if m.group(3):
                    sig += f" → {m.group(3).strip()}"
                doc = self._peek_docstring(lines, i)
                symbols[m.group(1)] = (sig, CompletionKind.FUNCTION, doc)
                continue
            m = re.match(r"^def\s+(\w+)", line)
            if m:
                symbols[m.group(1)] = ("", CompletionKind.FUNCTION, "")
                continue
            m = re.match(r"^([A-Za-z_]\w*)\s*=", line)
            if m and not m.group(1).startswith("_"):
                symbols[m.group(1)] = ("", CompletionKind.PROPERTY, "")
                continue
            # Track relative re-exports in __init__.py
            if is_init:
                m = re.match(r"^from\s+\.(\w+)\s+import\s+(.+?)$", line)
                if m:
                    rel_module = m.group(1)
                    for name_part in m.group(2).split(","):
                        name_part = name_part.strip()
                        if name_part and not name_part.startswith("#"):
                            original = name_part.split(" as ")[0].strip()
                            if original and original not in symbols:
                                reexports[original] = rel_module

        # Resolve re-exported symbols from sibling files
        if reexports:
            pkg_dir = py_file.parent
            resolved_modules = {}  # cache: rel_module → symbols dict
            for name, rel_module in reexports.items():
                if name in symbols:
                    continue
                if rel_module not in resolved_modules:
                    sibling = pkg_dir / f"{rel_module}.py"
                    if sibling.is_file():
                        resolved_modules[rel_module] = {
                            item.name: (item.signature, item.kind, item.docstring) for item in self._parse_symbols(sibling)
                        }
                    else:
                        resolved_modules[rel_module] = {}
                if name in resolved_modules.get(rel_module, {}):
                    symbols[name] = resolved_modules[rel_module][name]

        return sorted(
            [CompletionItem(name, kind, sig, doc) for name, (sig, kind, doc) in symbols.items()],
            key=lambda x: x.name,
        )

    def _find_enclosing_class(self, buffer_text, cursor_offset):
        """Find the class name that encloses the given cursor offset."""
        text_before = buffer_text[:cursor_offset]
        lines = text_before.split("\n")
        if not lines:
            return None
        current_line = lines[-1]
        if current_line.strip():
            current_indent = len(current_line) - len(current_line.lstrip())
        else:
            current_indent = float("inf")

        for i in range(len(lines) - 1, -1, -1):
            line = lines[i]
            stripped = line.lstrip()
            if re.match(r"class\s+\w+", stripped):
                class_indent = len(line) - len(stripped)
                if class_indent < current_indent:
                    m = re.match(r"class\s+(\w+)", stripped)
                    if m:
                        return m.group(1)
        return None

    def _extract_self_completions(self, text, class_name):
        """Extract all members accessible via self. for a class."""
        members = {}
        text = self._normalize_multiline_defs(text)
        class_match = re.search(rf"^class\s+{re.escape(class_name)}\b[^:]*:", text, re.MULTILINE)
        if not class_match:
            return []
        lines = text[class_match.end() :].split("\n")
        base_indent = None
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip())
            if base_indent is None:
                base_indent = indent
                if indent == 0:
                    break
            if indent < base_indent:
                break
            stripped = line.strip()
            # Methods (include private, skip dunder)
            m = re.match(r"def\s+(\w+)\s*(\([^)]*\))\s*(?:->\s*(.+?))?\s*:", stripped)
            if m:
                name = m.group(1)
                if not (name.startswith("__") and name.endswith("__")):
                    sig = f"{name}{m.group(2)}"
                    if m.group(3):
                        sig += f" → {m.group(3).strip()}"
                    doc = self._peek_docstring(lines, i)
                    members[name] = (sig, CompletionKind.FUNCTION, doc)
                continue
            m = re.match(r"def\s+(\w+)", stripped)
            if m:
                name = m.group(1)
                if not (name.startswith("__") and name.endswith("__")):
                    members[name] = ("", CompletionKind.FUNCTION, "")
                continue
            # Class-level attributes
            if indent == base_indent:
                m = re.match(r"class\s+(\w+)", stripped)
                if m:
                    members[m.group(1)] = ("", CompletionKind.CLASS, "")
                    continue
                m = re.match(r"([A-Za-z_]\w*)\s*[:=]", stripped)
                if m:
                    members[m.group(1)] = ("", CompletionKind.PROPERTY, "")
                    continue
            # Instance attributes (self.xxx = ...)
            m = re.match(r"self\.(\w+)\s*=", stripped)
            if m:
                name = m.group(1)
                if name not in members:
                    members[name] = ("", CompletionKind.PROPERTY, "")
        return sorted(
            [CompletionItem(name, kind, sig, doc) for name, (sig, kind, doc) in members.items()],
            key=lambda x: x.name,
        )

    def _resolve_variable_type(self, text, var_name):
        """Resolve the class name from a variable's assignment or type annotation.

        Handles patterns like:
        - var = ClassName(...)
        - var = module.ClassName(...)
        - var: ClassName = ...
        """
        # var = ClassName(...) or var = module.ClassName(...)
        m = re.search(rf"^\s*{re.escape(var_name)}\s*=\s*([\w.]+)\(", text, re.MULTILINE)
        if m:
            return m.group(1).split(".")[-1]
        # var: ClassName = ...
        m = re.search(rf"^\s*{re.escape(var_name)}\s*:\s*([\w.]+)\s*=", text, re.MULTILINE)
        if m:
            return m.group(1).split(".")[-1]
        return None

    def _resolve_chain_in_text(self, text, parts):
        """Walk a chain of class names in text and return members of the final class."""
        current_text = text
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                # Try nested class first
                members = self._extract_class_members(current_text, part)
                if members:
                    return members
                # If part is an attribute (enum member, class var) inside a class body,
                # return methods from that class body. Only applies when we've drilled
                # into a class (i > 0), not at top-level buffer scope.
                if i > 0 and re.search(rf"^\s*{re.escape(part)}\s*=", current_text, re.MULTILINE):
                    return self._extract_methods_from_body(current_text)
                return []
            body = self._get_class_body_text(current_text, part)
            if not body:
                return []
            current_text = body
        return []

    def _extract_methods_from_body(self, body_text):
        """Extract public methods from a class body (for attribute/enum member completions)."""
        members = {}
        body_text = self._normalize_multiline_defs(body_text)
        lines = body_text.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            m = re.match(r"def\s+(\w+)\s*(\([^)]*\))\s*(?:->\s*(.+?))?\s*:", stripped)
            if m and not m.group(1).startswith("_"):
                sig = f"{m.group(1)}{m.group(2)}"
                if m.group(3):
                    sig += f" → {m.group(3).strip()}"
                doc = self._peek_docstring(lines, i)
                members[m.group(1)] = (sig, CompletionKind.FUNCTION, doc)
                continue
            m = re.match(r"def\s+(\w+)", stripped)
            if m and not m.group(1).startswith("_"):
                members[m.group(1)] = ("", CompletionKind.FUNCTION, "")
        return sorted(
            [CompletionItem(name, kind, sig, doc) for name, (sig, kind, doc) in members.items()],
            key=lambda x: x.name,
        )

    def _get_class_body_text(self, text, class_name):
        """Extract the body of a class as text, including nested definitions."""
        class_match = re.search(rf"^class\s+{re.escape(class_name)}\b[^:]*:", text, re.MULTILINE)
        if not class_match:
            return None
        lines = text[class_match.end() :].split("\n")
        body_lines = []
        base_indent = None
        for line in lines:
            if not line.strip():
                body_lines.append(line)
                continue
            indent = len(line) - len(line.lstrip())
            if base_indent is None:
                base_indent = indent
                if indent == 0:
                    break
            if indent < base_indent:
                break
            body_lines.append(line)
        return "\n".join(body_lines)

    def _find_venv_site_packages(self, file_path):
        """Find virtualenv site-packages directories for the project."""
        venv_names = [".venv", "venv"]
        current = Path(file_path).parent
        while current != current.parent:
            for venv_name in venv_names:
                venv_path = current / venv_name
                if venv_path.is_dir():
                    for sp in glob_module.glob(str(venv_path / "lib" / "python*" / "site-packages")):
                        if Path(sp).is_dir():
                            return [Path(sp)]
            if (current / ".git").exists():
                break
            current = current.parent
        return []

    def _find_module_file(self, rel_path, file_path):
        """Find the .py file for a module, searching project dirs then venv."""
        current = Path(file_path).parent
        searched = set()
        while current != current.parent:
            for root in (current, current / "src"):
                if root in searched or not root.is_dir():
                    continue
                searched.add(root)
                py_file = root / f"{rel_path}.py"
                if not py_file.is_file():
                    py_file = root / rel_path / "__init__.py"
                if py_file.is_file():
                    return py_file
            if (current / ".git").exists():
                break
            current = current.parent
        # Fallback: search venv site-packages
        for sp in self._find_venv_site_packages(file_path):
            py_file = sp / f"{rel_path}.py"
            if not py_file.is_file():
                py_file = sp / rel_path / "__init__.py"
            if py_file.is_file():
                return py_file
        return None

    def _read_module_text(self, module_path, file_path):
        """Read the source text of a Python module file."""
        rel_path = module_path.replace(".", "/")
        py_file = self._find_module_file(rel_path, file_path)
        if py_file:
            try:
                return py_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                return None
        return None

    def _follow_reexport(self, module_text, class_name, module_path, file_path):
        """Follow re-exports in __init__.py (e.g., from .sub import ClassName)."""
        pattern = rf"^from\s+\.(\w+)\s+import\s+.*\b{re.escape(class_name)}\b"
        m = re.search(pattern, module_text, re.MULTILINE)
        if not m:
            return None
        sub_path = f"{module_path}.{m.group(1)}"
        return self._read_module_text(sub_path, file_path)

    def _extract_class_members(self, text, class_name):
        """Extract public methods and class-level attributes from a class."""
        members = {}
        text = self._normalize_multiline_defs(text)
        class_match = re.search(rf"^class\s+{re.escape(class_name)}\b[^:]*:", text, re.MULTILINE)
        if not class_match:
            return []
        lines = text[class_match.end() :].split("\n")
        base_indent = None
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip())
            if base_indent is None:
                base_indent = indent
                if indent == 0:
                    break
            if indent < base_indent:
                break
            stripped = line.strip()
            m = re.match(r"def\s+(\w+)\s*(\([^)]*\))\s*(?:->\s*(.+?))?\s*:", stripped)
            if m and not m.group(1).startswith("_"):
                sig = f"{m.group(1)}{m.group(2)}"
                if m.group(3):
                    sig += f" → {m.group(3).strip()}"
                doc = self._peek_docstring(lines, i)
                members[m.group(1)] = (sig, CompletionKind.FUNCTION, doc)
                continue
            m = re.match(r"def\s+(\w+)", stripped)
            if m and not m.group(1).startswith("_"):
                members[m.group(1)] = ("", CompletionKind.FUNCTION, "")
                continue
            if indent == base_indent:
                m = re.match(r"class\s+(\w+)", stripped)
                if m:
                    members[m.group(1)] = ("", CompletionKind.CLASS, "")
                    continue
                m = re.match(r"([A-Za-z]\w*)\s*=", stripped)
                if m:
                    members[m.group(1)] = ("", CompletionKind.PROPERTY, "")
        return sorted(
            [CompletionItem(name, kind, sig, doc) for name, (sig, kind, doc) in members.items()],
            key=lambda x: x.name,
        )
