"""Terminal Stack — manages multiple terminal panes (vertical stack or tabbed)."""

import os

from gi.repository import Gtk

from constants import (
    TERMINAL_TAB_BAR_MARGIN_BOTTOM,
)
from shared.focus_border_mixin import FocusBorderMixin
from shared.focus_manager import get_component_focus_manager
from shared.gtk_event_utils import is_button_click, is_click_inside_widget
from shared.settings import get_setting


class TerminalStack(FocusBorderMixin, Gtk.Box):
    """Container that holds one or more TerminalView instances.

    Supports two layout modes controlled by ``behavior.terminals_on_vertical_stack``:

    * **Vertical stack** (default, ``True``): all terminals are stacked vertically
      and visible simultaneously – each pane has its own header with +/× buttons.
    * **Tab bar** (``False``): a horizontal scrollable tab bar sits at the top and
      a ``Gtk.Stack`` shows only the active terminal.  Individual terminal headers
      hide their +/× buttons; those actions live on the tab bar instead.

    Proxies the TerminalView API so callers can treat it as a drop-in replacement.
    """

    COMPONENT_ID = "terminal"

    def __init__(self, get_workspace_folders_callback=None, config_dir=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._get_workspace_folders = get_workspace_folders_callback
        self._config_dir = config_dir
        self._terminals = []
        self._tab_buttons = []
        self._active_idx = 0
        self._shutting_down = False
        self._next_terminal_number = 1

        # Read layout mode from settings
        self._vertical_mode = get_setting("behavior.terminals_on_vertical_stack", True)

        # Callbacks set by parent (forwarded to child terminals)
        self.on_open_file = None
        self.on_maximize = None
        self._maximized_terminal = None  # Track which terminal is maximized in vertical mode

        # Focus border on the outer container (TerminalStack)
        self._init_focus_border()
        focus_mgr = get_component_focus_manager()
        focus_mgr.register(
            self.COMPONENT_ID,
            on_focus_in=self._on_focus_in,
            on_focus_out=self._on_focus_out,
        )

        # In vertical mode, add click controller (CAPTURE phase) to detect
        # which terminal pane was clicked and move focus border to it.
        if self._vertical_mode:
            click_ctrl = Gtk.GestureClick.new()
            click_ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            click_ctrl.connect("pressed", self._on_panel_click)
            self.add_controller(click_ctrl)

        # Build tab-mode UI chrome (hidden in vertical mode)
        if not self._vertical_mode:
            self._build_tab_bar()

        # Container that holds terminals
        if self._vertical_mode:
            # Vertical mode: terminals are direct children of self
            self._content_container = self
        else:
            # Tab mode: terminals live in a Gtk.Stack
            self._content_stack = Gtk.Stack()
            self._content_stack.set_transition_type(Gtk.StackTransitionType.NONE)
            self._content_stack.set_vexpand(True)
            self._content_stack.set_hexpand(True)
            self.append(self._content_stack)

        # Create first terminal (skip focus registration — TerminalStack owns it)
        self._add_terminal(register_focus=False)

    # ── Tab bar (tab mode only) ───────────────────────────────────────

    def _build_tab_bar(self):
        """Create header row and tab bar for tab mode (matches AI chat layout)."""
        from terminal.terminal_header import TerminalHeader

        hdr = TerminalHeader(include_close=False)
        hdr.add_btn.set_tooltip_text("New terminal tab")

        # Wire up signal handlers
        hdr.header_btn.connect("clicked", self._on_header_click)
        hdr.add_btn.connect("clicked", lambda b: self._on_add_request())
        hdr.clear_btn.connect("clicked", lambda b: self.clear())
        hdr.maximize_btn.connect("clicked", self._on_stack_maximize_clicked)

        # Expose widgets for external access
        self._terminal_header = hdr
        self._header_box = hdr.box
        self._header_btn = hdr.header_btn
        self._stack_add_btn = hdr.add_btn
        self._stack_clear_btn = hdr.clear_btn
        self._stack_maximize_btn = hdr.maximize_btn

        self.append(hdr.box)

        # Tab bar row: [◀] [scrollable tabs] [▶]
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

    def _add_tab_button(self, index, title):
        """Add a tab button for a terminal at *index*."""
        from terminal.terminal_tab_button import TerminalTabButton

        btn = TerminalTabButton(
            index=index,
            title=title,
            on_select=self._switch_to_tab,
            on_close=self._close_tab,
            show_close=len(self._terminals) > 1,
        )
        self._tab_buttons.append(btn)
        self._tab_bar.append(btn)

    def _rebuild_tab_indices(self):
        """Re-index tab buttons after a removal."""
        for i, btn in enumerate(self._tab_buttons):
            btn.index = i

    def _switch_to_tab(self, index):
        """Switch the visible terminal in tab mode."""
        if index < 0 or index >= len(self._terminals):
            return
        self._active_idx = index
        self._content_stack.set_visible_child_name(f"term_{id(self._terminals[index])}")
        self._update_tab_selection()
        self._scroll_tab_into_view(index)
        self._update_header_title()
        # Focus the terminal
        self._terminals[index].grab_focus()

    def _close_tab(self, index):
        """Close a terminal tab."""
        if index < 0 or index >= len(self._terminals):
            return
        self._remove_terminal(self._terminals[index])

    def _update_tab_selection(self):
        """Highlight only the active tab."""
        for i, btn in enumerate(self._tab_buttons):
            btn.set_selected(i == self._active_idx)

    def _update_tab_close_buttons(self):
        """Show close buttons only when there are multiple tabs."""
        show = len(self._tab_buttons) > 1
        for btn in self._tab_buttons:
            btn.set_show_close(show)

    def _scroll_tab_bar(self, direction: int) -> None:
        """Scroll the tab bar left (-1) or right (+1) by one tab width."""
        hadj = self._tab_bar_scroll.get_hadjustment()
        if not hadj:
            return
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
        offset = 0
        for i in range(index):
            offset += self._tab_buttons[i].get_width() + 4
        btn_w = btn.get_width()
        cur = hadj.get_value()
        page = hadj.get_page_size()
        if offset < cur:
            hadj.set_value(offset)
        elif offset + btn_w > cur + page:
            hadj.set_value(offset + btn_w - page)

    def _update_tab_bar_visibility(self) -> None:
        """Show the tab bar row only when there are multiple tabs."""
        self._tab_bar_row.set_visible(len(self._terminals) > 1)

    def _update_header_title(self):
        """Update the header label to show the active terminal's folder name."""
        if not self._vertical_mode and hasattr(self, "_header_btn"):
            self._header_btn.set_label("Terminal")

    def _update_active_tab_title(self):
        """Update the active tab button's title to match its terminal's cwd."""
        if 0 <= self._active_idx < len(self._tab_buttons):
            t = self._active
            if t:
                self._tab_buttons[self._active_idx].set_title(os.path.basename(t.get_cwd()))

    # ── Stack management ──────────────────────────────────────────────

    def _add_terminal(self, register_focus=False):
        """Create and append a new TerminalView."""
        from terminal.terminal_view import TerminalView

        tv = TerminalView(
            get_workspace_folders_callback=self._get_workspace_folders,
            config_dir=self._config_dir,
        )
        tv.set_vexpand(True)

        # Forward callbacks through the stack (read at call time so late-binding works)
        tv.on_open_file = lambda path, line=None: self.on_open_file(path, line) if self.on_open_file else None
        tv.on_maximize = lambda name, _tv=tv: self._on_pane_maximize(name, _tv)
        tv.on_add_terminal = self._on_add_request
        tv.on_close_terminal = lambda _tv=tv: self._remove_terminal(_tv)
        tv.on_directory_changed = lambda path: self._on_terminal_dir_changed()

        # Track focus changes so _active_idx stays current
        if hasattr(tv, "terminal") and tv.terminal:
            focus_ctrl = Gtk.EventControllerFocus()
            focus_ctrl.connect(
                "enter",
                lambda c, _tv=tv: self._on_child_focus(_tv),
            )
            tv.terminal.add_controller(focus_ctrl)

        self._next_terminal_number += 1

        self._terminals.append(tv)

        if self._vertical_mode:
            self.append(tv)
            self._update_close_buttons()
        else:
            # Tab mode: hide per-terminal header (buttons are in TerminalStack header)
            tv._header.set_visible(False)

            stack_name = f"term_{id(tv)}"
            self._content_stack.add_named(tv, stack_name)
            tab_title = os.path.basename(tv.cwd)
            self._add_tab_button(len(self._terminals) - 1, tab_title)
            self._update_tab_close_buttons()
            self._update_tab_bar_visibility()

        self._active_idx = len(self._terminals) - 1

        if not self._vertical_mode:
            self._content_stack.set_visible_child_name(f"term_{id(tv)}")
            self._update_tab_selection()

        return tv

    def _on_add_request(self):
        """Handle + button press: add a new terminal pane and spawn its shell."""
        prev_cwd = self._active.get_cwd() if self._active else None
        tv = self._add_terminal(register_focus=False)
        if prev_cwd:
            tv.change_directory(prev_cwd)
            idx = len(self._terminals) - 1
            if idx < len(self._tab_buttons):
                self._tab_buttons[idx].set_title(os.path.basename(prev_cwd))
        tv.spawn_shell()

    def _remove_terminal(self, tv):
        """Remove a terminal pane."""
        if len(self._terminals) <= 1:
            return
        # Reset maximize state if the closed terminal was maximized
        if self._maximized_terminal == tv:
            self._maximized_terminal = None
            for t in self._terminals:
                t.set_visible(True)
        idx = self._terminals.index(tv)
        tv.cleanup()

        if self._vertical_mode:
            self.remove(tv)
        else:
            self._content_stack.remove(tv)
            # Remove the corresponding tab button
            tab_btn = self._tab_buttons.pop(idx)
            self._tab_bar.remove(tab_btn)
            self._rebuild_tab_indices()

        self._terminals.remove(tv)
        if self._active_idx >= len(self._terminals):
            self._active_idx = len(self._terminals) - 1

        if self._vertical_mode:
            self._update_close_buttons()
        else:
            self._update_tab_close_buttons()
            self._update_tab_bar_visibility()
            self._content_stack.set_visible_child_name(f"term_{id(self._terminals[self._active_idx])}")
            self._update_tab_selection()

    def _update_close_buttons(self):
        """Show × close buttons only when there are multiple terminals (vertical mode)."""
        show = len(self._terminals) > 1
        for tv in self._terminals:
            tv._close_btn.set_visible(show)

    def _on_child_focus(self, tv):
        """Track which terminal pane is active."""
        try:
            idx = self._terminals.index(tv)
            self._active_idx = idx
            if self._vertical_mode:
                self._update_vertical_focus_border()
            else:
                self._update_tab_selection()
        except ValueError:
            pass
        get_component_focus_manager().set_focus(self.COMPONENT_ID)

    def _on_panel_click(self, gesture, n_press, x, y):
        """Handle click on panel to detect which terminal was clicked (vertical mode)."""
        # Deny IMMEDIATELY so the CAPTURE gesture cannot interfere with child
        # widget event delivery (buttons must receive the full press→release
        # sequence unimpeded).
        gesture.set_state(Gtk.EventSequenceState.DENIED)

        picked_widget = self.pick(x, y, Gtk.PickFlags.DEFAULT)
        if is_button_click(picked_widget):
            return
        fm = get_component_focus_manager()
        fm.set_focus(self.COMPONENT_ID)

        if self._vertical_mode:
            widget = gesture.get_widget()
            for i, tv in enumerate(self._terminals):
                if is_click_inside_widget(widget, x, y, tv):
                    if i != self._active_idx:
                        self._active_idx = i
                        self._update_vertical_focus_border()
                    break

    def _on_focus_in(self):
        """Called when this panel gains focus."""
        if self._vertical_mode:
            self._update_vertical_focus_border()
        else:
            self._set_focused(True)

    def _on_focus_out(self):
        """Called when this panel loses focus."""
        if self._vertical_mode:
            self._clear_vertical_focus_border()
        else:
            self._set_focused(False)

    def _update_vertical_focus_border(self):
        """In vertical mode, apply focus border to the active terminal only."""
        maximized_tv = getattr(self, "_maximized_terminal", None)
        for i, tv in enumerate(self._terminals):
            tv.remove_css_class(self.FOCUS_CSS_CLASS)
            tv.add_css_class(self.UNFOCUS_CSS_CLASS)
            # Sync maximize button "selected" CSS to follow maximized terminal
            if maximized_tv and tv == maximized_tv:
                tv.maximize_btn.add_css_class("selected")
            elif not maximized_tv:
                tv.maximize_btn.remove_css_class("selected")
        if 0 <= self._active_idx < len(self._terminals):
            tv = self._terminals[self._active_idx]
            tv.remove_css_class(self.UNFOCUS_CSS_CLASS)
            tv.add_css_class(self.FOCUS_CSS_CLASS)

    def _clear_vertical_focus_border(self):
        """In vertical mode, remove focus border from all terminals."""
        for tv in self._terminals:
            tv.remove_css_class(self.FOCUS_CSS_CLASS)
            tv.add_css_class(self.UNFOCUS_CSS_CLASS)

    # ── Header actions (tab mode) ─────────────────────────────────────

    def _on_header_click(self, button):
        """Handle click on TERMINAL title — show workspace project picker."""
        t = self._active
        if t:
            t._show_project_picker()

    def _on_terminal_dir_changed(self):
        """Update header and tab titles when a terminal changes directory."""
        self._update_header_title()
        if not self._vertical_mode:
            self._update_active_tab_title()

    def _on_stack_maximize_clicked(self, button):
        """Delegate maximize to parent — state and CSS managed by window_panels."""
        if self.on_maximize:
            self.on_maximize("terminal")

    def _on_pane_maximize(self, panel_name, terminal=None):
        """Handle maximize button click from a terminal pane.

        In vertical mode, maximizes a single terminal within the stack.
        In tab mode, delegates to parent maximize.
        """
        if self._vertical_mode and terminal is not None:
            if self._maximized_terminal == terminal:
                # Restore: show all terminals
                self._maximized_terminal = None
                for tv in self._terminals:
                    tv.set_visible(True)
                    if tv != terminal:
                        tv._is_maximized = False
                        tv.maximize_btn.remove_css_class("selected")
                        tv.maximize_btn.set_tooltip_text("Maximize")
            else:
                # Maximize: hide other terminals, show only the clicked one
                self._maximized_terminal = terminal
                for tv in self._terminals:
                    if tv == terminal:
                        tv.set_visible(True)
                    else:
                        tv.set_visible(False)
                        tv._is_maximized = False
                        tv.maximize_btn.remove_css_class("selected")
                        tv.maximize_btn.set_tooltip_text("Maximize")

            # Also trigger parent maximize to expand the overall terminal panel
            if self.on_maximize:
                self.on_maximize(panel_name)
        else:
            # Tab mode: just delegate to parent
            if self.on_maximize:
                self.on_maximize(panel_name)

    # ── Active terminal helper ────────────────────────────────────────

    @property
    def _active(self):
        if self._terminals:
            return self._terminals[min(self._active_idx, len(self._terminals) - 1)]
        return None

    # ── Proxied properties ────────────────────────────────────────────

    @property
    def terminal(self):
        """VTE widget of the active terminal."""
        t = self._active
        return t.terminal if t else None

    @property
    def cwd(self):
        t = self._active
        return t.cwd if t else os.getcwd()

    @cwd.setter
    def cwd(self, value):
        t = self._active
        if t:
            t.cwd = value

    @property
    def maximize_btn(self):
        """Maximize button (stack-level in tab mode, active terminal in vertical mode)."""
        if not self._vertical_mode and hasattr(self, "_stack_maximize_btn"):
            return self._stack_maximize_btn
        t = self._active
        return t.maximize_btn if t else None

    @property
    def _is_maximized(self):
        t = self._active
        return t._is_maximized if t else False

    @_is_maximized.setter
    def _is_maximized(self, value):
        maximized_tv = getattr(self, "_maximized_terminal", None)
        for tv in self._terminals:
            if self._vertical_mode:
                # In vertical mode, only the maximized terminal gets the selected state
                if maximized_tv and tv == maximized_tv and value:
                    tv._is_maximized = True
                    tv.maximize_btn.add_css_class("selected")
                    tv.maximize_btn.set_tooltip_text("Restore")
                else:
                    tv._is_maximized = False
                    tv.maximize_btn.remove_css_class("selected")
                    tv.maximize_btn.set_tooltip_text("Maximize")
            else:
                tv._is_maximized = value
                if value:
                    tv.maximize_btn.add_css_class("selected")
                    tv.maximize_btn.set_tooltip_text("Restore")
                else:
                    tv.maximize_btn.remove_css_class("selected")
                    tv.maximize_btn.set_tooltip_text("Maximize")
        if not self._vertical_mode and hasattr(self, "_stack_maximize_btn"):
            if value:
                self._stack_maximize_btn.add_css_class("selected")
                self._stack_maximize_btn.set_tooltip_text("Restore")
            else:
                self._stack_maximize_btn.remove_css_class("selected")
                self._stack_maximize_btn.set_tooltip_text("Maximize")

    # ── Proxied methods (active terminal) ─────────────────────────────

    def clear(self):
        t = self._active
        if t:
            t.clear()

    def spawn_shell(self):
        t = self._active
        if t:
            t.spawn_shell()

    def change_directory(self, path):
        t = self._active
        if t:
            t.change_directory(path)
            self._update_header_title()
            if not self._vertical_mode:
                self._update_active_tab_title()

    def get_cwd(self):
        t = self._active
        return t.get_cwd() if t else os.getcwd()

    def grab_focus(self):
        t = self._active
        if t:
            t.terminal.grab_focus()

    # ── Proxied methods (all terminals) ───────────────────────────────

    def apply_font_settings(self):
        for tv in self._terminals:
            tv.apply_font_settings()
        if not self._vertical_mode:
            for btn in self._tab_buttons:
                btn.apply_font_settings()
            self._terminal_header.apply_header_font()

    def apply_theme(self):
        for tv in self._terminals:
            tv.apply_theme()
        if not self._vertical_mode:
            for btn in self._tab_buttons:
                btn.apply_theme(btn.theme)

    def cleanup(self):
        self._shutting_down = True
        for tv in self._terminals:
            tv.cleanup()
