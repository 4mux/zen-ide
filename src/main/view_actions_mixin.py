"""View actions mixin — view and navigation action handlers for the main window."""

import os

from gi.repository import GLib


class ViewActionsMixin:
    """Mixin: action handlers for view/navigation menu items."""

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
            tab = self.editor_view._get_current_tab()
            cursor_line = 0
            if tab:
                cursor_line = tab.buffer.get_iter_at_mark(tab.buffer.get_insert()).get_line()
            self.split_panels.show(
                "diff",
                file_path=file_path,
                content=self.editor_view.get_current_content(),
                scroll_to_line=cursor_line,
            )

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

    def _on_open_ai_chat(self, session_id: str):
        """Focus or restore an AI session from Dev Pad."""
        # Ensure AI panel is visible
        self.ai_chat.set_visible(True)
        self.ai_chat.focus_session(session_id)

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

        # Use FocusManager as source of truth since it's updated by panel clicks
        from shared.focus_manager import get_focus_manager

        focus_mgr = get_focus_manager()
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
            self.editor_view.on_maximize = lambda name: self._maximize_panel(name)
            if getattr(self, "_ai_enabled", True):
                self.ai_chat.on_maximize = lambda name: self._maximize_panel(name)
            self.terminal_view.on_maximize = lambda name: self._maximize_panel(name)
        self.tree_view.set_visible(True)
        self.bottom_paned.set_visible(True)

        # Use idle_add to ensure window size is available after any pending operations
        GLib.idle_add(self._apply_default_layout)

    # --- Debug actions ---

    def _on_debug_start(self, action, param):
        """Start or continue debugging (F5)."""
        from debugger.debug_session import DebugSession, SessionState

        session = getattr(self, "_debug_session", None)
        if session and session.state == SessionState.STOPPED:
            session.continue_()
            return
        if session and session.state == SessionState.RUNNING:
            return
        # Clean up terminated/stale session so we can start fresh
        if session and session.state in (SessionState.TERMINATED, SessionState.IDLE):
            self._debug_session = None

        # Create a new debug session
        from debugger.debug_config import create_default_config, load_configurations

        file_path = self.editor_view.get_current_file_path()
        if not file_path:
            return

        workspace_folders = self.tree_view.get_workspace_folders()
        workspace = workspace_folders[0] if workspace_folders else os.path.dirname(file_path)

        # Try settings configurations first, then zero-config
        configs = load_configurations(workspace)
        if configs:
            config = configs[0]
        else:
            config = create_default_config(file_path, workspace_folders)
            if not config:
                self.split_panels.show("debug")
                self.debug_panel.append_output(
                    "Cannot debug: supported file types are Python (.py), C (.c), C++ (.cpp/.cc/.cxx), and JavaScript/TypeScript (.js/.ts/.jsx/.tsx)\n",
                    "error",
                )
                return

        # Show debug panel
        self.split_panels.show("debug")

        # Create session
        panel = self.debug_panel
        session = DebugSession(
            config,
            on_state_changed=self._on_debug_state_changed,
            on_output=panel.append_output,
            on_stopped=self._on_debug_session_stopped,
        )
        self._debug_session = session
        panel.set_session(session)

        # Log to Dev Pad
        from dev_pad.activity_store import log_debug_activity

        log_debug_activity(
            f"Debug session started — {os.path.basename(file_path)} ({config.type})",
            file_path=file_path,
        )

        try:
            session.start(file_path, workspace)
        except Exception:
            import traceback

            panel.append_output(f"Debug start failed:\n{traceback.format_exc()}", "stderr")

    def _on_debug_state_changed(self, session):
        """Handle debug session state changes — update status bar and panel."""
        from debugger.debug_session import SessionState

        # Clear execution-line highlight first — must run before anything
        # else that could raise and swallow the exception in _set_state.
        if session.state in (SessionState.RUNNING, SessionState.TERMINATED):
            self._clear_debug_decorations()

        self.debug_panel.on_session_state_changed(session)

    def _on_debug_stop(self, action, param):
        """Stop debugging (Shift+F5)."""
        session = getattr(self, "_debug_session", None)
        if session:
            session.stop()
            self._clear_debug_decorations()

            from dev_pad.activity_store import log_debug_activity

            log_debug_activity("Debug session ended")

    def _on_debug_step_over(self, action, param):
        """Step over (F10)."""
        session = getattr(self, "_debug_session", None)
        if session:
            session.step_over()

    def _on_debug_step_into(self, action, param):
        """Step into (F11)."""
        session = getattr(self, "_debug_session", None)
        if session:
            session.step_into()

    def _on_debug_step_out(self, action, param):
        """Step out (Shift+F11)."""
        session = getattr(self, "_debug_session", None)
        if session:
            session.step_out()

    def _on_debug_toggle_breakpoint(self, action, param):
        """Toggle breakpoint at current line (F9)."""
        from debugger.breakpoint_manager import get_breakpoint_manager

        file_path = self.editor_view.get_current_file_path()
        if not file_path:
            return
        tab = self.editor_view._get_current_tab()
        if not tab:
            return
        buf = tab.view.get_buffer()
        insert = buf.get_iter_at_mark(buf.get_insert())
        line = insert.get_line() + 1  # 1-based

        mgr = get_breakpoint_manager()
        mgr.toggle(file_path, line)
        tab.view.queue_draw()

        # Sync with active debug session
        session = getattr(self, "_debug_session", None)
        if session:
            session.sync_file_breakpoints(file_path)

    def _on_debug_toggle_panel(self, action, param):
        """Toggle debug panel (Ctrl+Shift+B)."""
        self.split_panels.toggle("debug")

    def _on_debug_session_stopped(self, session, thread_id, reason, file_path, line):
        """Called when execution stops (breakpoint, step). Updates editor decorations."""
        self.debug_panel.on_session_stopped(session, thread_id, reason, file_path, line)

        if reason == "breakpoint" and file_path:
            from dev_pad.activity_store import log_debug_activity

            log_debug_activity(
                f"Breakpoint hit — {os.path.basename(file_path)}:{line}",
                file_path=file_path,
            )

        # Update breakpoint renderer with current execution line
        if file_path:
            tab = self.editor_view._get_current_tab()
            if tab and hasattr(tab.view, "_breakpoint_renderer"):
                renderer = tab.view._breakpoint_renderer
                if renderer:
                    renderer.set_current_line(line)

    def _clear_debug_decorations(self):
        """Clear debug decorations from all open tabs."""
        for tab in self.editor_view.tabs.values():
            if hasattr(tab, "_breakpoint_renderer"):
                renderer = tab._breakpoint_renderer
                if renderer:
                    renderer.set_current_line(None)
