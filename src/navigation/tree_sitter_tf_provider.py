"""
Tree-sitter based Terraform/HCL navigation provider.

Replaces regex patterns with AST walks for symbol finding and
reference resolution in .tf files.
"""

import os
from typing import Dict, List, Optional, Tuple

from navigation.navigation_provider import NavigationProvider

# Block types with two labels: block_type "type_label" "name_label" {}
_TWO_LABEL = {"resource", "data"}
# Block types with one label: block_type "name_label" {}
_ONE_LABEL = {"variable", "output", "module"}
# Reference prefix → HCL block keyword mapping
_REF_TO_BLOCK = {"var": "variable", "local": "locals", "module": "module", "output": "output"}


class TreeSitterTfProvider(NavigationProvider):
    """Terraform/HCL code navigation backed by Tree-sitter."""

    SUPPORTED_EXTENSIONS = {".tf"}
    BLOCK_PREFIXES = {"data", "var", "local", "module", "output"}

    def supports_language(self, file_ext: str) -> bool:
        return file_ext.lower() in self.SUPPORTED_EXTENSIONS

    def parse_imports(self, content: str, file_ext: str = ".tf") -> Dict[str, str]:
        return {}

    def find_symbol_in_content(self, content: str, symbol: str, file_ext: str = ".tf") -> Optional[int]:
        """Find any block whose name matches *symbol*."""
        if file_ext.lower() not in self.SUPPORTED_EXTENSIONS:
            return None
        root = self._parse_root(content)
        if root is None:
            return None

        for block_type, labels, line in self._iter_blocks(root):
            if block_type in _TWO_LABEL and len(labels) >= 2 and labels[1] == symbol:
                return line
            if block_type in _ONE_LABEL and len(labels) >= 1 and labels[0] == symbol:
                return line

        # Check locals attributes
        for name, attr_line in self._iter_locals_attrs(root):
            if name == symbol:
                return attr_line

        return None

    # ------------------------------------------------------------------
    # File-level reference resolution
    # ------------------------------------------------------------------

    def resolve_reference(self, chain: str, current_file: str) -> Optional[Tuple[str, int]]:
        """Resolve a Terraform reference chain to a *(file_path, line_number)* tuple.

        Examples:
            data.aws_secretsmanager_secret.kafka_config.id -> data "aws_secretsmanager_secret" "kafka_config"
            var.schema_registry_secrets -> variable "schema_registry_secrets"
            local.msk_enabled -> msk_enabled = ... inside locals {}
            module.my_module.output_name -> module "my_module"
            aws_instance.web.id -> resource "aws_instance" "web"
        """
        parts = chain.split(".")
        if not parts:
            return None

        tf_dir = os.path.dirname(current_file)
        for tf_file in self._get_tf_files(tf_dir):
            try:
                with open(tf_file, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except (OSError, IOError):
                continue

            line = self.resolve_chain_in_content(content, parts)
            if line is not None:
                return (tf_file, line)

        return None

    def resolve_chain_in_content(self, content: str, parts: List[str]) -> Optional[int]:
        """Find the block matching a parsed reference chain.

        Returns a 1-based line number or *None*.
        """
        if not parts:
            return None

        root = self._parse_root(content)
        if root is None:
            return None

        prefix = parts[0]

        if prefix == "data" and len(parts) >= 3:
            return self._find_two_label_block(root, "data", parts[1], parts[2])

        if prefix == "var" and len(parts) >= 2:
            return self._find_one_label_block(root, "variable", parts[1])

        if prefix == "local" and len(parts) >= 2:
            for name, line in self._iter_locals_attrs(root):
                if name == parts[1]:
                    return line
            return None

        if prefix == "module" and len(parts) >= 2:
            return self._find_one_label_block(root, "module", parts[1])

        if prefix == "output" and len(parts) >= 2:
            return self._find_one_label_block(root, "output", parts[1])

        # Implicit resource: aws_instance.web → resource "aws_instance" "web"
        if len(parts) >= 2 and prefix not in _REF_TO_BLOCK:
            return self._find_two_label_block(root, "resource", parts[0], parts[1])

        return None

    # ------------------------------------------------------------------
    # File discovery
    # ------------------------------------------------------------------

    @staticmethod
    def _get_tf_files(directory: str) -> List[str]:
        """Get all .tf files in a directory."""
        tf_files = []
        try:
            for entry in os.listdir(directory):
                if entry.endswith(".tf"):
                    tf_files.append(os.path.join(directory, entry))
        except OSError:
            pass
        return sorted(tf_files)

    # ------------------------------------------------------------------
    # AST helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_root(content: str):
        from navigation.tree_sitter_core import TreeSitterCore

        tree = TreeSitterCore.parse(content.encode("utf-8"), "hcl")
        return tree.root_node if tree else None

    @staticmethod
    def _get_body(root):
        """Return the top-level body node."""
        for child in root.children:
            if child.type == "body":
                return child
        return root

    @classmethod
    def _iter_blocks(cls, root):
        """Yield *(block_type, labels, line)* for each top-level block."""
        body = cls._get_body(root)
        for child in body.children:
            if child.type != "block":
                continue
            block_type = None
            labels: list[str] = []
            for node in child.children:
                if node.type == "identifier" and block_type is None:
                    block_type = node.text.decode()
                elif node.type == "string_lit":
                    for sub in node.children:
                        if sub.type == "template_literal":
                            labels.append(sub.text.decode())
            if block_type:
                yield block_type, labels, child.start_point[0] + 1

    @classmethod
    def _iter_locals_attrs(cls, root):
        """Yield *(name, line)* for each attribute inside ``locals`` blocks."""
        body = cls._get_body(root)
        for child in body.children:
            if child.type != "block":
                continue
            first_id = None
            for node in child.children:
                if node.type == "identifier":
                    first_id = node.text.decode()
                    break
            if first_id != "locals":
                continue
            for node in child.children:
                if node.type == "body":
                    for attr in node.children:
                        if attr.type == "attribute":
                            for sub in attr.children:
                                if sub.type == "identifier":
                                    yield sub.text.decode(), attr.start_point[0] + 1
                                    break

    @classmethod
    def _find_two_label_block(cls, root, block_type: str, type_label: str, name_label: str) -> Optional[int]:
        for bt, labels, line in cls._iter_blocks(root):
            if bt == block_type and len(labels) >= 2 and labels[0] == type_label and labels[1] == name_label:
                return line
        return None

    @classmethod
    def _find_one_label_block(cls, root, block_type: str, name_label: str) -> Optional[int]:
        for bt, labels, line in cls._iter_blocks(root):
            if bt == block_type and len(labels) >= 1 and labels[0] == name_label:
                return line
        return None
