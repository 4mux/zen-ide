"""Tests for debugger/debug_config.py — launch configuration for Python, C, and C++."""

from unittest.mock import patch

import pytest

from debugger.debug_config import (
    DebugConfig,
    create_default_config,
    load_configurations,
    save_configurations,
    substitute_variables,
)
from shared.settings.default_settings import DEFAULT_SETTINGS

_MOCK_FILE_TYPES = DEFAULT_SETTINGS["debugger"]["file_types"]

# Mutable store for configurations used in tests
_mock_configurations = []


def _mock_get_setting(path, default=None):
    if path == "debugger.file_types":
        return _MOCK_FILE_TYPES
    if path == "debugger.configurations":
        return _mock_configurations
    return default


def _mock_set_setting(path, value):
    global _mock_configurations
    if path == "debugger.configurations":
        _mock_configurations = value


@pytest.fixture(autouse=True)
def _patch_settings():
    global _mock_configurations
    _mock_configurations = []
    with (
        patch("debugger.debug_config.get_setting", side_effect=_mock_get_setting),
        patch("debugger.debug_config.set_setting", side_effect=_mock_set_setting),
    ):
        yield


class TestCreateDefaultConfig:
    """Test zero-config configuration creation."""

    def test_python_default_config(self):
        config = create_default_config("/project/main.py", ["/project"])
        assert config is not None
        assert config.type == "python"
        assert config.program == "/project/main.py"
        assert config.cwd == "/project"

    def test_c_default_config(self):
        config = create_default_config("/project/main.c", ["/project"])
        assert config is not None
        assert config.type == "cppdbg"
        assert config.program == "/project/main.c"
        assert config.cwd == "/project"

    def test_cpp_default_config(self):
        config = create_default_config("/project/main.cpp", ["/project"])
        assert config is not None
        assert config.type == "cppdbg"
        assert config.program == "/project/main.cpp"

    def test_cc_default_config(self):
        config = create_default_config("/project/app.cc", ["/project"])
        assert config is not None
        assert config.type == "cppdbg"

    def test_node_js_config(self):
        config = create_default_config("/project/app.js")
        assert config is not None
        assert config.type == "node"
        assert config.name == "Node: app.js"

    def test_rust_config(self):
        config = create_default_config("/project/main.rs")
        assert config is not None
        assert config.type == "codelldb"
        assert config.name == "Rust: main.rs"

    def test_ruby_config(self):
        config = create_default_config("/project/app.rb")
        assert config is not None
        assert config.type == "rdbg"
        assert config.name == "Ruby: app.rb"

    def test_unsupported_returns_none(self):
        assert create_default_config("/project/readme.txt") is None

    def test_uses_file_dir_when_no_workspace(self):
        config = create_default_config("/some/dir/script.py")
        assert config is not None
        assert config.cwd == "/some/dir"


class TestSubstituteVariables:
    """Test variable substitution in config values."""

    def test_file_variable(self):
        result = substitute_variables("${file}", file_path="/test.py")
        assert result == "/test.py"

    def test_workspace_folder(self):
        result = substitute_variables("${workspaceFolder}/build", workspace_folder="/project")
        assert result == "/project/build"

    def test_file_basename(self):
        result = substitute_variables("${fileBasename}", file_path="/path/to/main.py")
        assert result == "main.py"

    def test_file_basename_no_extension(self):
        result = substitute_variables("${fileBasenameNoExtension}", file_path="/path/to/main.py")
        assert result == "main"

    def test_file_dirname(self):
        result = substitute_variables("${fileDirname}", file_path="/path/to/main.py")
        assert result == "/path/to"

    def test_file_extname(self):
        result = substitute_variables("${fileExtname}", file_path="/path/to/main.py")
        assert result == ".py"

    def test_workspace_folder_basename(self):
        result = substitute_variables("${workspaceFolderBasename}", workspace_folder="/path/to/myproject")
        assert result == "myproject"

    def test_no_variables(self):
        assert substitute_variables("hello world") == "hello world"

    def test_empty_string(self):
        assert substitute_variables("") == ""

    def test_multiple_variables(self):
        result = substitute_variables(
            "${workspaceFolder}/build/${fileBasenameNoExtension}",
            file_path="/src/main.py",
            workspace_folder="/project",
        )
        assert result == "/project/build/main"


class TestDebugConfig:
    """Test DebugConfig dataclass."""

    def test_defaults(self):
        config = DebugConfig(name="Test")
        assert config.program == ""
        assert config.python == ""
        assert config.args == []
        assert config.cwd == ""
        assert config.env == {}
        assert config.stop_on_entry is False

    def test_type_default_is_python(self):
        config = DebugConfig(name="Test")
        assert config.type == "python"

    def test_type_cppdbg(self):
        config = DebugConfig(name="Test", _type="cppdbg")
        assert config.type == "cppdbg"


class TestConfigurations:
    """Test loading and saving configurations from settings."""

    def test_load_supported_configs(self):
        global _mock_configurations
        _mock_configurations = [
            {
                "name": "Python: Current File",
                "type": "python",
                "program": "${file}",
            },
            {
                "name": "C++: Demo",
                "type": "cppdbg",
                "program": "${workspaceFolder}/demo",
            },
            {
                "name": "Rust: Debug",
                "type": "codelldb",
                "program": "target/debug/app",
            },
        ]

        configs = load_configurations("/project")
        assert len(configs) == 3
        assert configs[0].name == "Python: Current File"
        assert configs[0].type == "python"
        assert configs[1].name == "C++: Demo"
        assert configs[1].type == "cppdbg"
        assert configs[1].program == "/project/demo"
        assert configs[2].name == "Rust: Debug"
        assert configs[2].type == "codelldb"

    def test_load_empty_returns_empty(self):
        configs = load_configurations("/project")
        assert configs == []

    def test_save_and_reload(self):
        configs = [
            DebugConfig(name="Python Test", program="${file}"),
        ]
        save_configurations(configs)

        reloaded = load_configurations()
        assert len(reloaded) == 1
        assert reloaded[0].name == "Python Test"

    def test_load_config_with_env_and_args(self):
        global _mock_configurations
        _mock_configurations = [
            {
                "name": "Test",
                "type": "python",
                "program": "main.py",
                "args": ["--verbose"],
                "env": {"DEBUG": "1"},
                "python": "/usr/bin/python3.12",
                "stopOnEntry": True,
            },
        ]

        configs = load_configurations("/project")
        assert len(configs) == 1
        assert configs[0].args == ["--verbose"]
        assert configs[0].env == {"DEBUG": "1"}
        assert configs[0].python == "/usr/bin/python3.12"
        assert configs[0].stop_on_entry is True

    def test_skips_unsupported_types(self):
        global _mock_configurations
        _mock_configurations = [
            {"name": "Good", "type": "python", "program": "main.py"},
            {"name": "Bad", "type": "unsupported_type", "program": "foo"},
        ]

        configs = load_configurations()
        assert len(configs) == 1
        assert configs[0].name == "Good"
