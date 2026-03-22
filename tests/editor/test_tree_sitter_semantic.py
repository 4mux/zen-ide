"""Tests for tree-sitter based semantic token extraction."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from editor.tree_sitter_semantic import _is_pascal_case, extract_semantic_tokens

try:
    from navigation.tree_sitter_core import TreeSitterCore

    _HAS_TS = TreeSitterCore.available()
except Exception:
    _HAS_TS = False

needs_ts = pytest.mark.skipif(not _HAS_TS, reason="tree-sitter not available")


def _parse(code: str, lang: str = "python"):
    tree = TreeSitterCore.parse(code.encode("utf-8"), lang)
    assert tree is not None, f"Failed to parse {lang} code"
    return tree.root_node


def _token_names(tokens, text: str):
    """Return list of (name_text, token_type) from byte offsets."""
    text_bytes = text.encode("utf-8")
    return [(text_bytes[s:e].decode("utf-8"), t) for s, e, t in tokens]


# ---------------------------------------------------------------------------
# PascalCase helper
# ---------------------------------------------------------------------------


class TestPascalCase:
    def test_basic(self):
        assert _is_pascal_case("MyClass") is True

    def test_single_char(self):
        assert _is_pascal_case("M") is False

    def test_all_caps(self):
        assert _is_pascal_case("CONSTANT") is False

    def test_lower(self):
        assert _is_pascal_case("myVar") is False

    def test_two_chars(self):
        assert _is_pascal_case("Ab") is True

    def test_with_digits(self):
        assert _is_pascal_case("Type2D") is True


# ---------------------------------------------------------------------------
# Python tokens
# ---------------------------------------------------------------------------


@needs_ts
class TestPythonSemantic:
    def test_function_call(self):
        code = "result = foo(x)"
        tokens = extract_semantic_tokens(_parse(code), "python")
        names = _token_names(tokens, code)
        assert ("foo", "func_call") in names

    def test_method_call(self):
        code = "obj.method()"
        tokens = extract_semantic_tokens(_parse(code), "python")
        names = _token_names(tokens, code)
        assert ("method", "func_call") in names

    def test_constructor_call(self):
        code = "x = MyClass()"
        tokens = extract_semantic_tokens(_parse(code), "python")
        names = _token_names(tokens, code)
        assert ("MyClass", "class") in names

    def test_class_reference(self):
        code = "x: MyType = None"
        tokens = extract_semantic_tokens(_parse(code), "python")
        names = _token_names(tokens, code)
        assert ("MyType", "class") in names

    def test_self_keyword(self):
        code = "class A:\n    def m(self):\n        self.x = 1"
        tokens = extract_semantic_tokens(_parse(code), "python")
        names = _token_names(tokens, code)
        self_tokens = [(n, t) for n, t in names if n == "self"]
        assert all(t == "self_kw" for _, t in self_tokens)
        assert len(self_tokens) >= 1

    def test_cls_keyword(self):
        code = "class A:\n    @classmethod\n    def m(cls):\n        cls.x = 1"
        tokens = extract_semantic_tokens(_parse(code), "python")
        names = _token_names(tokens, code)
        cls_tokens = [(n, t) for n, t in names if n == "cls"]
        assert all(t == "self_kw" for _, t in cls_tokens)
        assert len(cls_tokens) >= 1

    def test_property_access(self):
        code = "x = obj.attr"
        tokens = extract_semantic_tokens(_parse(code), "python")
        names = _token_names(tokens, code)
        assert ("attr", "property") in names

    def test_method_not_property(self):
        """Method calls should be func_call, not property."""
        code = "obj.method()"
        tokens = extract_semantic_tokens(_parse(code), "python")
        names = _token_names(tokens, code)
        assert ("method", "func_call") in names
        assert ("method", "property") not in names

    def test_param_definition(self):
        code = "def foo(bar, baz):\n    pass"
        tokens = extract_semantic_tokens(_parse(code), "python")
        names = _token_names(tokens, code)
        assert ("bar", "param") in names
        assert ("baz", "param") in names

    def test_param_usage_in_body(self):
        code = "def foo(x):\n    return x + 1"
        tokens = extract_semantic_tokens(_parse(code), "python")
        names = _token_names(tokens, code)
        # x appears twice: once as param def, once as param usage
        x_params = [(n, t) for n, t in names if n == "x" and t == "param"]
        assert len(x_params) >= 2

    def test_nested_function_params(self):
        code = "def outer(a):\n    def inner(b):\n        return a + b"
        tokens = extract_semantic_tokens(_parse(code), "python")
        names = _token_names(tokens, code)
        a_params = [(n, t) for n, t in names if n == "a" and t == "param"]
        b_params = [(n, t) for n, t in names if n == "b" and t == "param"]
        assert len(a_params) >= 2  # def + usage
        assert len(b_params) >= 2  # def + usage

    def test_skip_def_name(self):
        """Function/class definition names should not get semantic tags."""
        code = "def my_func():\n    pass"
        tokens = extract_semantic_tokens(_parse(code), "python")
        names = _token_names(tokens, code)
        assert ("my_func", "func_call") not in names

    def test_skip_class_def_name(self):
        code = "class MyClass:\n    pass"
        tokens = extract_semantic_tokens(_parse(code), "python")
        names = _token_names(tokens, code)
        assert ("MyClass", "class") not in names

    def test_strings_skipped(self):
        """Identifiers inside string literals should not be tagged."""
        code = 'x = "MyClass foo self"'
        tokens = extract_semantic_tokens(_parse(code), "python")
        names = _token_names(tokens, code)
        # None of the string contents should appear as tokens
        for name, _ in names:
            assert name not in ("MyClass", "foo", "self"), f"String content '{name}' was tagged"

    def test_comment_skipped(self):
        code = "# MyClass foo self\nx = 1"
        tokens = extract_semantic_tokens(_parse(code), "python")
        names = _token_names(tokens, code)
        for name, _ in names:
            assert name not in ("MyClass", "foo"), f"Comment content '{name}' was tagged"

    def test_typed_param(self):
        code = "def foo(x: int, y: str = ''):\n    pass"
        tokens = extract_semantic_tokens(_parse(code), "python")
        names = _token_names(tokens, code)
        assert ("x", "param") in names
        assert ("y", "param") in names

    def test_star_params(self):
        code = "def foo(*args, **kwargs):\n    pass"
        tokens = extract_semantic_tokens(_parse(code), "python")
        names = _token_names(tokens, code)
        assert ("args", "param") in names
        assert ("kwargs", "param") in names

    def test_chained_method(self):
        code = "obj.get().do_thing()"
        tokens = extract_semantic_tokens(_parse(code), "python")
        names = _token_names(tokens, code)
        assert ("get", "func_call") in names
        assert ("do_thing", "func_call") in names


# ---------------------------------------------------------------------------
# TypeScript / JavaScript tokens
# ---------------------------------------------------------------------------


@needs_ts
class TestTypeScriptSemantic:
    def test_function_call(self):
        code = "const x = foo(1);"
        tokens = extract_semantic_tokens(_parse(code, "javascript"), "javascript")
        names = _token_names(tokens, code)
        assert ("foo", "func_call") in names

    def test_method_call(self):
        code = "arr.push(1);"
        tokens = extract_semantic_tokens(_parse(code, "javascript"), "javascript")
        names = _token_names(tokens, code)
        assert ("push", "func_call") in names

    def test_constructor_call(self):
        code = "const x = new MyClass();"
        tokens = extract_semantic_tokens(_parse(code, "javascript"), "javascript")
        names = _token_names(tokens, code)
        assert ("MyClass", "class") in names

    def test_this_keyword(self):
        code = "class A { m() { this.x = 1; } }"
        tokens = extract_semantic_tokens(_parse(code, "javascript"), "javascript")
        names = _token_names(tokens, code)
        this_tokens = [(n, t) for n, t in names if n == "this"]
        assert len(this_tokens) >= 1
        assert all(t == "self_kw" for _, t in this_tokens)

    def test_property_access(self):
        code = "const x = obj.prop;"
        tokens = extract_semantic_tokens(_parse(code, "javascript"), "javascript")
        names = _token_names(tokens, code)
        assert ("prop", "property") in names

    def test_string_skipped(self):
        code = 'const s = "MyClass foo";'
        tokens = extract_semantic_tokens(_parse(code, "javascript"), "javascript")
        names = _token_names(tokens, code)
        for name, _ in names:
            assert name not in ("MyClass", "foo"), f"String content '{name}' was tagged"

    def test_pascal_case_class(self):
        code = "const x = MyType;"
        tokens = extract_semantic_tokens(_parse(code, "javascript"), "javascript")
        names = _token_names(tokens, code)
        assert ("MyType", "class") in names


@needs_ts
class TestTypeScriptParams:
    def test_function_params(self):
        code = "function foo(a, b) { return a + b; }"
        tokens = extract_semantic_tokens(_parse(code, "javascript"), "javascript")
        names = _token_names(tokens, code)
        a_params = [(n, t) for n, t in names if n == "a" and t == "param"]
        b_params = [(n, t) for n, t in names if n == "b" and t == "param"]
        assert len(a_params) >= 1
        assert len(b_params) >= 1

    def test_arrow_params(self):
        code = "const fn = (x) => x + 1;"
        tokens = extract_semantic_tokens(_parse(code, "javascript"), "javascript")
        names = _token_names(tokens, code)
        x_params = [(n, t) for n, t in names if n == "x" and t == "param"]
        assert len(x_params) >= 1


# ---------------------------------------------------------------------------
# Buffer cache
# ---------------------------------------------------------------------------


@needs_ts
class TestBufferCache:
    def test_cache_reuse(self):
        from editor.tree_sitter_buffer import TreeSitterBufferCache

        cache = TreeSitterBufferCache()
        code = "x = 1"
        t1 = cache.get_tree(code, "python")
        t2 = cache.get_tree(code, "python")
        assert t1 is t2  # Same object — no reparse

    def test_dirty_reparse(self):
        from editor.tree_sitter_buffer import TreeSitterBufferCache

        cache = TreeSitterBufferCache()
        code1 = "x = 1"
        t1 = cache.get_tree(code1, "python")
        cache._dirty = True
        code2 = "x = 2"
        t2 = cache.get_tree(code2, "python")
        assert t1 is not t2

    def test_invalidate(self):
        from editor.tree_sitter_buffer import TreeSitterBufferCache

        cache = TreeSitterBufferCache()
        cache.get_tree("x = 1", "python")
        cache.invalidate()
        assert cache._tree is None

    def test_incremental_parse(self):
        from editor.tree_sitter_buffer import TreeSitterBufferCache

        cache = TreeSitterBufferCache()
        code1 = "x = 1\ny = 2\n"
        t1 = cache.get_tree(code1, "python")
        assert t1 is not None

        # Simulate inserting "z = 3\n" at position 12 (end of file)
        insert_pos = len(code1.encode("utf-8"))
        insert_text = "z = 3\n"
        insert_bytes = len(insert_text.encode("utf-8"))
        lines_before = code1.count("\n")
        cache.record_insert(
            insert_pos,
            (lines_before, 0),
            insert_bytes,
            (lines_before, len(insert_text.rstrip("\n"))),
        )

        code2 = code1 + insert_text
        t2 = cache.get_tree(code2, "python")
        assert t2 is not None
        assert t2 is not t1
