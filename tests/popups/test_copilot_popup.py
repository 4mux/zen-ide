"""Tests for CopilotPopup (src/popups/copilot_popup.py)."""

from tests.popups.conftest import (
    class_inherits,
    find_class,
    find_method,
    parse_popup_source,
    read_popup_source,
)


class TestCopilotPopupStructure:
    """Verify CopilotPopup structural contracts."""

    def test_inherits_nvim_popup(self):
        tree = parse_popup_source("copilot_popup.py")
        assert class_inherits(tree, "CopilotPopup", "NvimPopup")

    def test_has_create_content(self):
        tree = parse_popup_source("copilot_popup.py")
        cls = find_class(tree, "CopilotPopup")
        assert find_method(cls, "_create_content") is not None

    def test_has_on_key_pressed(self):
        tree = parse_popup_source("copilot_popup.py")
        cls = find_class(tree, "CopilotPopup")
        assert find_method(cls, "_on_key_pressed") is not None

    def test_has_on_confirm_clicked(self):
        tree = parse_popup_source("copilot_popup.py")
        cls = find_class(tree, "CopilotPopup")
        assert find_method(cls, "_on_confirm_clicked") is not None

    def test_uses_create_button_row(self):
        source = read_popup_source("copilot_popup.py")
        assert "_create_button_row" in source


class TestCopilotPopupKeyHandling:
    """Verify key handling."""

    def test_enter_confirms(self):
        source = read_popup_source("copilot_popup.py")
        assert "KEY_Return" in source or "KEY_KP_Enter" in source

    def test_escape_closes_via_super(self):
        source = read_popup_source("copilot_popup.py")
        assert "super()._on_key_pressed" in source


class TestCopilotPopupContent:
    """Verify popup content."""

    def test_mentions_copilot(self):
        source = read_popup_source("copilot_popup.py")
        assert "Copilot" in source

    def test_has_cancel_button(self):
        source = read_popup_source("copilot_popup.py")
        assert "Cancel" in source

    def test_has_confirm_button(self):
        source = read_popup_source("copilot_popup.py")
        assert "Switch to Copilot" in source

    def test_has_hint_bar(self):
        source = read_popup_source("copilot_popup.py")
        assert "_create_hint_bar" in source
