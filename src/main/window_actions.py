"""Window actions mixin — all action handler callbacks for menu items and shortcuts."""

import os

from gi.repository import Gio, GLib, Gtk


class WindowActionsMixin:
    """Mixin: action handlers for file, edit, view, and help menu items."""

    # --- File actions ---

    def _on_new(self, action, param):
        """Create a new file."""
        self.editor_view.new_file()

    def _on_new_sketch_pad(self, action, param):
        """Create a new untitled sketch pad."""
        self.editor_view.new_sketch_file()

    def _on_open(self, action, param):
        """Open a file."""
        dialog = Gtk.FileDialog()
        dialog.open(self, None, self._on_open_response)

    def _on_open_response(self, dialog, result):
        """Handle file dialog response."""
        try:
            file = dialog.open_finish(result)
            if file:
                path = file.get_path()
                self.editor_view.open_file(path)
        except GLib.Error:
            pass  # Cancelled

    def _on_open_folder(self, action, param):
        """Open a folder as workspace."""
        dialog = Gtk.FileDialog()
        dialog.set_title("Open Folder")
        dialog.select_folder(self, None, self._on_open_folder_response)

    def _on_open_folder_response(self, dialog, result):
        """Handle folder dialog response."""
        try:
            file = dialog.select_folder_finish(result)
            if file:
                path = file.get_path()
                from shared.git_ignore_utils import collect_global_patterns
                from shared.settings import set_setting

                collect_global_patterns([path])
                self.tree_view.load_workspace([path])
                self.set_title(f"Zen IDE — {os.path.basename(path)}")
                set_setting("workspace.workspace_file", "")
                set_setting("workspace.folders", [path])
                # Show all panels in case we were in single-file mode
                self._show_all_panels()
        except GLib.Error:
            pass  # Cancelled

    def _on_new_workspace(self, action, param):
        """Create a new .zen-workspace file with a template and prompt to save."""
        import json as json_module

        # Start with a blank template — the user will fill in the folders
        template = {
            "folders": [
                {
                    "name": "my-project",
                    "path": ".",
                }
            ],
        }
        content = json_module.dumps(template, indent=2) + "\n"

        # Show a Save dialog so the user picks where to store the workspace file
        dialog = Gtk.FileDialog()
        dialog.set_title("Save New Workspace As")

        # Default file name
        dialog.set_initial_name("my-project.zen-workspace")

        # Filter for workspace files
        filter_ws = Gtk.FileFilter()
        filter_ws.set_name("Zen Workspace Files")
        filter_ws.add_pattern("*.zen-workspace")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filter_ws)
        dialog.set_filters(filters)

        dialog.save(
            self,
            None,
            lambda d, r: self._on_new_workspace_save_response(d, r, content),
        )

    def _on_new_workspace_save_response(self, dialog, result, content):
        """Handle the Save dialog response for a new workspace file."""
        try:
            file = dialog.save_finish(result)
            if not file:
                return
            path = file.get_path()

            # Ensure .zen-workspace extension
            if not path.endswith(".zen-workspace"):
                path += ".zen-workspace"

            # Write the template to disk
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

            # Open the newly created file in the editor for further editing
            self.editor_view.open_file(path)

            # Ask whether to load this workspace now
            from popups.confirm_dialog import show_confirm

            show_confirm(
                self,
                title="Load Workspace",
                message=f'Workspace "{os.path.basename(path)}" saved.\n\nDo you want to load it now?',
                confirm_text="Load",
                cancel_text="Not Now",
                on_confirm=lambda: self._load_workspace_file(path),
            )
        except GLib.Error:
            pass  # User cancelled

    def _on_open_workspace(self, action, param):
        """Open a .zen-workspace or .code-workspace file."""
        dialog = Gtk.FileDialog()
        dialog.set_title("Open Workspace")
        # Filter for workspace files
        filter_ws = Gtk.FileFilter()
        filter_ws.set_name("Workspace Files")
        filter_ws.add_pattern("*.zen-workspace")
        filter_ws.add_pattern("*.code-workspace")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filter_ws)
        dialog.set_filters(filters)
        dialog.open(self, None, self._on_open_workspace_response)

    def _on_open_workspace_response(self, dialog, result):
        """Handle workspace dialog response."""
        try:
            file = dialog.open_finish(result)
            if file:
                path = file.get_path()
                self._load_workspace_file(path)
        except GLib.Error:
            pass  # Cancelled

    def _on_edit_workspace(self, action, param):
        """Open the current workspace file in the editor for manual editing."""
        from shared.settings import get_setting

        ws_file = get_setting("workspace.workspace_file", "")
        if ws_file and os.path.isfile(ws_file):
            self.editor_view.open_file(ws_file)

    def _load_workspace_file(self, workspace_path: str):
        """Load a .zen-workspace or .code-workspace file and open its folders."""
        import json as json_module
        import re

        from shared.git_ignore_utils import collect_global_patterns
        from shared.settings import set_setting

        try:
            with open(workspace_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Workspace files may have trailing commas and comments
            # Remove single-line comments (// ...)
            content = re.sub(r"//[^\n]*", "", content)
            # Remove trailing commas before } or ]
            content = re.sub(r",(\s*[}\]])", r"\1", content)

            workspace_data = json_module.loads(content)

            folders = workspace_data.get("folders", [])
            if not folders:
                return

            # Resolve folder paths relative to workspace file
            ws_dir = os.path.dirname(workspace_path)
            resolved_folders = []
            for folder in folders:
                folder_path = folder.get("path", "")
                if folder_path:
                    if not os.path.isabs(folder_path):
                        folder_path = os.path.normpath(os.path.join(ws_dir, folder_path))
                    if os.path.isdir(folder_path):
                        resolved_folders.append(folder_path)
                    else:
                        pass

            if resolved_folders:
                # Collect gitignore patterns BEFORE loading tree
                collect_global_patterns(resolved_folders)
                # Load multiple workspace folders
                ws_name = os.path.basename(workspace_path)
                self.tree_view.load_workspace(resolved_folders, workspace_name=ws_name)
                self.set_title(f"Zen IDE — {ws_name}")
                set_setting("workspace.workspace_file", workspace_path)
                set_setting("workspace.folders", [])
                # Show all panels in case we were in single-file mode
                self._show_all_panels()
        except Exception:
            pass

    # --- Save / Close ---

    def _on_save(self, action, param):
        """Save current file."""
        if self.editor_view.save_current():
            from shared.settings import SETTINGS_FILE, load_settings

            # Reload settings if the user just saved settings.json
            current_path = self.editor_view.get_current_file_path()
            if current_path and SETTINGS_FILE == current_path:
                try:
                    load_settings()
                except Exception:
                    pass

    def _on_close_tab(self, action, param):
        """Close current tab."""
        # Hide diff view before closing so the next tab doesn't open in diff mode
        if self.split_panels.is_visible("diff"):
            self.split_panels.hide("diff")
        self.editor_view.close_current_tab()
        if not self._has_open_files():
            self.status_bar_widget.set_file(None)

    # --- Edit actions ---

    def _on_undo(self, action, param):
        """Undo in editor."""
        self.editor_view.undo()

    def _on_redo(self, action, param):
        """Redo in editor."""
        self.editor_view.redo()

    def _on_find(self, action, param):
        """Show find bar."""
        if self.split_panels.is_visible("diff"):
            self.diff_view.show_find_bar()
        else:
            self.editor_view.show_find_bar()

    def _on_find_replace(self, action, param):
        """Show find & replace bar."""
        self.editor_view.show_find_bar(replace=True)

    def _on_go_to_line(self, action, param):
        """Show Go-To-Line dialog."""
        self.editor_view.show_go_to_line()

    def _on_toggle_comment(self, action, param):
        """Toggle comment on current line(s)."""
        self.editor_view.toggle_comment()

    def _on_indent(self, action, param):
        """Indent current line(s)."""
        self.editor_view.indent()

    def _on_unindent(self, action, param):
        """Unindent current line(s)."""
        self.editor_view.unindent()

    # --- View / Navigation actions ---

    def _on_focus_explorer(self, action, param):
        """Focus the tree view."""
        self._focused_panel = "tree"
        if not self.tree_view.get_visible():
            self.tree_view.set_visible(True)
        self.tree_view.focus_tree()

    def _on_clear_terminal(self, action, param):
        """Clear the terminal."""
        self.terminal_view.clear()

    def _on_global_search(self, action, param):
        """Open global search dialog."""
        from popups.global_search_dialog import GlobalSearchDialog

        folders = self.tree_view.get_workspace_folders()
        dialog = GlobalSearchDialog(
            self,
            workspace_folders=folders,
            on_result_selected=lambda path, line: self.editor_view.open_file(path, line),
        )
        dialog.present()

    def _on_quick_open(self, action, param):
        """Open quick open dialog."""
        from popups.quick_open_dialog import QuickOpenDialog

        folders = self.tree_view.get_workspace_folders()
        dialog = QuickOpenDialog(
            self,
            workspace_folders=folders,
            on_file_selected=lambda path: self.editor_view.open_file(path),
        )
        dialog.present()

    def _on_show_diff(self, action, param):
        """Toggle diff view in split pane for current file."""
        if self.split_panels.is_visible("diff"):
            self.split_panels.hide("diff")
            return
        file_path = self.editor_view.get_current_file_path()
        if file_path:
            self.split_panels.show("diff", file_path=file_path, content=self.editor_view.get_current_content())

    def _on_show_dev_pad(self, action, param):
        """Toggle the Dev Pad tab."""
        self.editor_view.toggle_dev_pad(self.dev_pad)

    def _on_open_sketch_pad(self, action, param):
        """Open the workspace .zen_sketch file, or create a new in-memory sketch."""
        import glob as glob_mod

        folders = self.tree_view.get_workspace_folders()

        # Look for existing .zen_sketch file in workspace roots
        for folder in folders:
            matches = glob_mod.glob(os.path.join(folder, "*.zen_sketch"))
            if matches:
                self.editor_view.open_file(matches[0])
                return

        # No existing file — open an in-memory sketch tab (no file created)
        self.editor_view.new_sketch_file()

    def _on_focus_terminal(self, action, param):
        """Focus the terminal."""
        self._focused_panel = "terminal"
        self.terminal_view.grab_focus()

    def _on_focus_ai_chat(self, action, param):
        """Focus the AI chat input."""
        self._focused_panel = "ai_chat"
        self.ai_chat.focus_input()

    def _on_stop_ai(self, action, param):
        """Stop AI generation if processing, or close diff view."""
        if self.ai_chat.is_processing():
            self.ai_chat.stop_ai()
        elif self.split_panels.is_visible("diff"):
            self.split_panels.hide("diff")

    def _on_next_tab(self, action, param):
        """Switch to next editor tab."""
        n = self.editor_view.notebook.get_n_pages()
        if n > 1:
            current = self.editor_view.notebook.get_current_page()
            self.editor_view.notebook.set_current_page((current + 1) % n)

    def _on_prev_tab(self, action, param):
        """Switch to previous editor tab."""
        n = self.editor_view.notebook.get_n_pages()
        if n > 1:
            current = self.editor_view.notebook.get_current_page()
            self.editor_view.notebook.set_current_page((current - 1) % n)

    def _on_zoom_in(self, action, param):
        """Increase font size (or sketch zoom if sketch tab is active)."""
        tab = self.editor_view._get_current_tab()
        if getattr(tab, "_is_sketch", False):
            tab.widget._canvas_widget.zoom(0.1)
            return

        if self.editor_view._has_dev_pad_tab() and self.editor_view._is_dev_pad_active():
            self._zoom_dev_pad(1)
            return

        from constants import MAX_FONT_SIZE

        self._font_size = min(self._font_size + 1, MAX_FONT_SIZE)
        self._apply_font_size()
        self._zoom_markdown_previews("in")

    def _on_zoom_out(self, action, param):
        """Decrease font size (or sketch zoom if sketch tab is active)."""
        tab = self.editor_view._get_current_tab()
        if getattr(tab, "_is_sketch", False):
            tab.widget._canvas_widget.zoom(-0.1)
            return

        if self.editor_view._has_dev_pad_tab() and self.editor_view._is_dev_pad_active():
            self._zoom_dev_pad(-1)
            return

        from constants import MIN_FONT_SIZE

        self._font_size = max(self._font_size - 1, MIN_FONT_SIZE)
        self._apply_font_size()
        self._zoom_markdown_previews("out")

    def _on_maximize_focused(self, action, param):
        """Maximize the currently focused panel, or restore if already maximized."""
        # If any panel is already maximized, restore it first
        if self._maximized_panel:
            self._maximize_panel(self._maximized_panel)
            return

        # Use ComponentFocusManager as source of truth since it's updated by panel clicks
        from shared.focus_manager import get_component_focus_manager

        focus_mgr = get_component_focus_manager()
        focused = focus_mgr.get_current_focus()
        # Map component IDs to panel names (they're the same in our case)
        panel = focused if focused in ("editor", "terminal", "ai_chat", "tree", "treeview") else self._focused_panel
        # Normalize "treeview" to "tree"
        if panel == "treeview":
            panel = "tree"
        self._maximize_panel(panel)

    def _on_maximize_window(self, action, param):
        """Maximize window and reset layout to defaults (Cmd+Shift+0)."""
        # Reset layout to defaults
        self._maximized_panel = None
        self._sync_maximize_buttons()
        self._saved_positions = {}
        if not self.is_maximized():
            self.maximize()
            # Window maximize is async; delay layout until resize completes
            GLib.timeout_add(150, self._apply_default_layout)
        else:
            GLib.idle_add(self._apply_default_layout)

    def _on_reset_layout(self, action, param):
        """Reset all splitter positions to default layout."""
        # Restore any maximized panel
        if self._maximized_panel:
            self._maximized_panel = None
            self._sync_maximize_buttons()

        # Clear saved positions
        self._saved_positions = {}

        # If panels were hidden in single-file mode, create and show them
        if not self._bottom_panels_created:
            self._create_bottom_panels()
            if getattr(self, "_ai_enabled", True):
                self.ai_chat.on_maximize = lambda name: self._maximize_panel(name)
            self.terminal_view.on_maximize = lambda name: self._maximize_panel(name)
        self.tree_view.set_visible(True)
        self.bottom_paned.set_visible(True)

        # Use idle_add to ensure window size is available after any pending operations
        GLib.idle_add(self._apply_default_layout)

    # --- Theme / Font actions ---

    def _on_theme_picker(self, action, param):
        """Open theme picker with live preview."""
        from popups.theme_picker_dialog import show_theme_picker

        show_theme_picker(self, self._apply_theme)

    def _on_toggle_dark_light(self, action, param):
        """Toggle between dark and light mode."""
        from themes import toggle_dark_light

        toggle_dark_light()
        self._apply_theme()

    def _on_open_settings_file(self, action, param):
        """Open the settings.json file in the editor."""
        from shared.settings import SETTINGS_FILE, load_settings

        settings_path = SETTINGS_FILE
        if not os.path.exists(settings_path):
            load_settings()
        if os.path.exists(settings_path):
            self.editor_view.open_file(settings_path)

    def _on_fonts(self, action, param):
        """Open font picker dialog."""
        from fonts import set_font_settings
        from popups.font_picker_dialog import show_font_picker

        def apply_font(family: str, weight: str, size: int, target: str):
            """Apply font settings to target component."""
            set_font_settings(target, family=family, size=size, weight=weight)
            # Update cached font size for zoom
            if target == "editor":
                self._font_size = size
            # Refresh specific component
            self._refresh_component_font(target)

        show_font_picker(self, on_apply=apply_font)

    def _on_show_welcome(self, action, param):
        """Show the welcome screen as a new tab."""
        self._show_welcome_screen()

    # --- Help actions ---

    def _on_shortcuts(self, action, param):
        """Show keyboard shortcuts in vim-style popup."""
        from popups.keyboard_shortcuts_popup import show_keyboard_shortcuts

        show_keyboard_shortcuts(self)

    def _on_system_monitor(self, action, param):
        """Toggle the system monitor split view."""
        self.split_panels.toggle("system_monitor")

    def _on_view_crash_logs(self, action, param):
        """Open the crash log file in the editor."""
        from shared.crash_log import get_crash_log_path

        crash_log = get_crash_log_path()
        if crash_log.exists():
            self.editor_view.open_file(str(crash_log))
        else:
            # Create empty crash log if it doesn't exist
            crash_log.parent.mkdir(parents=True, exist_ok=True)
            crash_log.write_text("# Crash Log\n\nNo crashes recorded yet.\n")
            self.editor_view.open_file(str(crash_log))

    def _on_about(self, action, param):
        """Show about dialog in vim-style popup."""
        from popups.about_popup import show_about

        show_about(self)

    def _on_toggle_inspect(self, action, param):
        """Toggle the widget inspector mode (browser DevTools-like)."""
        if not hasattr(self, "_widget_inspector") or self._widget_inspector is None:
            from debug.widget_inspector import WidgetInspector

            self._widget_inspector = WidgetInspector(self)
        self._widget_inspector.toggle()

    # --- Reload / Quit ---

    def _on_reload_ide(self, action, param):
        """Hot reload the IDE (Cmd+R) - saves state and restarts with make run-gtk."""
        import subprocess

        # Save current state before reloading
        self._save_state()

        # Get the zen_ide project directory (3 levels up from src/main/window_actions.py)
        zen_ide_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        # Start the new process in a new session
        subprocess.Popen(
            ["make", "run"],
            cwd=zen_ide_dir,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Clean up AI processes before restarting
        if hasattr(self, "ai_chat") and hasattr(self.ai_chat, "cleanup"):
            self.ai_chat.cleanup()

        # Force exit immediately - os._exit bypasses cleanup but ensures we don't
        # linger while the new instance starts
        from shared.utils import persist_clipboard

        persist_clipboard()
        os._exit(0)

    def _on_quit(self, action, param):
        """Quit the application."""
        self.close()
