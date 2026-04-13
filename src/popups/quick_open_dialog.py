"""
Quick Open Dialog for Zen IDE.
Provides fuzzy file finding across the workspace using Neovim-style popup.
"""

import os
import threading

from gi.repository import Gdk, GLib, Gtk, Pango

from popups.nvim_popup import NvimPopup
from shared.main_thread import main_thread_call


class QuickOpenDialog(NvimPopup):
    """Quick open dialog for fuzzy file finding (Ctrl+P style)."""

    def __init__(self, parent, workspace_folders: list[str], on_file_selected=None):
        self.workspace_folders = workspace_folders
        self.on_file_selected = on_file_selected
        self.all_files: list[tuple[str, str]] = []  # (full_path, relative_path)
        self.filtered_files: list[tuple[str, str]] = []
        self._search_timeout = None
        self._filter_generation = 0
        super().__init__(parent, title="Quick Open", width=800, height=600)

        # Load files in background
        self._load_files_async()

    def _create_content(self):
        """Create the quick open UI."""
        # Search entry
        self.search_entry = self._create_search_entry("Type to search files...")
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.search_entry.connect("activate", self._on_activate)
        self.search_entry.connect("stop-search", self._on_stop_search)
        self._content_box.append(self.search_entry)

        # Results list
        scrolled, self.results_list = self._create_scrolled_listbox(
            min_height=450,
            max_height=550,
        )
        self.results_list.connect("row-activated", self._on_row_activated)
        self._content_box.append(scrolled)

        # Status label
        self.status_label = self._create_status_label("Loading files...")
        self._content_box.append(self.status_label)

        # Focus search entry
        self.search_entry.grab_focus()

    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Handle key press."""
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
        elif keyval == Gdk.KEY_BackSpace and meta:
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
        """Delete text from cursor to beginning of line in a Gtk.SearchEntry."""
        pos = entry.get_position()
        if pos > 0:
            text = entry.get_text()
            entry.set_text(text[pos:])
            entry.set_position(0)

    def _move_selection(self, delta: int):
        """Move list selection up or down."""
        selected = self.results_list.get_selected_row()
        rows = list(self.results_list)

        if not rows:
            return

        if selected is None:
            idx = 0 if delta > 0 else len(rows) - 1
        else:
            idx = (rows.index(selected) + delta) % len(rows)

        self.results_list.select_row(rows[idx])
        rows[idx].grab_focus()

    def _load_files_async(self):
        """Load all files in background."""
        thread = threading.Thread(target=self._load_files_worker)
        thread.daemon = True
        thread.start()

    def _load_files_worker(self):
        """Worker thread to load all files via ripgrep."""
        import subprocess

        files = []

        valid_folders = [f for f in self.workspace_folders if os.path.isdir(f)]
        if not valid_folders:
            main_thread_call(self._on_files_loaded, files)
            return

        try:
            result = subprocess.run(
                ["rg", "--files", "--hidden"] + valid_folders,
                capture_output=True,
                text=True,
                timeout=30,
            )

            multi = len(self.workspace_folders) > 1

            for line in result.stdout.split("\n"):
                if not line:
                    continue

                full_path = line

                # Build display path
                if multi:
                    for folder in valid_folders:
                        if full_path.startswith(folder):
                            folder_name = os.path.basename(folder)
                            rel = full_path[len(folder) :].lstrip(os.sep)
                            display_path = os.path.join(folder_name, rel)
                            break
                    else:
                        display_path = full_path
                else:
                    display_path = os.path.relpath(full_path, valid_folders[0])

                files.append((full_path, display_path))
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

        main_thread_call(self._on_files_loaded, files)

    def _on_files_loaded(self, files: list[tuple[str, str]]):
        """Called when files are loaded."""
        self.all_files = sorted(files, key=lambda x: x[1].lower())
        self.status_label.set_text(f"{len(files)} files")
        self._do_filter()
        return False

    def _on_search_changed(self, entry):
        """Handle search text change (debounced)."""
        if self._search_timeout:
            GLib.source_remove(self._search_timeout)
        self._search_timeout = GLib.timeout_add(150, self._do_filter)

    def _do_filter(self):
        """Kick off filtering on a background thread."""
        if self._search_timeout:
            GLib.source_remove(self._search_timeout)
        self._search_timeout = None

        query = self.search_entry.get_text()
        all_files = self.all_files

        self._filter_generation += 1
        generation = self._filter_generation

        thread = threading.Thread(
            target=self._filter_worker,
            args=(query, all_files, generation),
            daemon=True,
        )
        thread.start()
        return False

    def _filter_worker(self, query: str, all_files: list[tuple[str, str]], generation: int):
        """Compute fuzzy matches off the main thread."""
        if not query:
            filtered = all_files[:100]
        else:
            query_lower = query.lower()
            scored = []
            for full_path, display_path in all_files:
                score = self._fuzzy_score(query_lower, display_path.lower())
                if score > 0:
                    scored.append((score, full_path, display_path))
            scored.sort(key=lambda x: -x[0])
            filtered = [(f, d) for _, f, d in scored[:100]]

        if self._filter_generation == generation:
            main_thread_call(self._apply_results, filtered, generation)

    def _apply_results(self, filtered: list[tuple[str, str]], generation: int):
        """Replace the list rows on the main thread (only if still current)."""
        if self._filter_generation != generation:
            return

        self.filtered_files = filtered

        # Clear current results
        while True:
            row = self.results_list.get_first_child()
            if row:
                self.results_list.remove(row)
            else:
                break

        # Add rows
        for full_path, display_path in filtered:
            row = Gtk.ListBoxRow()
            row._file_path = full_path
            row.add_css_class("nvim-popup-list-item")

            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.set_margin_start(8)
            box.set_margin_end(8)
            box.set_margin_top(2)
            box.set_margin_bottom(2)

            # File name
            name_label = Gtk.Label(label=os.path.basename(display_path))
            name_label.set_halign(Gtk.Align.START)
            name_label.add_css_class("nvim-popup-file-name")
            box.append(name_label)

            # Path
            path_label = Gtk.Label(label=os.path.dirname(display_path))
            path_label.set_halign(Gtk.Align.START)
            path_label.add_css_class("nvim-popup-file-path")
            path_label.set_ellipsize(Pango.EllipsizeMode.START)
            box.append(path_label)

            row.set_child(box)
            self.results_list.append(row)

        # Select first row
        first_row = self.results_list.get_first_child()
        if first_row:
            self.results_list.select_row(first_row)

    def _fuzzy_score(self, query: str, text: str) -> int:
        """Calculate fuzzy match score."""
        if not query:
            return 1

        score = 0
        query_idx = 0

        # Bonus for filename match
        filename = os.path.basename(text)
        if query in filename:
            score += 100
        elif query in text:
            score += 50  # Substring match in path

        # Sequential character matching (fuzzy)
        prev_match_idx = -1
        for i, char in enumerate(text):
            if query_idx < len(query) and char == query[query_idx]:
                score += 10
                # Bonus for consecutive matches
                if prev_match_idx == i - 1:
                    score += 5
                # Bonus for match at word boundary (after / . _ -)
                if i == 0 or text[i - 1] in "/._ -":
                    score += 15
                prev_match_idx = i
                query_idx += 1

        # All characters must match
        if query_idx < len(query):
            return 0

        # Shorter paths score higher (prefer closer matches)
        score += max(0, 50 - len(text) // 5)

        return score

    def _on_activate(self, entry):
        """Handle Enter key in search entry."""
        selected = self.results_list.get_selected_row()
        if selected:
            self._select_file(selected)

    def _on_stop_search(self, entry):
        """Handle Escape key in search entry."""
        self.close()

    def _on_row_activated(self, listbox, row):
        """Handle row activation."""
        self._select_file(row)

    def _select_file(self, row):
        """Select a file and close dialog."""
        if hasattr(row, "_file_path"):
            if self.on_file_selected:
                self.on_file_selected(row._file_path)
            self.close()
