"""Tests for ConfirmDialog (src/popups/confirm_dialog.py)."""

import ast

from tests.popups.conftest import (
    class_inherits,
    find_class,
    find_method,
    parse_popup_source,
    read_popup_source,
)


class TestConfirmDialogStructure:
    """Verify ConfirmDialog structural contracts."""

    def test_inherits_nvim_popup(self):
        tree = parse_popup_source("confirm_dialog.py")
        assert class_inherits(tree, "ConfirmDialog", "NvimPopup")

    def test_has_on_key_pressed(self):
        tree = parse_popup_source("confirm_dialog.py")
        cls = find_class(tree, "ConfirmDialog")
        assert find_method(cls, "_on_key_pressed") is not None

    def test_has_create_content(self):
        tree = parse_popup_source("confirm_dialog.py")
        cls = find_class(tree, "ConfirmDialog")
        assert find_method(cls, "_create_content") is not None

    def test_has_present(self):
        tree = parse_popup_source("confirm_dialog.py")
        cls = find_class(tree, "ConfirmDialog")
        assert find_method(cls, "present") is not None

    def test_uses_create_button_row(self):
        source = read_popup_source("confirm_dialog.py")
        assert "_create_button_row" in source

    def test_uses_close_with_result(self):
        source = read_popup_source("confirm_dialog.py")
        assert "_close_with_result" in source


class TestConfirmDialogKeyHandling:
    """Verify key handling patterns in source code."""

    def test_handles_y_key_for_confirm(self):
        source = read_popup_source("confirm_dialog.py")
        assert "KEY_y" in source or "KEY_Y" in source

    def test_handles_n_key_for_cancel(self):
        source = read_popup_source("confirm_dialog.py")
        assert "KEY_n" in source or "KEY_N" in source

    def test_handles_tab_key_for_switch(self):
        source = read_popup_source("confirm_dialog.py")
        assert "KEY_Tab" in source

    def test_handles_enter_key(self):
        source = read_popup_source("confirm_dialog.py")
        assert "KEY_Return" in source

    def test_handles_escape_key(self):
        source = read_popup_source("confirm_dialog.py")
        assert "KEY_Escape" in source


class TestConfirmDialogCallbacks:
    """Verify callback patterns."""

    def test_has_on_confirm_callback(self):
        source = read_popup_source("confirm_dialog.py")
        assert "_on_confirm" in source

    def test_has_on_cancel_callback(self):
        source = read_popup_source("confirm_dialog.py")
        assert "_on_cancel" in source

    def test_close_with_result_true_on_confirm(self):
        """Confirming should call _close_with_result(True, ...)."""
        source = read_popup_source("confirm_dialog.py")
        assert "_close_with_result(True" in source

    def test_close_with_result_false_on_cancel(self):
        """Cancelling should call _close_with_result(False, ...)."""
        source = read_popup_source("confirm_dialog.py")
        assert "_close_with_result(False" in source


class TestConfirmDialogButtonCycling:
    """Test the Tab button cycling logic (2 buttons)."""

    def test_tab_switches_between_two_buttons(self):
        """Tab handling should reference both _confirm_btn and _cancel_btn."""
        source = read_popup_source("confirm_dialog.py")
        assert "_confirm_btn" in source
        assert "_cancel_btn" in source
        # Tab handler should check which has focus
        assert "has_focus()" in source


class TestShowConfirmHelper:
    """Verify the show_confirm helper function."""

    def test_show_confirm_function_exists(self):
        tree = parse_popup_source("confirm_dialog.py")
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "show_confirm":
                return
        raise AssertionError("show_confirm function not found")

    def test_show_confirm_checks_nvim_mode(self):
        source = read_popup_source("confirm_dialog.py")
        assert "is_nvim_mode" in source
