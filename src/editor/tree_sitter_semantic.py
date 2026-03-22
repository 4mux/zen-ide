"""
Tree-sitter based semantic token extraction.

Replaces the regex patterns in ``semantic_highlight.py`` with a single
AST walk.  Naturally skips strings and comments because those are
distinct node types that never contain ``identifier`` children.

Token types returned match the tag names used by semantic_highlight:
  "class"     — PascalCase class reference / constructor call
  "func_call" — function or method call
  "param"     — parameter definition or usage
  "self_kw"   — self / cls / this keyword
  "property"  — attribute/property access (not a method call)
"""

# Skip param-usage highlighting for files larger than this (bytes).
_MAX_PARAM_FILE_SIZE = 50_000

_PY_SKIP_NAMES = frozenset(
    {
        "if",
        "elif",
        "else",
        "for",
        "while",
        "with",
        "try",
        "except",
        "finally",
        "return",
        "yield",
        "raise",
        "pass",
        "break",
        "continue",
        "and",
        "or",
        "not",
        "in",
        "is",
        "lambda",
        "assert",
        "global",
        "nonlocal",
        "del",
        "async",
        "await",
        "class",
        "def",
        "import",
        "from",
        "as",
    }
)

_JS_SKIP_NAMES = frozenset(
    {
        "if",
        "else",
        "for",
        "while",
        "do",
        "switch",
        "case",
        "default",
        "break",
        "continue",
        "return",
        "throw",
        "try",
        "catch",
        "finally",
        "new",
        "delete",
        "typeof",
        "instanceof",
        "void",
        "in",
        "of",
        "with",
        "debugger",
        "class",
        "extends",
        "function",
        "var",
        "let",
        "const",
        "import",
        "export",
        "from",
        "as",
        "async",
        "await",
        "yield",
        "super",
        "type",
        "interface",
        "enum",
        "implements",
        "namespace",
        "module",
        "declare",
        "abstract",
        "readonly",
        "keyof",
        "infer",
        "satisfies",
    }
)


def _is_pascal_case(name: str) -> bool:
    return len(name) > 1 and name[0].isupper() and any(c.islower() for c in name)


def _same_field(parent, field, node):
    """Check whether *node* is the *field* child of *parent*."""
    child = parent.child_by_field_name(field)
    return child is not None and child.start_byte == node.start_byte and child.end_byte == node.end_byte


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------


def _get_python_params(func_node):
    """Return a set of parameter name strings for a function_definition."""
    params = func_node.child_by_field_name("parameters")
    if params is None:
        return frozenset()

    names = set()
    for child in params.children:
        if child.type == "identifier":
            n = child.text.decode("utf-8")
            if n not in ("self", "cls"):
                names.add(n)
        elif child.type in (
            "typed_parameter",
            "typed_default_parameter",
            "default_parameter",
        ):
            for sub in child.children:
                if sub.type == "identifier":
                    n = sub.text.decode("utf-8")
                    if n not in ("self", "cls"):
                        names.add(n)
                    break
        elif child.type in ("list_splat_pattern", "dictionary_splat_pattern"):
            for sub in child.children:
                if sub.type == "identifier":
                    names.add(sub.text.decode("utf-8"))
                    break
    return frozenset(names)


def _classify_python(node, tokens, param_scope):
    if node.type != "identifier":
        return

    name = node.text.decode("utf-8")
    parent = node.parent
    if parent is None:
        return

    # self / cls
    if name in ("self", "cls"):
        tokens.append((node.start_byte, node.end_byte, "self_kw"))
        return

    # Definition names — GtkSourceView already highlights these
    if parent.type in ("function_definition", "class_definition"):
        if _same_field(parent, "name", node):
            return

    # Import names — skip
    if parent.type in (
        "import_statement",
        "import_from_statement",
        "aliased_import",
        "dotted_name",
    ):
        return

    # Decorator name — skip
    if parent.type == "decorator":
        return

    # Direct function call: func(...)
    if parent.type == "call" and _same_field(parent, "function", node):
        if _is_pascal_case(name):
            tokens.append((node.start_byte, node.end_byte, "class"))
        elif name not in _PY_SKIP_NAMES:
            tokens.append((node.start_byte, node.end_byte, "func_call"))
        return

    # Attribute child inside attribute node
    if parent.type == "attribute" and _same_field(parent, "attribute", node):
        gp = parent.parent
        if gp is not None and gp.type == "call" and _same_field(gp, "function", parent):
            # Method call: obj.method()
            if name not in _PY_SKIP_NAMES:
                tokens.append((node.start_byte, node.end_byte, "func_call"))
        else:
            # Property access: obj.attr
            tokens.append((node.start_byte, node.end_byte, "property"))
        return

    # Parameter definition site
    if parent.type == "parameters":
        tokens.append((node.start_byte, node.end_byte, "param"))
        return
    if parent.type in (
        "typed_parameter",
        "typed_default_parameter",
        "default_parameter",
    ):
        # First identifier child is the parameter name
        for child in parent.children:
            if child.type == "identifier":
                if child.start_byte == node.start_byte:
                    tokens.append((node.start_byte, node.end_byte, "param"))
                return
    if parent.type in ("list_splat_pattern", "dictionary_splat_pattern"):
        tokens.append((node.start_byte, node.end_byte, "param"))
        return

    # Parameter usage inside function body
    if name in param_scope:
        tokens.append((node.start_byte, node.end_byte, "param"))
        return

    # PascalCase class reference
    if _is_pascal_case(name):
        tokens.append((node.start_byte, node.end_byte, "class"))
        return


# ---------------------------------------------------------------------------
# TypeScript / JavaScript
# ---------------------------------------------------------------------------


def _get_ts_params(func_node):
    """Return a set of parameter name strings for a TS/JS function node."""
    params = func_node.child_by_field_name("parameters")
    if params is None:
        # Arrow functions: (a, b) => ...
        params = func_node.child_by_field_name("parameter")
        if params is None:
            return frozenset()

    names = set()
    for child in _walk_flat(params):
        if child.type == "identifier":
            p = child.parent
            if p is not None and p.type in (
                "formal_parameters",
                "required_parameter",
                "optional_parameter",
                "rest_pattern",
            ):
                names.add(child.text.decode("utf-8"))
            elif p is not None and p.type == "identifier" and p.parent and p.parent.type == "formal_parameters":
                names.add(child.text.decode("utf-8"))
    # Simpler fallback: just grab direct identifier children of formal_parameters
    if not names and params is not None:
        for child in params.children:
            if child.type == "identifier":
                names.add(child.text.decode("utf-8"))
            elif child.type in ("required_parameter", "optional_parameter"):
                pat = child.child_by_field_name("pattern")
                if pat and pat.type == "identifier":
                    names.add(pat.text.decode("utf-8"))
    return frozenset(names)


def _classify_ts(node, tokens, param_scope):
    ntype = node.type

    # this keyword
    if ntype == "this":
        tokens.append((node.start_byte, node.end_byte, "self_kw"))
        return

    if ntype not in ("identifier", "property_identifier", "type_identifier"):
        return

    name = node.text.decode("utf-8")
    parent = node.parent
    if parent is None:
        return

    # Definition names — skip
    if parent.type in (
        "function_declaration",
        "class_declaration",
        "interface_declaration",
        "type_alias_declaration",
        "enum_declaration",
        "method_definition",
    ):
        if _same_field(parent, "name", node):
            return

    # Variable declarator name — skip
    if parent.type == "variable_declarator" and _same_field(parent, "name", node):
        return

    # Import names — skip
    if parent.type in ("import_specifier", "import_clause", "namespace_import"):
        return

    # Direct function call
    if parent.type == "call_expression" and _same_field(parent, "function", node):
        if _is_pascal_case(name):
            tokens.append((node.start_byte, node.end_byte, "class"))
        elif name not in _JS_SKIP_NAMES:
            tokens.append((node.start_byte, node.end_byte, "func_call"))
        return

    # new ClassName(...)
    if parent.type == "new_expression":
        if _is_pascal_case(name):
            tokens.append((node.start_byte, node.end_byte, "class"))
            return

    # Member expression property
    if parent.type == "member_expression" and _same_field(parent, "property", node):
        gp = parent.parent
        if gp is not None and gp.type == "call_expression" and _same_field(gp, "function", parent):
            if name not in _JS_SKIP_NAMES:
                tokens.append((node.start_byte, node.end_byte, "func_call"))
        else:
            tokens.append((node.start_byte, node.end_byte, "property"))
        return

    # Parameter definition site
    if parent.type in ("formal_parameters", "required_parameter", "optional_parameter", "rest_pattern"):
        tokens.append((node.start_byte, node.end_byte, "param"))
        return

    # Parameter usage
    if name in param_scope:
        tokens.append((node.start_byte, node.end_byte, "param"))
        return

    # Type annotation identifier — class color for PascalCase
    if parent.type in ("type_annotation", "type_identifier", "generic_type", "predefined_type"):
        if _is_pascal_case(name):
            tokens.append((node.start_byte, node.end_byte, "class"))
        return

    # JSX element names
    if parent.type in ("jsx_opening_element", "jsx_closing_element", "jsx_self_closing_element"):
        if _is_pascal_case(name):
            tokens.append((node.start_byte, node.end_byte, "class"))
        return

    # PascalCase class reference
    if _is_pascal_case(name):
        tokens.append((node.start_byte, node.end_byte, "class"))
        return


# ---------------------------------------------------------------------------
# Generic walk
# ---------------------------------------------------------------------------


def _walk_flat(node):
    """Yield all descendant nodes depth-first."""
    yield node
    for child in node.children:
        yield from _walk_flat(child)


_PY_FUNC_TYPES = frozenset({"function_definition"})
_TS_FUNC_TYPES = frozenset(
    {
        "function_declaration",
        "method_definition",
        "arrow_function",
        "function",
    }
)


def _walk(node, tokens, param_scope, lang_type, classify_fn, func_types, get_params_fn):
    """Recursive walk that tracks parameter scope."""
    new_scope = param_scope

    if node.type in func_types:
        param_names = get_params_fn(node)
        if param_names:
            new_scope = param_scope | param_names

    classify_fn(node, tokens, new_scope)

    for child in node.children:
        _walk(child, tokens, new_scope, lang_type, classify_fn, func_types, get_params_fn)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_semantic_tokens(root_node, lang_type: str):
    """Extract semantic tokens from a tree-sitter root node.

    *lang_type* is a tree-sitter language name: ``"python"``,
    ``"javascript"``, ``"typescript"``, or ``"tsx"``.

    Returns a list of ``(start_byte, end_byte, token_type)`` tuples.
    """
    tokens = []
    track_params = root_node.end_byte <= _MAX_PARAM_FILE_SIZE

    if lang_type == "python":
        fn = _classify_python
        ft = _PY_FUNC_TYPES
        gp = _get_python_params if track_params else lambda _: frozenset()
    else:
        fn = _classify_ts
        ft = _TS_FUNC_TYPES
        gp = _get_ts_params if track_params else lambda _: frozenset()

    _walk(root_node, tokens, frozenset(), lang_type, fn, ft, gp)
    return tokens
