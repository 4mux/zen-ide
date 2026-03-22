"""Tests for editor/autocomplete/python_provider.py - Python completions."""

from editor.autocomplete.python_provider import PythonCompletionProvider
from editor.autocomplete.tree_sitter_provider import (
    _find_class_node,
    _is_dataclass_node,
    _parse,
    py_extract_class_members,
    py_extract_definitions,
    py_extract_imports,
    py_extract_init_signature,
    py_find_enclosing_class,
    py_resolve_chain,
    py_resolve_variable_type,
)


def _py(text):
    """Parse Python text and return (source_bytes, tree)."""
    source, tree = _parse(text, "python")
    assert tree is not None, f"Failed to parse: {text[:60]}"
    return source, tree


class TestGetImports:
    """Test import extraction from Python source."""

    def test_simple_import(self):
        source, tree = _py("import os")
        items = py_extract_imports(source, tree)
        names = [i.name for i in items]
        assert "os" in names

    def test_aliased_import(self):
        source, tree = _py("import numpy as np")
        items = py_extract_imports(source, tree)
        names = [i.name for i in items]
        assert "np" in names

    def test_from_import(self):
        source, tree = _py("from os.path import join, dirname")
        items = py_extract_imports(source, tree)
        names = [i.name for i in items]
        assert "join" in names
        assert "dirname" in names

    def test_from_import_with_alias(self):
        source, tree = _py("from collections import OrderedDict as OD")
        items = py_extract_imports(source, tree)
        names = [i.name for i in items]
        assert "OD" in names


class TestGetSymbols:
    """Test local symbol extraction."""

    def test_class_definition(self):
        source, tree = _py("class MyClass:\n    pass")
        items = py_extract_definitions(source, tree)
        names = [i.name for i in items]
        assert "MyClass" in names

    def test_function_definition(self):
        source, tree = _py("def hello(name: str) -> str:\n    pass")
        items = py_extract_definitions(source, tree)
        names = [i.name for i in items]
        assert "hello" in names

    def test_function_with_signature(self):
        source, tree = _py("def greet(name: str) -> str:\n    pass")
        items = py_extract_definitions(source, tree)
        funcs = [i for i in items if i.name == "greet"]
        assert len(funcs) == 1
        assert "greet" in funcs[0].signature

    def test_variable_assignment(self):
        source, tree = _py("MY_CONST = 42")
        items = py_extract_definitions(source, tree)
        names = [i.name for i in items]
        assert "MY_CONST" in names

    def test_dunder_excluded(self):
        source, tree = _py("__all__ = ['foo']")
        items = py_extract_definitions(source, tree)
        names = [i.name for i in items]
        assert "__all__" not in names


class TestNormalizeMultilineDefs:
    """Test that multi-line defs are handled correctly via tree-sitter."""

    def test_single_line_unchanged(self):
        source, tree = _py("def foo(x): pass")
        items = py_extract_definitions(source, tree)
        assert any(i.name == "foo" for i in items)

    def test_multiline_joined(self):
        text = "def foo(\n    x,\n    y\n):\n    pass"
        source, tree = _py(text)
        items = py_extract_definitions(source, tree)
        funcs = [i for i in items if i.name == "foo"]
        assert len(funcs) == 1
        assert "x" in funcs[0].signature
        assert "y" in funcs[0].signature


class TestGetCompletions:
    """Test full completions list."""

    def test_includes_keywords(self):
        p = PythonCompletionProvider()
        items = p.get_completions("")
        names = [i.name for i in items]
        assert "if" in names
        assert "def" in names
        assert "class" in names

    def test_includes_builtins(self):
        p = PythonCompletionProvider()
        items = p.get_completions("")
        names = [i.name for i in items]
        assert "len" in names
        assert "print" in names
        assert "isinstance" in names


class TestFindEnclosingClass:
    """Test enclosing class detection."""

    def test_finds_class(self):
        text = "class Foo:\n    def bar(self):\n        self."
        source, tree = _py(text)
        byte_offset = len(text.encode("utf-8"))
        result = py_find_enclosing_class(source, tree, byte_offset)
        assert result == "Foo"

    def test_no_class(self):
        text = "def standalone():\n    pass"
        source, tree = _py(text)
        byte_offset = len(text.encode("utf-8"))
        result = py_find_enclosing_class(source, tree, byte_offset)
        assert result is None


class TestExtractClassMembers:
    """Test class member extraction."""

    def test_extracts_methods(self):
        text = "class Foo:\n    def bar(self):\n        pass\n    def baz(self) -> int:\n        pass"
        source, tree = _py(text)
        items = py_extract_class_members(source, tree, "Foo")
        names = [i.name for i in items]
        assert "bar" in names
        assert "baz" in names

    def test_excludes_private(self):
        text = "class Foo:\n    def _private(self):\n        pass\n    def public(self):\n        pass"
        source, tree = _py(text)
        items = py_extract_class_members(source, tree, "Foo")
        names = [i.name for i in items]
        assert "_private" not in names
        assert "public" in names

    def test_extracts_attributes(self):
        text = "class Foo:\n    count = 0\n    name = 'test'"
        source, tree = _py(text)
        items = py_extract_class_members(source, tree, "Foo")
        names = [i.name for i in items]
        assert "count" in names
        assert "name" in names


class TestGetClassBodyText:
    """Test class body traversal via tree-sitter (replaces text extraction)."""

    def test_extracts_body(self):
        text = "class Foo:\n    x = 1\n    def bar(self):\n        pass\n\nclass Other:\n    pass"
        source, tree = _py(text)
        items = py_extract_class_members(source, tree, "Foo", include_private=True)
        names = [i.name for i in items]
        assert "x" in names
        assert "bar" in names

    def test_class_not_found(self):
        text = "class Foo:\n    pass"
        source, tree = _py(text)
        items = py_extract_class_members(source, tree, "Bar")
        assert items == []


class TestResolveVariableType:
    """Test variable type resolution from assignments."""

    def test_constructor_call(self):
        text = "client = OnboardingClient(config)"
        source, tree = _py(text)
        assert py_resolve_variable_type(source, tree, "client") == "OnboardingClient"

    def test_module_constructor_call(self):
        text = "client = clients.OnboardingClient(config)"
        source, tree = _py(text)
        assert py_resolve_variable_type(source, tree, "client") == "OnboardingClient"

    def test_type_annotation(self):
        text = "client: OnboardingClient = create_client()"
        source, tree = _py(text)
        assert py_resolve_variable_type(source, tree, "client") == "OnboardingClient"

    def test_no_match(self):
        text = "x = 42"
        source, tree = _py(text)
        assert py_resolve_variable_type(source, tree, "x") is None

    def test_not_found(self):
        text = "other = Foo()"
        source, tree = _py(text)
        assert py_resolve_variable_type(source, tree, "client") is None


class TestResolveChainInTextNoFalsePositive:
    """Test that py_resolve_chain doesn't return wrong methods for variables."""

    def test_variable_at_top_level_returns_empty(self):
        """A variable assignment at top level should NOT return all methods from the file."""
        text = (
            "from clients import OnboardingClient\n"
            "\n"
            "class Handler:\n"
            "    def process(self):\n"
            "        pass\n"
            "\n"
            "onboarding_client = OnboardingClient()\n"
        )
        source, tree = _py(text)
        result = py_resolve_chain(source, tree, ["onboarding_client"])
        assert result == []

    def test_enum_member_inside_class_still_works(self):
        """Attribute access on a class returns its members."""
        text = "class Status:\n    ACTIVE = 'active'\n    INACTIVE = 'inactive'\n    def label(self) -> str:\n        pass\n"
        source, tree = _py(text)
        # Resolve ["Status"] to get the class members
        result = py_resolve_chain(source, tree, ["Status"])
        names = [i.name for i in result]
        assert "label" in names
        assert "ACTIVE" in names


class TestPeekDocstring:
    """Test docstring extraction from function/class definitions via tree-sitter."""

    def test_triple_quoted_docstring(self):
        text = 'class C:\n    def foo(self):\n        """This is foo."""\n        pass'
        source, tree = _py(text)
        items = py_extract_class_members(source, tree, "C", include_private=True)
        item = next(i for i in items if i.name == "foo")
        assert item.docstring == "This is foo."

    def test_single_quoted_docstring(self):
        text = "class C:\n    def bar(self):\n        '''Bar doc.'''\n        pass"
        source, tree = _py(text)
        items = py_extract_class_members(source, tree, "C", include_private=True)
        item = next(i for i in items if i.name == "bar")
        assert item.docstring == "Bar doc."

    def test_multiline_docstring(self):
        text = 'class C:\n    def baz(self):\n        """\n        Baz description.\n        """\n        pass'
        source, tree = _py(text)
        items = py_extract_class_members(source, tree, "C", include_private=True)
        item = next(i for i in items if i.name == "baz")
        assert item.docstring == "Baz description."

    def test_multiline_docstring_content_after_quote(self):
        text = 'class C:\n    def qux(self):\n        """Qux description.\n        More info.\n        """\n        pass'
        source, tree = _py(text)
        items = py_extract_class_members(source, tree, "C", include_private=True)
        item = next(i for i in items if i.name == "qux")
        assert item.docstring == "Qux description."

    def test_hash_comment_above_def(self):
        """Tree-sitter extracts actual docstrings, not comments above defs."""
        text = "class C:\n    # Calculate the sum of values\n    def calc_sum(self, values):\n        pass"
        source, tree = _py(text)
        items = py_extract_class_members(source, tree, "C", include_private=True)
        item = next(i for i in items if i.name == "calc_sum")
        assert item.docstring == ""

    def test_hash_comment_with_blank_line(self):
        """Tree-sitter extracts actual docstrings, not comments."""
        text = "class C:\n    # Helper function\n\n    def helper(self):\n        pass"
        source, tree = _py(text)
        items = py_extract_class_members(source, tree, "C", include_private=True)
        item = next(i for i in items if i.name == "helper")
        assert item.docstring == ""

    def test_docstring_preferred_over_comment(self):
        text = 'class C:\n    # Above comment\n    def foo(self):\n        """Docstring wins."""\n        pass'
        source, tree = _py(text)
        items = py_extract_class_members(source, tree, "C", include_private=True)
        item = next(i for i in items if i.name == "foo")
        assert item.docstring == "Docstring wins."

    def test_no_docstring_no_comment(self):
        text = "class C:\n    x = 1\n    def foo(self):\n        pass"
        source, tree = _py(text)
        items = py_extract_class_members(source, tree, "C", include_private=True)
        item = next(i for i in items if i.name == "foo")
        assert item.docstring == ""

    def test_first_def_at_index_zero(self):
        text = "def first():\n    pass"
        source, tree = _py(text)
        items = py_extract_definitions(source, tree)
        item = next(i for i in items if i.name == "first")
        assert item.docstring == ""


class TestExtractDocstringAt:
    """Test docstring extraction from top-level definitions via tree-sitter."""

    def test_docstring_after_def(self):
        text = 'def foo():\n    """Foo docs."""\n    pass'
        source, tree = _py(text)
        items = py_extract_definitions(source, tree)
        item = next(i for i in items if i.name == "foo")
        assert item.docstring == "Foo docs."

    def test_comment_above_def(self):
        """Tree-sitter only extracts actual docstrings, not comments above defs."""
        text = "# Initialize the connection\ndef connect():\n    pass"
        source, tree = _py(text)
        items = py_extract_definitions(source, tree)
        item = next(i for i in items if i.name == "connect")
        assert item.docstring == ""

    def test_docstring_preferred_over_comment(self):
        text = '# Above comment\ndef foo():\n    """Docstring."""\n    pass'
        source, tree = _py(text)
        items = py_extract_definitions(source, tree)
        item = next(i for i in items if i.name == "foo")
        assert item.docstring == "Docstring."

    def test_no_docstring_no_comment(self):
        text = "x = 1\ndef foo():\n    pass"
        source, tree = _py(text)
        items = py_extract_definitions(source, tree)
        item = next(i for i in items if i.name == "foo")
        assert item.docstring == ""


class TestClassMembersDocstrings:
    """Test that class member extraction includes docstrings."""

    def test_method_with_docstring(self):
        text = 'class MyClass:\n    def greet(self, name):\n        """Say hello."""\n        pass\n'
        source, tree = _py(text)
        items = py_extract_class_members(source, tree, "MyClass")
        item = next(i for i in items if i.name == "greet")
        assert item.docstring == "Say hello."

    def test_method_with_comment(self):
        """Tree-sitter only extracts actual docstrings, not comments."""
        text = "class MyClass:\n    # Compute the total\n    def total(self):\n        return 42\n"
        source, tree = _py(text)
        items = py_extract_class_members(source, tree, "MyClass")
        item = next(i for i in items if i.name == "total")
        assert item.docstring == ""

    def test_method_no_doc(self):
        text = "class MyClass:\n    x = 1\n    def run(self):\n        pass\n"
        source, tree = _py(text)
        items = py_extract_class_members(source, tree, "MyClass")
        item = next(i for i in items if i.name == "run")
        assert item.docstring == ""


class TestFollowReexport:
    """Test _follow_reexport_ts for __init__.py re-export resolution."""

    def test_matches_reexport(self):
        p = PythonCompletionProvider()
        init_text = "from .db_handler import DBHandler\nfrom .utils import helper\n"
        source, tree = _py(init_text)
        result = p._follow_reexport_ts(source, tree, "DBHandler", "mypkg", "/fake/path.py")
        assert result is None  # file not found on disk, but logic is correct

    def test_no_match_returns_none(self):
        p = PythonCompletionProvider()
        init_text = "from .utils import helper\n"
        source, tree = _py(init_text)
        result = p._follow_reexport_ts(source, tree, "NoSuchClass", "mypkg", "/fake/path.py")
        assert result is None

    def test_matches_among_multiple_imports(self):
        p = PythonCompletionProvider()
        init_text = "from .sub import Alpha, Beta, Gamma\n"
        source, tree = _py(init_text)
        result = p._follow_reexport_ts(source, tree, "Beta", "mypkg", "/fake/path.py")
        assert result is None

    def test_does_not_match_non_relative_import(self):
        p = PythonCompletionProvider()
        init_text = "from other_pkg import MyClass\n"
        source, tree = _py(init_text)
        result = p._follow_reexport_ts(source, tree, "MyClass", "mypkg", "/fake/path.py")
        assert result is None


class TestReexportResolveDotCompletions:
    """Test that resolve_dot_completions follows __init__.py re-exports."""

    def test_follows_reexport_to_submodule(self, tmp_path):
        """When __init__.py re-exports a class, completions come from the submodule."""
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from .handler import MyHandler\n")
        (pkg / "handler.py").write_text(
            "class MyHandler:\n"
            '    def fetch(self, key):\n        """Fetch an item."""\n        pass\n'
            "    def save(self, item):\n        pass\n"
        )
        # Create a .git marker so _find_module_file stops walking
        (tmp_path / ".git").mkdir()

        # Caller file that imports MyHandler from mypkg
        caller = tmp_path / "app.py"
        caller.write_text("from mypkg import MyHandler\nhandler = MyHandler()\nhandler.\n")

        p = PythonCompletionProvider()
        items = p.resolve_dot_completions("handler", str(caller), caller.read_text())
        names = [i.name for i in items]
        assert "fetch" in names
        assert "save" in names

    def test_no_reexport_returns_empty(self, tmp_path):
        """When the class isn't in the module at all, returns empty."""
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("VERSION = '1.0'\n")
        (tmp_path / ".git").mkdir()

        caller = tmp_path / "app.py"
        caller.write_text("from mypkg import Missing\nobj = Missing()\nobj.\n")

        p = PythonCompletionProvider()
        items = p.resolve_dot_completions("obj", str(caller), caller.read_text())
        assert items == []


class TestDataclassSignature:
    """Test dataclass field extraction for constructor signatures."""

    @staticmethod
    def _init_sig(text, class_name):
        """Parse text and extract init signature for the named class."""
        source, tree = _py(text)
        class_node = _find_class_node(source, tree.root_node, class_name)
        if class_node is None:
            return f"{class_name}()"
        return py_extract_init_signature(source, class_node)

    def test_basic_dataclass_fields(self):
        text = (
            "from dataclasses import dataclass\n\n"
            "@dataclass\n"
            "class User:\n"
            "    name: str\n"
            "    age: int\n"
            "    active: bool = True\n"
        )
        sig = self._init_sig(text, "User")
        assert sig == "User(name: str, age: int, active: bool)"

    def test_dataclass_with_no_fields(self):
        text = "@dataclass\nclass Empty:\n    pass\n"
        sig = self._init_sig(text, "Empty")
        assert sig == "Empty()"

    def test_dataclass_skips_classvar(self):
        text = "@dataclass\nclass Config:\n    name: str\n    ClassVar_count: int\n    registry: ClassVar[dict] = {}\n"
        sig = self._init_sig(text, "Config")
        assert "registry" not in sig
        assert "name" in sig

    def test_dataclass_skips_field_init_false(self):
        text = "@dataclass\nclass Item:\n    name: str\n    computed: int = field(init=False, default=0)\n"
        sig = self._init_sig(text, "Item")
        assert "name" in sig
        assert "computed" not in sig

    def test_dataclasses_dot_dataclass(self):
        text = "@dataclasses.dataclass\nclass Point:\n    x: float\n    y: float\n"
        sig = self._init_sig(text, "Point")
        assert sig == "Point(x: float, y: float)"

    def test_dataclass_with_args(self):
        text = "@dataclass(frozen=True)\nclass Coord:\n    lat: float\n    lon: float\n"
        sig = self._init_sig(text, "Coord")
        assert sig == "Coord(lat: float, lon: float)"

    def test_not_a_dataclass(self):
        text = "class Plain:\n    x: int\n    y: int\n"
        sig = self._init_sig(text, "Plain")
        assert sig == "Plain()"

    def test_dataclass_with_explicit_init(self):
        """If a dataclass has explicit __init__, use that instead of fields."""
        text = (
            "@dataclass\n"
            "class Custom:\n"
            "    name: str\n"
            "    def __init__(self, name: str, extra: int):\n"
            "        self.name = name\n"
        )
        sig = self._init_sig(text, "Custom")
        assert sig == "Custom(self, name: str, extra: int)"

    def test_is_dataclass_with_other_decorators(self):
        text = "@some_decorator\n@dataclass\nclass Multi:\n    value: int\n"
        source, tree = _py(text)
        class_node = _find_class_node(source, tree.root_node, "Multi")
        assert _is_dataclass_node(source, class_node) is True

    def test_is_dataclass_false_for_plain_class(self):
        text = "class Plain:\n    pass\n"
        source, tree = _py(text)
        class_node = _find_class_node(source, tree.root_node, "Plain")
        assert _is_dataclass_node(source, class_node) is False

    def test_dataclass_completions_integration(self):
        """get_completions returns dataclass with proper signature."""
        p = PythonCompletionProvider()
        text = "from dataclasses import dataclass\n\n@dataclass\nclass Record:\n    id: int\n    label: str\n"
        items = p.get_completions(text)
        record = next((i for i in items if i.name == "Record"), None)
        assert record is not None
        assert "id: int" in record.signature
        assert "label: str" in record.signature


# ---------------------------------------------------------------------------
# Parameter completion tests
# ---------------------------------------------------------------------------


class TestSplitCallArgs:
    """Test argument splitting for function calls."""

    def test_simple_args(self):
        p = PythonCompletionProvider()
        assert p._split_call_args("a, b, c") == ["a", "b", "c"]

    def test_empty(self):
        p = PythonCompletionProvider()
        assert p._split_call_args("") == []

    def test_nested_parens(self):
        p = PythonCompletionProvider()
        result = p._split_call_args("func(x, y), b")
        assert result == ["func(x, y)", "b"]

    def test_string_with_comma(self):
        p = PythonCompletionProvider()
        result = p._split_call_args('"hello, world", b')
        assert result == ['"hello, world"', "b"]

    def test_keyword_args(self):
        p = PythonCompletionProvider()
        result = p._split_call_args("a, key=True, other=3")
        assert result == ["a", "key=True", "other=3"]

    def test_nested_brackets(self):
        p = PythonCompletionProvider()
        result = p._split_call_args("[1, 2], {a: b}")
        assert result == ["[1, 2]", "{a: b}"]


class TestParseParamsWithDefaults:
    """Test parameter parsing from function signatures."""

    def test_simple_params(self):
        p = PythonCompletionProvider()
        result = p._parse_params_with_defaults("func(a, b, c)")
        assert result == [("a", None), ("b", None), ("c", None)]

    def test_strips_self(self):
        p = PythonCompletionProvider()
        result = p._parse_params_with_defaults("method(self, a, b)")
        assert result == [("a", None), ("b", None)]

    def test_strips_cls(self):
        p = PythonCompletionProvider()
        result = p._parse_params_with_defaults("method(cls, a)")
        assert result == [("a", None)]

    def test_default_values(self):
        p = PythonCompletionProvider()
        result = p._parse_params_with_defaults("func(a, b=True, c=None)")
        assert result == [("a", None), ("b", "True"), ("c", "None")]

    def test_type_annotations(self):
        p = PythonCompletionProvider()
        result = p._parse_params_with_defaults("func(a: int, b: str = 'hello')")
        assert result == [("a", None), ("b", "'hello'")]

    def test_skips_star_args(self):
        p = PythonCompletionProvider()
        result = p._parse_params_with_defaults("func(a, *args, **kwargs)")
        assert result == [("a", None)]

    def test_keyword_only_after_star(self):
        p = PythonCompletionProvider()
        result = p._parse_params_with_defaults("func(a, *, key=True)")
        assert result == [("a", None), ("key", "True")]

    def test_empty_params(self):
        p = PythonCompletionProvider()
        result = p._parse_params_with_defaults("func()")
        assert result == []

    def test_self_only(self):
        p = PythonCompletionProvider()
        result = p._parse_params_with_defaults("method(self)")
        assert result == []

    def test_positional_only_separator(self):
        p = PythonCompletionProvider()
        result = p._parse_params_with_defaults("func(a, /, b)")
        assert result == [("a", None), ("b", None)]


class TestDetectCallContext:
    """Test function call context detection using GtkTextBuffer mock."""

    @staticmethod
    def _make_buffer(text, cursor_pos):
        """Create a mock buffer with text and cursor at given position."""
        from unittest.mock import MagicMock

        class FakeIter:
            def __init__(self, pos):
                self._pos = pos
                self._text = text

            def copy(self):
                return FakeIter(self._pos)

            def get_char(self):
                if 0 <= self._pos < len(self._text):
                    return self._text[self._pos]
                return "\0"

            def get_offset(self):
                return self._pos

            def backward_char(self):
                if self._pos > 0:
                    self._pos -= 1
                    return True
                return False

            def forward_char(self):
                if self._pos < len(self._text):
                    self._pos += 1
                    return True
                return False

        buf = MagicMock()

        def get_text(start, end, hidden):
            return text[start._pos : end._pos]

        buf.get_text = get_text
        cursor_iter = FakeIter(cursor_pos)
        return buf, cursor_iter

    def test_simple_call(self):
        p = PythonCompletionProvider()
        text = "func(a, "
        buf, cursor = self._make_buffer(text, len(text))
        result = p._detect_call_context(buf, cursor)
        assert result is not None
        func_chain, kwargs, pos_count = result
        assert func_chain == "func"
        assert pos_count == 1
        assert kwargs == set()

    def test_call_with_kwargs(self):
        p = PythonCompletionProvider()
        text = "func(a, key=True, "
        buf, cursor = self._make_buffer(text, len(text))
        result = p._detect_call_context(buf, cursor)
        func_chain, kwargs, pos_count = result
        assert func_chain == "func"
        assert pos_count == 1
        assert kwargs == {"key"}

    def test_method_call(self):
        p = PythonCompletionProvider()
        text = "self.get_item(card_id, "
        buf, cursor = self._make_buffer(text, len(text))
        result = p._detect_call_context(buf, cursor)
        func_chain, kwargs, pos_count = result
        assert func_chain == "self.get_item"
        assert pos_count == 1

    def test_nested_call(self):
        p = PythonCompletionProvider()
        text = "func(other(x), "
        buf, cursor = self._make_buffer(text, len(text))
        result = p._detect_call_context(buf, cursor)
        func_chain, kwargs, pos_count = result
        assert func_chain == "func"
        assert pos_count == 1

    def test_empty_call(self):
        p = PythonCompletionProvider()
        text = "func("
        buf, cursor = self._make_buffer(text, len(text))
        result = p._detect_call_context(buf, cursor)
        func_chain, kwargs, pos_count = result
        assert func_chain == "func"
        assert pos_count == 0
        assert kwargs == set()

    def test_skips_keywords(self):
        p = PythonCompletionProvider()
        text = "if ("
        buf, cursor = self._make_buffer(text, len(text))
        result = p._detect_call_context(buf, cursor)
        assert result is None

    def test_not_in_call(self):
        p = PythonCompletionProvider()
        text = "x = 42\n"
        buf, cursor = self._make_buffer(text, len(text))
        result = p._detect_call_context(buf, cursor)
        assert result is None

    def test_dotted_method_call(self):
        p = PythonCompletionProvider()
        text = "db_table.get_item(card_id, "
        buf, cursor = self._make_buffer(text, len(text))
        result = p._detect_call_context(buf, cursor)
        func_chain, kwargs, pos_count = result
        assert func_chain == "db_table.get_item"
        assert pos_count == 1


class TestResolveFunctionSignature:
    """Test function signature resolution."""

    def test_local_function(self):
        p = PythonCompletionProvider()
        text = "def get_item(card_id, strong_consistent_read=False):\n    pass\n"
        sig = p._resolve_function_signature("get_item", None, text)
        assert sig is not None
        assert "card_id" in sig
        assert "strong_consistent_read=False" in sig

    def test_local_method_via_self(self):
        p = PythonCompletionProvider()
        text = (
            "class MyService:\n"
            "    def process(self, item_id: str, retry: bool = True) -> dict:\n"
            "        pass\n"
            "    def run(self):\n"
            "        self.process(x, "
        )
        cursor_offset = len(text)
        sig = p._resolve_function_signature("self.process", None, text, cursor_offset=cursor_offset)
        assert sig is not None
        assert "item_id" in sig
        assert "retry" in sig

    def test_local_class_constructor(self):
        p = PythonCompletionProvider()
        text = "class Config:\n    def __init__(self, host: str, port: int = 8080):\n        pass\n"
        sig = p._resolve_function_signature("Config", None, text)
        assert sig is not None
        assert "host" in sig
        assert "port" in sig

    def test_multiline_function(self):
        p = PythonCompletionProvider()
        text = "def fetch(\n    url: str,\n    timeout: int = 30,\n    verify: bool = True\n) -> dict:\n    pass\n"
        sig = p._resolve_function_signature("fetch", None, text)
        assert sig is not None
        assert "url" in sig
        assert "timeout" in sig
        assert "verify" in sig

    def test_resolved_variable_type(self):
        p = PythonCompletionProvider()
        text = (
            "class Client:\n"
            "    def connect(self, host: str, port: int = 443):\n"
            "        pass\n\n"
            "client = Client()\n"
            "client.connect("
        )
        sig = p._resolve_function_signature("client.connect", None, text)
        assert sig is not None
        assert "host" in sig
        assert "port" in sig


class TestCallParameterCompletionsEndToEnd:
    """End-to-end tests for parameter completions using buffer mock."""

    @staticmethod
    def _make_buffer(text, cursor_pos):
        return TestDetectCallContext._make_buffer(text, cursor_pos)

    def test_suggests_remaining_params(self):
        p = PythonCompletionProvider()
        code = "def get_item(card_id, strong_consistent_read=False):\n    pass\n\nget_item(card_id, "
        buf, cursor = self._make_buffer(code, len(code))
        items = p.get_call_parameter_completions(buf, cursor, None, code)
        assert len(items) == 1
        assert items[0].name == "strong_consistent_read"
        assert items[0].insert_text == "strong_consistent_read=False"

    def test_no_params_when_all_specified(self):
        p = PythonCompletionProvider()
        code = "def greet(name, greeting='Hello'):\n    pass\n\ngreet(name, greeting='Hi', "
        buf, cursor = self._make_buffer(code, len(code))
        items = p.get_call_parameter_completions(buf, cursor, None, code)
        assert len(items) == 0

    def test_empty_call_shows_all_params(self):
        p = PythonCompletionProvider()
        code = "def fetch(url, timeout=30, verify=True):\n    pass\n\nfetch("
        buf, cursor = self._make_buffer(code, len(code))
        items = p.get_call_parameter_completions(buf, cursor, None, code)
        names = [i.name for i in items]
        assert "url" in names
        assert "timeout" in names
        assert "verify" in names

    def test_skips_positional_args(self):
        p = PythonCompletionProvider()
        code = "def fetch(url, timeout=30, verify=True):\n    pass\n\nfetch(my_url, "
        buf, cursor = self._make_buffer(code, len(code))
        items = p.get_call_parameter_completions(buf, cursor, None, code)
        names = [i.name for i in items]
        assert "url" not in names
        assert "timeout" in names
        assert "verify" in names

    def test_param_has_correct_kind(self):
        from editor.autocomplete import CompletionKind

        p = PythonCompletionProvider()
        code = "def func(a, b=1):\n    pass\n\nfunc("
        buf, cursor = self._make_buffer(code, len(code))
        items = p.get_call_parameter_completions(buf, cursor, None, code)
        assert all(i.kind == CompletionKind.PARAMETER for i in items)

    def test_required_param_insert_text_has_equals(self):
        p = PythonCompletionProvider()
        code = "def func(a, b):\n    pass\n\nfunc("
        buf, cursor = self._make_buffer(code, len(code))
        items = p.get_call_parameter_completions(buf, cursor, None, code)
        a_item = next(i for i in items if i.name == "a")
        assert a_item.insert_text == "a="
