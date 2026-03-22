"""
Python completion provider for Zen IDE autocomplete.

Provides Python-specific completions: keywords, builtins, imports, symbols,
module path resolution, and dot-access member completions.

Uses tree-sitter for AST-based symbol extraction (functions, classes,
variables, imports, class members, signatures).  Filesystem-based module
resolution and venv introspection remain unchanged.
"""

import glob as glob_module
import keyword
import re
from pathlib import Path

from editor.autocomplete import CompletionItem, CompletionKind
from editor.autocomplete.tree_sitter_provider import (
    _parse,
    py_extract_definitions,
    py_extract_file_symbols,
    py_extract_imports,
    py_extract_self_members,
    py_find_enclosing_class,
    py_find_function_signature,
    py_find_method_signature,
    py_resolve_chain,
    py_resolve_variable_type,
)

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

        source, tree = _parse(buffer_text, "python")
        if tree is not None:
            imports = py_extract_imports(source, tree)
            if file_path:
                self._enrich_imports(imports, source, tree, file_path)
            completions.extend(imports)
            completions.extend(py_extract_definitions(source, tree))
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

        source, tree = _parse(buffer_text, "python")
        sig = self._resolve_function_signature(
            func_chain, file_path, buffer_text, source, tree, cursor_offset=cursor_iter.get_offset()
        )
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

    def _resolve_function_signature(self, func_chain, file_path, buffer_text, source=None, tree=None, *, cursor_offset=None):
        """Resolve a function/method call chain to its signature string."""
        if source is None or tree is None:
            source, tree = _parse(buffer_text, "python")
        if tree is None:
            return None

        parts = func_chain.split(".")

        if len(parts) == 1:
            return self._find_local_or_imported_signature(parts[0], file_path, source, tree)

        method_name = parts[-1]
        first = parts[0]

        # Handle self/cls
        if first in ("self", "cls") and cursor_offset is not None:
            byte_offset = len(buffer_text[:cursor_offset].encode("utf-8"))
            class_name = py_find_enclosing_class(source, tree, byte_offset)
            if class_name:
                return py_find_method_signature(source, tree, class_name, method_name)
            return None

        # Try resolving variable type
        resolved_class = py_resolve_variable_type(source, tree, first)
        if resolved_class:
            sig = py_find_method_signature(source, tree, resolved_class, method_name)
            if sig:
                return sig
            sig = self._find_method_in_imported_class(resolved_class, method_name, source, tree, file_path)
            if sig:
                return sig

        # Try as a direct class reference
        sig = py_find_method_signature(source, tree, first, method_name)
        if sig:
            return sig

        # Try imported class.method
        sig = self._find_method_in_imported_class(first, method_name, source, tree, file_path)
        if sig:
            return sig

        return None

    def _find_local_or_imported_signature(self, func_name, file_path, source, tree):
        """Find function signature in local definitions or imports."""
        sig = py_find_function_signature(source, tree, func_name)
        if sig:
            return sig

        if not file_path:
            return None

        # Search imports for the function name
        module_info = self._find_import_module(source, tree, func_name)
        if module_info:
            module_path, original_name = module_info
            module_text = self._read_module_text(module_path, file_path)
            if module_text:
                m_source, m_tree = _parse(module_text, "python")
                if m_tree:
                    sig = py_find_function_signature(m_source, m_tree, original_name)
                    if sig and original_name != func_name:
                        sig = sig.replace(original_name, func_name, 1)
                    return sig
        return None

    def _find_method_in_imported_class(self, class_name, method_name, source, tree, file_path):
        """Find a method signature in an imported class."""
        if not file_path:
            return None

        module_info = self._find_import_module(source, tree, class_name)
        if not module_info:
            return None

        module_path, original_name = module_info
        module_text = self._read_module_text(module_path, file_path)
        if not module_text:
            return None

        m_source, m_tree = _parse(module_text, "python")
        if m_tree:
            sig = py_find_method_signature(m_source, m_tree, original_name, method_name)
            if sig:
                return sig
            # Follow re-exports
            sub_text = self._follow_reexport_ts(m_source, m_tree, original_name, module_path, file_path)
            if sub_text:
                s_source, s_tree = _parse(sub_text, "python")
                if s_tree:
                    sig = py_find_method_signature(s_source, s_tree, original_name, method_name)
                    if sig:
                        return sig
        return None

    @staticmethod
    def _find_import_module(source, tree, name):
        """Find the module path and original name for an imported symbol.

        Returns (module_path, original_name) or None.
        """
        root = tree.root_node
        from editor.autocomplete.tree_sitter_provider import _node_text

        for child in root.children:
            if child.type == "import_from_statement":
                module_node = child.child_by_field_name("module_name")
                if not module_node:
                    continue
                module_path = _node_text(source, module_node)
                if module_path.startswith("."):
                    continue
                for imp in child.children:
                    if imp.type == "dotted_name" and imp != module_node:
                        if _node_text(source, imp) == name:
                            return module_path, name
                    elif imp.type == "aliased_import":
                        alias = imp.child_by_field_name("alias")
                        orig = imp.child_by_field_name("name")
                        if alias and _node_text(source, alias) == name:
                            return module_path, _node_text(source, orig) if orig else name
                        if not alias and orig and _node_text(source, orig) == name:
                            return module_path, name
            # Handle try/except blocks containing imports
            elif child.type == "try_statement":
                for body_child in child.children:
                    block = body_child if body_child.type == "block" else None
                    if body_child.type == "except_clause":
                        for sub in body_child.children:
                            if sub.type == "block":
                                block = sub
                    if block:
                        for stmt in block.children:
                            if stmt.type == "import_from_statement":
                                result = PythonCompletionProvider._find_import_in_stmt(source, stmt, name)
                                if result:
                                    return result
        return None

    @staticmethod
    def _find_import_in_stmt(source, stmt, name):
        """Check a single import_from_statement for an imported name."""
        from editor.autocomplete.tree_sitter_provider import _node_text

        module_node = stmt.child_by_field_name("module_name")
        if not module_node:
            return None
        module_path = _node_text(source, module_node)
        if module_path.startswith("."):
            return None
        for imp in stmt.children:
            if imp.type == "dotted_name" and imp != module_node:
                if _node_text(source, imp) == name:
                    return module_path, name
            elif imp.type == "aliased_import":
                alias = imp.child_by_field_name("alias")
                orig = imp.child_by_field_name("name")
                if alias and _node_text(source, alias) == name:
                    return module_path, _node_text(source, orig) if orig else name
                if not alias and orig and _node_text(source, orig) == name:
                    return module_path, name
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

        source, tree = _parse(buffer_text, "python")
        if tree is None:
            return []

        # Handle self/cls: resolve to enclosing class
        if first in ("self", "cls") and cursor_offset is not None:
            byte_offset = len(buffer_text[:cursor_offset].encode("utf-8"))
            class_name = py_find_enclosing_class(source, tree, byte_offset)
            if class_name:
                if len(parts) == 1:
                    return py_extract_self_members(source, tree, class_name)
                else:
                    chain = [class_name] + parts[1:]
                    return py_resolve_chain(source, tree, chain)
            return []

        # Try to resolve variable type from assignment
        resolved_class = py_resolve_variable_type(source, tree, first)
        if resolved_class and resolved_class != first:
            resolved_parts = [resolved_class] + parts[1:]
            local = py_resolve_chain(source, tree, resolved_parts)
            if local:
                return local
            first = resolved_class
            parts = resolved_parts

        # Check local classes first
        local = py_resolve_chain(source, tree, parts)
        if local:
            return local

        # Find module path from imports
        module_info = self._find_import_module(source, tree, first)
        if not module_info:
            return []

        module_path, original_name = module_info
        module_text = self._read_module_text(module_path, file_path)
        if not module_text:
            return []

        m_source, m_tree = _parse(module_text, "python")
        if m_tree is None:
            return []

        chain = [original_name] + parts[1:]
        result = py_resolve_chain(m_source, m_tree, chain)
        if result:
            return result

        # Follow re-exports
        sub_text = self._follow_reexport_ts(m_source, m_tree, original_name, module_path, file_path)
        if sub_text:
            s_source, s_tree = _parse(sub_text, "python")
            if s_tree:
                return py_resolve_chain(s_source, s_tree, chain)
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

    def _enrich_imports(self, imports, source, tree, file_path):
        """Enrich imported symbols with kind, signature, and docstring from source files."""
        from editor.autocomplete.tree_sitter_provider import _node_text

        # Build map: module_path → list of (original, alias)
        module_names: dict[str, list[tuple[str, str]]] = {}
        root = tree.root_node
        for child in root.children:
            if child.type != "import_from_statement":
                continue
            module_node = child.child_by_field_name("module_name")
            if not module_node:
                continue
            mod_path = _node_text(source, module_node)
            if mod_path.startswith("."):
                continue
            for imp in child.children:
                if imp.type == "dotted_name" and imp != module_node:
                    name = _node_text(source, imp)
                    module_names.setdefault(mod_path, []).append((name, name))
                elif imp.type == "aliased_import":
                    alias_n = imp.child_by_field_name("alias")
                    orig_n = imp.child_by_field_name("name")
                    orig = _node_text(source, orig_n) if orig_n else ""
                    alias = _node_text(source, alias_n) if alias_n else orig
                    if alias:
                        module_names.setdefault(mod_path, []).append((orig, alias))

        import_by_alias = {item.name: item for item in imports}
        for mod_path, names in module_names.items():
            rel_path = mod_path.replace(".", "/")
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

    def _parse_symbols(self, py_file):
        """Parse a Python file and extract top-level symbol names using tree-sitter.

        For __init__.py files, also follows relative re-exports.
        """
        try:
            text = py_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return []

        m_source, m_tree = _parse(text, "python")
        if m_tree is None:
            return []

        result = py_extract_file_symbols(m_source, m_tree)
        if isinstance(result, tuple):
            symbols, reexports = result
        else:
            return result

        # Resolve re-exported symbols from sibling files
        if reexports:
            pkg_dir = py_file.parent
            resolved_modules: dict[str, dict] = {}
            for name, rel_module in reexports.items():
                if name in symbols:
                    continue
                if rel_module not in resolved_modules:
                    sibling = pkg_dir / f"{rel_module}.py"
                    if sibling.is_file():
                        resolved_modules[rel_module] = {item.name: item for item in self._parse_symbols(sibling)}
                    else:
                        resolved_modules[rel_module] = {}
                if name in resolved_modules.get(rel_module, {}):
                    symbols[name] = resolved_modules[rel_module][name]

        return sorted(symbols.values(), key=lambda x: x.name)

    def _follow_reexport_ts(self, source, tree, class_name, module_path, file_path):
        """Follow re-exports in __init__.py using tree-sitter."""
        from editor.autocomplete.tree_sitter_provider import _node_text

        root = tree.root_node
        for child in root.children:
            if child.type != "import_from_statement":
                continue
            module_node = child.child_by_field_name("module_name")
            if not module_node:
                continue
            mod_text = _node_text(source, module_node)
            if not mod_text.startswith(".") or mod_text.startswith(".."):
                continue
            # Check if class_name is among the imported names
            for imp in child.children:
                name = None
                if imp.type == "dotted_name" and imp != module_node:
                    name = _node_text(source, imp)
                elif imp.type == "aliased_import":
                    orig = imp.child_by_field_name("name")
                    if orig:
                        name = _node_text(source, orig)
                if name == class_name:
                    rel_module = mod_text.lstrip(".")
                    sub_path = f"{module_path}.{rel_module}"
                    return self._read_module_text(sub_path, file_path)
        return None

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
