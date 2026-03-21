"""Window fonts mixin — font size, zoom, and font application to components."""


class WindowFontsMixin:
    """Mixin: font management, zoom, and font refresh for all components."""

    def _apply_font_size(self):
        """Apply font settings to all components."""
        from fonts import set_font_settings

        # Update font size in settings
        set_font_settings("editor", size=self._font_size)

        # Apply to all open editor tabs, preserving scroll position
        if hasattr(self, "editor_view") and self.editor_view:
            from gi.repository import GLib

            for tab in self.editor_view.tabs.values():
                if hasattr(tab, "apply_font_settings"):
                    vadj = tab.view.get_vadjustment()
                    scroll_pos = vadj.get_value() if vadj else 0
                    tab.apply_font_settings()
                    if vadj and scroll_pos > 0:
                        GLib.idle_add(lambda v=vadj, p=scroll_pos: v.set_value(p) or False)
            # Also check for welcome screens in notebook
            from main.welcome_screen import WelcomeScreen

            notebook = self.editor_view.notebook
            for i in range(notebook.get_n_pages()):
                page = notebook.get_nth_page(i)
                if isinstance(page, WelcomeScreen):
                    page.apply_font_settings(self._font_size)

        # Update diff view font (only if already created)
        if self._diff_view is not None:
            self._diff_view.update_font_settings()

        # Update terminal font
        self._apply_terminal_font()

        # Update treeview font
        self._apply_treeview_font()

        # Update dev pad font (mirrors editor font)
        if hasattr(self, "dev_pad") and self.dev_pad:
            self.dev_pad.apply_font_settings()

    def _apply_terminal_font(self):
        """Apply font settings to terminal."""
        if not hasattr(self, "terminal_view") or not self.terminal_view:
            return
        self.terminal_view.apply_font_settings()

    def _apply_treeview_font(self):
        """Apply font settings to treeview."""
        if not hasattr(self, "tree_view") or not self.tree_view:
            return
        # Tree panel handles settings change notifications
        if hasattr(self.tree_view, "tree"):
            self.tree_view.tree._setup_fonts()
            self.tree_view.tree._setup_icons()
            self.tree_view.tree._update_virtual_size()
            self.tree_view.tree.drawing_area.queue_draw()

    def _refresh_all_fonts(self):
        """Refresh fonts for all components."""
        self._refresh_component_font("editor")
        self._refresh_component_font("terminal")
        self._refresh_component_font("explorer")
        self._refresh_component_font("ai_chat")
        self._refresh_component_font("dev_pad")

    def _refresh_component_font(self, component: str):
        """Refresh font for a specific component."""
        if component == "editor":
            if hasattr(self, "editor_view") and self.editor_view:
                for tab in self.editor_view.tabs.values():
                    if hasattr(tab, "apply_font_settings"):
                        tab.apply_font_settings()
                    tab_btn = getattr(tab, "_tab_button", None)
                    if tab_btn and hasattr(tab_btn, "apply_font_settings"):
                        tab_btn.apply_font_settings()
        elif component == "terminal":
            self._apply_terminal_font()
        elif component == "explorer":
            self._apply_treeview_font()
        elif component == "ai_chat":
            # AI terminal font refresh - uses update_font() which also refreshes the header
            if hasattr(self, "ai_chat") and self.ai_chat:
                if hasattr(self.ai_chat, "update_font"):
                    self.ai_chat.update_font()
        elif component == "dev_pad":
            if hasattr(self, "dev_pad") and self.dev_pad:
                self.dev_pad.apply_font_settings()

    def _zoom_markdown_previews(self, direction):
        """Apply zoom to all open markdown previews."""
        if not hasattr(self, "editor_view") or not self.editor_view:
            return
        for tab in self.editor_view.tabs.values():
            preview = getattr(tab, "_md_preview", None)
            if preview:
                if direction == "in":
                    preview.zoom_in()
                elif direction == "out":
                    preview.zoom_out()
                else:
                    preview.zoom_reset()
