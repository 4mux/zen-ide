"""EditorView — tabbed editor interface with file management."""

import os
from typing import Callable

from gi.repository import GLib, Gtk

from icons import IconsManager
from shared.focus_border_mixin import FocusBorderMixin
from shared.focus_manager import get_focus_manager
from shared.ui import ZenButton
from themes import subscribe_theme_change

from . import SKETCH_EXTENSION
from .core import _iter_at_line, _iter_at_line_offset
from .editor_tab import EditorTab
from .editor_view_file_openers_mixin import EditorViewFileOpenersMixin
from .editor_view_find_mixin import EditorViewFindMixin
from .editor_view_scroll_mixin import EditorViewScrollMixin
from .editor_view_tabs_mixin import EditorViewTabsMixin


class EditorView(
    EditorViewTabsMixin, EditorViewFileOpenersMixin, EditorViewFindMixin, EditorViewScrollMixin, FocusBorderMixin, Gtk.Box
):
    """Editor view with tabbed interface."""

    COMPONENT_ID = "editor"

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        # Initialize focus border
        self._init_focus_border()

        # Register with focus manager
        focus_mgr = get_focus_manager()
        focus_mgr.register(
            self.COMPONENT_ID,
            on_focus_in=self._on_focus_in,
            on_focus_out=self._on_focus_out,
        )

        # Use tab_id (unique, never changes) as key, NOT page_num (position, changes on close)
        self.tabs: dict[int, EditorTab] = {}  # tab_id -> EditorTab
        self._next_tab_id = 1

        # Callback for when a file is opened (for tree view sync)
        self.on_file_opened: Callable[[str], None] | None = None
        # Callback for when a tab is switched (for tree view sync)
        self.on_tab_switched: Callable[[str], None] | None = None
        # Callback for cursor position changes (for status bar)
        self.on_cursor_position_changed: Callable[[int, int, int], None] | None = None
        # Callback for diagnostics updates (for status bar)
        self.on_diagnostics_changed: Callable[[int, int], None] | None = None
        # Callback for gutter diagnostic click (for diagnostics popup)
        self.on_gutter_diagnostic_clicked: Callable | None = None
        # Callback for when all tabs are closed (no files open)
        self.on_tabs_empty: Callable[[], None] | None = None
        # Callback for when any tab is closed (for persisting open files)
        self.on_tab_closed: Callable[[], None] | None = None

        # Callbacks for editor action buttons
        self.on_maximize: Callable[[str], None] | None = None

        # Custom tab bar: [scroll-left] [scrollable tabs] [scroll-right] [actions]
        tab_bar_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)

        self._scroll_left_btn = Gtk.Button.new_from_icon_name("pan-start-symbolic")
        self._scroll_left_btn.add_css_class("flat")
        self._scroll_left_btn.connect("clicked", lambda _b: self._scroll_tab_bar(-1))
        tab_bar_row.append(self._scroll_left_btn)

        self._tab_bar_scroll = Gtk.ScrolledWindow()
        self._tab_bar_scroll.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        self._tab_bar_scroll.set_propagate_natural_width(False)
        self._tab_bar_scroll.set_hexpand(True)

        self._tab_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        self._tab_bar_scroll.set_child(self._tab_bar)
        tab_bar_row.append(self._tab_bar_scroll)

        self._scroll_right_btn = Gtk.Button.new_from_icon_name("pan-end-symbolic")
        self._scroll_right_btn.add_css_class("flat")
        self._scroll_right_btn.connect("clicked", lambda _b: self._scroll_tab_bar(1))
        tab_bar_row.append(self._scroll_right_btn)

        # Action buttons at the end of the tab bar
        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        action_box.set_margin_end(4)

        self.debug_btn = ZenButton(icon=IconsManager.PLAY, tooltip="Start Debugging (F5)")
        self.debug_btn.connect("clicked", self._on_debug_btn_clicked)
        action_box.append(self.debug_btn)

        self.maximize_btn = ZenButton(icon=IconsManager.MAXIMIZE, tooltip="Maximize")
        self.maximize_btn.connect("clicked", self._on_maximize_clicked)
        action_box.append(self.maximize_btn)

        tab_bar_row.append(action_box)
        self.append(tab_bar_row)

        # Notebook with built-in tabs hidden — we manage tabs via the custom bar
        self.notebook = Gtk.Notebook()
        self.notebook.set_show_tabs(False)
        self.notebook.set_show_border(False)
        self.notebook.set_vexpand(True)
        self.notebook.connect("switch-page", self._on_tab_changed)
        self.append(self.notebook)

        # Track active/previous tab for close-button restoration
        self._active_tab_id = -1
        self._previous_active_tab_id = -1

        # Find bar created lazily on first Cmd+F (saves ~2-3ms at startup)
        self._find_bar_created = False

        # Track modifications by tab_id
        self._modification_handler_ids = {}

        # Search context (persisted so match count updates work)
        self._search_context = None
        self._search_settings = None

        # Add click controller to gain focus
        click_ctrl = Gtk.GestureClick.new()
        click_ctrl.connect("pressed", self._on_panel_click)
        self.add_controller(click_ctrl)

        # Code navigation system
        self._code_navigation = None

        # Callback for getting workspace folders (set by main app)
        self.get_workspace_folders: Callable[[], list] | None = None

        # Subscribe to theme changes so all editor tabs update
        subscribe_theme_change(self._on_theme_change)

    def _on_theme_change(self, theme):
        """Re-apply theme to all open editor tabs, preserving scroll position."""
        for tab in self.tabs.values():
            vadj = tab.view.get_vadjustment()
            scroll_pos = vadj.get_value() if vadj else 0
            tab._apply_theme()
            if vadj and scroll_pos > 0:
                GLib.idle_add(lambda v=vadj, p=scroll_pos: v.set_value(p) or False)

    def _on_buffer_changed_by_id(self, tab_id: int):
        """Handle buffer content change by tab_id."""
        if tab_id not in self.tabs:
            return
        tab = self.tabs[tab_id]
        start, end = tab.buffer.get_start_iter(), tab.buffer.get_end_iter()
        current_content = tab.buffer.get_text(start, end, True)
        was_modified = tab.modified
        tab.modified = current_content != tab.original_content
        if tab.modified != was_modified:
            self._update_tab_title_by_id(tab_id)

    def _on_md_buffer_changed(self, tab: EditorTab):
        """Handle Markdown buffer change - update preview with debouncing."""
        self._debounced_preview_update(tab, "_md_preview", "_md_update_timeout", 300)

    def _on_openapi_buffer_changed(self, tab: EditorTab):
        """Handle OpenAPI buffer change - update preview with debouncing."""
        self._debounced_preview_update(tab, "_openapi_preview", "_openapi_update_timeout", 500)

    def _debounced_preview_update(self, tab, preview_attr, timeout_attr, delay_ms):
        """Generic debounced preview update for markdown/openapi split views."""
        preview = getattr(tab, preview_attr, None)
        if not preview:
            return
        if hasattr(tab, timeout_attr) and getattr(tab, timeout_attr):
            GLib.source_remove(getattr(tab, timeout_attr))

        def do_update():
            p = getattr(tab, preview_attr, None)
            if p:
                start, end = tab.buffer.get_start_iter(), tab.buffer.get_end_iter()
                p.update_from_editor(tab.buffer.get_text(start, end, True), tab.file_path)
            setattr(tab, timeout_attr, None)
            return False

        setattr(tab, timeout_attr, GLib.timeout_add(delay_ms, do_update))

    def _on_cursor_moved(self, tab_id: int):
        """Handle cursor movement - notify callback for status bar."""
        current_tab_id = self._get_tab_id_for_page_num(self.notebook.get_current_page())
        if tab_id != current_tab_id:
            return

        if self.on_cursor_position_changed and tab_id in self.tabs:
            tab = self.tabs[tab_id]
            insert = tab.buffer.get_insert()
            iter_at_cursor = tab.buffer.get_iter_at_mark(insert)
            line = iter_at_cursor.get_line() + 1
            col = iter_at_cursor.get_line_offset() + 1
            total_lines = tab.buffer.get_line_count()
            self.on_cursor_position_changed(line, col, total_lines)

    def _on_diagnostics_updated(self, file_path: str, errors: int, warnings: int):
        """Handle diagnostics update - notify callback for status bar."""
        tab = self._get_current_tab()
        if tab and tab.file_path == file_path and self.on_diagnostics_changed:
            self.on_diagnostics_changed(errors, warnings)

    def _on_gutter_diagnostic_clicked(self, file_path: str):
        """Handle click on gutter diagnostic dot."""
        if self.on_gutter_diagnostic_clicked:
            self.on_gutter_diagnostic_clicked()

    def get_current_tab(self) -> EditorTab | None:
        """Get the current tab, or None if no tabs are open."""
        return self._get_current_tab()

    def get_tab_by_path(self, file_path: str) -> EditorTab | None:
        """Get tab for a given file path, or None if not open."""
        norm = os.path.normpath(file_path)
        for tab in self.tabs.values():
            if tab.file_path and os.path.normpath(tab.file_path) == norm:
                return tab
        return None

    def set_minimap_visible(self, visible: bool):
        """Show or hide the minimap and its indicator on all tabs."""
        for tab in self.tabs.values():
            if hasattr(tab, "_minimap") and tab._minimap:
                tab._minimap.set_visible(visible)
            if hasattr(tab, "_minimap_indicator") and tab._minimap_indicator:
                tab._minimap_indicator.set_visible(visible)

    def close_current_tab(self):
        """Close the current tab."""
        page_num = self.notebook.get_current_page()
        if page_num >= 0:
            tab_id = self._get_tab_id_for_page_num(page_num)
            if tab_id >= 0:
                self._close_tab_by_id(tab_id)
            elif page_num < self.notebook.get_n_pages():
                # Remove corresponding button from custom tab bar (non-tracked tabs)
                page = self.notebook.get_nth_page(page_num)
                cls_name = page.__class__.__name__
                child = self._tab_bar.get_first_child()
                while child:
                    nxt = child.get_next_sibling()
                    tid = getattr(child, "tab_id", None)
                    if (cls_name == "WelcomeScreen" and tid == -1) or (cls_name == "DevPad" and tid == -2):
                        self._tab_bar.remove(child)
                        break
                    child = nxt
                self.notebook.remove_page(page_num)
                if self.notebook.get_n_pages() == 0 and self.on_tabs_empty:
                    self.on_tabs_empty()

    def save_current(self) -> bool:
        """Save the current file."""
        page_num = self.notebook.get_current_page()
        tab_id = self._get_tab_id_for_page_num(page_num)
        if tab_id < 0 or tab_id not in self.tabs:
            return False

        tab = self.tabs[tab_id]
        if getattr(tab, "_is_image", False):
            return False

        if tab.is_new and not tab.file_path:
            self._show_save_dialog_by_id(tab_id)
            return False

        if tab.is_new and tab.file_path:
            parent_dir = os.path.dirname(tab.file_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

        if tab.save_file():
            self._update_tab_title_by_id(tab_id)
            if hasattr(tab, "_minimap_indicator") and tab._minimap_indicator:
                tab._minimap_indicator.refresh_head()
            return True

        return False

    def _show_save_dialog_by_id(self, tab_id: int):
        """Show a save file dialog for untitled files."""
        dialog = Gtk.FileDialog()
        dialog.set_title("Save File")
        dialog.save(self.get_root(), None, lambda d, r, tid=tab_id: self._on_save_response_by_id(d, r, tid))

    def _on_save_response_by_id(self, dialog, result, tab_id: int):
        """Handle save dialog response."""
        try:
            file = dialog.save_finish(result)
            if file and tab_id in self.tabs:
                path = file.get_path()
                tab = self.tabs[tab_id]
                if getattr(tab, "_is_sketch", False) and not path.endswith(SKETCH_EXTENSION):
                    path += SKETCH_EXTENSION
                if tab.save_file(path):
                    if hasattr(tab, "_set_language_from_file"):
                        tab._set_language_from_file(path)
                    self._update_tab_title_by_id(tab_id)
                    if hasattr(tab, "_minimap_indicator") and tab._minimap_indicator:
                        tab._minimap_indicator.set_file_path(path)
                    if getattr(tab, "_is_sketch", False):
                        from dev_pad import log_sketch_activity

                        content = tab.widget.get_content() if hasattr(tab.widget, "get_content") else ""
                        log_sketch_activity(content=content, file_path=path)
                    else:
                        from dev_pad import log_file_activity

                        log_file_activity(path, "open")
        except GLib.Error:
            pass

    def _update_tab_title_by_id(self, tab_id: int):
        """Update the tab title and modified indicator."""
        if tab_id not in self.tabs:
            return
        tab = self.tabs[tab_id]
        if hasattr(tab, "_tab_button"):
            tab._tab_button.set_title(tab.get_title())
            tab._tab_button.set_modified(tab.modified)
        elif hasattr(tab, "_tab_label"):
            tab._tab_label.set_label(tab.get_title())

    def _on_tab_changed(self, notebook, page, page_num):
        """Handle tab change."""
        new_tab_id = self._get_tab_id_for_page_num(page_num)
        if self._active_tab_id >= 0 and self._active_tab_id != new_tab_id:
            self._previous_active_tab_id = self._active_tab_id
        self._active_tab_id = new_tab_id

        self._sync_tab_selection(page_num)
        tab_id = new_tab_id
        if tab_id >= 0 and tab_id in self.tabs:
            tab = self.tabs[tab_id]
            if tab.file_path and self.on_tab_switched:
                self.on_tab_switched(tab.file_path)

    def _select_tab_by_id(self, tab_id: int):
        """Switch to a tab by its id (called from custom tab bar click)."""
        page_num = self._get_page_num_for_tab_id(tab_id)
        if page_num >= 0:
            self.notebook.set_current_page(page_num)

    def _sync_tab_selection(self, active_page_num):
        """Update TabButton selection state in the custom tab bar."""
        from shared.ui.tab_button import TabButton

        active_tab_id = self._get_tab_id_for_page_num(active_page_num)
        # For non-tracked pages (Welcome, DevPad), match by page index
        active_page = self.notebook.get_nth_page(active_page_num) if active_page_num >= 0 else None
        active_cls = active_page.__class__.__name__ if active_page else ""
        # Map special class names to tab_ids
        special_ids = {"WelcomeScreen": -1, "DevPad": -2}

        child = self._tab_bar.get_first_child()
        while child:
            if isinstance(child, TabButton):
                tid = getattr(child, "tab_id", None)
                if active_tab_id >= 0:
                    child.set_selected(tid == active_tab_id)
                elif active_cls in special_ids:
                    child.set_selected(tid == special_ids[active_cls])
                else:
                    child.set_selected(False)
            child = child.get_next_sibling()
        # Scroll the active tab into view
        if active_tab_id >= 0:
            GLib.idle_add(lambda: self._scroll_tab_into_view(active_tab_id) or False)

    def _get_current_tab(self) -> EditorTab | None:
        """Get the current tab, or None if no tabs are open."""
        page_num = self.notebook.get_current_page()
        tab_id = self._get_tab_id_for_page_num(page_num)
        if tab_id >= 0 and tab_id in self.tabs:
            return self.tabs[tab_id]
        return None

    def undo(self):
        """Undo in the current editor."""
        tab = self._get_current_tab()
        if not tab:
            return
        if getattr(tab, "_is_sketch", False):
            tab.undo()
            return
        ic = getattr(tab, "_inline_completion", None)
        if ic is not None and ic.is_active:
            ic.dismiss()
        if tab.buffer.get_can_undo():
            tab.buffer.undo()

    def redo(self):
        """Redo in the current editor."""
        tab = self._get_current_tab()
        if not tab:
            return
        if getattr(tab, "_is_sketch", False):
            tab.redo()
        elif tab.buffer.get_can_redo():
            tab.buffer.redo()

    def get_current_content(self) -> str:
        """Get content of the current editor."""
        tab = self._get_current_tab()
        if not tab:
            return ""
        if getattr(tab, "_is_sketch", False):
            return tab.widget.get_content()
        start = tab.buffer.get_start_iter()
        end = tab.buffer.get_end_iter()
        return tab.buffer.get_text(start, end, True)

    def get_current_file_path(self) -> str:
        """Get file path of the current editor."""
        tab = self._get_current_tab()
        if not tab:
            return ""
        return tab.file_path or ""

    def toggle_comment(self):
        """Toggle comment on current line(s)."""
        tab = self._get_current_tab()
        if not tab:
            return

        buffer = tab.buffer

        if buffer.get_has_selection():
            start, end = buffer.get_selection_bounds()
        else:
            cursor = buffer.get_insert()
            start = buffer.get_iter_at_mark(cursor)
            end = start.copy()

        start.set_line_offset(0)
        if not end.ends_line():
            end.forward_to_line_end()

        lang = buffer.get_language()
        comment_start = "#"
        if lang:
            lang_id = lang.get_id()
            if lang_id in ("c", "cpp", "java", "javascript", "typescript", "rust", "go", "swift", "kotlin"):
                comment_start = "//"

        start_line = start.get_line()
        end_line = end.get_line()

        buffer.begin_user_action()
        for line_num in range(start_line, end_line + 1):
            line_iter = _iter_at_line(buffer, line_num)
            line_end = line_iter.copy()
            line_end.forward_to_line_end()
            line_text = buffer.get_text(line_iter, line_end, True)

            stripped = line_text.lstrip()
            if stripped.startswith(comment_start):
                indent = len(line_text) - len(stripped)
                comment_len = len(comment_start)
                if stripped.startswith(comment_start + " "):
                    comment_len += 1
                del_start = _iter_at_line_offset(buffer, line_num, indent)
                del_end = _iter_at_line_offset(buffer, line_num, indent + comment_len)
                buffer.delete(del_start, del_end)
            else:
                insert_iter = _iter_at_line(buffer, line_num)
                buffer.insert(insert_iter, comment_start + " ")

        buffer.end_user_action()

    def indent(self):
        """Indent current line(s)."""
        self._indent_lines(indent=True)

    def unindent(self):
        """Unindent current line(s)."""
        self._indent_lines(indent=False)

    def _indent_lines(self, indent: bool):
        """Indent or unindent selected lines."""
        tab = self._get_current_tab()
        if not tab:
            return

        buffer = tab.buffer

        if buffer.get_has_selection():
            start, end = buffer.get_selection_bounds()
        else:
            cursor = buffer.get_insert()
            start = buffer.get_iter_at_mark(cursor)
            end = start.copy()

        start_line = start.get_line()
        end_line = end.get_line()

        tab_width = tab.view.get_tab_width()
        indent_str = " " * tab_width

        buffer.begin_user_action()
        for line_num in range(start_line, end_line + 1):
            line_iter = _iter_at_line(buffer, line_num)

            if indent:
                buffer.insert(line_iter, indent_str)
            else:
                line_end = line_iter.copy()
                line_end.forward_to_line_end()
                line_text = buffer.get_text(line_iter, line_end, True)

                spaces_to_remove = 0
                for c in line_text[:tab_width]:
                    if c == " ":
                        spaces_to_remove += 1
                    elif c == "\t":
                        spaces_to_remove = tab_width
                        break
                    else:
                        break

                if spaces_to_remove > 0:
                    del_end = _iter_at_line_offset(buffer, line_num, spaces_to_remove)
                    buffer.delete(line_iter, del_end)

        buffer.end_user_action()

    def has_unsaved_changes(self) -> bool:
        """Check if any tab has unsaved changes."""
        return any(tab.modified for tab in self.tabs.values())

    def get_unsaved_tabs(self) -> list:
        """Return list of (tab_id, tab) for modified tabs."""
        return [(tid, t) for tid, t in self.tabs.items() if t.modified]

    def _on_panel_click(self, gesture, n_press, x, y):
        """Handle click on panel to gain focus."""
        self._handle_panel_click_focus()

    def _on_focus_in(self):
        """Called when this panel gains focus."""
        self._handle_panel_focus_in()

    def _on_focus_out(self):
        """Called when this panel loses focus."""
        self._handle_panel_focus_out()

    def _on_cmd_click(self, buffer, view, file_path, click_iter):
        """Handle Cmd+Click for code navigation."""
        if not self._code_navigation:
            self._init_code_navigation()
        if self._code_navigation:
            self._code_navigation.handle_cmd_click(buffer, view, file_path, click_iter)

    def _init_code_navigation(self):
        """Initialize the code navigation system."""
        from navigation.code_navigation import CodeNavigation

        self._code_navigation = CodeNavigation(
            open_file_callback=self._navigation_open_file,
            get_workspace_folders=self.get_workspace_folders,
            get_current_buffer_view=self._get_current_buffer_view,
        )

    def _navigation_open_file(self, file_path: str, line_number: int = None) -> bool:
        """Open a file from navigation."""
        return self.open_file(file_path, line_number=line_number)

    def _get_current_buffer_view(self):
        """Return (buffer, view) for the current tab, or None."""
        tab = self._get_current_tab()
        if tab:
            return (tab.buffer, tab.view)
        return None

    # ── Custom tab bar scrolling ───────────────────────────────────────

    def _scroll_tab_bar(self, direction: int) -> None:
        """Scroll the custom tab bar left (-1) or right (+1)."""
        hadj = self._tab_bar_scroll.get_hadjustment()
        if not hadj:
            return
        step = 120
        new_val = hadj.get_value() + direction * step
        new_val = max(0, min(new_val, hadj.get_upper() - hadj.get_page_size()))
        hadj.set_value(new_val)

    def _scroll_tab_into_view(self, tab_id: int) -> None:
        """Ensure the tab button for *tab_id* is visible in the scroll area."""
        if tab_id not in self.tabs:
            return
        tab = self.tabs[tab_id]
        btn = getattr(tab, "_tab_button", None)
        if not btn:
            return
        hadj = self._tab_bar_scroll.get_hadjustment()
        if not hadj:
            return
        # Walk siblings to compute offset
        offset = 0
        child = self._tab_bar.get_first_child()
        while child and child != btn:
            offset += child.get_width() + 2  # spacing=2
            child = child.get_next_sibling()
        btn_w = btn.get_width()
        cur = hadj.get_value()
        page = hadj.get_page_size()
        if offset < cur:
            hadj.set_value(offset)
        elif offset + btn_w > cur + page:
            hadj.set_value(offset + btn_w - page)

    def _on_debug_btn_clicked(self, button):
        """Activate the debug_start action."""
        root = self.get_root()
        if root:
            app = root.get_application()
            if app:
                app.activate_action("debug_start")

    def _on_maximize_clicked(self, button):
        """Delegate maximize to parent window."""
        if self.on_maximize:
            self.on_maximize("editor")
