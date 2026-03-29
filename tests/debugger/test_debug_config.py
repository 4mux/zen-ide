"""Tests for debugger/debug_config.py — launch configuration for Python, C, and C++."""

import json
import os
import tempfile

from debugger.debug_config import (
    DebugConfig,
    create_default_config,
    load_launch_configs,
    save_launch_configs,
    substitute_variables,
)


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


class TestLaunchConfigs:
    """Test launch.json loading and saving."""

    def test_load_supported_configs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            zen_dir = os.path.join(tmpdir, ".zen")
            os.makedirs(zen_dir)
            launch_file = os.path.join(zen_dir, "launch.json")

            data = {
                "version": "0.2.0",
                "configurations": [
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
                ],
            }
            with open(launch_file, "w") as f:
                json.dump(data, f)

            configs = load_launch_configs(tmpdir)
            # Should load Python, cppdbg, and codelldb (all supported)
            assert len(configs) == 3
            assert configs[0].name == "Python: Current File"
            assert configs[0].type == "python"
            assert configs[2].name == "Rust: Debug"
            assert configs[2].type == "codelldb"
            assert configs[1].name == "C++: Demo"
            assert configs[1].type == "cppdbg"

    def test_load_missing_file(self):
        configs = load_launch_configs("/nonexistent")
        assert configs == []

    def test_save_and_reload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            configs = [
                DebugConfig(
                    name="Python Test",
                    program="${file}",
                ),
            ]
            save_launch_configs(tmpdir, configs)

            reloaded = load_launch_configs(tmpdir)
            assert len(reloaded) == 1
            assert reloaded[0].name == "Python Test"

    def test_save_creates_zen_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            save_launch_configs(tmpdir, [DebugConfig(name="Test")])
            assert os.path.isdir(os.path.join(tmpdir, ".zen"))
            assert os.path.isfile(os.path.join(tmpdir, ".zen", "launch.json"))

    def test_load_config_with_env_and_args(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            zen_dir = os.path.join(tmpdir, ".zen")
            os.makedirs(zen_dir)
            launch_file = os.path.join(zen_dir, "launch.json")

            data = {
                "version": "0.2.0",
                "configurations": [
                    {
                        "name": "Test",
                        "type": "python",
                        "program": "main.py",
                        "args": ["--verbose"],
                        "env": {"DEBUG": "1"},
                        "python": "/usr/bin/python3.12",
                        "stopOnEntry": True,
                    },
                ],
            }
            with open(launch_file, "w") as f:
                json.dump(data, f)

            configs = load_launch_configs(tmpdir)
            assert len(configs) == 1
            assert configs[0].args == ["--verbose"]
            assert configs[0].env == {"DEBUG": "1"}
            assert configs[0].python == "/usr/bin/python3.12"
            assert configs[0].stop_on_entry is True
