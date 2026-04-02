"""
Global Search Dialog for Zen IDE.
Searches across all files in the workspace using Neovim-style popup.
"""

import os
import threading

from gi.repository import Gdk, GLib, Gtk, Pango

from icons import get_file_icon
from popups.nvim_popup import NvimPopup
from popups.search_engine_mixin import SearchEngineMixin, SearchResult
from popups.selection_dialog import show_selection
from shared.settings import get_setting

# Re-export for backward compatibility
SearchResult = SearchResult  # noqa: F811


class GlobalSearchDialog(SearchEngineMixin, NvimPopup):
    """Global search dialog for searching files in workspace using Neovim-style UI."""

    def __init__(self, parent, workspace_folders: list[str], on_result_selected=None):
        self.workspace_folders = workspace_folders
        self.on_result_selected = on_result_selected
        self.results: list[SearchResult] = []
        self._search_thread = None
        self._search_timeout = None
        self._selected_index = 0
        self._project_names: list[str] = []
        self._selected_project_index = 0
        self._use_nvim_project_popup = get_setting("behavior.is_nvim_emulation_enabled", False)
        self.project_button = None
        self._dropdown_active = False
        self._project_picker_open = False
        super().__init__(parent, title="Search in Files", width=700, height=500)

    def _create_content(self):
        """Create the search dialog UI."""
        # Search entry
        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._content_box.append(search_box)

        self.search_entry = self._create_search_entry("Search in files...")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.search_entry.connect("activate", self._on_search_activate)
        search_box.append(self.search_entry)

        # Case sensitive toggle
        self.case_sensitive = Gtk.CheckButton(label="Aa")
        self.case_sensitive.set_tooltip_text("Match Case")
        search_box.append(self.case_sensitive)

        # Project filter dropdown (only show if multiple workspace folders)
        if len(self.workspace_folders) > 1:
            project_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            project_box.set_margin_top(4)
            self._content_box.append(project_box)

            project_label = Gtk.Label(label="Project:")
            project_label.add_css_class("nvim-popup-list-item-hint")
            project_box.append(project_label)

            self._project_names = ["All Projects"] + [os.path.basename(f) for f in self.workspace_folders]
            if self._use_nvim_project_popup:
                self.project_dropdown = None
                self.project_button = self._create_button(self._project_names[0])
                self.project_button.set_hexpand(True)
                self.project_button.connect("clicked", self._on_project_button_clicked)
                project_box.append(self.project_button)
            else:
                self._project_string_list = Gtk.StringList.new(self._project_names)
                self.project_dropdown = Gtk.DropDown(model=self._project_string_list)
                self.project_dropdown.set_selected(0)
                self.project_dropdown.set_hexpand(True)
                self.project_dropdown.connect("notify::selected", self._on_project_changed)
                project_box.append(self.project_dropdown)
        else:
            self.project_dropdown = None
            self.project_button = None

        # Results count
        self.results_label = self._create_status_label("")
        self._content_box.append(self.results_label)

        # Results list
        scrolled, self.results_list = self._create_scrolled_listbox(
            min_height=350,
            max_height=400,
        )
        self.results_list.connect("row-activated", self._on_result_activated)
        self._content_box.append(scrolled)

        # Hint
        hint_bar = self._create_hint_bar(
            [
                ("↑↓", "navigate"),
                ("Enter", "open"),
                ("Esc", "close"),
            ]
        )
        self._content_box.append(hint_bar)

        # Focus search entry
        self.search_entry.grab_focus()

    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Handle key press with j/k navigation."""
        meta = state & Gdk.ModifierType.META_MASK

        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        elif keyval == Gdk.KEY_Down:
            self._move_selection(1)
            return True
        elif keyval == Gdk.KEY_Up:
            self._move_selection(-1)
            return True
        elif keyval == Gdk.KEY_Return:
            # If search entry has focus and there's text, search; otherwise select result
            if self.search_entry.has_focus():
                self._do_search()
            else:
                self._activate_selected()
            return True
        elif keyval == Gdk.KEY_BackSpace and meta:
            # Cmd+Backspace: delete from cursor to beginning of line
            self._delete_to_line_start(self.search_entry)
            return True

        # j/k navigation only when not typing in search entry
        if not self._has_text_entry_focus():
            if keyval == Gdk.KEY_j:
                self._move_selection(1)
                return True
            elif keyval == Gdk.KEY_k:
                self._move_selection(-1)
                return True
        return False

    def _delete_to_line_start(self, entry):
        """Delete text from cursor to beginning of line in a Gtk.Entry."""
        pos = entry.get_position()
        if pos > 0:
            text = entry.get_text()
            entry.set_text(text[pos:])
            entry.set_position(0)

    def _move_selection(self, delta: int):
        """Move selection by delta."""
        # Get only result rows (not file headers)
        result_rows = [row for row in self.results_list if hasattr(row, "_result")]
        if not result_rows:
            return

        # Find current selection
        current_row = self.results_list.get_selected_row()
        try:
            current_idx = result_rows.index(current_row) if current_row in result_rows else -1
        except ValueError:
            current_idx = -1

        new_idx = (current_idx + delta) % len(result_rows)
        self._selected_index = new_idx
        self.results_list.select_row(result_rows[new_idx])
        result_rows[new_idx].grab_focus()

    def _activate_selected(self):
        """Activate the currently selected result."""
        row = self.results_list.get_selected_row()
        if row and hasattr(row, "_result"):
            self._on_result_activated(self.results_list, row)

    def _on_focus_leave(self, controller):
        """Override to prevent close when dropdown popover or project selection popup takes focus."""
        if self._project_picker_open:
            return
        if self.project_dropdown is not None or self.project_button is not None:
            # Schedule a check - if focus is still in our window hierarchy, don't close
            GLib.timeout_add(100, self._check_focus_and_close)
            return
        # No dropdown or project button, use default behavior
        super()._on_focus_leave(controller)

    def _on_active_changed(self, window, pspec):
        """Override to prevent close when project selection popup is open."""
        if self._project_picker_open:
            return
        super()._on_active_changed(window, pspec)

    def _check_focus_and_close(self):
        """Check if focus is still related to this dialog before closing."""
        if self._closing or self._project_picker_open:
            return False
        # Get the currently focused widget in the app
        focus_widget = self.get_focus()
        if focus_widget is not None:
            # Focus is still in this window, don't close
            return False
        # Check if the window is still active (dropdown popover might have it)
        if self.is_active():
            return False
        # Check if the dropdown's internal popover is currently visible
        if self._is_dropdown_popover_visible():
            # Re-check later when the popover closes
            GLib.timeout_add(200, self._check_focus_and_close)
            return False
        # No focus in this window - close it
        self._result = None
        self.close()
        return False

    def _is_dropdown_popover_visible(self):
        """Check if the project dropdown's internal popover is currently showing."""
        if self.project_dropdown is None:
            return False
        popover = self._find_popover(self.project_dropdown)
        return popover is not None and popover.get_visible()

    def _find_popover(self, widget):
        """Recursively find a Gtk.Popover in the widget's child tree."""
        child = widget.get_first_child()
        while child:
            if isinstance(child, Gtk.Popover):
                return child
            found = self._find_popover(child)
            if found:
                return found
            child = child.get_next_sibling()
        return None

    def _on_project_changed(self, dropdown, _pspec):
        """Re-run search when project filter changes."""
        if dropdown is not None:
            self._selected_project_index = dropdown.get_selected()
        if self.search_entry.get_text().strip():
            self._do_search()

    def _on_project_button_clicked(self, _button):
        """Show a nvim-style project picker when the button is clicked."""
        self._project_picker_open = True
        items = []
        for idx, name in enumerate(self._project_names):
            item = {"label": name, "value": idx}
            if idx > 0:
                item["hint"] = self.workspace_folders[idx - 1]
            items.append(item)
        show_selection(
            self,
            title="Select Project",
            items=items,
            on_select=self._on_project_selected,
            show_icons=False,
            on_cancel=self._on_project_picker_closed,
        )

    def _on_project_picker_closed(self):
        """Called when the project picker is dismissed without selection."""
        self._delayed_clear_picker_flag()

    def _dismiss_click_outside(self):
        """Override to prevent dismiss when project picker is open."""
        if self._project_picker_open:
            return False
        return super()._dismiss_click_outside()

    def _delayed_clear_picker_flag(self):
        """Reset _project_picker_open after a short delay so focus events settle."""
        GLib.timeout_add(150, self._clear_project_picker_flag)

    def _clear_project_picker_flag(self):
        """Clear the project picker flag and re-grab focus."""
        self._project_picker_open = False
        if not self._closing:
            self.search_entry.grab_focus()
        return GLib.SOURCE_REMOVE

    def _on_project_selected(self, item):
        """Handle project selection from the nvim popup."""
        if isinstance(item, dict):
            idx = item.get("value", 0)
        else:
            try:
                idx = self._project_names.index(item)
            except ValueError:
                idx = 0
        self._selected_project_index = idx
        if self.project_button is not None:
            self.project_button.set_label(self._project_names[idx])
        self._on_project_changed(None, None)
        self._delayed_clear_picker_flag()

    def _get_selected_project_index(self) -> int:
        """Return the currently selected project index."""
        if self.project_dropdown is not None:
            return self.project_dropdown.get_selected()
        return self._selected_project_index

    def _get_search_folders(self):
        """Return folders to search based on project dropdown selection."""
        selected_index = self._get_selected_project_index()
        if selected_index == 0:
            return self.workspace_folders
        idx = selected_index - 1
        if 0 <= idx < len(self.workspace_folders):
            return [self.workspace_folders[idx]]
        return self.workspace_folders

    def _on_search_changed(self, entry):
        """Handle search text change (debounced)."""
        # Cancel previous search
        if self._search_timeout:
            GLib.source_remove(self._search_timeout)
            self._search_timeout = None

        # Debounce search
        self._search_timeout = GLib.timeout_add(300, self._do_search)

    def _on_search_activate(self, entry):
        """Handle Enter key in search entry."""
        self._do_search()

    def _do_search(self):
        """Perform the search."""
        # Cancel any pending debounce timeout so it doesn't fire again
        if self._search_timeout:
            GLib.source_remove(self._search_timeout)
        self._search_timeout = None

        query = self.search_entry.get_text().strip()
        if len(query) < 2:
            self._clear_results()
            return False

        # Clear previous results
        self._clear_results()
        self.results_label.set_text("Searching...")

        # Read GTK widget state on main thread before spawning worker
        case_flag = [] if self.case_sensitive.get_active() else ["-i"]
        search_folders = self._get_search_folders()

        # Bump generation so stale threads discard their results
        self._search_generation += 1
        generation = self._search_generation

        # Run search in background
        thread = threading.Thread(
            target=self._search_worker,
            args=(query, generation, case_flag, search_folders),
        )
        thread.daemon = True
        thread.start()

        return False

    def present(self):
        """Show the dialog and focus the entry."""
        super().present()
        self.search_entry.grab_focus()

    def _clear_results(self):
        """Clear all results from the list."""
        while True:
            row = self.results_list.get_first_child()
            if row:
                self.results_list.remove(row)
            else:
                break
        self.results = []
        self.results_label.set_text("")

    def _update_results(self, results: list[SearchResult]):
        """Update results list on main thread."""
        # Clear existing results first to avoid duplicates when search triggers multiple times
        while True:
            row = self.results_list.get_first_child()
            if row:
                self.results_list.remove(row)
            else:
                break
        self.results = results
        self.results_label.set_text(f"{len(results)} results")

        current_file = None
        first_result_row = None
        for result in results:
            # Add file header if new file
            if result.file_path != current_file:
                current_file = result.file_path
                file_row = Gtk.ListBoxRow()
                file_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
                file_box.set_margin_top(8)
                file_box.set_margin_start(8)

                # File icon (file-type-specific)
                icon_char, icon_color = get_file_icon(result.file_path)
                icon_label = Gtk.Label(label=icon_char)
                icon_label.add_css_class("nvim-popup-list-item-icon")
                icon_label.set_markup(f'<span foreground="{icon_color}">{icon_char}</span>')
                file_box.append(icon_label)

                file_name_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
                file_label = Gtk.Label(label=os.path.basename(result.file_path))
                file_label.set_halign(Gtk.Align.START)
                file_label.add_css_class("nvim-popup-title")
                file_name_box.append(file_label)

                path_label = Gtk.Label(label=os.path.dirname(result.file_path))
                path_label.set_halign(Gtk.Align.START)
                path_label.set_ellipsize(Pango.EllipsizeMode.START)
                path_label.add_css_class("nvim-popup-list-item-hint")
                file_name_box.append(path_label)

                file_box.append(file_name_box)

                file_row.set_child(file_box)
                file_row.set_activatable(False)
                file_row.set_selectable(False)
                self.results_list.append(file_row)

            # Add result row
            row = Gtk.ListBoxRow()
            row._result = result
            row.add_css_class("nvim-popup-list-item")

            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.set_margin_start(16)
            box.set_margin_top(2)
            box.set_margin_bottom(2)

            # Line number
            line_label = Gtk.Label(label=f"{result.line_number}:")
            line_label.add_css_class("nvim-popup-list-item-hint")
            line_label.set_width_chars(5)
            line_label.set_xalign(1.0)
            box.append(line_label)

            # Line text (truncated)
            text = result.line_text[:100] + ("..." if len(result.line_text) > 100 else "")
            text_label = Gtk.Label(label=text)
            text_label.set_halign(Gtk.Align.START)
            text_label.set_ellipsize(Pango.EllipsizeMode.END)
            text_label.add_css_class("nvim-popup-list-item-text")
            box.append(text_label)

            row.set_child(box)
            self.results_list.append(row)

            if first_result_row is None:
                first_result_row = row

        # Select first result
        if first_result_row:
            self.results_list.select_row(first_result_row)

        return False

    def _on_result_activated(self, listbox, row):
        """Handle result row activation."""
        if hasattr(row, "_result"):
            result = row._result
            if self.on_result_selected:
                self.on_result_selected(result.file_path, result.line_number)
            self.close()
