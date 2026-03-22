"""
Tests for Tree-sitter navigation infrastructure.

Tests the core parser manager, query definitions, and
language-specific providers (Python, TypeScript/JavaScript).
"""

import pytest


class TestTreeSitterCore:
    """Tests for the lazy parser manager."""

    def test_available(self):
        from navigation.tree_sitter_core import TreeSitterCore

        assert TreeSitterCore.available() is True

    def test_get_language_python(self):
        from navigation.tree_sitter_core import TreeSitterCore

        lang = TreeSitterCore.get_language("python")
        assert lang is not None

    def test_get_language_javascript(self):
        from navigation.tree_sitter_core import TreeSitterCore

        lang = TreeSitterCore.get_language("javascript")
        assert lang is not None

    def test_get_language_typescript(self):
        from navigation.tree_sitter_core import TreeSitterCore

        lang = TreeSitterCore.get_language("typescript")
        assert lang is not None

    def test_get_language_tsx(self):
        from navigation.tree_sitter_core import TreeSitterCore

        lang = TreeSitterCore.get_language("tsx")
        assert lang is not None

    def test_get_language_unsupported(self):
        from navigation.tree_sitter_core import TreeSitterCore

        lang = TreeSitterCore.get_language("cobol")
        assert lang is None

    def test_get_parser_caches(self):
        from navigation.tree_sitter_core import TreeSitterCore

        p1 = TreeSitterCore.get_parser("python")
        p2 = TreeSitterCore.get_parser("python")
        assert p1 is p2

    def test_parse_python(self):
        from navigation.tree_sitter_core import TreeSitterCore

        tree = TreeSitterCore.parse(b"def foo(): pass", "python")
        assert tree is not None
        assert tree.root_node.type == "module"

    def test_parse_unsupported_returns_none(self):
        from navigation.tree_sitter_core import TreeSitterCore

        tree = TreeSitterCore.parse(b"something", "cobol")
        assert tree is None

    def test_lang_for_ext(self):
        from navigation.tree_sitter_core import TreeSitterCore

        assert TreeSitterCore.lang_for_ext(".py") == "python"
        assert TreeSitterCore.lang_for_ext(".ts") == "typescript"
        assert TreeSitterCore.lang_for_ext(".tsx") == "tsx"
        assert TreeSitterCore.lang_for_ext(".js") == "javascript"
        assert TreeSitterCore.lang_for_ext(".jsx") == "javascript"
        assert TreeSitterCore.lang_for_ext(".rs") is None

    def test_query_compiles(self):
        from navigation.tree_sitter_core import TreeSitterCore

        q = TreeSitterCore.query("python", "(function_definition name: (identifier) @name) @node")
        assert q is not None

    def test_run_query_returns_matches(self):
        from navigation.tree_sitter_core import TreeSitterCore

        tree = TreeSitterCore.parse(b"def foo(): pass\ndef bar(): pass", "python")
        q = TreeSitterCore.query("python", "(function_definition name: (identifier) @name) @node")
        matches = TreeSitterCore.run_query(tree, q)
        names = []
        for _, captures in matches:
            for n in captures.get("name", []):
                names.append(n.text.decode("utf-8"))
        assert names == ["foo", "bar"]


class TestTreeSitterPyProvider:
    """Tests for the Python Tree-sitter navigation provider."""

    @pytest.fixture
    def provider(self):
        from navigation.tree_sitter_py_provider import TreeSitterPyProvider

        return TreeSitterPyProvider()

    def test_supports_language(self, provider):
        assert provider.supports_language(".py") is True
        assert provider.supports_language(".pyw") is True
        assert provider.supports_language(".pyi") is True
        assert provider.supports_language(".js") is False

    def test_find_class(self, provider):
        content = "class MyClass:\n    pass\n"
        assert provider.find_symbol_in_content(content, "MyClass") == 1

    def test_find_function(self, provider):
        content = "def my_func(x):\n    return x\n"
        assert provider.find_symbol_in_content(content, "my_func") == 1

    def test_find_async_function(self, provider):
        content = "async def fetch_data():\n    pass\n"
        assert provider.find_symbol_in_content(content, "fetch_data") == 1

    def test_find_variable(self, provider):
        content = "result = compute()\n"
        assert provider.find_symbol_in_content(content, "result") == 1

    def test_find_typed_variable(self, provider):
        content = "count: int = 0\n"
        assert provider.find_symbol_in_content(content, "count") == 1

    def test_find_decorated_function(self, provider):
        content = "@decorator\ndef decorated():\n    pass\n"
        assert provider.find_symbol_in_content(content, "decorated") == 2

    def test_find_nested_class(self, provider):
        content = "class Outer:\n    class Inner:\n        pass\n"
        assert provider.find_symbol_in_content(content, "Outer") == 1
        assert provider.find_symbol_in_content(content, "Inner") == 2

    def test_not_found(self, provider):
        content = "class Foo:\n    pass\n"
        assert provider.find_symbol_in_content(content, "Bar") is None

    def test_parse_import(self, provider):
        content = "import os\n"
        result = provider.parse_imports(content)
        assert result["os"] == "os"

    def test_parse_import_as(self, provider):
        content = "import json as j\n"
        result = provider.parse_imports(content)
        assert result["j"] == "json"

    def test_parse_from_import(self, provider):
        content = "from typing import Optional\n"
        result = provider.parse_imports(content)
        assert result["Optional"] == "typing.Optional"

    def test_parse_from_import_as(self, provider):
        content = "from os.path import join as pjoin\n"
        result = provider.parse_imports(content)
        assert result["pjoin"] == "os.path.join"

    def test_parse_relative_import(self, provider):
        content = "from .utils import helper\n"
        result = provider.parse_imports(content)
        assert result["helper"] == ".utils.helper"

    def test_parse_multi_import(self, provider):
        content = "from typing import Optional, Dict\n"
        result = provider.parse_imports(content)
        assert result["Optional"] == "typing.Optional"
        assert result["Dict"] == "typing.Dict"

    def test_parse_parenthesized_import_with_comments(self, provider):
        content = "from os.path import (\n    join,  # for joining\n    # dirname,\n    exists,\n)\n"
        result = provider.parse_imports(content)
        assert "join" in result
        assert "exists" in result
        assert "dirname" not in result

    def test_parse_imports_falls_back_to_source_bytes_when_node_text_missing(self, provider, monkeypatch):
        from navigation.tree_sitter_core import TreeSitterCore

        class _FakeNode:
            def __init__(self, start_byte, end_byte, text=None):
                self.start_byte = start_byte
                self.end_byte = end_byte
                self.text = text

        content = "from typing import Optional\n"
        provider._ensure_queries = lambda: None
        provider._imp_query = object()

        monkeypatch.setattr(TreeSitterCore, "parse", lambda source, lang: object())
        monkeypatch.setattr(
            TreeSitterCore,
            "run_query",
            lambda tree, query: [
                (
                    0,
                    {
                        "module": [_FakeNode(5, 11)],
                        "name": [_FakeNode(19, 27)],
                    },
                )
            ],
        )

        assert provider.parse_imports(content) == {"Optional": "typing.Optional"}


class TestTreeSitterTsProvider:
    """Tests for the TypeScript/JavaScript Tree-sitter navigation provider."""

    @pytest.fixture
    def provider(self):
        from navigation.tree_sitter_ts_provider import TreeSitterTsProvider

        return TreeSitterTsProvider()

    def test_supports_language(self, provider):
        assert provider.supports_language(".ts") is True
        assert provider.supports_language(".tsx") is True
        assert provider.supports_language(".js") is True
        assert provider.supports_language(".jsx") is True
        assert provider.supports_language(".py") is False

    def test_find_function(self, provider):
        content = "function greet(name: string) {}\n"
        assert provider.find_symbol_in_content(content, "greet") == 1

    def test_find_exported_function(self, provider):
        content = "export function greet(name: string) {}\n"
        assert provider.find_symbol_in_content(content, "greet") == 1

    def test_find_class(self, provider):
        content = "class UserService {}\n"
        assert provider.find_symbol_in_content(content, "UserService") == 1

    def test_find_interface(self, provider):
        content = "interface Config { port: number }\n"
        assert provider.find_symbol_in_content(content, "Config") == 1

    def test_find_type_alias(self, provider):
        content = "type ID = string | number\n"
        assert provider.find_symbol_in_content(content, "ID") == 1

    def test_find_enum(self, provider):
        content = "enum Color { Red, Green, Blue }\n"
        assert provider.find_symbol_in_content(content, "Color") == 1

    def test_find_const(self, provider):
        content = 'const API_URL = "http://localhost"\n'
        assert provider.find_symbol_in_content(content, "API_URL") == 1

    def test_find_arrow_function(self, provider):
        content = "const handler = () => {}\n"
        assert provider.find_symbol_in_content(content, "handler") == 1

    def test_find_exported_const(self, provider):
        content = "export const handler = () => {}\n"
        assert provider.find_symbol_in_content(content, "handler") == 1

    def test_not_found(self, provider):
        content = "function foo() {}\n"
        assert provider.find_symbol_in_content(content, "bar") is None

    def test_find_js_function(self, provider):
        content = "function foo() {}\n"
        assert provider.find_symbol_in_content(content, "foo", ".js") == 1

    def test_find_js_class(self, provider):
        content = "class Bar {}\n"
        assert provider.find_symbol_in_content(content, "Bar", ".js") == 1

    def test_parse_named_import(self, provider):
        content = 'import { useState } from "react"\n'
        result = provider.parse_imports(content)
        assert result["useState"] == "react"

    def test_parse_multiple_named_imports(self, provider):
        content = 'import { useState, useEffect } from "react"\n'
        result = provider.parse_imports(content)
        assert result["useState"] == "react"
        assert result["useEffect"] == "react"

    def test_parse_default_import(self, provider):
        content = 'import React from "react"\n'
        result = provider.parse_imports(content)
        assert result["React"] == "react"

    def test_parse_namespace_import(self, provider):
        content = 'import * as path from "path"\n'
        result = provider.parse_imports(content)
        assert result["path"] == "path"

    def test_find_tsx_component(self, provider):
        content = "const App = () => <div/>\n"
        assert provider.find_symbol_in_content(content, "App", ".tsx") == 1

    def test_multiline_definitions(self, provider):
        content = "function first() {}\n\nclass Second {}\n\nconst third = 42\n"
        assert provider.find_symbol_in_content(content, "first") == 1
        assert provider.find_symbol_in_content(content, "Second") == 3
        assert provider.find_symbol_in_content(content, "third") == 5

    def test_find_member_in_enum(self, provider):
        content = "enum Color {\n  Red,\n  Green,\n  Blue,\n}\n"
        assert provider.find_member_in_content(content, "Color", "Green") == 3

    def test_find_member_in_class(self, provider):
        content = "class Foo {\n  bar() {}\n  baz: number\n}\n"
        assert provider.find_member_in_content(content, "Foo", "bar") == 2

    def test_find_member_in_exported_enum(self, provider):
        content = "export enum Status {\n  Active,\n  Inactive,\n}\n"
        assert provider.find_member_in_content(content, "Status", "Active") == 2

    def test_find_member_not_found(self, provider):
        content = "enum Color {\n  Red,\n  Green,\n}\n"
        assert provider.find_member_in_content(content, "Color", "Blue") is None

    def test_find_member_wrong_container(self, provider):
        content = "enum Color {\n  Red,\n}\nenum Size {\n  Large,\n}\n"
        assert provider.find_member_in_content(content, "Color", "Large") is None

    def test_find_member_container_not_found(self, provider):
        content = "enum Color {\n  Red,\n}\n"
        assert provider.find_member_in_content(content, "Unknown", "Red") is None


class TestPyProviderNewMethods:
    """Tests for new TreeSitterPyProvider methods (variable class, self attr, params, etc.)."""

    @pytest.fixture
    def provider(self):
        from navigation.tree_sitter_py_provider import TreeSitterPyProvider

        return TreeSitterPyProvider()

    # --- find_variable_class ---
    def test_variable_class_simple(self, provider):
        content = "validator = SomeValidator()\n"
        assert provider.find_variable_class(content, "validator") == "SomeValidator"

    def test_variable_class_qualified(self, provider):
        content = "client = vault.Client(token)\n"
        assert provider.find_variable_class(content, "client") == "vault.Client"

    def test_variable_class_lowercase_rhs_ignored(self, provider):
        content = "x = simple_func()\n"
        assert provider.find_variable_class(content, "x") is None

    def test_variable_class_not_a_call(self, provider):
        content = "y = 42\n"
        assert provider.find_variable_class(content, "y") is None

    def test_variable_class_not_found(self, provider):
        content = "x = Foo()\n"
        assert provider.find_variable_class(content, "y") is None

    def test_variable_class_indented(self, provider):
        content = "def f():\n    mgr = Manager(cfg)\n"
        assert provider.find_variable_class(content, "mgr") == "Manager"

    # --- find_self_attr_class ---
    def test_self_attr_simple(self, provider):
        content = "self.utils = MyClass(arg1)\n"
        assert provider.find_self_attr_class(content, "utils") == "MyClass"

    def test_self_attr_qualified(self, provider):
        content = "self.client = vault.Client()\n"
        assert provider.find_self_attr_class(content, "client") == "vault.Client"

    def test_self_attr_not_found(self, provider):
        content = "self.utils = MyClass(arg1)\n"
        assert provider.find_self_attr_class(content, "other") is None

    def test_self_attr_lowercase_rhs(self, provider):
        content = "self.x = some_func()\n"
        assert provider.find_self_attr_class(content, "x") is None

    def test_self_attr_in_init(self, provider):
        content = "class Foo:\n    def __init__(self):\n        self.bar = BarClass()\n"
        assert provider.find_self_attr_class(content, "bar") == "BarClass"

    # --- find_import_source ---
    def test_import_source_relative(self, provider):
        content = "from .settings_manager import get_setting\n"
        assert provider.find_import_source(content, "get_setting") == ".settings_manager"

    def test_import_source_absolute(self, provider):
        content = "from shared.settings import Manager\n"
        assert provider.find_import_source(content, "Manager") == "shared.settings"

    def test_import_source_not_found(self, provider):
        content = "from os import path\n"
        assert provider.find_import_source(content, "missing") is None

    def test_import_source_double_relative(self, provider):
        content = "from ..utils import helper\n"
        assert provider.find_import_source(content, "helper") == "..utils"

    def test_import_source_parenthesized(self, provider):
        content = "from .core import (\n    Foo,\n    Bar,\n)\n"
        assert provider.find_import_source(content, "Bar") == ".core"

    # --- find_import_line ---
    def test_import_line_simple(self, provider):
        content = "import os\nfrom typing import Optional\nx = 1\n"
        assert provider.find_import_line(content, "Optional") == 2

    def test_import_line_not_found(self, provider):
        content = "import os\n"
        assert provider.find_import_line(content, "missing") is None

    def test_import_line_parenthesized(self, provider):
        content = "from os.path import (\n    join,\n    exists,\n)\n"
        # The import statement starts on line 1
        assert provider.find_import_line(content, "join") == 1

    # --- find_param_declaration ---
    def test_param_simple(self, provider):
        content = "def foo(x, y):\n    return x + y\n"
        assert provider.find_param_declaration(content, "x", 2) == 1

    def test_param_typed(self, provider):
        content = "def process(validator: SomeValidator, count: int = 0):\n    validator.run()\n"
        assert provider.find_param_declaration(content, "validator", 2) == 1

    def test_param_not_found(self, provider):
        content = "def foo(x):\n    return z\n"
        assert provider.find_param_declaration(content, "z", 2) is None

    def test_param_on_same_line_returns_none(self, provider):
        content = "def foo(x):\n    pass\n"
        assert provider.find_param_declaration(content, "x", 1) is None

    def test_param_multiline_signature(self, provider):
        content = "def foo(\n    first,\n    second,\n):\n    return first + second\n"
        assert provider.find_param_declaration(content, "second", 5) == 3

    def test_param_nested_function(self, provider):
        content = "def outer(a):\n    def inner(b):\n        return b\n    return inner(a)\n"
        # Clicking on line 3 (return b), inner's param b
        assert provider.find_param_declaration(content, "b", 3) == 2

    def test_param_kwargs(self, provider):
        content = "def foo(**kwargs):\n    print(kwargs)\n"
        assert provider.find_param_declaration(content, "kwargs", 2) == 1

    def test_param_args(self, provider):
        content = "def foo(*args):\n    print(args)\n"
        assert provider.find_param_declaration(content, "args", 2) == 1

    # --- find_constructor_class ---
    def test_constructor_simple(self, provider):
        content = "MyClass(arg).method()"
        assert provider.find_constructor_class(content, "method") == "MyClass"

    def test_constructor_not_found(self, provider):
        content = "foo().bar()"
        assert provider.find_constructor_class(content, "bar") is None

    def test_constructor_qualified(self, provider):
        content = "result = mod.MyClass(x).process()"
        assert provider.find_constructor_class(content, "process") == "mod.MyClass"

    def test_constructor_no_chain(self, provider):
        content = "MyClass(arg)"
        assert provider.find_constructor_class(content, "method") is None
