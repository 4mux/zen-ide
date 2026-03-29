"""Tests for debugger/gdb_debugger.py — GDB Machine Interface client."""

import os
import shutil
import subprocess
import tempfile

import pytest

from debugger.gdb_debugger import (
    GdbClient,
    _mi_unescape,
    _parse_mi_dict,
    _parse_mi_list,
    _parse_mi_string,
)


# ── MI output parsing tests ──


class TestMiUnescape:
    def test_newline(self):
        assert _mi_unescape("hello\\nworld") == "hello\nworld"

    def test_tab(self):
        assert _mi_unescape("a\\tb") == "a\tb"

    def test_quote(self):
        assert _mi_unescape('say \\"hi\\"') == 'say "hi"'

    def test_backslash(self):
        assert _mi_unescape("path\\\\to") == "path\\to"

    def test_no_escapes(self):
        assert _mi_unescape("plain text") == "plain text"


class TestParseMiString:
    def test_simple_string(self):
        val, pos = _parse_mi_string('"hello"', 0)
        assert val == "hello"
        assert pos == 7

    def test_string_with_escapes(self):
        val, pos = _parse_mi_string('"line1\\nline2"', 0)
        assert val == "line1\nline2"

    def test_string_with_quotes(self):
        val, pos = _parse_mi_string('"say \\"hi\\""', 0)
        assert val == 'say "hi"'

    def test_empty_string(self):
        val, pos = _parse_mi_string('""', 0)
        assert val == ""


class TestParseMiDict:
    def test_empty(self):
        assert _parse_mi_dict("") == {}

    def test_single_string_value(self):
        result = _parse_mi_dict('reason="breakpoint-hit"')
        assert result == {"reason": "breakpoint-hit"}

    def test_multiple_values(self):
        result = _parse_mi_dict('file="main.c",line="42",func="main"')
        assert result == {"file": "main.c", "line": "42", "func": "main"}

    def test_nested_tuple(self):
        result = _parse_mi_dict('frame={file="main.c",line="10"}')
        assert result == {"frame": {"file": "main.c", "line": "10"}}

    def test_nested_list(self):
        result = _parse_mi_dict('stack=[{level="0",func="main"},{level="1",func="start"}]')
        assert "stack" in result
        assert len(result["stack"]) == 2


class TestParseMiList:
    def test_empty_list(self):
        val, pos = _parse_mi_list("[]", 0)
        assert val == []

    def test_string_list(self):
        val, pos = _parse_mi_list('["a","b","c"]', 0)
        assert val == ["a", "b", "c"]

    def test_tuple_list(self):
        val, pos = _parse_mi_list('[{a="1"},{a="2"}]', 0)
        assert len(val) == 2


# ── GdbClient unit tests ──


class TestGdbClientInit:
    def test_init_defaults(self):
        client = GdbClient(lambda e, b: None)
        assert client._process is None
        assert client.is_running is False

    def test_stop_without_start_is_safe(self):
        client = GdbClient(lambda e, b: None)
        client.stop()


class TestGdbClientTransformResult:
    def setup_method(self):
        self.client = GdbClient(lambda e, b: None)

    def test_transform_stack_frames(self):
        payload = {
            "stack": [
                {"frame": {"level": "0", "func": "main", "fullname": "/test/main.c", "line": "10"}},
                {"frame": {"level": "1", "func": "__libc_start_main", "file": "libc.c", "line": "0"}},
            ]
        }
        result = self.client._transform_result(payload)
        assert "frames" in result
        assert len(result["frames"]) == 2
        assert result["frames"][0]["name"] == "main"
        assert result["frames"][0]["file"] == "/test/main.c"
        assert result["frames"][0]["line"] == 10

    def test_transform_variables_as_scopes(self):
        payload = {
            "variables": [
                {"name": "x", "value": "42", "type": "int"},
                {"name": "y", "value": "3.14", "type": "double"},
            ]
        }
        result = self.client._transform_result(payload)
        assert "scopes" in result
        assert len(result["scopes"]) == 1
        assert result["scopes"][0]["name"] == "Locals"
        assert result["scopes"][0]["ref"] > 0

    def test_transform_expression_value(self):
        payload = {"value": "42"}
        result = self.client._transform_result(payload)
        assert result == {"result": "42"}

    def test_transform_passthrough(self):
        payload = {"foo": "bar"}
        result = self.client._transform_result(payload)
        assert result == {"foo": "bar"}


class TestGdbClientAsyncExec:
    def setup_method(self):
        self.events = []
        # Mock main_thread_call since we can't import gi
        import debugger.gdb_debugger as mod

        self._orig = None
        self.client = GdbClient(lambda e, b: self.events.append((e, b)))

    def test_handle_breakpoint_hit(self):
        self.client._handle_async_exec(
            "stopped",
            {
                "reason": "breakpoint-hit",
                "frame": {"fullname": "/test/main.c", "line": "10"},
            },
        )
        # Events are dispatched via main_thread_call which we can't test without GTK
        # But we can verify no crash occurred

    def test_handle_exited_normally(self):
        self.client._handle_async_exec("stopped", {"reason": "exited-normally"})

    def test_handle_running(self):
        # Should be a no-op
        self.client._handle_async_exec("running", {})


class TestGdbClientResolve:
    def setup_method(self):
        self.client = GdbClient(lambda e, b: None)

    def test_find_makefile_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = os.path.join(tmpdir, "src")
            os.makedirs(src_dir)
            # Create Makefile in root
            with open(os.path.join(tmpdir, "Makefile"), "w") as f:
                f.write("all:\n\techo hello\n")

            result = self.client._find_makefile_dir(
                os.path.join(src_dir, "main.c"), tmpdir
            )
            assert result == tmpdir

    def test_find_makefile_dir_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = os.path.join(tmpdir, "src")
            os.makedirs(src_dir)
            result = self.client._find_makefile_dir(
                os.path.join(src_dir, "main.c"), tmpdir
            )
            assert result is None

    def test_find_binary_from_makefile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a Makefile with TARGET
            with open(os.path.join(tmpdir, "Makefile"), "w") as f:
                f.write("TARGET := myapp\nall:\n\techo\n")
            # Create the binary
            binary = os.path.join(tmpdir, "myapp")
            with open(binary, "w") as f:
                f.write("#!/bin/sh\n")
            os.chmod(binary, 0o755)

            result = self.client._find_binary_from_makefile(tmpdir)
            assert result == binary


@pytest.mark.skipif(not shutil.which("gcc"), reason="gcc not available")
class TestGdbClientCompileSingle:
    def test_compile_c_file(self):
        events = []
        # We need to mock main_thread_call for this test
        import debugger.gdb_debugger as mod
        import shared.main_thread as mt

        orig = mt.main_thread_call
        mt.main_thread_call = lambda fn, *args: fn(*args)

        try:
            client = GdbClient(lambda e, b: events.append((e, b)))
            with tempfile.TemporaryDirectory() as tmpdir:
                src = os.path.join(tmpdir, "test.c")
                with open(src, "w") as f:
                    f.write("int main() { return 0; }\n")

                binary = client._compile_single(src, tmpdir)
                assert binary is not None
                assert os.path.isfile(binary)
                assert os.access(binary, os.X_OK)
        finally:
            mt.main_thread_call = orig

    def test_compile_error(self):
        events = []
        import shared.main_thread as mt

        orig = mt.main_thread_call
        mt.main_thread_call = lambda fn, *args: fn(*args)

        try:
            client = GdbClient(lambda e, b: events.append((e, b)))
            with tempfile.TemporaryDirectory() as tmpdir:
                src = os.path.join(tmpdir, "bad.c")
                with open(src, "w") as f:
                    f.write("this is not valid C code!!!\n")

                binary = client._compile_single(src, tmpdir)
                assert binary is None
                # Should have output compile error
                assert any("stderr" in str(e) for e in events)
        finally:
            mt.main_thread_call = orig
