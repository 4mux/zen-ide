"""
Terraform-specific code navigation for Zen IDE.
Handles Cmd+Click go-to-definition for Terraform (.tf) files.
"""

import os


class TerraformNavigationMixin:
    """Terraform-specific navigation methods mixed into CodeNavigation."""

    @property
    def _ts_tf(self):
        """Lazy-loaded Tree-sitter Terraform provider."""
        if not hasattr(self, "_ts_tf_provider"):
            from navigation.tree_sitter_tf_provider import TreeSitterTfProvider

            self._ts_tf_provider = TreeSitterTfProvider()
        return self._ts_tf_provider

    def _handle_terraform_click(self, buffer, view, file_path, click_iter) -> bool:
        """Handle Cmd+Click for Terraform (.tf) files."""
        word = self._get_word_at_iter(buffer, click_iter)
        if not word:
            return False

        chain = self._get_chain_at_iter(buffer, click_iter)
        if not chain:
            return False

        provider = self._ts_tf
        result = provider.resolve_reference(chain, file_path)
        if result:
            target_file, target_line = result
            if target_file == file_path:
                self._navigate_to_line(buffer, view, target_line, symbol=word)
            else:
                self._pending_navigate_symbol = word
                self._pending_file_path = target_file
                self._pending_navigate_line = target_line
                self.open_file_callback(target_file, None)
                self._schedule_pending_navigation()
            return True

        # Fall back: search all .tf files for the word as a symbol definition
        content = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
        line_num = provider.find_symbol_in_content(content, word, ".tf")
        if line_num:
            self._navigate_to_line(buffer, view, line_num, symbol=word)
            return True

        # Search other .tf files in same directory
        tf_dir = os.path.dirname(file_path)
        for tf_file in provider._get_tf_files(tf_dir):
            if tf_file == file_path:
                continue
            try:
                with open(tf_file, "r", encoding="utf-8", errors="replace") as f:
                    tf_content = f.read()
            except (OSError, IOError):
                continue
            line_num = provider.find_symbol_in_content(tf_content, word, ".tf")
            if line_num:
                self._pending_navigate_symbol = word
                self._pending_file_path = tf_file
                self._pending_navigate_line = line_num
                self.open_file_callback(tf_file, None)
                self._schedule_pending_navigation()
                return True

        return False
