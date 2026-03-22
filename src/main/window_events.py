"""Window events mixin — editor, tree, terminal event callbacks and file watcher."""

import os


class WindowEventsMixin:
    """Mixin: event callbacks from editor, tree, terminal, and file watcher."""

    def _on_editor_tab_switched(self, notebook, page, page_num):
        """Handle editor tab changes."""
        self._focused_panel = "editor"

        # Get tab info using page_num (signal fires before page is fully switched)
        tab_id = self.editor_view._get_tab_id_for_page_num(page_num)
        file_path = None
        tab = None
        if tab_id >= 0 and tab_id in self.editor_view.tabs:
            tab = self.editor_view.tabs[tab_id]
            file_path = tab.file_path

        # Update status bar with current file info
        self.status_bar_widget.set_file(file_path)

        # Update position and modified indicator
        if tab and hasattr(tab, "buffer"):
            buf = tab.buffer
            insert = buf.get_insert()
            iter_at_cursor = buf.get_iter_at_mark(insert)
            line = iter_at_cursor.get_line() + 1
            col = iter_at_cursor.get_line_offset() + 1
            total_lines = buf.get_line_count()
            self.status_bar_widget.set_position(line, col, total_lines)
            self.status_bar_widget.set_modified(tab.modified)

        # Update diagnostics in status bar — show workspace-wide totals
        from shared.diagnostics_manager import get_diagnostics_manager

        mgr = get_diagnostics_manager()
        errors, warnings = mgr.get_total_counts()
        self.status_bar_widget.set_diagnostics(errors, warnings)

        # Update diff view if visible
        if self.split_panels.is_visible("diff"):
            if file_path:
                self.diff_view.show_diff(file_path, self.editor_view.get_current_content())

        # Update IDE state file for AI context
        self._update_ide_state_file()

    def _on_tree_file_selected(self, file_path: str):
        """Handle file selection from tree view."""
        from constants import IMAGE_EXTENSIONS

        # Close diff view if open before switching to a new file
        if self.split_panels.is_visible("diff"):
            self.split_panels.hide("diff")

        if file_path and os.path.isfile(file_path):
            # Skip tree reveal since the file was clicked directly in the tree
            self._opening_from_tree = True
            try:
                ext = os.path.splitext(file_path)[1].lower()
                if ext in IMAGE_EXTENSIONS:
                    self.editor_view.open_image(file_path)
                else:
                    # Check if file is binary
                    from editor.preview.binary_viewer import is_binary_file

                    if is_binary_file(file_path):
                        self.editor_view.open_binary(file_path)
                    else:
                        self.editor_view.open_file(file_path)
            finally:
                self._opening_from_tree = False

    def _has_open_files(self) -> bool:
        """Check if the editor has any open file tabs."""
        return len(self.editor_view.tabs) > 0

    def _on_editor_file_opened(self, file_path: str):
        """Handle file opened in editor - reveal in tree with animation."""
        # Restore from panel maximize when a file is opened (editor stays maximized)
        if getattr(self, "_maximized_panel", None) and self._maximized_panel != "editor":
            self._saved_positions = {}  # Discard — apply default layout instead
            self._maximize_panel(self._maximized_panel)
        # Always expand editor if it was collapsed — not mutually exclusive with
        # un-maximizing above, since _maximize_panel defers layout via idle_add
        # and _editor_collapsed may still be True at this point.
        if getattr(self, "_editor_collapsed", False):
            self._expand_editor()
        if (
            file_path
            and os.path.isfile(file_path)
            and self._has_open_files()
            and not getattr(self, "_opening_from_tree", False)
        ):
            self.tree_view.reveal_file(file_path, animate=True)
        # Update status bar (guard: may be placeholder before _deferred_init_panels)
        if hasattr(self.status_bar_widget, "set_file"):
            self.status_bar_widget.set_file(file_path)
            self._update_status_bar_position()
        # Follow file in terminal
        self._terminal_follow_file(file_path)

        # Update IDE state file for AI context
        self._update_ide_state_file()

    def _on_terminal_open_file(self, file_path: str, line_num: int | None):
        """Handle Cmd+click file navigation from terminal."""
        if file_path and os.path.isfile(file_path):
            if self.split_panels.is_visible("diff"):
                self.split_panels.hide("diff")
            # Ensure editor area is visible before opening the file — the
            # on_file_opened callback normally handles this, but if load_file
            # fails silently the callback never fires, leaving the editor
            # collapsed at 0 height.
            if getattr(self, "_editor_collapsed", False):
                self._expand_editor()
            # Suppress terminal_follow_file so opening a file from the terminal
            # doesn't cd the shell back to the repo root.
            self._opening_from_terminal = True
            try:
                self.editor_view.open_file(file_path, line_num)
            finally:
                self._opening_from_terminal = False

    def _on_editor_tab_switched_reveal(self, file_path: str):
        """Handle tab switch in editor - reveal file in tree with animation."""
        if (
            file_path
            and os.path.isfile(file_path)
            and self._has_open_files()
            and not getattr(self, "_opening_from_tree", False)
        ):
            self.tree_view.reveal_file(file_path, animate=True)
        # Update status bar (guard: may be placeholder before _deferred_init_panels)
        if hasattr(self.status_bar_widget, "set_file"):
            self.status_bar_widget.set_file(file_path)
            self._update_status_bar_position()
        # Follow file in terminal (skip when the file was opened from the terminal itself)
        if not getattr(self, "_opening_from_terminal", False):
            self._terminal_follow_file(file_path)

    def _terminal_follow_file(self, file_path: str):
        """Change terminal directory to the file's repo root if terminal_follow_file is enabled.

        Only changes directory when the file belongs to a different repo than
        the terminal's current working directory, so navigating within the same
        repo never disrupts the user's shell position.
        """
        from shared.settings import get_setting

        if not file_path or not get_setting("behavior.terminal_follow_file", True):
            return
        if not hasattr(self.terminal_view, "get_cwd"):
            return
        from shared.git_manager import get_git_manager

        git = get_git_manager()
        file_repo = git.get_repo_root(file_path)
        current_cwd = self.terminal_view.get_cwd()
        current_repo = git.get_repo_root(current_cwd) if current_cwd else None

        # Only cd when switching to a file in a different repo (or non-repo location)
        if file_repo and file_repo == current_repo:
            return
        target_dir = file_repo if file_repo else os.path.dirname(file_path)
        if target_dir and target_dir != current_cwd:
            self.terminal_view.change_directory(target_dir)

    def _has_welcome_screen(self):
        """Check if a WelcomeScreen page is displayed in the notebook."""
        if not hasattr(self, "editor_view"):
            return False
        for i in range(self.editor_view.notebook.get_n_pages()):
            page = self.editor_view.notebook.get_nth_page(i)
            if page.__class__.__name__ == "WelcomeScreen":
                return True
        return False

    def _has_dev_pad_tab(self):
        """Check if a DevPad page is displayed in the notebook."""
        if not hasattr(self, "editor_view"):
            return False
        for i in range(self.editor_view.notebook.get_n_pages()):
            page = self.editor_view.notebook.get_nth_page(i)
            if page.__class__.__name__ == "DevPad":
                return True
        return False

    def _on_tab_closed(self):
        """Persist open files to settings after a tab is closed."""
        from shared.settings import save_workspace

        open_files = []
        for tab in self.editor_view.tabs.values():
            if tab.file_path:
                open_files.append(tab.file_path)
        last_file = self.editor_view.get_current_file_path()
        save_workspace(open_files=open_files, last_file=last_file)

        # Update IDE state file for AI context
        self._update_ide_state_file()

    def _on_tabs_empty(self):
        """Handle all editor tabs closed — collapse editor area."""
        # Don't collapse if welcome screen is still displayed
        if self._has_welcome_screen():
            return
        # Only collapse editor if auto_expand_terminals is enabled
        from shared.settings import get_setting

        if get_setting("behavior.auto_expand_terminals", True):
            self._collapse_editor()

    def _collapse_editor(self):
        """Collapse editor to 0 height, letting bottom panels fill the space."""
        if getattr(self, "_editor_collapsed", False):
            return
        # Save current right_paned position before collapsing
        self._pre_collapse_right_pos = self.right_paned.get_position()
        self._editor_collapsed = True
        from shared.utils import animate_paned

        def on_collapse_done():
            self.right_paned.add_css_class("editor-collapsed")
            self._sync_terminal_resize()

        animate_paned(self.right_paned, 0, on_done=on_collapse_done)

    def _expand_editor(self):
        """Restore editor to default layout proportions."""
        if not getattr(self, "_editor_collapsed", False):
            return
        self._editor_collapsed = False
        self.right_paned.remove_css_class("editor-collapsed")
        # Apply default layout: 65% editor, 35% bottom panels
        window_height = self.get_height()
        editor_height = int(window_height * 0.65)

        from shared.utils import animate_paned

        animate_paned(self.right_paned, editor_height, on_done=self._sync_terminal_resize)

        # Only reset bottom panels to default proportions if auto_expand_terminals is enabled
        from shared.settings import get_setting

        if get_setting("behavior.auto_expand_terminals", True):
            self._auto_expand_terminals()

    def _auto_expand_terminals(self):
        """Reset bottom panels to default proportions - only called when auto_expand_terminals is enabled."""
        from constants import DEFAULT_TREE_WIDTH
        from shared.utils import animate_paned

        ai_enabled = getattr(self, "_ai_enabled", True)
        window_width = self.get_width()
        bottom_panel_width = window_width - DEFAULT_TREE_WIDTH
        ai_chat_width = bottom_panel_width // 2 if ai_enabled else 0
        if self._bottom_panels_created:
            if ai_enabled:
                self.ai_chat.set_visible(True)
            self.terminal_view.set_visible(True)
        animate_paned(self.bottom_paned, ai_chat_width)

    def _on_cursor_position_changed(self, line: int, col: int, total_lines: int):
        """Handle cursor position change from editor."""
        self.status_bar_widget.set_position(line, col, total_lines)

    def _on_diagnostics_changed(self, errors: int, warnings: int):
        """Handle diagnostics update from editor — show workspace-wide totals."""
        from shared.diagnostics_manager import get_diagnostics_manager

        mgr = get_diagnostics_manager()
        total_errors, total_warnings = mgr.get_total_counts()
        self.status_bar_widget.set_diagnostics(total_errors, total_warnings)

    def _on_diagnostics_clicked(self):
        """Handle click on diagnostics indicator — toggle workspace-wide diagnostics popup."""
        # Close existing popup if already open
        existing = getattr(self, "_workspace_diag_popup", None)
        if existing is not None and existing.get_visible():
            existing.close()
            self._workspace_diag_popup = None
            return

        from popups.diagnostics_popup import show_workspace_diagnostics

        def on_jump_file(file_path: str, line: int):
            if self.split_panels.is_visible("diff"):
                self.split_panels.hide("diff")
            self.editor_view.open_file(file_path, line_number=line)

        popup = show_workspace_diagnostics(self, on_jump_to_file=on_jump_file)
        popup.connect("close-request", lambda _w: setattr(self, "_workspace_diag_popup", None) or False)
        self._workspace_diag_popup = popup

    def _update_status_bar_position(self):
        """Update the status bar with current cursor position."""
        if not hasattr(self.status_bar_widget, "set_position"):
            return
        tab = self.editor_view.get_current_tab()
        if tab and hasattr(tab, "buffer"):
            buf = tab.buffer
            insert = buf.get_insert()
            iter_at_cursor = buf.get_iter_at_mark(insert)
            line = iter_at_cursor.get_line() + 1
            col = iter_at_cursor.get_line_offset() + 1
            total_lines = buf.get_line_count()
            self.status_bar_widget.set_position(line, col, total_lines)
            self.status_bar_widget.set_modified(tab.modified)

    def _start_file_watcher(self):
        """Start watching workspace folders for file system changes."""
        from shared.file_watcher import start_file_watcher

        workspace_folders = self.tree_view.get_workspace_folders()
        start_file_watcher(
            workspace_folders=workspace_folders,
            on_tree_refresh=self._on_watcher_tree_refresh,
            on_git_refresh=self._on_watcher_git_refresh,
            on_file_modified=self._on_watcher_file_modified,
        )

    def _on_watcher_tree_refresh(self):
        """Handle tree refresh triggered by file watcher."""
        if hasattr(self.tree_view, "refresh"):
            self.tree_view.refresh()

    def _on_watcher_git_refresh(self, force: bool = False):
        """Handle git refresh triggered by file watcher."""
        self.tree_view.refresh_git_status()

    def _on_watcher_file_modified(self, file_path: str):
        """Handle external file modification detected by file watcher."""
        if hasattr(self.editor_view, "on_external_file_change"):
            self.editor_view.on_external_file_change(file_path)
