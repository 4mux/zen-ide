#!/usr/bin/env python3
"""
Simple regression tests for font popup closing behavior.

This test suite verifies that the font picker dialog fix is in place
by checking for the existence of critical methods and that imports work.
"""

import inspect
import os
import sys
import unittest

# Add the src directory to the path so we can import the modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestFontPopupFix(unittest.TestCase):
    """Simple tests to verify the font popup fix is in place."""

    def test_font_picker_can_be_imported(self):
        """Test that the FontPickerDialog can be imported without major errors."""
        try:
            # This will trigger any major import issues
            from popups.font_picker_dialog import FontPickerDialog

            self.assertIsNotNone(FontPickerDialog)
        except Exception as e:
            # If it fails to import, that's a major regression
            self.fail(f"FontPickerDialog failed to import: {e}")

    def test_critical_methods_exist(self):
        """Test that the critical override methods exist."""
        from popups.font_picker_dialog import FontPickerDialog

        # These methods are critical for the fix
        critical_methods = [
            "_on_focus_leave",
            "_on_active_changed",
            "_check_active_and_close",
            "_on_target_button_clicked",
            "_on_sub_popup_closing",
            "_restore_focus_and_clear_sub_popup",
        ]

        for method_name in critical_methods:
            self.assertTrue(
                hasattr(FontPickerDialog, method_name), f"Critical method {method_name} must exist to prevent regression"
            )

    def test_override_methods_are_simple(self):
        """Test that the override methods are simple (just return)."""
        from popups.font_picker_dialog import FontPickerDialog

        # These methods should be overridden to just return
        override_methods = ["_on_focus_leave", "_on_active_changed", "_check_active_and_close"]

        for method_name in override_methods:
            method = getattr(FontPickerDialog, method_name)

            # Get the source code
            source = inspect.getsource(method).strip()

            # The overridden methods should be very simple - just return
            # They should contain "return" and not much else
            self.assertIn("return", source, f"{method_name} should contain 'return' statement")

            # They should be short (the override is just "return")
            lines = [
                line.strip()
                for line in source.split("\n")
                if line.strip() and not line.strip().startswith('"""') and not line.strip().startswith("def")
            ]

            # Should have very few non-docstring, non-def lines
            self.assertLessEqual(
                len(lines), 3, f"{method_name} should be a simple override (found {len(lines)} lines: {lines})"
            )

    def test_signal_connection_logic_exists(self):
        """Test that the target button handler has proper signal connection logic."""
        from popups.font_picker_dialog import FontPickerDialog

        method = FontPickerDialog._on_target_button_clicked
        source = inspect.getsource(method)

        # Should handle both types of context menus
        self.assertIn("close-request", source, "Should handle NvimPopup close-request signal")
        self.assertIn("closed", source, "Should handle SystemContextMenu closed signal")
        self.assertIn("isinstance", source, "Should check instance type for correct signal")
        self.assertIn("NvimPopup", source, "Should check for NvimPopup type")

    def test_focus_restoration_logic_exists(self):
        """Test that focus restoration logic is properly implemented."""
        from popups.font_picker_dialog import FontPickerDialog

        # Check that the focus restoration method exists
        self.assertTrue(hasattr(FontPickerDialog, "_restore_focus_and_clear_sub_popup"))

        method = FontPickerDialog._restore_focus_and_clear_sub_popup
        source = inspect.getsource(method)

        # Should restore focus and clear sub_popup
        self.assertIn("grab_focus", source, "Should restore focus")
        self.assertIn("_sub_popup", source, "Should clear _sub_popup reference")


class TestDocumentationExists(unittest.TestCase):
    """Test that documentation was created."""

    def test_documentation_files_exist(self):
        """Test that documentation files were created."""
        docs_dir = os.path.join(os.path.dirname(__file__), "..", "docs")

        expected_docs = ["POPUP_SYSTEM.md", "FONT_POPUP_FIX.md"]

        for doc_file in expected_docs:
            doc_path = os.path.join(docs_dir, doc_file)
            self.assertTrue(os.path.exists(doc_path), f"Documentation file {doc_file} should exist")

            # Check that the file has substantial content
            with open(doc_path, "r") as f:
                content = f.read()
                self.assertGreater(len(content), 1000, f"{doc_file} should have substantial content")

    def test_popup_system_documentation_content(self):
        """Test that popup system documentation covers key topics."""
        docs_dir = os.path.join(os.path.dirname(__file__), "..", "docs")
        doc_path = os.path.join(docs_dir, "POPUP_SYSTEM.md")

        with open(doc_path, "r") as f:
            content = f.read()

        # Should document the key concepts
        key_topics = [
            "NvimPopup",
            "_on_focus_leave",
            "_on_active_changed",
            "_check_active_and_close",
            "sub-popup",
            "auto-closing",
            "FontPickerDialog",
        ]

        for topic in key_topics:
            self.assertIn(topic, content, f"Popup system documentation should mention {topic}")

    def test_font_popup_fix_documentation_content(self):
        """Test that font popup fix documentation explains the problem and solution."""
        docs_dir = os.path.join(os.path.dirname(__file__), "..", "docs")
        doc_path = os.path.join(docs_dir, "FONT_POPUP_FIX.md")

        with open(doc_path, "r") as f:
            content = f.read()

        # Should explain the problem and solution
        key_sections = [
            "Problem Description",
            "Root Cause Analysis",
            "Solution Implementation",
            "Apply to",
            "close-request",
            "closed",
            "race condition",
            "signal connection",
        ]

        for section in key_sections:
            self.assertIn(section, content, f"Font popup fix documentation should mention {section}")


class TestRegressionProtection(unittest.TestCase):
    """Test that the specific regression is protected against."""

    def test_no_premature_sub_popup_clearing(self):
        """Test that _on_target_selected doesn't clear _sub_popup."""
        from popups.font_picker_dialog import FontPickerDialog

        method = FontPickerDialog._on_target_selected
        source = inspect.getsource(method)

        # Should NOT clear _sub_popup in this method
        # The old buggy version did: self._sub_popup = None
        lines = source.split("\n")

        sub_popup_assignments = [line for line in lines if "_sub_popup" in line and "=" in line and "None" in line]

        self.assertEqual(
            len(sub_popup_assignments), 0, f"_on_target_selected should not clear _sub_popup. Found: {sub_popup_assignments}"
        )

    def test_proper_closing_timing(self):
        """Test that _on_sub_popup_closing uses proper timing."""
        from popups.font_picker_dialog import FontPickerDialog

        method = FontPickerDialog._on_sub_popup_closing
        source = inspect.getsource(method)

        # Should use GLib.idle_add for proper timing
        self.assertIn("GLib.idle_add", source, "_on_sub_popup_closing should use GLib.idle_add for proper timing")
        self.assertIn(
            "_restore_focus_and_clear_sub_popup", source, "_on_sub_popup_closing should call the restoration method"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
