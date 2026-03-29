"""Tests for debugger/dap_registry.py — DAP adapter discovery."""

from unittest.mock import patch

from debugger.dap_registry import (
    detect_dap_type,
    find_adapter,
    make_adapter_from_path,
)
from shared.settings.default_settings import DEFAULT_SETTINGS

_MOCK_ADAPTERS = DEFAULT_SETTINGS["debugger"]["adapters"]
_MOCK_FILE_TYPES = DEFAULT_SETTINGS["debugger"]["file_types"]


def _mock_get_setting(path, default=None):
    if path == "debugger.adapters":
        return _MOCK_ADAPTERS
    if path == "debugger.file_types":
        return _MOCK_FILE_TYPES
    return default


@patch("debugger.dap_registry.get_setting", side_effect=_mock_get_setting)
class TestDetectDapType:
    def test_rust_extension(self, _mock):
        assert detect_dap_type("/project/main.rs") == "codelldb"

    def test_ruby_extension(self, _mock):
        assert detect_dap_type("/project/app.rb") == "rdbg"

    def test_unknown_extension(self, _mock):
        assert detect_dap_type("/project/main.go") is None

    def test_python_not_dap(self, _mock):
        assert detect_dap_type("/project/main.py") is None


@patch("debugger.dap_registry.get_setting", side_effect=_mock_get_setting)
class TestFindAdapter:
    @patch("debugger.dap_registry._find_executable", return_value="/usr/bin/codelldb")
    def test_find_codelldb(self, mock_which, _mock_settings):
        info = find_adapter("codelldb")
        assert info is not None
        assert info.type == "codelldb"
        assert info.command[0] == "codelldb"

    @patch("debugger.dap_registry._find_executable", return_value="/usr/bin/rdbg")
    def test_find_rdbg(self, mock_which, _mock_settings):
        info = find_adapter("rdbg")
        assert info is not None
        assert info.type == "rdbg"
        assert info.launch_args_key == "script"
        assert "command" in info.extra_launch_args

    @patch("debugger.dap_registry._find_executable", return_value=None)
    def test_missing_binary_returns_none(self, mock_which, _mock_settings):
        assert find_adapter("codelldb") is None

    def test_unknown_type_returns_none(self, _mock_settings):
        assert find_adapter("unknown_adapter") is None


class TestMakeAdapterFromPath:
    def test_creates_info(self):
        info = make_adapter_from_path("/opt/my-adapter", ["--arg1"], "custom")
        assert info.command == ["/opt/my-adapter", "--arg1"]
        assert info.type == "custom"

    def test_empty_args(self):
        info = make_adapter_from_path("/opt/adapter", [], "dap")
        assert info.command == ["/opt/adapter"]
