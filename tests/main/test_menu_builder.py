"""Tests for MenuBuilder — verifies menu structure and items."""

from gi.repository import Gio

from main.menu_builder import MenuBuilder


def _section_items(menu: Gio.Menu, section_idx: int) -> list[tuple[str, str]]:
    """Return (label, action) pairs for the given section index."""
    # Each top-level item is a section; get its link
    section = menu.get_item_link(section_idx, Gio.MENU_LINK_SECTION)
    items = []
    for i in range(section.get_n_items()):
        label = section.get_item_attribute_value(i, Gio.MENU_ATTRIBUTE_LABEL, None)
        action = section.get_item_attribute_value(i, Gio.MENU_ATTRIBUTE_ACTION, None)
        items.append((label.get_string() if label else None, action.get_string() if action else None))
    return items


def _section_label(menu: Gio.Menu, section_idx: int) -> str | None:
    """Return the section label for the given index."""
    val = menu.get_item_attribute_value(section_idx, Gio.MENU_ATTRIBUTE_LABEL, None)
    return val.get_string() if val else None


class TestMenuBuilder:
    """Tests for MenuBuilder.build()."""

    def setup_method(self):
        self.menu = MenuBuilder().build()

    def test_has_four_sections(self):
        assert self.menu.get_n_items() == 4

    def test_section_labels(self):
        labels = [_section_label(self.menu, i) for i in range(4)]
        assert labels == ["File", "Edit", "View", "Help"]

    def test_file_section_items(self):
        items = _section_items(self.menu, 0)
        labels = [label for label, _ in items]
        assert labels == [
            "New",
            "New Sketch Pad",
            "Open...",
            "Open Folder...",
            "New Workspace...",
            "Open Workspace...",
            "Edit Workspace...",
            "Save",
            "Close Tab",
        ]

    def test_file_section_actions(self):
        items = _section_items(self.menu, 0)
        actions = [action for _, action in items]
        assert actions == [
            "app.new",
            "app.new_sketch_pad",
            "app.open",
            "app.open_folder",
            "app.new_workspace",
            "app.open_workspace",
            "app.edit_workspace",
            "app.save",
            "app.close_tab",
        ]

    def test_edit_section_items(self):
        items = _section_items(self.menu, 1)
        labels = [label for label, _ in items]
        assert labels == ["Undo", "Redo", "Find...", "Find & Replace...", "Go to Line...", "Toggle Comment"]

    def test_edit_section_actions(self):
        items = _section_items(self.menu, 1)
        actions = [action for _, action in items]
        assert actions == ["app.undo", "app.redo", "app.find", "app.find_replace", "app.go_to_line", "app.toggle_comment"]

    def test_view_section_items(self):
        items = _section_items(self.menu, 2)
        labels = [label for label, _ in items]
        assert "Quick Open" in labels
        assert "Search in Files" in labels
        assert "Show Diff" in labels
        assert "Reload IDE" in labels
        assert len(labels) == 13

    def test_view_section_actions(self):
        items = _section_items(self.menu, 2)
        actions = [action for _, action in items]
        assert "app.quick_open" in actions
        assert "app.reload_ide" in actions

    def test_help_section_items(self):
        items = _section_items(self.menu, 3)
        labels = [label for label, _ in items]
        assert labels == [
            "Open Settings File",
            "Keyboard Shortcuts",
            "Widget Inspector",
            "System Monitor...",
            "View Crash Logs",
            "About",
        ]

    def test_help_section_actions(self):
        items = _section_items(self.menu, 3)
        actions = [action for _, action in items]
        assert actions == [
            "app.open_settings_file",
            "app.shortcuts",
            "app.toggle_inspect",
            "app.system_monitor",
            "app.view_crash_logs",
            "app.about",
        ]

    def test_build_returns_gio_menu(self):
        assert isinstance(self.menu, Gio.Menu)

    def test_multiple_builds_independent(self):
        menu2 = MenuBuilder().build()
        assert menu2.get_n_items() == self.menu.get_n_items()
        # They should be separate instances
        assert menu2 is not self.menu
