"""Tab management (open, close, save dialogs) for EditorView."""

import os
import time

from gi.repository import GLib, Gtk, GtkSource

from constants import AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, MINIMAP_WIDTH
from shared.settings import get_setting

from . import MD_EXTENSIONS, OPENAPI_EXTENSIONS, SKETCH_EXTENSION
from .editor_tab import EditorTab


class EditorViewTabsMixin:
    """Mixin providing tab open/close/save management for EditorView."""

    def new_file(self):
        """Create a new empty file tab."""
        tab = EditorTab(is_new=True)
        tab_id = self._add_tab(tab, "Untitled")
        tab.view.grab_focus()
        if self.on_file_opened:
            self.on_file_opened(None)
        return tab_id

    def open_or_create_file(self, file_path: str) -> bool:
        """Open a file if it exists, or create a temporary unsaved tab with that name."""
        if os.path.isfile(file_path):
            return self.open_file(file_path)
        self._close_welcome_tab()
        tab = EditorTab(file_path=file_path, is_new=True)
        tab._set_language_from_file(file_path)
        title = os.path.basename(file_path)
        tab_id = self._add_tab(tab, title)
        tab.view.grab_focus()
        if self.on_file_opened:
            self.on_file_opened(file_path)
        return True

    def new_sketch_file(self):
        """Create a new untitled sketch pad tab."""
        self._close_welcome_tab()
        from ..sketch_tab import SketchTab

        sketch_tab = SketchTab(None)
        sketch_tab.original_content = sketch_tab.widget.get_content()
        tab_id = self._next_tab_id
        self._next_tab_id += 1
        sketch_tab.widget._zen_tab_id = tab_id

        from shared.ui.tab_button import FileTabButton

        tab_btn = FileTabButton(tab_id, sketch_tab.get_title(), on_close=lambda tid: self._close_tab_by_id(tid))
        page_num = self.notebook.append_page(sketch_tab.widget, None)
        self._tab_bar.append(tab_btn)
        click = Gtk.GestureClick.new()
        click.connect("pressed", lambda g, n, x, y, tid=tab_id: self._select_tab_by_id(tid))
        tab_btn.add_controller(click)
        sketch_tab._tab_button = tab_btn
        sketch_tab._tab_id = tab_id
        self.tabs[tab_id] = sketch_tab
        self.notebook.set_current_page(page_num)
        if self.on_file_opened:
            self.on_file_opened(None)

    def _close_welcome_tab(self):
        """Close the Welcome tab if present."""
        for i in range(self.notebook.get_n_pages()):
            page = self.notebook.get_nth_page(i)
            if page.__class__.__name__ == "WelcomeScreen":
                # Remove welcome button from custom tab bar
                child = self._tab_bar.get_first_child()
                while child:
                    nxt = child.get_next_sibling()
                    if getattr(child, "tab_id", None) == -1:
                        self._tab_bar.remove(child)
                        break
                    child = nxt
                if i < self.notebook.get_n_pages():
                    self.notebook.remove_page(i)
                return

    def toggle_dev_pad(self, dev_pad):
        """Toggle the Dev Pad as an editor tab."""
        for i in range(self.notebook.get_n_pages()):
            page = self.notebook.get_nth_page(i)
            if page.__class__.__name__ == "DevPad":
                if self.notebook.get_current_page() == i:
                    self.notebook.remove_page(i)
                    if self.notebook.get_n_pages() == 0 and self.on_tabs_empty:
                        self.on_tabs_empty()
                else:
                    self.notebook.set_current_page(i)
                return

        window = self.get_root()
        if window and getattr(window, "_editor_collapsed", False):
            window._expand_editor()

        from shared.ui.tab_button import TabButton

        dev_pad.set_visible(True)
        dev_pad.show_panel()
        dev_pad.set_hexpand(True)
        dev_pad.set_vexpand(True)
        tab_btn = TabButton(-2, "Dev Pad", on_close=lambda tid: self._close_dev_pad_tab())
        self._dev_pad_tab_btn = tab_btn
        page_num = self.notebook.append_page(dev_pad, None)
        self._tab_bar.append(tab_btn)
        click = Gtk.GestureClick.new()
        click.connect("pressed", lambda g, n, x, y: self._switch_to_dev_pad())
        tab_btn.add_controller(click)
        self.notebook.set_current_page(page_num)

    def _switch_to_dev_pad(self):
        """Switch to the Dev Pad tab."""
        for i in range(self.notebook.get_n_pages()):
            page = self.notebook.get_nth_page(i)
            if page.__class__.__name__ == "DevPad":
                self.notebook.set_current_page(i)
                return

    def _close_dev_pad_tab(self):
        """Close the Dev Pad tab if present."""
        btn = getattr(self, "_dev_pad_tab_btn", None)
        if btn and btn.get_parent() == self._tab_bar:
            self._tab_bar.remove(btn)
        for i in range(self.notebook.get_n_pages()):
            page = self.notebook.get_nth_page(i)
            if page.__class__.__name__ == "DevPad":
                self.notebook.remove_page(i)
                if self.notebook.get_n_pages() == 0 and self.on_tabs_empty:
                    self.on_tabs_empty()
                return

    def _has_dev_pad_tab(self) -> bool:
        """Check if a DevPad tab is currently open."""
        for i in range(self.notebook.get_n_pages()):
            page = self.notebook.get_nth_page(i)
            if page.__class__.__name__ == "DevPad":
                return True
        return False

    def _is_dev_pad_active(self) -> bool:
        """Check if the DevPad tab is the currently active tab."""
        page_num = self.notebook.get_current_page()
        if page_num < 0:
            return False
        page = self.notebook.get_nth_page(page_num)
        return page.__class__.__name__ == "DevPad"

    def open_file(self, file_path: str, line_number: int = None, switch_to: bool = True) -> bool:
        """Open a file in a new tab or focus existing tab."""
        self._close_welcome_tab()
        norm = os.path.normpath(file_path)
        for tab_id, tab in self.tabs.items():
            if tab.file_path and os.path.normpath(tab.file_path) == norm:
                if switch_to:
                    page_num = self._get_page_num_for_tab_id(tab_id)
                    if page_num >= 0:
                        self.notebook.set_current_page(page_num)
                if line_number:
                    self._go_to_line(tab, line_number)
                if self.on_file_opened:
                    self.on_file_opened(file_path)
                from dev_pad import log_file_activity

                log_file_activity(file_path, "open")
                return True

        ext = os.path.splitext(file_path)[1].lower()
        if ext in IMAGE_EXTENSIONS:
            return self.open_image(file_path, switch_to=switch_to)

        if ext in AUDIO_EXTENSIONS:
            return self.open_audio(file_path, switch_to=switch_to)

        if ext == SKETCH_EXTENSION:
            return self._open_sketch_file(file_path, switch_to=switch_to)

        tab = EditorTab(file_path=file_path)
        if tab.load_file(file_path):
            page_num = self._add_tab(tab, tab.get_title(), switch_to=switch_to)
            if line_number:

                def _scroll_when_ready(view, ln=line_number, t=tab):
                    GLib.idle_add(lambda: self._go_to_line(t, ln) or False)

                if tab.view.get_mapped():
                    GLib.idle_add(lambda: self._go_to_line(tab, line_number) or False)
                else:
                    tab.view.connect("map", lambda w: _scroll_when_ready(w))
            if self.on_file_opened:
                self.on_file_opened(file_path)
            from dev_pad import log_file_activity

            log_file_activity(file_path, "open")
            return True

        return False

    def on_external_file_change(self, file_path: str) -> None:
        """Handle external file modification detected by file watcher."""
        norm = os.path.normpath(file_path)
        for tab_id, tab in self.tabs.items():
            if tab.file_path and os.path.normpath(tab.file_path) == norm:
                if getattr(tab, "_is_image", False) or getattr(tab, "_is_audio", False):
                    return
                if not tab.modified:
                    if time.monotonic() - tab._last_internal_save_time < 2.0:
                        return
                    tab.reload_file()
                return

    def _add_tab(self, tab: EditorTab, title: str, switch_to: bool = True) -> int:
        """Add a tab to the notebook. Returns tab_id (unique, stable)."""
        tab_id = self._next_tab_id
        self._next_tab_id += 1

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_kinetic_scrolling(True)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_child(tab.view)

        if get_setting("editor.scroll_past_end", True):

            def _update_scroll_past_end(*_args):
                h = scrolled.get_height()
                if h > 0:
                    tab.view.set_bottom_margin(max(h // 2, 200))

            vadj = scrolled.get_vadjustment()
            vadj.connect("notify::page-size", _update_scroll_past_end)

        editor_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        editor_box.append(scrolled)

        if get_setting("editor.show_minimap", True):
            scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.EXTERNAL)
            minimap = GtkSource.Map()
            minimap.set_view(tab.view)
            minimap.set_size_request(MINIMAP_WIDTH, -1)
            editor_box.append(minimap)
            tab._minimap = minimap

            from ..editor_minimap import EditorMinimap

            indicator = EditorMinimap(tab.view, scrolled)
            if tab.file_path:
                indicator.set_file_path(tab.file_path)
            editor_box.append(indicator)
            tab._minimap_indicator = indicator

        is_markdown = False
        is_openapi = False
        md_preview = None
        openapi_preview = None
        if tab.file_path:
            ext = os.path.splitext(tab.file_path)[1].lower()
            if ext in MD_EXTENSIONS:
                is_markdown = True
            elif ext in OPENAPI_EXTENSIONS:
                try:
                    start_iter = tab.buffer.get_start_iter()
                    end_iter = tab.buffer.get_end_iter()
                    file_content = tab.buffer.get_text(start_iter, end_iter, True)
                    from ..preview.openapi_preview import is_openapi_content

                    is_openapi = is_openapi_content(file_content)
                except ImportError:
                    pass

        if is_markdown:
            paned, md_preview, page_container = self._setup_markdown_split(editor_box, tab, tab_id, scrolled)
        elif is_openapi:
            paned, openapi_preview, page_container = self._setup_openapi_split(editor_box, tab, tab_id, scrolled)
        else:
            editor_box._zen_tab_id = tab_id
            page_container = editor_box

        from shared.ui.tab_button import FileTabButton

        file_tab_btn = FileTabButton(tab_id, title, on_close=lambda tid: self._close_tab_by_id(tid))
        page_num = self.notebook.append_page(page_container, None)
        self.tabs[tab_id] = tab

        # Add button to custom tab bar and wire click-to-select
        self._tab_bar.append(file_tab_btn)
        click = Gtk.GestureClick.new()
        click.connect("pressed", lambda g, n, x, y, tid=tab_id: self._select_tab_by_id(tid))
        file_tab_btn.add_controller(click)

        if is_markdown and md_preview:
            start = tab.buffer.get_start_iter()
            end = tab.buffer.get_end_iter()
            content = tab.buffer.get_text(start, end, True)
            md_preview.update_from_editor(content, tab.file_path)
        if is_openapi and openapi_preview:
            start = tab.buffer.get_start_iter()
            end = tab.buffer.get_end_iter()
            content = tab.buffer.get_text(start, end, True)
            openapi_preview.update_from_editor(content, tab.file_path)

        tab._tab_button = file_tab_btn
        tab._tab_id = tab_id

        handler_id = tab.buffer.connect("changed", lambda b, tid=tab_id: self._on_buffer_changed_by_id(tid))
        self._modification_handler_ids[tab_id] = handler_id
        tab.buffer.connect("notify::cursor-position", lambda b, p, tid=tab_id: self._on_cursor_moved(tid))
        tab.on_diagnostics_changed = self._on_diagnostics_updated
        tab._gutter_diagnostic_click_callback = self._on_gutter_diagnostic_clicked
        tab.set_cmd_click_callback(self._on_cmd_click)

        if switch_to:
            self.notebook.set_current_page(page_num)

        return tab_id

    def _setup_markdown_split(self, editor_box, tab, tab_id, scrolled):
        """Create markdown split view paned. Returns (paned, preview, page_container)."""
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_vexpand(True)
        paned.set_hexpand(True)
        paned.set_shrink_start_child(False)
        paned.set_shrink_end_child(False)
        paned.set_start_child(editor_box)

        from ..preview.markdown_preview import MarkdownPreview

        md_preview = MarkdownPreview()
        md_preview.set_hexpand(True)
        paned.set_end_child(md_preview)

        def _ensure_md_half():
            w = paned.get_allocated_width()
            if w > 10:
                paned.set_position(w // 2)
                return False
            return True

        GLib.timeout_add(100, _ensure_md_half)
        tab._md_preview = md_preview
        tab.buffer.connect("changed", lambda b, t=tab: self._on_md_buffer_changed(t))

        _syncing_from_preview = [False]
        _sync_guard_timer = [0]

        def _sync_md_scroll(adj, preview=md_preview, view=tab.view):
            if _syncing_from_preview[0] or preview.is_syncing_scroll:
                return
            visible = view.get_visible_rect()
            top_iter, _ = view.get_line_at_y(visible.y)
            preview.scroll_to_source_line(top_iter.get_line())

        scrolled.get_vadjustment().connect("value-changed", _sync_md_scroll)

        def _sync_editor_from_preview(fraction, _scrolled=scrolled):
            _syncing_from_preview[0] = True
            vadj = _scrolled.get_vadjustment()
            upper = vadj.get_upper()
            page = vadj.get_page_size()
            if upper > page:
                vadj.set_value(fraction * (upper - page))
            if _sync_guard_timer[0]:
                GLib.source_remove(_sync_guard_timer[0])
            _sync_guard_timer[0] = GLib.timeout_add(
                200, lambda: (_syncing_from_preview.__setitem__(0, False), _sync_guard_timer.__setitem__(0, 0)) or False
            )

        md_preview.set_on_preview_scroll(_sync_editor_from_preview)
        paned._zen_tab_id = tab_id
        return paned, md_preview, paned

    def _setup_openapi_split(self, editor_box, tab, tab_id, scrolled):
        """Create OpenAPI split view paned. Returns (paned, preview, page_container)."""
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_vexpand(True)
        paned.set_hexpand(True)
        paned.set_shrink_start_child(False)
        paned.set_shrink_end_child(False)
        paned.set_start_child(editor_box)

        from ..preview.openapi_preview import OpenAPIPreview

        openapi_preview = OpenAPIPreview()
        openapi_preview.set_hexpand(True)
        paned.set_end_child(openapi_preview)

        def _ensure_openapi_half():
            w = paned.get_allocated_width()
            if w > 10:
                paned.set_position(w // 2)
                return False
            return True

        GLib.timeout_add(100, _ensure_openapi_half)
        tab._openapi_preview = openapi_preview
        tab.buffer.connect("changed", lambda b, t=tab: self._on_openapi_buffer_changed(t))

        _syncing_from_preview = [False]
        _sync_guard_timer = [0]

        def _sync_openapi_scroll(adj, preview=openapi_preview, view=tab.view):
            if _syncing_from_preview[0] or preview.is_syncing_scroll:
                return
            visible = view.get_visible_rect()
            top_iter, _ = view.get_line_at_y(visible.y)
            preview.scroll_to_source_line(top_iter.get_line())

        scrolled.get_vadjustment().connect("value-changed", _sync_openapi_scroll)

        def _sync_editor_from_preview(fraction, _scrolled=scrolled):
            _syncing_from_preview[0] = True
            vadj = _scrolled.get_vadjustment()
            upper = vadj.get_upper()
            page = vadj.get_page_size()
            if upper > page:
                vadj.set_value(fraction * (upper - page))
            if _sync_guard_timer[0]:
                GLib.source_remove(_sync_guard_timer[0])
            _sync_guard_timer[0] = GLib.timeout_add(
                200, lambda: (_syncing_from_preview.__setitem__(0, False), _sync_guard_timer.__setitem__(0, 0)) or False
            )

        openapi_preview.set_on_preview_scroll(_sync_editor_from_preview)
        paned._zen_tab_id = tab_id
        return paned, openapi_preview, paned

    def _get_page_num_for_tab_id(self, tab_id: int) -> int:
        """Get the current notebook page number for a tab_id."""
        for i in range(self.notebook.get_n_pages()):
            page_widget = self.notebook.get_nth_page(i)
            if hasattr(page_widget, "_zen_tab_id") and page_widget._zen_tab_id == tab_id:
                return i
        return -1

    def _get_tab_id_for_page_num(self, page_num: int) -> int:
        """Get the tab_id for a notebook page number."""
        if page_num < 0:
            return -1
        page_widget = self.notebook.get_nth_page(page_num)
        if page_widget and hasattr(page_widget, "_zen_tab_id"):
            return page_widget._zen_tab_id
        return -1

    def _close_tab_by_id(self, tab_id: int):
        """Close a tab by its unique tab_id."""
        if tab_id not in self.tabs:
            return
        tab = self.tabs[tab_id]
        if tab.modified:
            self._confirm_close_tab_by_id(tab_id)
            return
        self._do_close_tab_by_id(tab_id)

    def _confirm_close_tab_by_id(self, tab_id: int):
        """Ask user about unsaved changes before closing."""
        from popups.save_confirm_popup import show_save_confirm

        tab = self.tabs[tab_id]
        name = os.path.basename(tab.file_path) if tab.file_path else "Untitled"

        def on_save():
            if tab_id not in self.tabs:
                return
            tab = self.tabs[tab_id]
            if tab.is_new and not tab.file_path:
                self._show_save_dialog_by_id(tab_id)
            else:
                if tab.is_new and tab.file_path:
                    parent_dir = os.path.dirname(tab.file_path)
                    if parent_dir:
                        os.makedirs(parent_dir, exist_ok=True)
                tab.save_file()
                self._do_close_tab_by_id(tab_id)

        def on_discard():
            self._do_close_tab_by_id(tab_id)

        show_save_confirm(
            self.get_root(),
            filename=name,
            on_save=on_save,
            on_discard=on_discard,
            on_cancel=None,
        )

    def _do_close_tab_by_id(self, tab_id: int):
        """Actually remove a tab by tab_id."""
        if tab_id not in self.tabs:
            return

        # Remove button from custom tab bar
        tab = self.tabs[tab_id]
        btn = getattr(tab, "_tab_button", None)
        if btn and btn.get_parent() == self._tab_bar:
            self._tab_bar.remove(btn)

        page_num = self._get_page_num_for_tab_id(tab_id)
        if page_num < 0 or page_num >= self.notebook.get_n_pages():
            if tab_id in self._modification_handler_ids:
                del self._modification_handler_ids[tab_id]
            del self.tabs[tab_id]
            return

        current_page = self.notebook.get_current_page()
        restore_tab_id = -1
        if page_num == current_page:
            prev_id = self._previous_active_tab_id
            if prev_id >= 0 and prev_id != tab_id and prev_id in self.tabs:
                restore_tab_id = prev_id

        self.notebook.remove_page(page_num)

        if restore_tab_id >= 0 and self.notebook.get_n_pages() > 0:
            restore_page = self._get_page_num_for_tab_id(restore_tab_id)
            if restore_page >= 0:
                self.notebook.set_current_page(restore_page)
        elif page_num != current_page and self.notebook.get_n_pages() > 0:
            new_current = current_page if page_num > current_page else current_page - 1
            self.notebook.set_current_page(max(0, new_current))

        if tab_id in self._modification_handler_ids:
            del self._modification_handler_ids[tab_id]
        del self.tabs[tab_id]

        if self.on_tab_closed:
            self.on_tab_closed()
        if self.notebook.get_n_pages() == 0 and self.on_tabs_empty:
            self.on_tabs_empty()
