"""AI Tab Bar mixin — tab management logic for AITerminalStack."""

from gi.repository import Gtk

from constants import TERMINAL_TAB_BAR_MARGIN_BOTTOM
from shared.focus_manager import get_focus_manager


class AITabBarMixin:
    """Mixin providing tab bar UI and tab switching/closing logic.

    Expects the host class to define:
        _views, _tab_buttons, _active_idx, _spinners, _vertical_mode,
        _content_stack, _header, _content_container, UNFOCUS_CSS_CLASS,
        FOCUS_CSS_CLASS, COMPONENT_ID, _add_view, _persist_tabs,
        _label_for_view, _get_workspace_folders, _get_editor_context
    """

    def _build_tab_bar(self) -> None:
        # Outer container: [◀] [scrollable tabs] [▶]
        self._tab_bar_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._tab_bar_row.set_margin_start(8)
        self._tab_bar_row.set_margin_end(8)
        self._tab_bar_row.set_margin_bottom(TERMINAL_TAB_BAR_MARGIN_BOTTOM)
        self._tab_bar_row.set_visible(False)

        self._scroll_left_btn = Gtk.Button.new_from_icon_name("pan-start-symbolic")
        self._scroll_left_btn.add_css_class("flat")
        self._scroll_left_btn.add_css_class("tab-scroll-btn")
        self._scroll_left_btn.connect("clicked", lambda _b: self._scroll_tab_bar(-1))
        self._tab_bar_row.append(self._scroll_left_btn)

        self._tab_bar_scroll = Gtk.ScrolledWindow()
        self._tab_bar_scroll.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        self._tab_bar_scroll.set_propagate_natural_width(False)
        self._tab_bar_scroll.set_hexpand(True)

        self._tab_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._tab_bar_scroll.set_child(self._tab_bar)
        self._tab_bar_row.append(self._tab_bar_scroll)

        self._scroll_right_btn = Gtk.Button.new_from_icon_name("pan-end-symbolic")
        self._scroll_right_btn.add_css_class("flat")
        self._scroll_right_btn.add_css_class("tab-scroll-btn")
        self._scroll_right_btn.connect("clicked", lambda _b: self._scroll_tab_bar(1))
        self._tab_bar_row.append(self._scroll_right_btn)

        self.append(self._tab_bar_row)

    def _add_tab_button(self, index: int, title: str) -> None:
        from terminal.terminal_tab_button import TerminalTabButton

        btn = TerminalTabButton(
            index=index,
            title=title,
            on_select=self._switch_to_tab,
            on_close=self._close_tab,
            show_close=len(self._views) > 1,
        )
        self._tab_buttons.append(btn)
        self._tab_bar.append(btn)

    def _switch_to_tab(self, index: int) -> None:
        if index < 0 or index >= len(self._views):
            return
        self._active_idx = index
        view = self._views[index]
        if self._vertical_mode:
            self._update_vertical_focus_border()
            view.terminal.grab_focus()
        else:
            self._content_stack.set_visible_child_name(f"ai_{id(view)}")
            self._update_tab_selection()
            self._scroll_tab_into_view(index)
            self._header.set_label(self._label_for_view(view))
            view.terminal.grab_focus()
        self._scroll_terminal_to_bottom(view)

    @staticmethod
    def _scroll_terminal_to_bottom(view) -> None:
        vadj = view.terminal.get_vadjustment()
        if vadj is not None:
            vadj.set_value(vadj.get_upper() - vadj.get_page_size())

    def _close_tab(self, index: int) -> None:
        if len(self._views) <= 1:
            self._clear_active()
            return
        if self._vertical_mode:
            self._stop_header_spinner(index)
        else:
            self._stop_tab_spinner(index)
        view = self._views[index]
        view.cleanup()
        if self._vertical_mode:
            self._content_container.remove(view)
            self._views.remove(view)
            # Reset maximize state if the closed view was maximized
            if getattr(self, "_maximized_view", None) is view:
                self._maximized_view = None
                for v in self._views:
                    v.set_visible(True)
            self._active_idx = min(self._active_idx, len(self._views) - 1)
        else:
            self._content_stack.remove(view)
            tab_btn = self._tab_buttons.pop(index)
            self._tab_bar.remove(tab_btn)
            self._views.remove(view)
            for i, btn in enumerate(self._tab_buttons):
                btn.index = i
            self._active_idx = min(self._active_idx, len(self._views) - 1)
            active = self._views[self._active_idx]
            self._content_stack.set_visible_child_name(f"ai_{id(active)}")
            self._update_tab_selection()
            self._update_tab_close_buttons()
            self._update_tab_bar_visibility()
        self._persist_tabs()

    def _close_tab_by_view(self, view) -> None:
        """Close a specific view (used in vertical mode)."""
        try:
            idx = self._views.index(view)
        except ValueError:
            return
        self._close_tab(idx)

    def _update_tab_selection(self) -> None:
        for i, btn in enumerate(self._tab_buttons):
            btn.set_selected(i == self._active_idx)

    def _update_tab_close_buttons(self) -> None:
        show = len(self._tab_buttons) > 1
        for btn in self._tab_buttons:
            btn.set_show_close(show)

    def _update_tab_bar_visibility(self) -> None:
        self._tab_bar_row.set_visible(len(self._views) > 1)

    def _scroll_tab_bar(self, direction: int) -> None:
        """Scroll the tab bar left (-1) or right (+1) by one tab width."""
        hadj = self._tab_bar_scroll.get_hadjustment()
        if not hadj:
            return
        # Use the width of a tab button as the scroll step
        step = 120
        if self._tab_buttons:
            step = max(self._tab_buttons[0].get_width(), 60)
        new_val = hadj.get_value() + direction * step
        new_val = max(0, min(new_val, hadj.get_upper() - hadj.get_page_size()))
        hadj.set_value(new_val)

    def _scroll_tab_into_view(self, index: int) -> None:
        """Ensure the tab button at *index* is visible in the scroll area."""
        if index < 0 or index >= len(self._tab_buttons):
            return
        btn = self._tab_buttons[index]
        hadj = self._tab_bar_scroll.get_hadjustment()
        if not hadj:
            return

        # Compute offset of btn within the tab bar box
        offset = 0
        for i in range(index):
            offset += self._tab_buttons[i].get_width() + 4  # spacing=4
        btn_w = btn.get_width()

        cur = hadj.get_value()
        page = hadj.get_page_size()
        if offset < cur:
            hadj.set_value(offset)
        elif offset + btn_w > cur + page:
            hadj.set_value(offset + btn_w - page)

    def _clear_active(self) -> None:
        active = self._active
        if active:
            active.clear()
            # Reset session state so clear behaves like a fresh session
            active._title_inferred = False
            active._session_id = None
            # Reset title on tab button
            idx = self._active_idx
            if not self._vertical_mode and 0 <= idx < len(self._tab_buttons):
                self._tab_buttons[idx].set_title(f"Chat {idx + 1}")
            # Reset title on vertical-mode header
            active._ai_header.title_label.set_label("")
            active._ai_header.title_label.set_visible(False)
            self._persist_tabs()
            # Respawn the AI CLI so the terminal is usable again
            active.spawn_shell()

    def _on_add_request(self) -> None:
        # Capture the active view's provider before _add_view moves the index.
        prev_provider = self._views[self._active_idx]._current_provider if self._views else None
        prev_model = self._views[self._active_idx]._current_model if self._views else None
        view = self._add_view()
        # Inherit provider and workspace cwd from the previous active view so
        # the new tab matches the current header selection.
        if prev_provider:
            view._current_provider = prev_provider
        if prev_model:
            view._current_model = prev_model
        if self._views and len(self._views) > 1:
            view.cwd = self._views[0].cwd
        view.spawn_shell()
        self._persist_tabs()
        focus_mgr = get_focus_manager()
        if focus_mgr.get_current_focus() == self.COMPONENT_ID:
            self._on_focus_in()
        else:
            focus_mgr.set_focus(self.COMPONENT_ID)

    def _on_processing_changed(self, view_idx: int, processing: bool) -> None:
        if self._vertical_mode:
            if 0 <= view_idx < len(self._views):
                if processing:
                    self._start_header_spinner(view_idx)
                else:
                    self._stop_header_spinner(view_idx)
            return
        if view_idx < 0 or view_idx >= len(self._tab_buttons):
            return
        if processing:
            self._start_tab_spinner(view_idx)
        else:
            self._stop_tab_spinner(view_idx)

    def _start_tab_spinner(self, view_idx: int) -> None:
        self._stop_tab_spinner(view_idx)
        btn = self._tab_buttons[view_idx]
        btn.close_btn.set_visible(False)

        gtk_spinner = Gtk.Spinner()
        gtk_spinner.set_size_request(12, 12)
        gtk_spinner.set_halign(Gtk.Align.CENTER)
        gtk_spinner.set_valign(Gtk.Align.CENTER)
        btn._content.append(gtk_spinner)
        gtk_spinner.start()
        self._spinners[view_idx] = {"widget": gtk_spinner}

    def _stop_tab_spinner(self, view_idx: int) -> None:
        state = self._spinners.pop(view_idx, None)
        if state:
            widget = state["widget"]
            widget.stop()
            parent = widget.get_parent()
            if parent:
                parent.remove(widget)
        if 0 <= view_idx < len(self._tab_buttons):
            btn = self._tab_buttons[view_idx]
            btn.close_btn.set_label("\u00d7")
            btn.close_btn.set_visible(btn._show_close)

    # -- vertical-mode spinner (header label) --

    def _start_header_spinner(self, view_idx: int) -> None:
        self._stop_header_spinner(view_idx)
        spinner_widget = self._views[view_idx]._ai_header.spinner_widget
        spinner_widget.set_visible(True)
        spinner_widget.start()
        self._spinners[view_idx] = {"header": True}

    def _stop_header_spinner(self, view_idx: int) -> None:
        state = self._spinners.pop(view_idx, None)
        if 0 <= view_idx < len(self._views):
            spinner_widget = self._views[view_idx]._ai_header.spinner_widget
            spinner_widget.stop()
            spinner_widget.set_visible(False)

    def _on_title_inferred(self, view_idx: int, title: str) -> None:
        if 0 <= view_idx < len(self._tab_buttons):
            self._tab_buttons[view_idx].set_title(title)
        if self._vertical_mode and 0 <= view_idx < len(self._views):
            header = self._views[view_idx]._ai_header
            header.title_label.set_label(title)
            header.title_label.set_visible(True)
        self._persist_tabs()
