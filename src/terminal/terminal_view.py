"""
Terminal View for Zen IDE.
Uses VTE (Virtual Terminal Emulator) for a proper terminal.
"""

import os

from gi.repository import Gdk, Gtk, Pango, Vte

from shared.focus_manager import get_component_focus_manager
from shared.settings import get_setting
from shared.utils import sanitize_font_for_vte as _sanitize_font_for_vte
from terminal.terminal_file_navigation import (
    TerminalFileNavigationMixin,
)
from terminal.terminal_scroll import (
    configure_vte_scrolling,
    map_terminal_scroll_delta,
)
from terminal.terminal_shell import TerminalShellMixin
from terminal.terminal_shortcuts import TerminalShortcutsMixin
from themes import get_theme, subscribe_theme_change


class TerminalView(
    TerminalFileNavigationMixin,
    TerminalShellMixin,
    TerminalShortcutsMixin,
    Gtk.Box,
):
    """Terminal emulator view using VTE."""

    COMPONENT_ID = "terminal"

    def __init__(self, get_workspace_folders_callback=None, config_dir=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        self.cwd = os.getcwd()
        self._get_workspace_folders = get_workspace_folders_callback
        self.config_dir = config_dir or os.path.expanduser("~/.zen_ide")
        self._shutting_down = False

        # Callback for opening files from terminal (set by parent)
        self.on_open_file = None  # Signature: on_open_file(path: str, line: int | None)

        # Callbacks for terminal stack management (set by TerminalStack)
        self.on_add_terminal = None  # Called when + button is clicked
        self.on_close_terminal = None  # Called when × button is clicked
        self.on_directory_changed = None  # Called when cwd changes

        self._create_ui()

        # Subscribe to theme changes so terminal colors update immediately
        subscribe_theme_change(lambda _theme: self.apply_theme())

        # Add click controller to gain focus
        click_ctrl = Gtk.GestureClick.new()
        click_ctrl.connect("pressed", self._on_panel_click)
        self.add_controller(click_ctrl)

    def _create_ui(self):
        from terminal.terminal_header import TerminalHeader

        hdr = TerminalHeader(include_close=True)

        # Wire up signal handlers
        hdr.header_btn.connect("clicked", self._on_header_click)
        hdr.add_btn.connect("clicked", lambda b: self._on_add_clicked())
        hdr.clear_btn.connect("clicked", lambda b: self.clear())
        hdr.maximize_btn.connect("clicked", self._on_maximize_clicked)
        hdr.close_btn.connect("clicked", lambda b: self._on_close_clicked())

        # Expose widgets for external access (TerminalStack references these)
        self.header_btn = hdr.header_btn
        self._add_btn = hdr.add_btn
        self.maximize_btn = hdr.maximize_btn
        self._close_btn = hdr.close_btn

        self._header = hdr.box
        self.append(hdr.box)

        # Scrolled window for terminal
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_kinetic_scrolling(True)
        scrolled.add_css_class("terminal-scrolled")
        self._scrolled_window = scrolled

        self.terminal = Vte.Terminal()
        self._configure_terminal()
        scrolled.set_child(self.terminal)

        self.append(scrolled)

        self._is_maximized = False
        self.on_maximize = None  # Callback: on_maximize(panel_name)

    def _configure_terminal(self):
        """Configure terminal appearance and behavior (called once from _create_ui)."""
        # Apply theme-dependent settings (colors, font, etc.)
        self._apply_terminal_theme()

        # Disable audible bell to prevent startup "dong" sound
        self.terminal.set_audible_bell(False)

        # Disable VTE text rewrapping on resize.  When enabled, VTE
        # reflows all existing text to fit the new width, but readline's
        # SIGWINCH handler doesn't know about the reflow and redraws
        # with stale cursor-position assumptions — producing a garbled
        # prompt (e.g. trailing characters after "$ ").  With rewrap
        # disabled, existing text stays put and readline can redraw
        # correctly.  New output still wraps at the current width.
        self.terminal.set_rewrap_on_resize(False)

        configure_vte_scrolling(self.terminal)
        self._setup_scroll_controller()

        # Setup hyperlink-style regex matching for file paths (underlines them)
        self._setup_file_path_matching()

        # Setup keyboard shortcuts for copy/paste
        self._setup_terminal_shortcuts()

        # Connect child exit signal
        self.terminal.connect("child-exited", self._on_child_exited)

        # Track CWD via OSC 7 for accurate relative file path resolution
        self.terminal.connect("notify::current-directory-uri", self._on_cwd_uri_changed)

    def _apply_terminal_theme(self):
        """Apply theme colors and font settings (safe to call on theme changes)."""
        theme = get_theme()

        # Font - use settings or default
        self.apply_font_settings()

        # Colors
        fg = Gdk.RGBA()
        fg.parse(theme.fg_color)

        bg = Gdk.RGBA()
        bg.parse(theme.panel_bg)

        # ANSI palette
        palette = []
        ansi_colors = [
            theme.term_black,
            theme.term_red,
            theme.term_green,
            theme.term_yellow,
            theme.term_blue,
            theme.term_magenta,
            theme.term_cyan,
            theme.term_white,
            # Bright variants (slightly lighter)
            self._lighten(theme.term_black, 0.2),
            self._lighten(theme.term_red, 0.2),
            self._lighten(theme.term_green, 0.2),
            self._lighten(theme.term_yellow, 0.2),
            self._lighten(theme.term_blue, 0.2),
            self._lighten(theme.term_magenta, 0.2),
            self._lighten(theme.term_cyan, 0.2),
            self._lighten(theme.term_white, 0.2),
        ]

        for color in ansi_colors:
            rgba = Gdk.RGBA()
            rgba.parse(color)
            palette.append(rgba)

        self.terminal.set_colors(fg, bg, palette)

        # Other settings
        self.terminal.set_scrollback_lines(10000)
        self.terminal.set_scroll_on_output(False)
        self.terminal.set_scroll_on_keystroke(True)
        blink = get_setting("cursor_blink", True)
        self.terminal.set_cursor_blink_mode(Vte.CursorBlinkMode.ON if blink else Vte.CursorBlinkMode.OFF)
        wide = get_setting("wide_cursor", False)
        self.terminal.set_cursor_shape(Vte.CursorShape.BLOCK if wide else Vte.CursorShape.IBEAM)

    @staticmethod
    def _lighten(hex_color: str, amount: float) -> str:
        """Lighten a hex color by a given amount."""
        hex_color = hex_color.lstrip("#")
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)

        r = min(255, int(r + (255 - r) * amount))
        g = min(255, int(g + (255 - g) * amount))
        b = min(255, int(b + (255 - b) * amount))

        return f"#{r:02x}{g:02x}{b:02x}"

    def apply_font_settings(self):
        """Apply font settings from settings manager."""
        if not hasattr(self, "terminal"):
            return

        # Use fonts.terminal settings
        from fonts import get_font_settings

        font_settings = get_font_settings("terminal")
        font_family = font_settings["family"]
        font_size = font_settings.get("size", 12)

        # Sanitize font for VTE (convert Propo to Mono variants)
        font_family = _sanitize_font_for_vte(font_family)

        font_desc = Pango.FontDescription.from_string(f"{font_family} {font_size}")
        self.terminal.set_font(font_desc)

    def clear(self):
        """Clear the terminal screen and scrollback buffer, then redraw the prompt."""
        self.terminal.reset(False, True)
        self.terminal.feed_child(b"\x0c")

    def _on_maximize_clicked(self, button):
        """Delegate maximize to parent — state and CSS managed by window_panels."""
        if hasattr(self, "on_maximize") and self.on_maximize:
            self.on_maximize("terminal")

    def _on_add_clicked(self):
        """Handle click on + button to add a terminal pane."""
        if self.on_add_terminal:
            self.on_add_terminal()

    def _on_close_clicked(self):
        """Handle click on × button to close this terminal pane."""
        if self.on_close_terminal:
            self.on_close_terminal()

    def _on_cwd_uri_changed(self, terminal, pspec):
        """Update internal CWD when shell reports directory change via OSC 7."""
        uri = terminal.get_current_directory_uri()
        if not uri:
            return
        try:
            from urllib.parse import unquote, urlparse

            path = unquote(urlparse(uri).path)
            if path and os.path.isdir(path):
                self.cwd = path
        except Exception:
            pass

    def apply_theme(self):
        """Apply the current theme to the terminal."""
        self._apply_terminal_theme()

    def _on_header_click(self, button):
        """Handle click on terminal title - show workspace project picker."""
        self._show_project_picker()

    def _show_project_picker(self):
        """Show an nvim popup menu to select a workspace project and switch the terminal to it."""
        if not self._get_workspace_folders:
            return

        folders = self._get_workspace_folders()
        if not folders:
            return

        # Build menu items
        items = []
        for folder in folders:
            folder_name = os.path.basename(folder)
            is_current = os.path.abspath(folder) == os.path.abspath(self.cwd)
            items.append(
                {
                    "label": f"{'✓ ' if is_current else '  '}{folder_name}",
                    "action": folder,
                    "enabled": True,
                }
            )

        def on_select(action):
            self.change_directory(action)
            if self.on_directory_changed:
                self.on_directory_changed(action)

        # Get parent window
        parent = self.get_root()
        if parent:
            from popups.nvim_context_menu import show_context_menu

            show_context_menu(parent, items, on_select, title="Select terminal")

    def _on_panel_click(self, gesture, n_press, x, y):
        """Handle click on panel to gain focus."""
        # Deny the gesture so child buttons (e.g. +, ×) still receive clicks
        gesture.set_state(Gtk.EventSequenceState.DENIED)
        get_component_focus_manager().set_focus(self.COMPONENT_ID)

    def _setup_scroll_controller(self):
        """Install terminal scroll remapping to keep pixel-style wheel behavior."""
        # Smooth scroll animation state
        self._scroll_target: float | None = None
        self._scroll_tick_id: int = 0
        self._SCROLL_LERP = 0.3  # fraction of remaining distance per frame

        flags = Gtk.EventControllerScrollFlags.VERTICAL
        if hasattr(Gtk.EventControllerScrollFlags, "KINETIC"):
            flags |= Gtk.EventControllerScrollFlags.KINETIC

        controller = Gtk.EventControllerScroll.new(flags)
        if hasattr(controller, "set_propagation_phase") and hasattr(Gtk, "PropagationPhase"):
            controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        controller.connect("scroll", self._on_scroll)
        self.terminal.add_controller(controller)
        self._scroll_controller = controller

    def _get_wheel_step_pixels(self) -> float:
        """Return per-notch wheel movement in pixels (kept in line with app scroll speed)."""
        speed = float(get_setting("scroll_speed", 0.4))
        return max(1.0, 60.0 * speed)

    def _get_touchpad_step_pixels(self) -> float:
        """Return per-delta touchpad movement in pixels (match other scrollable views)."""
        speed = float(get_setting("scroll_speed", 0.4))
        return max(1.0, 12.0 * speed)

    def _on_scroll(self, controller, dx, dy):
        """Accumulate scroll deltas and animate smoothly toward target."""
        if not hasattr(self, "_scrolled_window"):
            return False
        vadj = self._scrolled_window.get_vadjustment()
        if vadj is None:
            return False

        # Compute scrollable range first — if there is nothing to scroll
        # (e.g. alternate-screen mode), let VTE / ScrolledWindow handle
        # the event so mouse-wheel forwarding to the CLI app still works.
        lower = float(vadj.get_lower())
        upper = float(vadj.get_upper())
        page_size = float(vadj.get_page_size())
        maximum = max(lower, upper - page_size)
        if maximum <= lower:
            return False

        consume, delta = map_terminal_scroll_delta(
            controller,
            dy,
            wheel_step_pixels=self._get_wheel_step_pixels(),
            touchpad_step_pixels=self._get_touchpad_step_pixels(),
            gdk_module=Gdk,
        )
        if not consume or delta == 0.0:
            return False

        # Accumulate into scroll target
        if self._scroll_target is None:
            self._scroll_target = float(vadj.get_value())
        self._scroll_target = min(max(self._scroll_target + delta, lower), maximum)

        # Start animation tick if not running
        if not self._scroll_tick_id:
            self._scroll_tick_id = self._scrolled_window.add_tick_callback(self._smooth_scroll_tick)
        return True

    def _smooth_scroll_tick(self, widget, frame_clock):
        """Frame-clock tick: lerp scroll position toward target each frame."""
        vadj = self._scrolled_window.get_vadjustment()
        if vadj is None or self._scroll_target is None:
            self._scroll_tick_id = 0
            return False

        current = float(vadj.get_value())
        diff = self._scroll_target - current

        if abs(diff) < 0.5:
            vadj.set_value(self._scroll_target)
            self._scroll_target = None
            self._scroll_tick_id = 0
            return False

        vadj.set_value(current + diff * self._SCROLL_LERP)
        return True
