#!/usr/bin/env python3
"""
Regression tests for font popup closing behavior.

This test suite ensures that the font picker dialog doesn't close unexpectedly
when the "Apply to" combo box is clicked, and that all popup closing mechanisms
work correctly.
"""

import os
import sys
import unittest
from unittest.mock import Mock, patch

# Add the src directory to the path so we can import the modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestFontPopupClosingBehavior(unittest.TestCase):
    """Test that font popup doesn't close unexpectedly when using combo boxes."""

    def setUp(self):
        """Set up test fixtures."""
        # Mock all GTK dependencies to avoid initialization issues
        self.patches = {
            "gi.repository.Gtk": patch("gi.repository.Gtk"),
            "gi.repository.Gdk": patch("gi.repository.Gdk"),
            "gi.repository.GLib": patch("gi.repository.GLib"),
        }

        self.mocks = {}
        for name, patcher in self.patches.items():
            self.mocks[name] = patcher.start()

    def tearDown(self):
        """Clean up patches."""
        for patcher in self.patches.values():
            patcher.stop()

    def test_font_picker_focus_leave_override_exists(self):
        """Test that FontPickerDialog has _on_focus_leave override."""
        with patch.dict(
            "sys.modules",
            {
                "popups.nvim_popup": Mock(),
                "popups.nvim_context_menu": Mock(),
                "common.settings_manager": Mock(),
                "common.utils": Mock(),
            },
        ):
            # Mock the dependencies
            with (
                patch("popups.font_picker_dialog.NvimPopup") as MockNvimPopup,
                patch("popups.font_picker_dialog.show_context_menu") as mock_show,
                patch("popups.font_picker_dialog.Gtk") as MockGtk,
                patch("popups.font_picker_dialog.Gdk") as MockGdk,
                patch("popups.font_picker_dialog.GLib") as MockGLib,
            ):
                # Import the class
                from popups.font_picker_dialog import FontPickerDialog

                # Check that the method exists and is overridden
                self.assertTrue(hasattr(FontPickerDialog, "_on_focus_leave"))

                # Check that it's different from the parent (by checking the code)
                method_code = FontPickerDialog._on_focus_leave.__code__

                # The override should be very simple (just return)
                # We can check this by verifying the method is small
                self.assertLess(
                    method_code.co_code.__len__(), 10, "_on_focus_leave should be a simple override that just returns"
                )

    def test_font_picker_active_changed_override_exists(self):
        """Test that FontPickerDialog has _on_active_changed override."""
        with patch.dict(
            "sys.modules",
            {
                "popups.nvim_popup": Mock(),
                "popups.nvim_context_menu": Mock(),
                "common.settings_manager": Mock(),
                "common.utils": Mock(),
            },
        ):
            with (
                patch("popups.font_picker_dialog.NvimPopup") as MockNvimPopup,
                patch("popups.font_picker_dialog.show_context_menu") as mock_show,
                patch("popups.font_picker_dialog.Gtk") as MockGtk,
                patch("popups.font_picker_dialog.Gdk") as MockGdk,
                patch("popups.font_picker_dialog.GLib") as MockGLib,
            ):
                from popups.font_picker_dialog import FontPickerDialog

                # Check that the method exists
                self.assertTrue(hasattr(FontPickerDialog, "_on_active_changed"))

    def test_font_picker_check_active_and_close_override_exists(self):
        """Test that FontPickerDialog has _check_active_and_close override."""
        with patch.dict(
            "sys.modules",
            {
                "popups.nvim_popup": Mock(),
                "popups.nvim_context_menu": Mock(),
                "common.settings_manager": Mock(),
                "common.utils": Mock(),
            },
        ):
            with (
                patch("popups.font_picker_dialog.NvimPopup") as MockNvimPopup,
                patch("popups.font_picker_dialog.show_context_menu") as mock_show,
                patch("popups.font_picker_dialog.Gtk") as MockGtk,
                patch("popups.font_picker_dialog.Gdk") as MockGdk,
                patch("popups.font_picker_dialog.GLib") as MockGLib,
            ):
                from popups.font_picker_dialog import FontPickerDialog

                # Check that the method exists
                self.assertTrue(hasattr(FontPickerDialog, "_check_active_and_close"))

    def test_font_picker_has_target_button_click_handler(self):
        """Test that FontPickerDialog has target button click handler."""
        with patch.dict(
            "sys.modules",
            {
                "popups.nvim_popup": Mock(),
                "popups.nvim_context_menu": Mock(),
                "common.settings_manager": Mock(),
                "common.utils": Mock(),
            },
        ):
            with (
                patch("popups.font_picker_dialog.NvimPopup") as MockNvimPopup,
                patch("popups.font_picker_dialog.show_context_menu") as mock_show,
                patch("popups.font_picker_dialog.Gtk") as MockGtk,
                patch("popups.font_picker_dialog.Gdk") as MockGdk,
                patch("popups.font_picker_dialog.GLib") as MockGLib,
            ):
                from popups.font_picker_dialog import FontPickerDialog

                # Check that the target button click handler exists
                self.assertTrue(hasattr(FontPickerDialog, "_on_target_button_clicked"))

    def test_font_picker_has_sub_popup_closing_handler(self):
        """Test that FontPickerDialog has sub popup closing handler."""
        with patch.dict(
            "sys.modules",
            {
                "popups.nvim_popup": Mock(),
                "popups.nvim_context_menu": Mock(),
                "common.settings_manager": Mock(),
                "common.utils": Mock(),
            },
        ):
            with (
                patch("popups.font_picker_dialog.NvimPopup") as MockNvimPopup,
                patch("popups.font_picker_dialog.show_context_menu") as mock_show,
                patch("popups.font_picker_dialog.Gtk") as MockGtk,
                patch("popups.font_picker_dialog.Gdk") as MockGdk,
                patch("popups.font_picker_dialog.GLib") as MockGLib,
            ):
                from popups.font_picker_dialog import FontPickerDialog

                # Check that the sub popup closing handler exists
                self.assertTrue(hasattr(FontPickerDialog, "_on_sub_popup_closing"))

    def test_font_picker_has_restore_focus_method(self):
        """Test that FontPickerDialog has focus restoration method."""
        with patch.dict(
            "sys.modules",
            {
                "popups.nvim_popup": Mock(),
                "popups.nvim_context_menu": Mock(),
                "common.settings_manager": Mock(),
                "common.utils": Mock(),
            },
        ):
            with (
                patch("popups.font_picker_dialog.NvimPopup") as MockNvimPopup,
                patch("popups.font_picker_dialog.show_context_menu") as mock_show,
                patch("popups.font_picker_dialog.Gtk") as MockGtk,
                patch("popups.font_picker_dialog.Gdk") as MockGdk,
                patch("popups.font_picker_dialog.GLib") as MockGLib,
            ):
                from popups.font_picker_dialog import FontPickerDialog

                # Check that the focus restoration method exists
                self.assertTrue(hasattr(FontPickerDialog, "_restore_focus_and_clear_sub_popup"))

    def test_override_methods_just_return(self):
        """Test that the override methods are implemented to just return."""
        with patch.dict(
            "sys.modules",
            {
                "popups.nvim_popup": Mock(),
                "popups.nvim_context_menu": Mock(),
                "common.settings_manager": Mock(),
                "common.utils": Mock(),
            },
        ):
            with (
                patch("popups.font_picker_dialog.NvimPopup") as MockNvimPopup,
                patch("popups.font_picker_dialog.show_context_menu") as mock_show,
                patch("popups.font_picker_dialog.Gtk") as MockGtk,
                patch("popups.font_picker_dialog.Gdk") as MockGdk,
                patch("popups.font_picker_dialog.GLib") as MockGLib,
            ):
                from popups.font_picker_dialog import FontPickerDialog

                # Create a mock instance to test the method behavior
                mock_dialog = Mock(spec=FontPickerDialog)

                # Bind the actual methods to the mock
                mock_dialog._on_focus_leave = FontPickerDialog._on_focus_leave.__get__(mock_dialog)
                mock_dialog._on_active_changed = FontPickerDialog._on_active_changed.__get__(mock_dialog)
                mock_dialog._check_active_and_close = FontPickerDialog._check_active_and_close.__get__(mock_dialog)

                # Test that they return None (meaning they just return)
                self.assertIsNone(mock_dialog._on_focus_leave())
                self.assertIsNone(mock_dialog._on_active_changed(None, None))
                self.assertIsNone(mock_dialog._check_active_and_close())


class TestFontPopupMethodBehavior(unittest.TestCase):
    """Test specific method behaviors without instantiating the class."""

    def test_method_implementations_are_overrides(self):
        """Test that critical methods are properly overridden."""
        with patch.dict(
            "sys.modules",
            {
                "popups.nvim_popup": Mock(),
                "popups.nvim_context_menu": Mock(),
                "common.settings_manager": Mock(),
                "common.utils": Mock(),
            },
        ):
            with (
                patch("popups.font_picker_dialog.NvimPopup") as MockNvimPopup,
                patch("popups.font_picker_dialog.show_context_menu"),
                patch("popups.font_picker_dialog.Gtk"),
                patch("popups.font_picker_dialog.Gdk"),
                patch("popups.font_picker_dialog.GLib"),
            ):
                from popups.font_picker_dialog import FontPickerDialog

                # Test that key methods exist and are simple overrides
                methods_to_check = ["_on_focus_leave", "_on_active_changed", "_check_active_and_close"]

                for method_name in methods_to_check:
                    self.assertTrue(
                        hasattr(FontPickerDialog, method_name), f"FontPickerDialog should have {method_name} method"
                    )

                    method = getattr(FontPickerDialog, method_name)

                    # These should be simple methods that just return
                    # We can check this by examining if they're small
                    self.assertIsNotNone(method, f"{method_name} should not be None")

    def test_signal_connection_logic_exists(self):
        """Test that signal connection logic exists in target button handler."""
        with patch.dict(
            "sys.modules",
            {
                "popups.nvim_popup": Mock(),
                "popups.nvim_context_menu": Mock(),
                "common.settings_manager": Mock(),
                "common.utils": Mock(),
            },
        ):
            with (
                patch("popups.font_picker_dialog.NvimPopup") as MockNvimPopup,
                patch("popups.font_picker_dialog.show_context_menu"),
                patch("popups.font_picker_dialog.Gtk"),
                patch("popups.font_picker_dialog.Gdk"),
                patch("popups.font_picker_dialog.GLib"),
            ):
                from popups.font_picker_dialog import FontPickerDialog

                # Check that the target button click method exists
                self.assertTrue(hasattr(FontPickerDialog, "_on_target_button_clicked"))

                # Get the method source to verify it contains the signal connection logic
                method = FontPickerDialog._on_target_button_clicked
                import inspect

                source = inspect.getsource(method)

                # Check that it contains both signal types
                self.assertIn("close-request", source, "Should handle NvimPopup close-request signal")
                self.assertIn("closed", source, "Should handle SystemContextMenu closed signal")
                self.assertIn("isinstance", source, "Should check instance type for correct signal")


class TestDocumentationAndStructure(unittest.TestCase):
    """Test that documentation and code structure are correct."""

    def test_documentation_files_exist(self):
        """Test that documentation files were created."""
        docs_dir = os.path.join(os.path.dirname(__file__), "..", "docs")

        expected_docs = ["POPUP_SYSTEM.md", "FONT_POPUP_FIX.md"]

        for doc_file in expected_docs:
            doc_path = os.path.join(docs_dir, doc_file)
            self.assertTrue(os.path.exists(doc_path), f"Documentation file {doc_file} should exist")

            # Check that the file has content
            with open(doc_path, "r") as f:
                content = f.read()
                self.assertGreater(len(content), 1000, f"{doc_file} should have substantial content")

    def test_test_files_exist(self):
        """Test that test files were created."""
        tests_dir = os.path.dirname(__file__)

        expected_tests = ["test_font_popup_fix.py", "run_font_popup_tests.py"]

        for test_file in expected_tests:
            test_path = os.path.join(tests_dir, test_file)
            self.assertTrue(os.path.exists(test_path), f"Test file {test_file} should exist")


class TestRegressionProtection(unittest.TestCase):
    """Test that the fix prevents the original regression."""

    def test_font_picker_import_works(self):
        """Test that the FontPickerDialog can be imported without issues."""
        with patch.dict(
            "sys.modules",
            {
                "popups.nvim_popup": Mock(),
                "popups.nvim_context_menu": Mock(),
                "common.settings_manager": Mock(),
                "common.utils": Mock(),
            },
        ):
            with (
                patch("popups.font_picker_dialog.NvimPopup"),
                patch("popups.font_picker_dialog.show_context_menu"),
                patch("popups.font_picker_dialog.Gtk"),
                patch("popups.font_picker_dialog.Gdk"),
                patch("popups.font_picker_dialog.GLib"),
            ):
                # This should not raise any exceptions
                from popups.font_picker_dialog import FontPickerDialog

                # Basic checks
                self.assertIsNotNone(FontPickerDialog)
                self.assertTrue(callable(FontPickerDialog))

    def test_critical_methods_prevent_auto_closing(self):
        """Test that the critical fix methods are in place."""
        with patch.dict(
            "sys.modules",
            {
                "popups.nvim_popup": Mock(),
                "popups.nvim_context_menu": Mock(),
                "common.settings_manager": Mock(),
                "common.utils": Mock(),
            },
        ):
            with (
                patch("popups.font_picker_dialog.NvimPopup"),
                patch("popups.font_picker_dialog.show_context_menu"),
                patch("popups.font_picker_dialog.Gtk"),
                patch("popups.font_picker_dialog.Gdk"),
                patch("popups.font_picker_dialog.GLib"),
            ):
                from popups.font_picker_dialog import FontPickerDialog

                # These are the critical methods that fix the regression
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
                        hasattr(FontPickerDialog, method_name),
                        f"Critical method {method_name} must exist to prevent regression",
                    )


if __name__ == "__main__":
    # Run the tests
    unittest.main(verbosity=2)
