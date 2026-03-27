"""Debug Panel — bottom panel UI for debugging.

Shows debug toolbar, call stack, variables tree, breakpoints list,
and debug console. Registered via SplitPanelManager.
"""

import os

from gi.repository import GLib, Gtk, Pango

from themes import get_theme

from .breakpoint_manager import Breakpoint, get_breakpoint_manager
from .debug_console import DebugConsole
from .debug_session import DebugSession, SessionState


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

        # -- Toolbar --
        self._toolbar = self._create_toolbar()
        self.append(self._toolbar)

        # -- Main content: left (call stack + breakpoints) | right (variables + console) --
        content_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        content_paned.set_vexpand(True)
        content_paned.set_shrink_start_child(False)
        content_paned.set_shrink_end_child(False)
        self.append(content_paned)

        # Left side: call stack + breakpoints
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left_box.set_size_request(200, -1)
        content_paned.set_start_child(left_box)

        # Call stack section
        left_box.append(self._create_section_label("CALL STACK"))
        stack_scroll = Gtk.ScrolledWindow()
        stack_scroll.set_vexpand(True)
        stack_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        left_box.append(stack_scroll)

        self._stack_list = Gtk.ListBox()
        self._stack_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._stack_list.connect("row-activated", self._on_stack_frame_activated)
        self._stack_list.add_css_class("debug-stack-list")
        stack_scroll.set_child(self._stack_list)

        # Breakpoints section
        left_box.append(self._create_section_label("BREAKPOINTS"))
        bp_scroll = Gtk.ScrolledWindow()
        bp_scroll.set_vexpand(True)
        bp_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        left_box.append(bp_scroll)

        self._bp_list = Gtk.ListBox()
        self._bp_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._bp_list.add_css_class("debug-bp-list")
        bp_scroll.set_child(self._bp_list)

        # Right side: variables + console
        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right_box.set_size_request(200, -1)
        content_paned.set_end_child(right_box)

        # Variables section
        right_box.append(self._create_section_label("VARIABLES"))
        var_scroll = Gtk.ScrolledWindow()
        var_scroll.set_vexpand(True)
        var_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        right_box.append(var_scroll)

        self._var_tree = Gtk.TreeView()
        self._var_tree.set_headers_visible(True)
        self._var_tree.add_css_class("debug-var-tree")

        # Columns: Name, Value, Type
        name_col = Gtk.TreeViewColumn("Name", Gtk.CellRendererText(), text=0)
        name_col.set_resizable(True)
        name_col.set_min_width(80)
        self._var_tree.append_column(name_col)

        value_col = Gtk.TreeViewColumn("Value", Gtk.CellRendererText(), text=1)
        value_col.set_resizable(True)
        value_col.set_min_width(100)
        self._var_tree.append_column(value_col)

        type_col = Gtk.TreeViewColumn("Type", Gtk.CellRendererText(), text=2)
        type_col.set_resizable(True)
        self._var_tree.append_column(type_col)

        # TreeStore: name, value, type, variables_reference (hidden)
        self._var_store = Gtk.TreeStore(str, str, str, int)
        self._var_tree.set_model(self._var_store)
        self._var_tree.connect("row-expanded", self._on_variable_expanded)
        var_scroll.set_child(self._var_tree)

        # Debug console section
        right_box.append(self._create_section_label("DEBUG CONSOLE"))
        self._console = DebugConsole(on_evaluate=self._on_evaluate)
        self._console.set_vexpand(True)
        right_box.append(self._console)

        # Set initial paned position
        GLib.idle_add(lambda: content_paned.set_position(250) or False)

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
            ("Continue", "media-playback-start-symbolic", self._on_continue),
            ("Step Over", "go-next-symbolic", self._on_step_over),
            ("Step In", "go-down-symbolic", self._on_step_in),
            ("Step Out", "go-up-symbolic", self._on_step_out),
            ("Restart", "view-refresh-symbolic", self._on_restart),
            ("Stop", "process-stop-symbolic", self._on_stop),
        ]

        self._toolbar_buttons = {}
        for label, icon, callback in buttons:
            btn = Gtk.Button()
            btn.set_icon_name(icon)
            btn.set_tooltip_text(label)
            btn.connect("clicked", callback)
            btn.add_css_class("flat")
            btn.add_css_class("debug-toolbar-btn")
            toolbar.append(btn)
            self._toolbar_buttons[label] = btn

        # Status label
        self._status_label = Gtk.Label(label="Not debugging")
        self._status_label.set_hexpand(True)
        self._status_label.set_halign(Gtk.Align.END)
        self._status_label.add_css_class("debug-status")
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
            self._session.restart()

    def _on_stop(self, btn):
        if self._session:
            self._session.stop()

    # -- Call Stack --

    def update_call_stack(self, frames: list) -> None:
        """Update the call stack display."""
        # Remove all existing rows
        while True:
            row = self._stack_list.get_row_at_index(0)
            if row is None:
                break
            self._stack_list.remove(row)

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
            box.append(name_label)

            # File:line
            basename = os.path.basename(frame.source) if frame.source else ""
            loc_label = Gtk.Label(label=f"{basename}:{frame.line}")
            loc_label.add_css_class("dim-label")
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
        self._var_store.clear()
        if not self._session or self._session.state != SessionState.STOPPED:
            return

        scopes = self._session.get_scopes()
        for scope in scopes:
            scope_iter = self._var_store.append(None, [scope.name, "", "", scope.variables_reference])
            # Load variables for non-expensive scopes
            if not scope.expensive and scope.variables_reference:
                variables = self._session.get_variables(scope.variables_reference)
                for var in variables:
                    var_iter = self._var_store.append(scope_iter, [var.name, var.value, var.type, var.variables_reference])
                    # Add placeholder for expandable variables
                    if var.variables_reference > 0:
                        self._var_store.append(var_iter, ["...", "", "", 0])

    def _on_variable_expanded(self, tree_view, tree_iter, tree_path) -> None:
        """Lazy-load child variables when a tree node is expanded."""
        if not self._session:
            return
        ref = self._var_store.get_value(tree_iter, 3)
        if ref <= 0:
            return

        # Check if first child is placeholder
        child = self._var_store.iter_children(tree_iter)
        if child and self._var_store.get_value(child, 0) == "...":
            # Remove placeholder
            self._var_store.remove(child)
            # Load real children
            variables = self._session.get_variables(ref)
            for var in variables:
                var_iter = self._var_store.append(tree_iter, [var.name, var.value, var.type, var.variables_reference])
                if var.variables_reference > 0:
                    self._var_store.append(var_iter, ["...", "", "", 0])

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
            self._status_label.set_text("Terminated")

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

        # Update status
        reason_text = {
            "breakpoint": "Breakpoint hit",
            "step": "Step completed",
            "exception": "Exception",
            "pause": "Paused",
        }.get(reason, reason)
        basename = os.path.basename(file_path) if file_path else ""
        self._status_label.set_text(f"{reason_text} — {basename}:{line}")

    # -- Helpers --

    @staticmethod
    def _create_section_label(text: str) -> Gtk.Label:
        label = Gtk.Label(label=text)
        label.set_halign(Gtk.Align.START)
        label.set_margin_start(8)
        label.set_margin_top(4)
        label.set_margin_bottom(2)
        label.add_css_class("dim-label")
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
