"""Window layout mixin — main IDE layout, theme, focus tracking, file drop."""

from gi.repository import Gdk, Gtk

from main.layout_css_mixin import LayoutCssMixin
from main.layout_dnd_mixin import LayoutDndMixin


class WindowLayoutMixin(LayoutCssMixin, LayoutDndMixin):
    """Mixin: layout creation, theme application, focus tracking, file drop."""

    def _apply_startup_theme(self):
        """Apply minimal critical-path CSS for first paint.

        Only includes rules for widgets visible at startup: window, sidebar,
        editor, terminal placeholder, paned separators, headerbar, notebook
        tabs, and accent colours.  Full CSS is applied later via _apply_theme()
        in _deferred_init_panels.
        """
        from fonts import get_font_settings
        from themes import get_theme

        font_settings = get_font_settings("editor")
        font_family = font_settings["family"]
        font_size = font_settings.get("size", 13)
        theme = get_theme()

        from constants import TAB_BUTTON_HEIGHT

        tab_btn_height = TAB_BUTTON_HEIGHT

        # Defer GTK dark/light preference to _apply_theme (called in
        # _deferred_init_panels) to keep _on_window_mapped fast. Our CSS
        # handles all visible colours, so no flash occurs.
        self._last_dark_pref = None  # Will be set in _apply_theme

        if hasattr(self, "_theme_css_provider"):
            Gtk.StyleContext.remove_provider_for_display(
                Gdk.Display.get_default(),
                self._theme_css_provider,
            )
        css_provider = Gtk.CssProvider()
        self._theme_css_provider = css_provider
        css = f"""
            window {{
                background-color: {theme.main_bg};
                color: {theme.fg_color};
                font-family: '{font_family}';
                font-size: {font_size}pt;
            }}
            window:backdrop {{
                background-color: {theme.main_bg};
                color: {theme.fg_color};
            }}
            .sidebar {{
                background-color: {theme.panel_bg};
            }}
            .sidebar:backdrop {{
                background-color: {theme.panel_bg};
            }}
            .editor {{
                background-color: {theme.main_bg};
            }}
            .editor:backdrop {{
                background-color: {theme.main_bg};
            }}
            .terminal {{
                background-color: {theme.panel_bg};
            }}
            .terminal:backdrop {{
                background-color: {theme.panel_bg};
            }}
            paned > separator {{
                background-color: {theme.sash_color};
                min-width: 4px;
                min-height: 4px;
            }}
            paned > separator:backdrop {{
                background-color: {theme.sash_color};
            }}
            headerbar {{
                background-color: {theme.panel_bg};
                color: {theme.fg_color};
            }}
            headerbar:backdrop {{
                background-color: {theme.panel_bg};
                color: {theme.fg_color};
            }}
            notebook {{
                background-color: {theme.tab_bg};
            }}
            notebook:backdrop {{
                background-color: {theme.tab_bg};
            }}
            notebook > stack {{
                background-color: {theme.main_bg};
            }}
            notebook > stack:backdrop {{
                background-color: {theme.main_bg};
            }}
            notebook > header {{
                background-color: {theme.tab_bg};
                border-bottom: none;
            }}
            notebook > header:backdrop {{
                background-color: {theme.tab_bg};
                border-bottom: none;
            }}
            notebook > header > tabs {{
                background-color: {theme.tab_bg};
                min-height: 0;
                padding: 0;
                margin: 0;
            }}
            notebook > header > tabs > tab {{
                background-color: transparent;
                color: inherit;
                padding: 0;
                min-height: {tab_btn_height}px;
                margin: 0;
                border: none;
                border-bottom: none;
                box-shadow: none;
                outline: none;
                font-family: '{font_family}';
                font-size: {font_size}pt;
            }}
            notebook > header > tabs > tab:checked {{
                background-color: transparent;
                color: inherit;
                border-bottom-color: transparent;
                outline: none;
                outline-color: transparent;
            }}
            notebook > header > tabs > tab:hover {{
                background-color: transparent;
            }}
            @define-color accent_color {theme.accent_color};
            @define-color accent_bg_color {theme.accent_color};
            @define-color accent_fg_color {theme.fg_color};
            @define-color theme_selected_bg_color {theme.selection_bg};
            @define-color theme_selected_fg_color {theme.fg_color};
            @define-color theme_unfocused_selected_bg_color {theme.selection_bg};
            selection {{
                background-color: {theme.selection_bg};
            }}
            @define-color focus_border_color {theme.accent_color};
            {self._nerd_font_css(font_family)}
        """
        css_provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_USER,
        )

    def _create_layout(self):
        """Create the main IDE layout.

        Layout:
        +------------------+--------------------------------+
        |                  |            Editor              |
        |     TreeView     +--------------------------------+
        |                  |   AI Chat    |    Terminal     |
        +------------------+--------------------------------+

        A lightweight stub titlebar is used here instead of a full HeaderBar
        to avoid the ~13ms HeaderBar realization cost during present->map.
        The real HeaderBar is swapped in during _on_window_mapped (Phase 2),
        where the swap costs only ~2ms on an already-realized window.
        """
        from constants import (
            DEFAULT_BOTTOM_PANEL_MIN_HEIGHT,
            DEFAULT_EDITOR_SPLIT,
            DEFAULT_TREE_MIN_WIDTH,
            DEFAULT_TREE_WIDTH,
        )

        # Main vertical box for app content
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(main_box)

        # Read saved layout positions (use immediately to avoid visible jumps).
        # Reuse layout preloaded in ZenIDEWindow.__init__ to avoid duplicate
        # settings lookup on the startup critical path.
        layout = getattr(self, "_startup_layout", None)
        if layout is None:
            from shared.settings import get_layout

            layout = get_layout()
        saved_main = layout.get("main_splitter", DEFAULT_TREE_WIDTH)
        saved_right = layout.get("right_splitter", DEFAULT_EDITOR_SPLIT)
        saved_bottom = layout.get("bottom_splitter", 0)

        # Sanity check saved values
        win_w = layout.get("window_width", 1200)
        win_h = layout.get("window_height", 800)
        if saved_main < 50 or saved_main > win_w - 100:
            saved_main = DEFAULT_TREE_WIDTH
        if saved_right < 150 or saved_right > win_h - 100:
            saved_right = DEFAULT_EDITOR_SPLIT

        # Store for re-application after child swaps
        self._saved_layout = {
            "main": saved_main,
            "right": saved_right,
            "bottom": saved_bottom,
        }

        # Main horizontal paned: [TreeView | Right Panel]
        self.main_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.main_paned.set_shrink_start_child(True)  # Allow tree to shrink to 0 for fullscreen maximize
        self.main_paned.set_shrink_end_child(False)
        main_box.append(self.main_paned)

        # Left: TreeView placeholder (real TreeView created in _deferred_init for faster first paint)
        self.tree_view = Gtk.Box()
        self.tree_view.set_size_request(DEFAULT_TREE_MIN_WIDTH, -1)
        self.main_paned.set_start_child(self.tree_view)

        # Right: Vertical paned [Editor | Bottom Panel]
        self.right_paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        self.right_paned.set_shrink_start_child(True)
        self.right_paned.set_shrink_end_child(True)
        self.main_paned.set_end_child(self.right_paned)

        # Top right: Editor placeholder placed directly under right_paned for now.
        # The editor_split_paned wrapper (for diff/split view) is created lazily
        # in _on_window_mapped to reduce the pre-paint widget count (~2ms savings).
        self.editor_view = Gtk.Box()
        self.right_paned.set_start_child(self.editor_view)
        self.editor_split_paned = None

        # Lazy panel backing fields (created on first access via properties)
        self._diff_view = None
        self._system_monitor = None
        self._dev_pad = None
        self._debug_panel = None

        # Split panel manager is initialized when the real EditorView is created
        # in _deferred_init_editor to keep pre-map startup work minimal.
        self.split_panels = None

        # Bottom: single placeholder box — the real Paned with AI Chat + Terminal
        # is created in _create_bottom_panels after first paint to reduce the
        # pre-map widget count (saves 2 widget realizations).
        self.bottom_paned = Gtk.Box()
        self.bottom_paned.set_size_request(-1, DEFAULT_BOTTOM_PANEL_MIN_HEIGHT)
        self.right_paned.set_end_child(self.bottom_paned)

        # Placeholders for AI chat and terminal (set here so attribute access
        # works before _create_bottom_panels; not added to widget tree).
        self.ai_chat = None
        self.terminal_view = None

        # Set paned positions AFTER all children are added (adding children can reset positions)
        self.main_paned.set_position(saved_main)
        self.right_paned.set_position(saved_right)

        # Lock positions during init to prevent GTK resetting them during child swaps.
        # Unlocked in _deferred_init after all real children are in place.
        # Only lock main and right paneds — bottom_paned is a placeholder Box
        # until _create_bottom_panels and doesn't need locking.
        self._locked_position_handlers = []
        for paned, pos in [
            (self.main_paned, saved_main),
            (self.right_paned, saved_right),
        ]:
            if pos > 0:
                self._locked_position_handlers.append((paned, self._lock_paned_position(paned, pos)))

        # Status bar placeholder deferred — the real StatusBar is created in
        # _deferred_init_panels. No placeholder needed since main_box only
        # contains the main_paned at first paint.
        self._main_box = main_box
        self.status_bar_widget = None

        # Lightweight stub titlebar — avoids the ~13ms Gtk.HeaderBar realization
        # cost during present->map. The real HeaderBar is swapped in after the
        # first paint in _on_window_mapped, where the swap costs only ~2ms because
        # the window already has a titlebar (no re-realize needed).
        stub = Gtk.Box()
        stub.set_size_request(-1, 1)
        self.set_titlebar(stub)
        self._header = None
        self._header_title = None

    def _ensure_header_bar(self):
        """Create HeaderBar lazily when post-paint startup initializes menus."""
        if self._header is not None:
            return self._header

        header = Gtk.HeaderBar()
        self.set_titlebar(header)
        self._header = header
        return header

    def _init_split_panels(self):
        """Initialize split panel manager once a real EditorView exists."""
        if self.split_panels is not None:
            return

        from editor.split_panel_manager import SplitPanelManager

        self.split_panels = SplitPanelManager(self.editor_split_paned, self.editor_view)
        self.split_panels.register("diff", None, self._show_diff_panel, self._hide_diff_panel)
        self.split_panels.register(
            "system_monitor",
            None,
            lambda: self._show_end_child_panel(self.system_monitor),
            lambda: self._hide_end_child_panel(self.system_monitor),
        )
        self.split_panels.register(
            "debug",
            None,
            lambda: self._show_end_child_panel(self.debug_panel),
            lambda: self._hide_end_child_panel(self.debug_panel),
        )

    def _lock_paned_position(self, paned, position):
        """Lock a paned at a specific position during initialization.

        Returns the signal handler ID (disconnect to unlock).
        """
        adjusting = [False]

        def on_position_changed(p, pspec):
            if adjusting[0]:
                return
            if p.get_position() != position:
                adjusting[0] = True
                p.set_position(position)
                adjusting[0] = False

        return paned.connect("notify::position", on_position_changed)

    def _setup_focus_tracking(self):
        """Add focus controllers to track which panel is focused (for maximize).

        This uses the FocusManager to coordinate focus between panels.
        When a panel's widget gains GTK focus, it notifies the focus manager.
        """
        from shared.focus_manager import get_focus_manager

        focus_mgr = get_focus_manager()

        # Helper to create a focus controller that updates both _focused_panel and FocusManager
        def add_focus_tracker(widget, panel_name, component_id):
            focus_ctrl = Gtk.EventControllerFocus()

            def on_focus_enter(c):
                self._focused_panel = panel_name
                focus_mgr.set_focus(component_id)

            focus_ctrl.connect("enter", on_focus_enter)
            widget.add_controller(focus_ctrl)

        # Tree view focus - track on the drawing area (the focusable element)
        if hasattr(self.tree_view, "tree") and hasattr(self.tree_view.tree, "drawing_area"):
            add_focus_tracker(self.tree_view.tree.drawing_area, "tree", "treeview")

        # Editor focus - track on the notebook (when tabs switch, editors get focus)
        # Guarded: editor_view may be a placeholder during first paint
        if hasattr(self.editor_view, "notebook"):
            add_focus_tracker(self.editor_view.notebook, "editor", "editor")

        # Terminal focus - track on the actual VTE terminal widget
        if hasattr(self.terminal_view, "terminal"):
            add_focus_tracker(self.terminal_view.terminal, "terminal", "terminal")

        # AI terminal focus - the VTE widget handles its own focus via click controller
