"""Window actions mixin — all action handler callbacks for menu items and shortcuts."""

import os

from main.file_actions_mixin import FileActionsMixin
from main.view_actions_mixin import ViewActionsMixin


class WindowActionsMixin(FileActionsMixin, ViewActionsMixin):
    """Mixin: action handlers for file, edit, view, and help menu items."""

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
