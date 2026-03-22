"""Window panels mixin — split panel show/hide, maximize, and layout management."""

import os

from gi.repository import GLib


class WindowPanelsMixin:
    """Mixin: split panel visibility, maximize/restore, layout management."""

    def _sync_terminal_resize(self):
        """Force terminal to reconcile PTY size after abrupt pane layout changes."""
        if not self._bottom_panels_created:
            return False
        terminal_view = getattr(self, "terminal_view", None)
        terminal = getattr(terminal_view, "terminal", None)
        if (
            terminal_view
            and terminal_view.get_visible()
            and terminal
            and hasattr(terminal, "check_resize")
            and terminal.get_mapped()
            and terminal.get_allocated_width() > 30
            and terminal.get_allocated_height() > 30
        ):
            terminal.check_resize()
        return False

    # -- Split panel show/hide callbacks (registered with SplitPanelManager) --

    def _show_diff_panel(self, file_path: str, content: str):
        """Show diff view replacing the editor."""
        self.editor_view.set_visible(False)
        self.split_panels.swap_end_child(self.diff_view)
        self.diff_view.show_diff(file_path, content)
        self.diff_view.set_visible(True)
        self.diff_view.grab_focus()
        from shared.focus_manager import get_component_focus_manager

        get_component_focus_manager().set_focus(self.diff_view.COMPONENT_ID)

    def _hide_diff_panel(self):
        """Hide the diff view and restore the editor."""
        self.diff_view.set_visible(False)
        self.editor_view.set_visible(True)

    def _show_end_child_panel(self, widget):
        """Show a widget as a 50% split end_child panel."""
        self.split_panels.swap_end_child(widget)
        widget.show_panel()
        GLib.idle_add(self.split_panels.set_half_position)

        # Ensure editor area gets enough vertical space for the panel
        if getattr(self, "_editor_collapsed", False):
            self._expand_editor()
        else:
            self._ensure_editor_min_height()

    def _hide_end_child_panel(self, widget):
        """Hide an end_child panel and restore full editor width."""
        widget.hide_panel()
        self.split_panels.restore_full_position()

        # If no editor tabs remain, collapse editor so terminals auto-expand
        if not self.editor_view.tabs and not self._has_welcome_screen() and not self._has_dev_pad_tab():
            self._collapse_editor()
        """Ensure editor area gets at least 60% of window height.

        When bottom panels (AI chat + terminal) dominate the vertical space,
        adjust right_paned position so the editor/sketch area is usable.
        """
        window_height = self.get_height()
        if window_height <= 0:
            return
        min_editor_height = int(window_height * 0.6)
        current_pos = self.right_paned.get_position()
        if current_pos < min_editor_height:
            from shared.utils import animate_paned

            animate_paned(self.right_paned, min_editor_height, on_done=self._sync_terminal_resize)

    # -- End split panel callbacks --

    def _on_diff_revert(self, file_path: str):
        """Handle revert from diff view - reload the file in editor and auto-save."""
        if file_path and self.editor_view.get_current_file_path() == file_path:
            tab = self.editor_view._get_current_tab()
            if tab:
                tab.reload_file()
                page_num = self.editor_view.notebook.get_current_page()
                tab_id = self.editor_view._get_tab_id_for_page_num(page_num)
                if tab_id >= 0:
                    self.editor_view._update_tab_title_by_id(tab_id)
            self.tree_view.refresh_git_status()

    def _on_diff_navigate(self, line_number: int):
        """Handle double-click on diff view - close diff and scroll editor to line."""
        self.split_panels.hide("diff")
        GLib.idle_add(lambda: self.editor_view.go_to_line_smooth(line_number) or False)

    # -- Maximize / restore --

    def _maximize_panel(self, panel_name: str):
        """Maximize a panel (editor, terminal, ai_chat) or restore."""
        from shared.utils import animate_paned

        ai_enabled = getattr(self, "_ai_enabled", True)

        if self._maximized_panel == panel_name:
            # Restore to saved positions before maximize
            self._maximized_panel = None
            if self._bottom_panels_created:
                if ai_enabled:
                    self.ai_chat.set_visible(True)
                self.terminal_view.set_visible(True)
            saved = self._saved_positions
            self._saved_positions = {}
            if saved:
                GLib.idle_add(self._restore_saved_positions, saved)
            else:
                GLib.idle_add(self._apply_default_layout)
        else:
            # Save current positions
            self._saved_positions = {
                "main": self.main_paned.get_position(),
                "right": self.right_paned.get_position(),
                "bottom": self.bottom_paned.get_position(),
            }
            if self._bottom_panels_created and panel_name != "ai_chat":
                if ai_enabled:
                    self.ai_chat.set_visible(True)
                self.terminal_view.set_visible(True)
            w = self.get_width()
            h = self.get_height()

            if panel_name == "editor":
                animate_paned(self.main_paned, 0)
                animate_paned(self.right_paned, h, on_done=self._sync_terminal_resize)
            elif panel_name == "terminal":
                animate_paned(self.main_paned, 0)
                animate_paned(self.right_paned, 0)
                animate_paned(self.bottom_paned, 0, on_done=self._sync_terminal_resize)
                if ai_enabled:
                    self.ai_chat.set_visible(False)
            elif panel_name == "ai_chat" and ai_enabled:
                self.ai_chat.set_visible(True)  # may be hidden from a prior terminal maximize
                animate_paned(self.main_paned, 0)
                self.right_paned.set_shrink_start_child(True)
                animate_paned(self.right_paned, 0)
                animate_paned(self.bottom_paned, w, on_done=self._sync_terminal_resize)
                self.terminal_view.set_visible(False)
            elif panel_name == "tree":
                animate_paned(self.main_paned, w)
                animate_paned(self.right_paned, h, on_done=self._sync_terminal_resize)

            self._maximized_panel = panel_name

        self._sync_maximize_buttons()

    def _sync_maximize_buttons(self):
        """Sync maximize button selected state on panels with internal _maximized_panel."""
        if not self._bottom_panels_created:
            return
        ai_enabled = getattr(self, "_ai_enabled", True)
        for panel_name, widget in [("terminal", self.terminal_view), ("ai_chat", self.ai_chat)]:
            if not ai_enabled and panel_name == "ai_chat":
                continue
            is_max = self._maximized_panel == panel_name
            widget._is_maximized = is_max
            btn = getattr(widget, "maximize_btn", None)
            if btn:
                if is_max:
                    btn.add_css_class("selected")
                    btn.set_tooltip_text("Restore")
                else:
                    btn.remove_css_class("selected")
                    btn.set_tooltip_text("Maximize")

    # -- Panel visibility --

    def _show_all_panels(self):
        """Ensure all UI panels are visible (creates them if needed)."""
        from constants import DEFAULT_TREE_WIDTH
        from shared.utils import animate_paned

        ai_enabled = getattr(self, "_ai_enabled", True)

        # Create bottom panels if not yet created (single-file mode)
        if not self._bottom_panels_created:
            self._create_bottom_panels()
            if ai_enabled:
                self.ai_chat.on_maximize = lambda name: self._maximize_panel(name)
            self.terminal_view.on_maximize = lambda name: self._maximize_panel(name)
            # Start terminal shell
            workspace_dirs = self.tree_view.get_workspace_folders()
            if workspace_dirs and os.path.isdir(workspace_dirs[0]):
                self.terminal_view.change_directory(workspace_dirs[0])
            self.terminal_view.spawn_shell()

        # Show tree view and bottom panels
        self.tree_view.set_visible(True)
        self.bottom_paned.set_visible(True)

        if self.main_paned.get_position() < 50:
            animate_paned(self.main_paned, DEFAULT_TREE_WIDTH)

        window_height = self.get_height()
        # Collapse editor if no tabs are open (only if auto_expand_terminals is enabled)
        from shared.settings.settings_manager import get_setting

        if (
            hasattr(self, "editor_view")
            and not self.editor_view.tabs
            and get_setting("behavior.auto_expand_terminals", True)
        ):
            animate_paned(self.right_paned, 0, on_done=self._sync_terminal_resize)
            self._editor_collapsed = True
        elif self.right_paned.get_position() < 50:
            animate_paned(self.right_paned, int(window_height * 0.65), on_done=self._sync_terminal_resize)

    # -- Default layout --

    def _apply_default_layout(self):
        """Apply default layout positions based on current window size."""
        from constants import DEFAULT_TREE_WIDTH
        from shared.utils import animate_paned

        ai_enabled = getattr(self, "_ai_enabled", True)

        if self._bottom_panels_created:
            if ai_enabled:
                self.ai_chat.set_visible(True)
            self.terminal_view.set_visible(True)

        # Get current window dimensions
        window_width = self.get_width()
        window_height = self.get_height()

        # Default proportions:
        # - Tree view: DEFAULT_TREE_WIDTH fixed width
        # - Editor takes ~65% of vertical space, bottom panel ~35%
        # - AI chat and terminal split 50/50 horizontally in bottom panel (when AI enabled)
        editor_height = int(window_height * 0.65)
        bottom_panel_width = window_width - DEFAULT_TREE_WIDTH
        ai_chat_width = bottom_panel_width // 2 if ai_enabled else 0

        # Apply positions with animation
        animate_paned(self.main_paned, DEFAULT_TREE_WIDTH)
        # Collapse editor if no tabs and no welcome/dev-pad screen (only if auto_expand_terminals is enabled)
        from shared.settings.settings_manager import get_setting

        if (
            hasattr(self, "editor_view")
            and not self.editor_view.tabs
            and not self._has_welcome_screen()
            and not self._has_dev_pad_tab()
            and get_setting("behavior.auto_expand_terminals", True)
        ):
            animate_paned(self.right_paned, 0)
            self._editor_collapsed = True
        else:
            animate_paned(self.right_paned, editor_height)
            self._editor_collapsed = False
        # Only reset bottom panel proportions if auto_expand_terminals is enabled
        from shared.settings.settings_manager import get_setting

        if get_setting("behavior.auto_expand_terminals", True):
            animate_paned(self.bottom_paned, ai_chat_width, on_done=self._sync_terminal_resize)

        return False  # Don't repeat

    def _restore_saved_positions(self, saved):
        """Restore paned positions from saved state."""
        from shared.utils import animate_paned

        ai_enabled = getattr(self, "_ai_enabled", True)

        if self._bottom_panels_created:
            if ai_enabled:
                self.ai_chat.set_visible(True)
            self.terminal_view.set_visible(True)
        if "main" in saved:
            animate_paned(self.main_paned, saved["main"])
        if "right" in saved:
            # Collapse editor if no tabs and no welcome/dev-pad screen (only if auto_expand_terminals is enabled)
            from shared.settings.settings_manager import get_setting

            if (
                hasattr(self, "editor_view")
                and not self.editor_view.tabs
                and not self._has_welcome_screen()
                and not self._has_dev_pad_tab()
                and get_setting("behavior.auto_expand_terminals", True)
            ):
                animate_paned(self.right_paned, 0)
                self._editor_collapsed = True
            else:
                animate_paned(self.right_paned, saved["right"])
                self._editor_collapsed = False
        if "bottom" in saved:
            # Only restore saved bottom position if auto_expand_terminals is enabled
            from shared.settings.settings_manager import get_setting

            if get_setting("behavior.auto_expand_terminals", True):
                # When AI is disabled, force position to 0 so terminal fills the space
                target = 0 if not ai_enabled else saved["bottom"]
                animate_paned(self.bottom_paned, target, on_done=self._sync_terminal_resize)
            # If auto_expand_terminals is False, don't restore saved position
            # (keep whatever position the panel currently has)
        return False  # Don't repeat
