"""Debug Panel — bottom panel UI for debugging.

Shows debug toolbar, call stack, variables tree, breakpoints list,
and debug console. Registered via SplitPanelManager.
"""

import os

from gi.repository import GLib, Graphene, Gtk, Pango

from icons import IconsManager
from shared.ui import ZenButton
from shared.ui.zen_tree import ZenTree, ZenTreeItem
from shared.utils import tuple_to_gdk_rgba
from themes import get_theme

from .breakpoint_manager import Breakpoint, get_breakpoint_manager
from .debug_console import DebugConsole
from .debug_session import DebugSession, SessionState


class _DebugVarTree(ZenTree):
    """ZenTree subclass for debug variable inspection with text wrapping."""

    _WRAP_PADDING = 6  # vertical padding for wrapped rows

    def __init__(self, session_getter):
        super().__init__(font_context="editor")
        self._session_getter = session_getter
        self._item_positions: list[tuple[float, float]] = []  # (y, height) per item

    def refresh(self, session):
        """Rebuild the variable tree from session scopes."""
        if not session or session.state != SessionState.STOPPED:
            self.set_roots([])
            return

        roots = []
        scopes = session.get_scopes()
        for i, scope in enumerate(scopes):
            scope_item = ZenTreeItem(
                name=scope.name,
                is_expandable=scope.variables_reference > 0,
                is_last=(i == len(scopes) - 1),
                data={"ref": scope.variables_reference, "loaded": False},
            )
            # Pre-load non-expensive scopes
            if not scope.expensive and scope.variables_reference:
                self._load_scope_vars(session, scope_item)
            roots.append(scope_item)
        self.set_roots(roots)

    def _load_scope_vars(self, session, parent_item):
        """Load variables into a scope/variable item."""
        ref = parent_item.data.get("ref", 0)
        if ref <= 0:
            return
        variables = session.get_variables(ref)
        for i, var in enumerate(variables):
            child = ZenTreeItem(
                name=var.name,
                is_expandable=var.variables_reference > 0,
                depth=parent_item.depth + 1,
                parent=parent_item,
                is_last=(i == len(variables) - 1),
                data={
                    "value": var.value,
                    "type": var.type,
                    "ref": var.variables_reference,
                    "loaded": False,
                },
            )
            parent_item.children.append(child)
        parent_item.data["loaded"] = True

    def _load_item_children(self, item):
        """Lazy-load child variables when expanding."""
        if item.data.get("loaded"):
            return
        session = self._session_getter()
        if not session or session.state != SessionState.STOPPED:
            return
        self._load_scope_vars(session, item)

    # -- Variable-height rendering overrides --

    def _get_item_at_y(self, y):
        """Binary search through computed positions for click hit-testing."""
        positions = self._item_positions
        if not positions or len(positions) != len(self.items):
            return super()._get_item_at_y(y)
        lo, hi = 0, len(positions) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            iy, ih = positions[mid]
            if y < iy:
                hi = mid - 1
            elif y >= iy + ih:
                lo = mid + 1
            else:
                return self.items[mid]
        return None

    def _update_virtual_size(self):
        """Use computed total height when available."""
        positions = self._item_positions
        if positions and len(positions) == len(self.items):
            last_y, last_h = positions[-1]
            self.drawing_area.set_size_request(-1, max(int(last_y + last_h), 100))
        else:
            super()._update_virtual_size()

    def _ensure_visible(self, item, animate=False, _retries=0, _gen=-1):
        """Scroll to make item visible using variable positions."""
        positions = self._item_positions
        if not positions or len(positions) != len(self.items):
            return super()._ensure_visible(item, animate, _retries, _gen)
        if _gen == -1:
            self._ensure_visible_gen += 1
            _gen = self._ensure_visible_gen
        elif _gen != self._ensure_visible_gen:
            return False
        try:
            idx = self.items.index(item)
            vadj = self.get_vadjustment()
            if not vadj:
                return False
            item_y, item_h = positions[idx]
            page = vadj.get_page_size()
            scroll_y = vadj.get_value()
            if page <= 0:
                if _retries < 5:
                    GLib.idle_add(self._ensure_visible, item, animate, _retries + 1, _gen)
                return False
            if item_y >= scroll_y and item_y + item_h <= scroll_y + page:
                return False
            if item_y < scroll_y:
                vadj.set_value(item_y)
            else:
                vadj.set_value(item_y + item_h - page)
        except ValueError:
            pass
        return False

    def _measure_row_height(self, layout, item, width):
        """Measure height needed for an item's wrapped text."""
        data = getattr(item, "data", None) or {}
        value = data.get("value", "")
        if not value:
            return self.row_height

        x = self.LEFT_PADDING + item.depth * self.INDENT_WIDTH + self.INDENT_WIDTH
        avail = max(width - x - self.LEFT_PADDING, 60)

        layout.set_font_description(self.text_font_desc)
        layout.set_width(int(avail * Pango.SCALE))
        layout.set_wrap(Pango.WrapMode.CHAR)
        layout.set_text(f"{item.name}: {value}", -1)
        _, logical = layout.get_pixel_extents()
        layout.set_width(-1)
        layout.set_wrap(Pango.WrapMode.WORD)

        return max(self.row_height, logical.height + self._WRAP_PADDING)

    def _on_snapshot(self, snapshot, width, height):
        """Draw tree with variable-height wrapped rows."""
        rect = Graphene.Rect()
        rect.init(0, 0, width, height)
        snapshot.append_color(tuple_to_gdk_rgba(self.bg_color), rect)

        if not self.items:
            self._item_positions = []
            return

        pango_ctx = self.drawing_area.get_pango_context()
        layout = Pango.Layout.new(pango_ctx)

        # Cache font metrics on first draw (same as base class)
        if self._cached_text_height is None:
            layout.set_font_description(self.text_font_desc)
            layout.set_text("Ay", -1)
            text_ink, text_logical = layout.get_pixel_extents()
            self._cached_text_height = text_logical.height
            self._cached_text_ink_center = text_ink.y + text_ink.height / 2
            layout.set_font_description(self.icon_font_desc)
            layout.set_text(self.chevron_expanded, -1)
            icon_ink, icon_logical = layout.get_pixel_extents()
            self._cached_icon_height = icon_logical.height
            self._cached_icon_ink_center = icon_ink.y + icon_ink.height / 2

        vadj = self.get_vadjustment()
        scroll_y = vadj.get_value() if vadj else 0
        view_bottom = scroll_y + height

        positions = []
        y = 0.0
        point = Graphene.Point()

        for item in self.items:
            row_h = self._measure_row_height(layout, item, width)
            positions.append((y, row_h))

            # Only draw visible rows
            if y + row_h > scroll_y and y < view_bottom:
                # Selection / hover background
                if self._is_item_selected(item):
                    hide = (
                        self.drawing_area.has_focus()
                        and not self._cursor_blinker.cursor_visible
                        and item == self.selected_item
                    )
                    if not hide:
                        rect.init(0, y, width, row_h)
                        snapshot.append_color(tuple_to_gdk_rgba(self.selected_bg), rect)
                elif item == self.hover_item:
                    rect.init(0, y, width, row_h)
                    snapshot.append_color(tuple_to_gdk_rgba(self.hover_bg), rect)

                # Draw content
                self._draw_var_row(snapshot, layout, point, item, y, width)

            y += row_h

        self._item_positions = positions

        # Sync virtual size
        total_h = max(int(y), 100)
        self.drawing_area.set_size_request(-1, total_h)

    def _draw_var_row(self, snapshot, layout, point, item, y, width):
        """Draw a single variable row with chevron and wrapped name: value."""
        # Align chevron to first line
        first_line_y = y + (self.row_height - self._cached_text_height) / 2
        icon_y = first_line_y + self._cached_text_ink_center - self._cached_icon_ink_center

        x = self.LEFT_PADDING + item.depth * self.INDENT_WIDTH

        # Chevron
        layout.set_font_description(self.icon_font_desc)
        if self._is_item_expandable(item):
            chevron = self.chevron_expanded if item.expanded else self.chevron_collapsed
            layout.set_text(chevron, -1)
            snapshot.save()
            point.init(x, icon_y)
            snapshot.translate(point)
            snapshot.append_layout(layout, tuple_to_gdk_rgba(self.chevron_color))
            snapshot.restore()
        x += self.INDENT_WIDTH

        # Text
        layout.set_font_description(self.text_font_desc)
        data = getattr(item, "data", None) or {}
        value = data.get("value", "")
        avail = max(width - x - self.LEFT_PADDING, 60)

        layout.set_width(int(avail * Pango.SCALE))
        layout.set_wrap(Pango.WrapMode.CHAR)

        text_y = y + self._WRAP_PADDING // 2

        if value:
            full_text = f"{item.name}: {value}"
            layout.set_text(full_text, -1)

            # Dim the value portion
            attrs = Pango.AttrList.new()
            sep_bytes = len(item.name.encode("utf-8")) + 2  # ": "
            total_bytes = len(full_text.encode("utf-8"))
            dim = Pango.attr_foreground_new(
                int(self.fg_color[0] * 0.6 * 65535),
                int(self.fg_color[1] * 0.6 * 65535),
                int(self.fg_color[2] * 0.6 * 65535),
            )
            dim.start_index = sep_bytes
            dim.end_index = total_bytes
            attrs.insert(dim)
            layout.set_attributes(attrs)

            snapshot.save()
            point.init(x, text_y)
            snapshot.translate(point)
            snapshot.append_layout(layout, tuple_to_gdk_rgba(self.fg_color))
            snapshot.restore()
            layout.set_attributes(None)
        else:
            layout.set_text(item.name, -1)
            snapshot.save()
            point.init(x, text_y)
            snapshot.translate(point)
            snapshot.append_layout(layout, tuple_to_gdk_rgba(self.fg_color))
            snapshot.restore()

        # Reset layout state
        layout.set_width(-1)
        layout.set_wrap(Pango.WrapMode.WORD)


class DebugPanel(Gtk.Box):
    """Debug panel with toolbar, call stack, variables, breakpoints, and console."""

    COMPONENT_ID = "debug_panel"

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._window = window
        self._session: DebugSession | None = None
        self._breakpoint_mgr = get_breakpoint_manager()
        self.add_css_class("debug-panel")

        theme = get_theme()
        from fonts import get_font_settings

        font_settings = get_font_settings("editor")
        font_family = font_settings["family"]
        self._font_desc = Pango.FontDescription.from_string(f"{font_family} 12")
        self._font_attrs = Pango.AttrList.new()
        self._font_attrs.insert(Pango.attr_font_desc_new(self._font_desc))

        # -- Toolbar --
        self._toolbar = self._create_toolbar()
        self.append(self._toolbar)

        # -- Main content: all sections stacked vertically --
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content_box.set_vexpand(True)
        self.append(content_box)

        # Call stack section
        content_box.append(self._create_section_label("CALL STACK"))
        stack_scroll = Gtk.ScrolledWindow()
        stack_scroll.set_vexpand(True)
        stack_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        content_box.append(stack_scroll)

        self._stack_list = Gtk.ListBox()
        self._stack_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._stack_list.connect("row-activated", self._on_stack_frame_activated)
        self._stack_list.add_css_class("debug-stack-list")
        stack_scroll.set_child(self._stack_list)

        # Variables section — using ZenTree
        content_box.append(self._create_section_label("VARIABLES"))
        self._var_tree = _DebugVarTree(session_getter=lambda: self._session)
        self._var_tree.set_vexpand(True)
        content_box.append(self._var_tree)

        # Breakpoints section
        content_box.append(self._create_section_label("BREAKPOINTS"))
        bp_scroll = Gtk.ScrolledWindow()
        bp_scroll.set_vexpand(True)
        bp_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        content_box.append(bp_scroll)

        self._bp_list = Gtk.ListBox()
        self._bp_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._bp_list.add_css_class("debug-bp-list")
        bp_scroll.set_child(self._bp_list)

        # Debug console section
        content_box.append(self._create_section_label("DEBUG CONSOLE"))
        self._console = DebugConsole(on_evaluate=self._on_evaluate)
        self._console.set_vexpand(True)
        content_box.append(self._console)

        # Subscribe to breakpoint changes
        self._breakpoint_mgr.subscribe(self._on_breakpoints_changed)
        self._refresh_breakpoints_list()

    def set_session(self, session: DebugSession | None) -> None:
        """Set the active debug session."""
        self._session = session
        self._update_toolbar_state()
        if session:
            self._console.clear()

    # -- Toolbar --

    def _create_toolbar(self) -> Gtk.Box:
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        toolbar.set_margin_top(4)
        toolbar.set_margin_bottom(4)
        toolbar.set_margin_start(8)
        toolbar.set_margin_end(8)
        toolbar.add_css_class("debug-toolbar")

        buttons = [
            ("Continue", IconsManager.CONTINUE, self._on_continue),
            ("Step Over", IconsManager.STEP_OVER, self._on_step_over),
            ("Step In", IconsManager.STEP_INTO, self._on_step_in),
            ("Step Out", IconsManager.STEP_OUT, self._on_step_out),
            ("Restart", IconsManager.RESTART, self._on_restart),
            ("Stop", IconsManager.STOP, self._on_stop),
        ]

        self._toolbar_buttons = {}
        for label, icon, callback in buttons:
            btn = ZenButton(icon=icon, tooltip=label)
            btn.connect("clicked", callback)
            btn.add_css_class("debug-toolbar-btn")
            toolbar.append(btn)
            self._toolbar_buttons[label] = btn

        # Status label
        self._status_label = Gtk.Label(label="Not debugging")
        self._status_label.set_hexpand(True)
        self._status_label.set_halign(Gtk.Align.END)
        self._status_label.add_css_class("debug-status")
        self._status_label.set_attributes(self._font_attrs)
        toolbar.append(self._status_label)

        # Close button
        close_btn = Gtk.Button()
        close_btn.set_icon_name("window-close-symbolic")
        close_btn.set_tooltip_text("Close debug panel")
        close_btn.connect("clicked", lambda _: self._window.split_panels.hide("debug"))
        close_btn.add_css_class("flat")
        toolbar.append(close_btn)

        return toolbar

    def _update_toolbar_state(self) -> None:
        """Update toolbar button sensitivity based on session state."""
        if not self._session:
            state = SessionState.IDLE
        else:
            state = self._session.state

        is_stopped = state == SessionState.STOPPED
        is_running = state == SessionState.RUNNING
        is_active = is_stopped or is_running

        self._toolbar_buttons["Continue"].set_sensitive(is_stopped)
        self._toolbar_buttons["Step Over"].set_sensitive(is_stopped)
        self._toolbar_buttons["Step In"].set_sensitive(is_stopped)
        self._toolbar_buttons["Step Out"].set_sensitive(is_stopped)
        self._toolbar_buttons["Restart"].set_sensitive(is_active)
        self._toolbar_buttons["Stop"].set_sensitive(is_active)

        state_labels = {
            SessionState.IDLE: "Not debugging",
            SessionState.INITIALIZING: "Starting...",
            SessionState.RUNNING: "Running",
            SessionState.STOPPED: "Paused",
            SessionState.TERMINATED: "Terminated",
        }
        self._status_label.set_text(state_labels.get(state, ""))

    # -- Toolbar callbacks --

    def _on_continue(self, btn):
        if self._session:
            self._session.continue_()

    def _on_step_over(self, btn):
        if self._session:
            self._session.step_over()

    def _on_step_in(self, btn):
        if self._session:
            self._session.step_into()

    def _on_step_out(self, btn):
        if self._session:
            self._session.step_out()

    def _on_restart(self, btn):
        if self._session:
            self._console.clear()
            self._clear_call_stack()
            self._var_tree.set_roots([])
            self._session.restart()

    def _on_stop(self, btn):
        if self._session:
            self._session.stop()

    # -- Call Stack --

    def _clear_call_stack(self) -> None:
        """Remove all rows from the call stack list."""
        while True:
            row = self._stack_list.get_row_at_index(0)
            if row is None:
                break
            self._stack_list.remove(row)

    def update_call_stack(self, frames: list) -> None:
        """Update the call stack display."""
        self._clear_call_stack()

        for i, frame in enumerate(frames):
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            box.set_margin_start(4)
            box.set_margin_end(4)
            box.set_margin_top(2)
            box.set_margin_bottom(2)

            # Function name
            name_label = Gtk.Label(label=frame.name)
            name_label.set_halign(Gtk.Align.START)
            name_label.set_hexpand(True)
            name_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            name_label.set_attributes(self._font_attrs)
            box.append(name_label)

            # File:line
            basename = os.path.basename(frame.source) if frame.source else ""
            loc_label = Gtk.Label(label=f"{basename}:{frame.line}")
            loc_label.add_css_class("dim-label")
            loc_label.set_attributes(self._font_attrs)
            box.append(loc_label)

            row.set_child(box)
            row._frame = frame
            self._stack_list.append(row)

    def _on_stack_frame_activated(self, listbox, row) -> None:
        """Handle click on a stack frame — navigate to source."""
        if not hasattr(row, "_frame"):
            return
        frame = row._frame
        if self._session:
            self._session.set_current_frame(frame)
            self._refresh_variables()
        # Navigate editor to the frame location
        if frame.source and os.path.isfile(frame.source):
            self._window.editor_view.open_file(frame.source, frame.line)

    # -- Variables --

    def _refresh_variables(self) -> None:
        """Refresh the variables tree from the current session."""
        self._var_tree.refresh(self._session)

    # -- Breakpoints list --

    def _refresh_breakpoints_list(self) -> None:
        """Refresh the breakpoints list display."""
        while True:
            row = self._bp_list.get_row_at_index(0)
            if row is None:
                break
            self._bp_list.remove(row)

        all_bps = self._breakpoint_mgr.get_all()
        for file_path, bps in sorted(all_bps.items()):
            for bp in sorted(bps, key=lambda b: b.line):
                row = Gtk.ListBoxRow()
                box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
                box.set_margin_start(4)
                box.set_margin_end(4)
                box.set_margin_top(1)
                box.set_margin_bottom(1)

                # Enable/disable checkbox
                check = Gtk.CheckButton()
                check.set_active(bp.enabled)
                check.connect("toggled", self._on_bp_toggled, bp)
                box.append(check)

                # File:line label
                basename = os.path.basename(file_path)
                label_text = f"{basename}:{bp.line}"
                if bp.condition:
                    label_text += f" ({bp.condition})"
                elif bp.log_message:
                    label_text += f" \u2139 {bp.log_message}"

                label = Gtk.Label(label=label_text)
                label.set_halign(Gtk.Align.START)
                label.set_hexpand(True)
                label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
                label.set_attributes(self._font_attrs)
                box.append(label)

                # Click to navigate
                gesture = Gtk.GestureClick()
                gesture.connect("pressed", self._on_bp_clicked, bp)
                row.add_controller(gesture)

                row.set_child(box)
                self._bp_list.append(row)

    def _on_bp_toggled(self, check_button, bp: Breakpoint) -> None:
        """Toggle breakpoint enabled state."""
        self._breakpoint_mgr.set_enabled(bp.file_path, bp.line, check_button.get_active())
        # Sync with adapter
        if self._session:
            self._session.sync_file_breakpoints(bp.file_path)

    def _on_bp_clicked(self, gesture, n_press, x, y, bp: Breakpoint) -> None:
        """Navigate to breakpoint location."""
        if n_press == 1 and os.path.isfile(bp.file_path):
            self._window.editor_view.open_file(bp.file_path, bp.line)

    def _on_breakpoints_changed(self, file_path: str, action: str) -> None:
        """Called when breakpoints change."""
        self._refresh_breakpoints_list()
        # Sync with adapter if session is active
        if self._session and file_path:
            self._session.sync_file_breakpoints(file_path)

    # -- Debug Console --

    def _on_evaluate(self, expression: str) -> str | None:
        """Evaluate an expression in the debug console."""
        if not self._session or self._session.state != SessionState.STOPPED:
            return "<not stopped>"
        return self._session.evaluate(expression)

    def append_output(self, text: str, category: str = "stdout") -> None:
        """Append output to the debug console."""
        self._console.append_output(text, category)

    # -- Session state callbacks --

    def on_session_state_changed(self, session: DebugSession) -> None:
        """Called when the debug session state changes."""
        self._update_toolbar_state()
        if session.state == SessionState.TERMINATED:
            self._clear_call_stack()
            self._var_tree.set_roots([])

    def on_session_stopped(self, session: DebugSession, thread_id: int, reason: str, file_path: str, line: int) -> None:
        """Called when execution stops (breakpoint hit, step completed)."""
        self._update_toolbar_state()

        # Update call stack
        frames = session.get_call_stack(thread_id)
        self.update_call_stack(frames)

        # Update variables
        self._refresh_variables()

        # Navigate to stopped location
        if file_path and os.path.isfile(file_path):
            self._window.editor_view.open_file(file_path, line)

    # -- Helpers --

    def _create_section_label(self, text: str) -> Gtk.Label:
        label = Gtk.Label(label=text)
        label.set_halign(Gtk.Align.START)
        label.set_margin_start(8)
        label.set_margin_top(4)
        label.set_margin_bottom(2)
        label.add_css_class("dim-label")
        label.set_attributes(self._font_attrs)
        return label

    # -- Panel show/hide (required by SplitPanelManager) --

    def show_panel(self) -> None:
        """Show the debug panel."""
        self.set_visible(True)

    def hide_panel(self) -> None:
        """Hide the debug panel."""
        self.set_visible(False)

    def cleanup(self) -> None:
        """Clean up resources."""
        self._breakpoint_mgr.unsubscribe(self._on_breakpoints_changed)
        if self._session:
            self._session.stop()
