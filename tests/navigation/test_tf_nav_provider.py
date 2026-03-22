"""Tests for navigation/tree_sitter_tf_provider.py - Terraform HCL navigation."""

import os
import tempfile

from navigation.tree_sitter_tf_provider import TreeSitterTfProvider


class TestSupportsLanguage:
    """Test file extension support."""

    def test_supports_tf(self):
        p = TreeSitterTfProvider()
        assert p.supports_language(".tf") is True

    def test_case_insensitive(self):
        p = TreeSitterTfProvider()
        assert p.supports_language(".TF") is True

    def test_py_not_supported(self):
        p = TreeSitterTfProvider()
        assert p.supports_language(".py") is False


class TestParseImports:
    """Terraform doesn't have imports."""

    def test_always_empty(self):
        p = TreeSitterTfProvider()
        assert p.parse_imports("resource {}", ".tf") == {}


class TestFindSymbol:
    """Test finding Terraform symbols."""

    def test_find_resource(self):
        p = TreeSitterTfProvider()
        content = 'resource "aws_instance" "web" {\n  ami = "abc"\n}'
        assert p.find_symbol_in_content(content, "web", ".tf") == 1

    def test_find_variable(self):
        p = TreeSitterTfProvider()
        content = 'variable "region" {\n  default = "us-east-1"\n}'
        assert p.find_symbol_in_content(content, "region", ".tf") == 1

    def test_find_output(self):
        p = TreeSitterTfProvider()
        content = 'output "ip_address" {\n  value = aws_instance.web.public_ip\n}'
        assert p.find_symbol_in_content(content, "ip_address", ".tf") == 1

    def test_find_module(self):
        p = TreeSitterTfProvider()
        content = 'module "vpc" {\n  source = "./modules/vpc"\n}'
        assert p.find_symbol_in_content(content, "vpc", ".tf") == 1

    def test_find_data(self):
        p = TreeSitterTfProvider()
        content = 'data "aws_ami" "latest" {\n  owners = ["self"]\n}'
        assert p.find_symbol_in_content(content, "latest", ".tf") == 1

    def test_find_local_assignment(self):
        p = TreeSitterTfProvider()
        content = 'locals {\n  env = "prod"\n}'
        assert p.find_symbol_in_content(content, "env", ".tf") == 2

    def test_symbol_not_found(self):
        p = TreeSitterTfProvider()
        assert p.find_symbol_in_content("", "nonexistent", ".tf") is None

    def test_unsupported_ext(self):
        p = TreeSitterTfProvider()
        assert p.find_symbol_in_content("", "x", ".py") is None


class TestResolveChainInContent:
    """Test tree-sitter reference chain resolution."""

    def test_data_reference(self):
        ts = TreeSitterTfProvider()
        content = 'data "aws_ami" "latest" {\n  owners = ["self"]\n}'
        assert ts.resolve_chain_in_content(content, ["data", "aws_ami", "latest"]) == 1

    def test_var_reference(self):
        ts = TreeSitterTfProvider()
        content = 'variable "region" {\n  default = "us-east-1"\n}'
        assert ts.resolve_chain_in_content(content, ["var", "region"]) == 1

    def test_local_reference(self):
        ts = TreeSitterTfProvider()
        content = 'locals {\n  env = "prod"\n}'
        assert ts.resolve_chain_in_content(content, ["local", "env"]) == 2

    def test_module_reference(self):
        ts = TreeSitterTfProvider()
        content = 'module "vpc" {\n  source = "./modules/vpc"\n}'
        assert ts.resolve_chain_in_content(content, ["module", "vpc"]) == 1

    def test_output_reference(self):
        ts = TreeSitterTfProvider()
        content = 'output "ip" {\n  value = "x"\n}'
        assert ts.resolve_chain_in_content(content, ["output", "ip"]) == 1

    def test_resource_reference(self):
        ts = TreeSitterTfProvider()
        content = 'resource "aws_instance" "web" {\n  ami = "abc"\n}'
        assert ts.resolve_chain_in_content(content, ["aws_instance", "web"]) == 1

    def test_empty_parts(self):
        ts = TreeSitterTfProvider()
        assert ts.resolve_chain_in_content("", []) is None

    def test_not_found(self):
        ts = TreeSitterTfProvider()
        assert ts.resolve_chain_in_content("", ["var", "nope"]) is None


class TestResolveReference:
    """Test reference resolution across files."""

    def test_resolve_variable(self):
        p = TreeSitterTfProvider()
        with tempfile.TemporaryDirectory() as tmpdir:
            tf_file = os.path.join(tmpdir, "main.tf")
            vars_file = os.path.join(tmpdir, "vars.tf")
            with open(tf_file, "w") as f:
                f.write('resource "aws_instance" "web" {}')
            with open(vars_file, "w") as f:
                f.write('variable "region" {\n  default = "us-east-1"\n}')
            result = p.resolve_reference("var.region", tf_file)
            assert result is not None
            assert result[1] == 1  # Line 1

    def test_resolve_not_found(self):
        p = TreeSitterTfProvider()
        with tempfile.TemporaryDirectory() as tmpdir:
            tf_file = os.path.join(tmpdir, "main.tf")
            with open(tf_file, "w") as f:
                f.write("")
            result = p.resolve_reference("var.nonexistent", tf_file)
            assert result is None


class TestGetTfFiles:
    """Test .tf file discovery."""

    def test_finds_tf_files(self):
        p = TreeSitterTfProvider()
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ["main.tf", "vars.tf", "readme.md"]:
                with open(os.path.join(tmpdir, name), "w") as f:
                    f.write("")
            files = p._get_tf_files(tmpdir)
            assert len(files) == 2
            assert all(f.endswith(".tf") for f in files)

    def test_sorted_output(self):
        p = TreeSitterTfProvider()
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ["z.tf", "a.tf"]:
                with open(os.path.join(tmpdir, name), "w") as f:
                    f.write("")
            files = p._get_tf_files(tmpdir)
            assert files[0].endswith("a.tf")


class TestNoRegexImport:
    """Verify tree_sitter_tf_provider.py does not use regex."""

    def test_no_re_import(self):
        import inspect

        import navigation.tree_sitter_tf_provider as mod

        source = inspect.getsource(mod)
        assert "import re" not in source
