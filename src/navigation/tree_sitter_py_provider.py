"""
Python navigation provider using Tree-sitter AST queries.

Replaces regex-based symbol finding and import parsing with
structural AST queries for accurate, scope-aware navigation.
"""

from typing import Dict, List, Optional

from .navigation_provider import NavigationProvider


class TreeSitterPyProvider(NavigationProvider):
    """Python code navigation backed by Tree-sitter."""

    _def_query = None
    _imp_query = None

    def supports_language(self, file_ext: str) -> bool:
        return file_ext in (".py", ".pyw", ".pyi")

    def _ensure_queries(self):
        if self._def_query is None:
            from .tree_sitter_core import TreeSitterCore
            from .tree_sitter_queries import PY_DEFINITIONS, PY_IMPORTS

            self._def_query = TreeSitterCore.query("python", PY_DEFINITIONS)
            self._imp_query = TreeSitterCore.query("python", PY_IMPORTS)

    @staticmethod
    def _walk(node):
        """Yield all descendant nodes depth-first."""
        yield node
        for child in node.children:
            yield from TreeSitterPyProvider._walk(child)

    @staticmethod
    def _node_text(node, source_bytes: bytes) -> Optional[str]:
        """Return decoded node text, reconstructing it from source bytes if needed."""
        if node is None:
            return None

        text = getattr(node, "text", None)
        if isinstance(text, bytes):
            return text.decode("utf-8")
        if isinstance(text, str):
            return text

        start_byte = getattr(node, "start_byte", None)
        end_byte = getattr(node, "end_byte", None)
        if isinstance(start_byte, int) and isinstance(end_byte, int):
            return source_bytes[start_byte:end_byte].decode("utf-8")

        return None

    def find_symbol_in_content(self, content: str, symbol: str, file_ext: str = ".py") -> Optional[int]:
        """Find a symbol definition in Python source. Returns 1-based line number or None."""
        from .tree_sitter_core import TreeSitterCore

        self._ensure_queries()
        source_bytes = content.encode("utf-8")
        tree = TreeSitterCore.parse(source_bytes, "python")
        if tree is None:
            return None

        matches = TreeSitterCore.run_query(tree, self._def_query)
        seen_lines = set()
        for _, captures in matches:
            for name_node in captures.get("name", []):
                if self._node_text(name_node, source_bytes) == symbol:
                    line = name_node.start_point[0] + 1
                    if line not in seen_lines:
                        return line
                    seen_lines.add(line)
        return None

    def parse_imports(self, content: str, file_ext: str = ".py") -> Dict[str, str]:
        """Parse Python imports into {alias_or_name: module_path} mapping."""
        from .tree_sitter_core import TreeSitterCore

        self._ensure_queries()
        source_bytes = content.encode("utf-8")
        tree = TreeSitterCore.parse(source_bytes, "python")
        if tree is None:
            return {}

        result = {}
        matches = TreeSitterCore.run_query(tree, self._imp_query)
        for _, captures in matches:
            module_nodes = captures.get("module", [])
            name_nodes = captures.get("name", [])
            alias_nodes = captures.get("alias", [])

            if not module_nodes:
                continue

            module_text = self._node_text(module_nodes[0], source_bytes)
            if not module_text:
                continue

            if name_nodes:
                # from X import Y / from X import Y as Z
                imported_name = self._node_text(name_nodes[0], source_bytes)
                if not imported_name:
                    continue
                alias = self._node_text(alias_nodes[0], source_bytes) if alias_nodes else imported_name
                if not alias:
                    continue
                result[alias] = f"{module_text}.{imported_name}"
            elif alias_nodes:
                # import X as Y
                alias = self._node_text(alias_nodes[0], source_bytes)
                if not alias:
                    continue
                result[alias] = module_text
            else:
                # import X
                short = module_text.split(".")[-1]
                result[short] = module_text
        return result

    def find_import_source(self, content: str, symbol: str) -> Optional[str]:
        """Find the raw module reference where a symbol is imported via ``from ... import``.

        For ``from .xxx import symbol``, returns ``".xxx"``.
        For ``from abc.def import symbol``, returns ``"abc.def"``.
        Returns ``None`` if the symbol is not found in any ``from ... import`` statement.
        """
        from .tree_sitter_core import TreeSitterCore

        self._ensure_queries()
        source_bytes = content.encode("utf-8")
        tree = TreeSitterCore.parse(source_bytes, "python")
        if tree is None:
            return None

        matches = TreeSitterCore.run_query(tree, self._imp_query)
        for _, captures in matches:
            module_nodes = captures.get("module", [])
            name_nodes = captures.get("name", [])

            if not module_nodes or not name_nodes:
                continue

            imported_name = self._node_text(name_nodes[0], source_bytes)
            if imported_name == symbol:
                return self._node_text(module_nodes[0], source_bytes)

        return None

    def find_import_line(self, content: str, symbol: str) -> Optional[int]:
        """Find the 1-based line number where *symbol* appears in a ``from ... import`` statement."""
        from .tree_sitter_core import TreeSitterCore

        self._ensure_queries()
        source_bytes = content.encode("utf-8")
        tree = TreeSitterCore.parse(source_bytes, "python")
        if tree is None:
            return None

        matches = TreeSitterCore.run_query(tree, self._imp_query)
        for _, captures in matches:
            name_nodes = captures.get("name", [])
            alias_nodes = captures.get("alias", [])
            node_nodes = captures.get("node", [])

            if not name_nodes:
                continue

            imported_name = self._node_text(name_nodes[0], source_bytes)
            if not imported_name:
                continue
            alias = self._node_text(alias_nodes[0], source_bytes) if alias_nodes else imported_name

            if imported_name == symbol or alias == symbol:
                if node_nodes:
                    return node_nodes[0].start_point[0] + 1
                return name_nodes[0].start_point[0] + 1

        return None

    def find_variable_class(self, content: str, var_name: str) -> Optional[str]:
        """Find the class a variable is instantiated from.

        Looks for ``var = ClassName(...)`` or ``var = module.ClassName(...)``.
        Returns the class name (possibly qualified like ``"vault.Client"``), or ``None``.
        """
        from .tree_sitter_core import TreeSitterCore

        source_bytes = content.encode("utf-8")
        tree = TreeSitterCore.parse(source_bytes, "python")
        if tree is None:
            return None

        for node in self._walk(tree.root_node):
            if node.type != "assignment":
                continue

            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if left is None or right is None:
                continue

            if left.type != "identifier" or self._node_text(left, source_bytes) != var_name:
                continue

            if right.type != "call":
                continue

            func = right.child_by_field_name("function")
            if func is None:
                continue

            func_text = self._node_text(func, source_bytes)
            if not func_text:
                continue
            last_part = func_text.rsplit(".", 1)[-1]
            if last_part[:1].isupper():
                return func_text

        return None

    def find_self_attr_class(self, content: str, attr_name: str) -> Optional[str]:
        """Find the class a ``self`` attribute is instantiated from.

        Looks for ``self.attr = ClassName(...)`` or ``self.attr = module.ClassName(...)``.
        Returns the class name (possibly qualified), or ``None``.
        """
        from .tree_sitter_core import TreeSitterCore

        source_bytes = content.encode("utf-8")
        tree = TreeSitterCore.parse(source_bytes, "python")
        if tree is None:
            return None

        for node in self._walk(tree.root_node):
            if node.type != "assignment":
                continue

            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if left is None or right is None:
                continue

            if left.type != "attribute":
                continue
            obj = left.child_by_field_name("object")
            attr = left.child_by_field_name("attribute")
            if obj is None or attr is None:
                continue
            if obj.type != "identifier" or self._node_text(obj, source_bytes) != "self":
                continue
            if self._node_text(attr, source_bytes) != attr_name:
                continue

            if right.type != "call":
                continue

            func = right.child_by_field_name("function")
            if func is None:
                continue

            func_text = self._node_text(func, source_bytes)
            if not func_text:
                continue
            last_part = func_text.rsplit(".", 1)[-1]
            if last_part[:1].isupper():
                return func_text

        return None

    def find_param_declaration(self, content: str, word: str, click_line: int) -> Optional[int]:
        """Find the line where *word* is declared as a function parameter.

        Scans the AST for the innermost ``function_definition`` enclosing
        *click_line* (1-based), then checks its parameters for *word*.
        Returns the 1-based line of the parameter, or ``None``.
        """
        from .tree_sitter_core import TreeSitterCore

        source_bytes = content.encode("utf-8")
        tree = TreeSitterCore.parse(source_bytes, "python")
        if tree is None:
            return None

        click_line_0 = click_line - 1

        # Find innermost enclosing function_definition
        enclosing = None
        for node in self._walk(tree.root_node):
            if node.type == "function_definition":
                if node.start_point[0] <= click_line_0 <= node.end_point[0]:
                    enclosing = node

        if enclosing is None:
            return None

        params = enclosing.child_by_field_name("parameters")
        if params is None:
            return None

        for param_node in self._extract_param_names(params):
            if self._node_text(param_node, source_bytes) == word:
                param_line = param_node.start_point[0] + 1
                if param_line == click_line:
                    return None
                return param_line

        return None

    @staticmethod
    def _extract_param_names(params_node) -> List:
        """Extract parameter name nodes from a ``parameters`` AST node."""
        result = []
        for child in params_node.children:
            if child.type == "identifier":
                result.append(child)
            elif child.type in (
                "typed_parameter",
                "typed_default_parameter",
                "default_parameter",
            ):
                for sub in child.children:
                    if sub.type == "identifier":
                        result.append(sub)
                        break
            elif child.type in ("list_splat_pattern", "dictionary_splat_pattern"):
                for sub in child.children:
                    if sub.type == "identifier":
                        result.append(sub)
                        break
        return result

    def find_constructor_class(self, line_text: str, method_name: str) -> Optional[str]:
        """Find a class name in ``ClassName(...).method`` on a single line.

        Returns the class name if found, or ``None``.
        """
        from .tree_sitter_core import TreeSitterCore

        source_bytes = line_text.encode("utf-8")
        tree = TreeSitterCore.parse(source_bytes, "python")
        if tree is None:
            return None

        for node in self._walk(tree.root_node):
            if node.type != "attribute":
                continue

            attr = node.child_by_field_name("attribute")
            obj = node.child_by_field_name("object")
            if attr is None or obj is None:
                continue
            if self._node_text(attr, source_bytes) != method_name:
                continue
            if obj.type != "call":
                continue

            func = obj.child_by_field_name("function")
            if func is None:
                continue

            func_text = self._node_text(func, source_bytes)
            if not func_text:
                continue
            last_part = func_text.rsplit(".", 1)[-1]
            if last_part[:1].isupper():
                return func_text

        return None
