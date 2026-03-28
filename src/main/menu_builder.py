"""Builds the application menu for Zen IDE."""

from __future__ import annotations

from gi.repository import Gio


class MenuBuilder:
    """Constructs the Gio.Menu used by the IDE header bar."""

    def build(self) -> Gio.Menu:
        """Create and return the full application menu."""
        menu = Gio.Menu()

        # File section
        file_section = Gio.Menu()
        file_section.append("New", "app.new")
        file_section.append("New Sketch Pad", "app.new_sketch_pad")
        file_section.append("Open...", "app.open")
        file_section.append("Open Folder...", "app.open_folder")
        file_section.append("New Workspace...", "app.new_workspace")
        file_section.append("Open Workspace...", "app.open_workspace")
        file_section.append("Edit Workspace...", "app.edit_workspace")
        file_section.append("Save", "app.save")
        file_section.append("Close Tab", "app.close_tab")
        menu.append_section("File", file_section)

        # Edit section
        edit_section = Gio.Menu()
        edit_section.append("Undo", "app.undo")
        edit_section.append("Redo", "app.redo")
        edit_section.append("Find...", "app.find")
        edit_section.append("Find & Replace...", "app.find_replace")
        edit_section.append("Go to Line...", "app.go_to_line")
        edit_section.append("Toggle Comment", "app.toggle_comment")
        menu.append_section("Edit", edit_section)

        # View section
        view_section = Gio.Menu()
        view_section.append("Quick Open", "app.quick_open")
        view_section.append("Search in Files", "app.global_search")
        view_section.append("Show Diff", "app.show_diff")
        view_section.append("Toggle Dev Pad", "app.show_dev_pad")
        view_section.append("Sketch Pad", "app.open_sketch_pad")
        view_section.append("Show Welcome Screen", "app.show_welcome")
        view_section.append("Focus Explorer", "app.focus_explorer")
        view_section.append("Clear Terminal", "app.clear_terminal")
        view_section.append("Reset Layout", "app.reset_layout")
        view_section.append("Fonts...", "app.fonts")
        view_section.append("Theme...", "app.theme_picker")
        view_section.append("Toggle Dark/Light", "app.toggle_dark_light")
        view_section.append("Reload IDE", "app.reload_ide")
        menu.append_section("View", view_section)

        # Help section
        help_section = Gio.Menu()
        help_section.append("Open Settings File", "app.open_settings_file")
        help_section.append("Keyboard Shortcuts", "app.shortcuts")
        help_section.append("Widget Inspector", "app.toggle_inspect")
        help_section.append("System Monitor...", "app.system_monitor")
        help_section.append("View Crash Logs", "app.view_crash_logs")
        help_section.append("About", "app.about")
        menu.append_section("Help", help_section)

        return menu
