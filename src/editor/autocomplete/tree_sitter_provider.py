"""
Tree-sitter based completion extraction for Zen IDE.

Provides AST-based extraction functions used by the language-specific
completion providers (Python, JS/TS).  All tree-sitter imports are
deferred to the functions that use them to preserve startup performance.
"""

from editor.autocomplete.autocomplete import CompletionItem, CompletionKind

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node_text(source: bytes, node) -> str:
    """Extract UTF-8 text spanned by a tree-sitter node."""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _top_level_children(root, type_name: str):
    """Yield direct children of *root* that match *type_name*."""
    for child in root.children:
        if child.type == type_name:
            yield child
        elif child.type == "decorated_definition":
            for sub in child.children:
                if sub.type == type_name:
                    yield sub


def _parse(source_text: str, lang: str):
    """Parse source text and return (source_bytes, tree) or (None, None)."""
    from navigation.tree_sitter_core import TreeSitterCore

    source_bytes = source_text.encode("utf-8")
    tree = TreeSitterCore.parse(source_bytes, lang)
    if tree is None:
        return None, None
    return source_bytes, tree


# ---------------------------------------------------------------------------
# Python — signature & docstring extraction
# ---------------------------------------------------------------------------


def py_extract_signature(source: bytes, func_node) -> str:
    """Build a human-readable signature from a ``function_definition`` node."""
    name_node = func_node.child_by_field_name("name")
    params_node = func_node.child_by_field_name("parameters")
    return_type = func_node.child_by_field_name("return_type")

    name = _node_text(source, name_node) if name_node else "?"
    params = _node_text(source, params_node) if params_node else "()"
    sig = f"{name}{params}"
    if return_type:
        sig += f" → {_node_text(source, return_type)}"
    return sig


def py_extract_docstring(source: bytes, node) -> str:
    """Extract the first line of a docstring from a function/class body."""
    body = node.child_by_field_name("body")
    if not body or body.child_count == 0:
        return ""

    first_stmt = body.children[0]
    if first_stmt.type != "expression_statement" or first_stmt.child_count == 0:
        return ""
    expr = first_stmt.children[0]
    if expr.type != "string":
        return ""

    doc = _node_text(source, expr)
    for quote in ('"""', "'''"):
        if doc.startswith(quote) and doc.endswith(quote):
            doc = doc[3:-3].strip()
            return doc.split("\n")[0].strip()[:120]
    return ""


# ---------------------------------------------------------------------------
# Python — init / dataclass constructor
# ---------------------------------------------------------------------------


def _is_dataclass_node(source: bytes, class_node) -> bool:
    """Check whether *class_node* has a ``@dataclass`` decorator."""
    parent = class_node.parent
    if parent and parent.type == "decorated_definition":
        for child in parent.children:
            if child.type == "decorator":
                text = _node_text(source, child)
                if "dataclass" in text:
                    return True
    return False


def _extract_dataclass_fields(source: bytes, body_node) -> list[str]:
    """Extract ``name: Type`` fields from a dataclass body for the constructor signature."""
    fields = []
    for child in body_node.children:
        if child.type != "expression_statement" or child.child_count == 0:
            continue
        expr = child.children[0]
        if expr.type == "assignment":
            ann = expr.child_by_field_name("type")
            left = expr.child_by_field_name("left")
            if left and left.type == "identifier" and ann:
                name = _node_text(source, left)
                fields.append(f"{name}: {_node_text(source, ann)}")
        elif expr.type == "type":
            # Bare annotation: ``x: int``  (no default value)
            # tree-sitter-python wraps these as ``type`` nodes
            text = _node_text(source, expr).strip()
            if ":" in text:
                fields.append(text)
    return fields


def py_extract_init_signature(source: bytes, class_node) -> str:
    """Extract ``ClassName(params)`` from ``__init__`` or ``@dataclass`` fields."""
    name_node = class_node.child_by_field_name("name")
    class_name = _node_text(source, name_node) if name_node else "?"

    body = class_node.child_by_field_name("body")
    if not body:
        return f"{class_name}()"

    # Look for explicit __init__
    for child in body.children:
        func = None
        if child.type == "function_definition":
            func = child
        elif child.type == "decorated_definition":
            for sub in child.children:
                if sub.type == "function_definition":
                    func = sub
                    break
        if func:
            fname = func.child_by_field_name("name")
            if fname and _node_text(source, fname) == "__init__":
                params = func.child_by_field_name("parameters")
                return f"{class_name}{_node_text(source, params)}" if params else f"{class_name}()"

    # Dataclass fields as constructor params
    if _is_dataclass_node(source, class_node):
        fields = _extract_dataclass_fields(source, body)
        if fields:
            return f"{class_name}({', '.join(fields)})"

    return f"{class_name}()"


# ---------------------------------------------------------------------------
# Python — top-level definitions
# ---------------------------------------------------------------------------


def py_extract_definitions(source: bytes, tree) -> list[CompletionItem]:
    """Extract top-level function, class, and variable definitions."""
    items: list[CompletionItem] = []
    root = tree.root_node

    for node in _top_level_children(root, "function_definition"):
        name_node = node.child_by_field_name("name")
        if not name_node:
            continue
        name = _node_text(source, name_node)
        sig = py_extract_signature(source, node)
        doc = py_extract_docstring(source, node)
        items.append(CompletionItem(name, CompletionKind.FUNCTION, sig, doc))

    for node in _top_level_children(root, "class_definition"):
        name_node = node.child_by_field_name("name")
        if not name_node:
            continue
        name = _node_text(source, name_node)
        doc = py_extract_docstring(source, node)
        init_sig = py_extract_init_signature(source, node)
        items.append(CompletionItem(name, CompletionKind.CLASS, init_sig, doc))

    # Top-level assignments: ``name = ...``
    for child in root.children:
        if child.type != "expression_statement" or child.child_count == 0:
            continue
        expr = child.children[0]
        if expr.type != "assignment":
            continue
        left = expr.child_by_field_name("left")
        if left and left.type == "identifier":
            name = _node_text(source, left)
            if name not in ("_", "__all__", "__version__"):
                items.append(CompletionItem(name, CompletionKind.VARIABLE))

    return items


# ---------------------------------------------------------------------------
# Python — imports
# ---------------------------------------------------------------------------


def py_extract_imports(source: bytes, tree) -> list[CompletionItem]:
    """Extract imported symbol names from the AST."""
    items: list[CompletionItem] = []
    root = tree.root_node

    for child in root.children:
        if child.type == "import_statement":
            _py_import_stmt(source, child, items)
        elif child.type == "import_from_statement":
            _py_import_from_stmt(source, child, items)
        # Handle imports inside try/except blocks
        elif child.type == "try_statement":
            for body_child in child.children:
                if body_child.type == "block":
                    for stmt in body_child.children:
                        if stmt.type == "import_statement":
                            _py_import_stmt(source, stmt, items)
                        elif stmt.type == "import_from_statement":
                            _py_import_from_stmt(source, stmt, items)
                elif body_child.type == "except_clause":
                    for stmt in body_child.children:
                        if stmt.type == "block":
                            for inner in stmt.children:
                                if inner.type == "import_statement":
                                    _py_import_stmt(source, inner, items)
                                elif inner.type == "import_from_statement":
                                    _py_import_from_stmt(source, inner, items)

    return items


def _py_import_stmt(source: bytes, node, items: list):
    """Process ``import X`` or ``import X as Y``."""
    for child in node.children:
        if child.type == "dotted_name":
            parts = _node_text(source, child).split(".")
            items.append(CompletionItem(parts[-1], CompletionKind.VARIABLE))
        elif child.type == "aliased_import":
            alias_node = child.child_by_field_name("alias")
            if alias_node:
                items.append(CompletionItem(_node_text(source, alias_node), CompletionKind.VARIABLE))
            else:
                name_node = child.child_by_field_name("name")
                if name_node:
                    parts = _node_text(source, name_node).split(".")
                    items.append(CompletionItem(parts[-1], CompletionKind.VARIABLE))


def _py_import_from_stmt(source: bytes, node, items: list):
    """Process ``from X import a, b as c``."""
    for child in node.children:
        if child.type == "dotted_name" and child != node.child_by_field_name("module_name"):
            items.append(CompletionItem(_node_text(source, child), CompletionKind.VARIABLE))
        elif child.type == "aliased_import":
            alias_node = child.child_by_field_name("alias")
            name_node = child.child_by_field_name("name")
            if alias_node:
                items.append(CompletionItem(_node_text(source, alias_node), CompletionKind.VARIABLE))
            elif name_node:
                items.append(CompletionItem(_node_text(source, name_node), CompletionKind.VARIABLE))


# ---------------------------------------------------------------------------
# Python — class members
# ---------------------------------------------------------------------------


def py_extract_class_members(source: bytes, tree, class_name: str, *, include_private: bool = False) -> list[CompletionItem]:
    """Extract public methods and class-level attributes from a named class."""
    class_node = _find_class_node(source, tree.root_node, class_name)
    if class_node is None:
        return []
    return _extract_members_from_class(source, class_node, include_private=include_private)


def py_extract_self_members(source: bytes, tree, class_name: str) -> list[CompletionItem]:
    """Extract all members accessible via ``self.`` (methods + attributes)."""
    class_node = _find_class_node(source, tree.root_node, class_name)
    if class_node is None:
        return []

    members: dict[str, CompletionItem] = {}
    body = class_node.child_by_field_name("body")
    if not body:
        return []

    for child in body.children:
        func = None
        if child.type == "function_definition":
            func = child
        elif child.type == "decorated_definition":
            for sub in child.children:
                if sub.type == "function_definition":
                    func = sub
                    break

        if func:
            fname = func.child_by_field_name("name")
            if not fname:
                continue
            name = _node_text(source, fname)
            # Skip dunder methods
            if name.startswith("__") and name.endswith("__"):
                continue
            sig = py_extract_signature(source, func)
            doc = py_extract_docstring(source, func)
            members[name] = CompletionItem(name, CompletionKind.FUNCTION, sig, doc)

            # Scan body for self.attr = ... assignments
            _collect_self_attrs(source, func, members)
            continue

        # Class-level attributes
        if child.type == "expression_statement" and child.child_count > 0:
            expr = child.children[0]
            if expr.type == "assignment":
                left = expr.child_by_field_name("left")
                if left and left.type == "identifier":
                    name = _node_text(source, left)
                    if name not in members:
                        members[name] = CompletionItem(name, CompletionKind.PROPERTY)

        # Nested class
        nested_cls = child if child.type == "class_definition" else None
        if child.type == "decorated_definition":
            for sub in child.children:
                if sub.type == "class_definition":
                    nested_cls = sub
                    break
        if nested_cls:
            n_node = nested_cls.child_by_field_name("name")
            if n_node:
                name = _node_text(source, n_node)
                members[name] = CompletionItem(name, CompletionKind.CLASS)

    return sorted(members.values(), key=lambda x: x.name)


def _collect_self_attrs(source: bytes, func_node, members: dict):
    """Walk a function body for ``self.attr = ...`` assignments."""
    body = func_node.child_by_field_name("body")
    if not body:
        return
    _walk_for_self_attrs(source, body, members)


def _walk_for_self_attrs(source: bytes, node, members: dict):
    """Recursively find ``self.X = ...`` patterns."""
    for child in node.children:
        if child.type == "expression_statement" and child.child_count > 0:
            expr = child.children[0]
            if expr.type == "assignment":
                left = expr.child_by_field_name("left")
                if left and left.type == "attribute":
                    obj = left.child_by_field_name("object")
                    attr = left.child_by_field_name("attribute")
                    if obj and attr and _node_text(source, obj) in ("self", "cls"):
                        name = _node_text(source, attr)
                        if name not in members:
                            members[name] = CompletionItem(name, CompletionKind.PROPERTY)
        # Recurse into blocks (if, for, with, try)
        if child.type in (
            "block",
            "if_statement",
            "for_statement",
            "while_statement",
            "with_statement",
            "try_statement",
            "except_clause",
            "else_clause",
            "elif_clause",
            "finally_clause",
        ):
            _walk_for_self_attrs(source, child, members)


def _extract_members_from_class(source: bytes, class_node, *, include_private: bool = False) -> list[CompletionItem]:
    """Extract public (or all) methods and attributes from a class_definition node."""
    members: dict[str, CompletionItem] = {}
    body = class_node.child_by_field_name("body")
    if not body:
        return []

    for child in body.children:
        func = None
        if child.type == "function_definition":
            func = child
        elif child.type == "decorated_definition":
            for sub in child.children:
                if sub.type == "function_definition":
                    func = sub
                    break

        if func:
            fname = func.child_by_field_name("name")
            if not fname:
                continue
            name = _node_text(source, fname)
            if not include_private and name.startswith("_"):
                continue
            sig = py_extract_signature(source, func)
            doc = py_extract_docstring(source, func)
            members[name] = CompletionItem(name, CompletionKind.FUNCTION, sig, doc)
            continue

        # Nested class
        nested_cls = child if child.type == "class_definition" else None
        if child.type == "decorated_definition":
            for sub in child.children:
                if sub.type == "class_definition":
                    nested_cls = sub
                    break
        if nested_cls:
            n_node = nested_cls.child_by_field_name("name")
            if n_node:
                name = _node_text(source, n_node)
                if not include_private and name.startswith("_"):
                    continue
                members[name] = CompletionItem(name, CompletionKind.CLASS)
            continue

        # Class attributes
        if child.type == "expression_statement" and child.child_count > 0:
            expr = child.children[0]
            if expr.type == "assignment":
                left = expr.child_by_field_name("left")
                if left and left.type == "identifier":
                    name = _node_text(source, left)
                    if not include_private and name.startswith("_"):
                        continue
                    members[name] = CompletionItem(name, CompletionKind.PROPERTY)

    return sorted(members.values(), key=lambda x: x.name)


# ---------------------------------------------------------------------------
# Python — enclosing class, variable type, function/method signatures
# ---------------------------------------------------------------------------


def py_find_enclosing_class(source: bytes, tree, byte_offset: int) -> str | None:
    """Return the name of the class containing *byte_offset*, or None."""
    node = tree.root_node
    result = None

    while True:
        found_child = False
        for child in node.children:
            inner = child
            # Unwrap decorated_definition
            if child.type == "decorated_definition":
                for sub in child.children:
                    if sub.type in ("class_definition", "function_definition"):
                        inner = sub
                        break
            if inner.start_byte <= byte_offset <= inner.end_byte:
                if inner.type == "class_definition":
                    name_node = inner.child_by_field_name("name")
                    if name_node:
                        result = _node_text(source, name_node)
                node = inner
                found_child = True
                break
        if not found_child:
            break

    return result


def py_resolve_variable_type(source: bytes, tree, var_name: str) -> str | None:
    """Resolve a variable's class from ``var = ClassName(...)`` or ``var: Type = ...``."""
    root = tree.root_node
    for child in root.children:
        if child.type != "expression_statement" or child.child_count == 0:
            continue
        expr = child.children[0]
        if expr.type != "assignment":
            continue
        left = expr.child_by_field_name("left")
        if not left or left.type != "identifier" or _node_text(source, left) != var_name:
            continue
        right = expr.child_by_field_name("right")
        if right and right.type == "call":
            func = right.child_by_field_name("function")
            if func:
                text = _node_text(source, func)
                return text.split(".")[-1]
        # var: Type = ...
        ann = expr.child_by_field_name("type")
        if ann:
            return _node_text(source, ann).split(".")[-1]
    return None


def py_find_function_signature(source: bytes, tree, func_name: str) -> str | None:
    """Find a top-level function's signature by name."""
    for node in _top_level_children(tree.root_node, "function_definition"):
        fname = node.child_by_field_name("name")
        if fname and _node_text(source, fname) == func_name:
            return py_extract_signature(source, node)
    # Check for class constructor
    for node in _top_level_children(tree.root_node, "class_definition"):
        cname = node.child_by_field_name("name")
        if cname and _node_text(source, cname) == func_name:
            return py_extract_init_signature(source, node)
    return None


def py_find_method_signature(source: bytes, tree_or_root, class_name: str, method_name: str) -> str | None:
    """Find a method's signature within a class."""
    root = tree_or_root.root_node if hasattr(tree_or_root, "root_node") else tree_or_root
    class_node = _find_class_node(source, root, class_name)
    if class_node is None:
        return None
    body = class_node.child_by_field_name("body")
    if not body:
        return None
    for child in body.children:
        func = None
        if child.type == "function_definition":
            func = child
        elif child.type == "decorated_definition":
            for sub in child.children:
                if sub.type == "function_definition":
                    func = sub
                    break
        if func:
            fname = func.child_by_field_name("name")
            if fname and _node_text(source, fname) == method_name:
                return py_extract_signature(source, func)
    return None


def py_extract_file_symbols(source: bytes, tree) -> list[CompletionItem]:
    """Extract all exportable symbols from a Python file (for import completions).

    Handles ``__init__.py`` re-exports by tracking ``from .sub import Name``.
    """
    symbols: dict[str, CompletionItem] = {}
    root = tree.root_node
    reexports: dict[str, str] = {}  # name → relative_module

    for child in root.children:
        _actual = child
        if child.type == "decorated_definition":
            for sub in child.children:
                if sub.type in ("function_definition", "class_definition"):
                    _actual = sub
                    break

        if _actual.type == "function_definition":
            fname = _actual.child_by_field_name("name")
            if fname:
                name = _node_text(source, fname)
                sig = py_extract_signature(source, _actual)
                doc = py_extract_docstring(source, _actual)
                symbols[name] = CompletionItem(name, CompletionKind.FUNCTION, sig, doc)

        elif _actual.type == "class_definition":
            cname = _actual.child_by_field_name("name")
            if cname:
                name = _node_text(source, cname)
                doc = py_extract_docstring(source, _actual)
                init_sig = py_extract_init_signature(source, _actual)
                symbols[name] = CompletionItem(name, CompletionKind.CLASS, init_sig, doc)

        elif child.type == "expression_statement" and child.child_count > 0:
            expr = child.children[0]
            if expr.type == "assignment":
                left = expr.child_by_field_name("left")
                if left and left.type == "identifier":
                    name = _node_text(source, left)
                    if not name.startswith("_"):
                        symbols[name] = CompletionItem(name, CompletionKind.PROPERTY)

        elif child.type == "import_from_statement":
            # Track relative re-exports: ``from .sub import Name``
            module_node = child.child_by_field_name("module_name")
            if module_node:
                mod_text = _node_text(source, module_node)
                if mod_text.startswith(".") and not mod_text.startswith(".."):
                    rel_module = mod_text.lstrip(".")
                    for imp_child in child.children:
                        if imp_child.type == "dotted_name" and imp_child != module_node:
                            name = _node_text(source, imp_child)
                            if name not in symbols:
                                reexports[name] = rel_module
                        elif imp_child.type == "aliased_import":
                            alias = imp_child.child_by_field_name("alias")
                            orig = imp_child.child_by_field_name("name")
                            n = alias or orig
                            if n:
                                name = _node_text(source, n)
                                if name not in symbols:
                                    reexports[name] = rel_module

    return symbols, reexports


# ---------------------------------------------------------------------------
# Python — chain resolution helpers
# ---------------------------------------------------------------------------


def py_resolve_chain(source: bytes, tree, parts: list[str]) -> list[CompletionItem]:
    """Walk a dotted chain (e.g. [ClassName, SubClass]) and return members of the final class."""
    current_node = tree.root_node if hasattr(tree, "root_node") else tree
    current_source = source

    for i, part in enumerate(parts):
        class_node = _find_class_node(current_source, current_node, part)
        if class_node is None:
            return []
        if i == len(parts) - 1:
            return _extract_members_from_class(current_source, class_node)
        body = class_node.child_by_field_name("body")
        if not body:
            return []
        current_node = body

    return []


def _find_class_node(source: bytes, root, class_name: str):
    """Find a class_definition node by name under *root*."""
    for child in root.children:
        actual = child
        if child.type == "decorated_definition":
            for sub in child.children:
                if sub.type == "class_definition":
                    actual = sub
                    break
        if actual.type == "class_definition":
            name_node = actual.child_by_field_name("name")
            if name_node and _node_text(source, name_node) == class_name:
                return actual
    return None


# ---------------------------------------------------------------------------
# JavaScript / TypeScript — definitions & imports
# ---------------------------------------------------------------------------


def js_extract_definitions(source: bytes, tree, *, is_typescript: bool = False) -> list[CompletionItem]:
    """Extract top-level symbol definitions from JS/TS AST."""
    items: list[CompletionItem] = []
    root = tree.root_node

    for child in root.children:
        _js_extract_node(source, child, items, is_typescript=is_typescript)
    return items


def _js_extract_node(source: bytes, node, items: list, *, is_typescript: bool = False):
    """Process a single top-level node for JS/TS definitions."""
    # Unwrap export
    if node.type == "export_statement":
        decl = node.child_by_field_name("declaration")
        if decl:
            _js_extract_node(source, decl, items, is_typescript=is_typescript)
        return

    if node.type == "function_declaration":
        name_node = node.child_by_field_name("name")
        if name_node:
            name = _node_text(source, name_node)
            doc = _js_extract_jsdoc(source, node)
            items.append(CompletionItem(name, CompletionKind.FUNCTION, docstring=doc))

    elif node.type == "class_declaration":
        name_node = node.child_by_field_name("name")
        if name_node:
            items.append(CompletionItem(_node_text(source, name_node), CompletionKind.CLASS))

    elif node.type in ("lexical_declaration", "variable_declaration"):
        for declarator in node.children:
            if declarator.type == "variable_declarator":
                name_node = declarator.child_by_field_name("name")
                if name_node and name_node.type == "identifier":
                    items.append(CompletionItem(_node_text(source, name_node), CompletionKind.VARIABLE))

    elif is_typescript and node.type == "interface_declaration":
        name_node = node.child_by_field_name("name")
        if name_node:
            items.append(CompletionItem(_node_text(source, name_node), CompletionKind.PROPERTY))

    elif is_typescript and node.type == "type_alias_declaration":
        name_node = node.child_by_field_name("name")
        if name_node:
            items.append(CompletionItem(_node_text(source, name_node), CompletionKind.PROPERTY))

    elif is_typescript and node.type == "enum_declaration":
        name_node = node.child_by_field_name("name")
        if name_node:
            items.append(CompletionItem(_node_text(source, name_node), CompletionKind.PROPERTY))


def js_extract_imports(source: bytes, tree) -> list[CompletionItem]:
    """Extract imported symbol names from JS/TS AST."""
    items: list[CompletionItem] = []
    root = tree.root_node

    for child in root.children:
        if child.type != "import_statement":
            continue
        for clause in child.children:
            if clause.type == "import_clause":
                _js_import_clause(source, clause, items)
    return items


def _js_import_clause(source: bytes, clause, items: list):
    """Process an import clause for named/default/namespace imports."""
    for child in clause.children:
        if child.type == "identifier":
            # Default import: ``import Foo from '...'``
            items.append(CompletionItem(_node_text(source, child), CompletionKind.VARIABLE))

        elif child.type == "named_imports":
            for spec in child.children:
                if spec.type == "import_specifier":
                    alias = spec.child_by_field_name("alias")
                    name = spec.child_by_field_name("name")
                    node = alias or name
                    if node:
                        items.append(CompletionItem(_node_text(source, node), CompletionKind.VARIABLE))

        elif child.type == "namespace_import":
            for sub in child.children:
                if sub.type == "identifier":
                    items.append(CompletionItem(_node_text(source, sub), CompletionKind.VARIABLE))


def _js_extract_jsdoc(source: bytes, node) -> str:
    """Extract first description line from a JSDoc comment preceding a node."""
    prev = node.prev_sibling
    if not prev or prev.type != "comment":
        # Try parent's prev sibling (export_statement wraps)
        parent = node.parent
        if parent and parent.type == "export_statement":
            prev = parent.prev_sibling
        if not prev or prev.type != "comment":
            return ""
    text = _node_text(source, prev)
    if not text.startswith("/**"):
        return ""
    text = text[3:]
    if text.endswith("*/"):
        text = text[:-2]
    for line in text.split("\n"):
        line = line.strip().lstrip("* ").strip()
        if line and not line.startswith("@"):
            return line[:120]
    return ""
