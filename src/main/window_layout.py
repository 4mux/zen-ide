"""Window layout mixin — main IDE layout, theme, focus tracking, file drop."""

import os

from gi.repository import Gdk, Gtk


class WindowLayoutMixin:
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
                background-color: {theme.editor_bg};
            }}
            .editor:backdrop {{
                background-color: {theme.editor_bg};
            }}
            .terminal {{
                background-color: {theme.terminal_bg};
            }}
            .terminal:backdrop {{
                background-color: {theme.terminal_bg};
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
                background-color: {theme.editor_bg};
            }}
            notebook > stack:backdrop {{
                background-color: {theme.editor_bg};
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

    def _apply_theme(self, font_family=None, font_size=None):
        """Apply the current theme colors.

        Args:
            font_family: Optional font family override. When None, imports fonts module.
            font_size: Optional font size override. When None, imports fonts module.
        """
        from themes import get_theme

        if font_family is None:
            from fonts import get_font_settings

            font_settings = get_font_settings("editor")
            font_family = font_settings["family"]
            font_size = font_settings.get("size", 13)

        # Terminal font for header/tab styling
        from fonts import get_font_settings as _get_font_settings

        term_font_settings = _get_font_settings("terminal")
        term_font_family = term_font_settings["family"]

        theme = get_theme()

        from constants import PANEL_HEADER_FONT_SIZE, TAB_BUTTON_HEIGHT

        tab_btn_height = TAB_BUTTON_HEIGHT

        # Only update GTK dark/light preference when it actually changes.
        # set_property("gtk-application-prefer-dark-theme") triggers a full
        # GTK style cascade (~9ms) even when setting the same value.
        # On startup, zen_ide.py already set the correct value, so the first
        # _apply_theme call (from _deferred_init_panels) skips this entirely.
        last_dark = getattr(self, "_last_dark_pref", None)
        if last_dark is None or last_dark != theme.is_dark:
            settings = Gtk.Settings.get_default()
            if settings:
                settings.set_property("gtk-application-prefer-dark-theme", theme.is_dark)
        self._last_dark_pref = theme.is_dark

        # Remove old CSS provider before adding new one to avoid style conflicts
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
                background-color: {theme.editor_bg};
            }}
            .editor:backdrop {{
                background-color: {theme.editor_bg};
            }}
            .terminal {{
                background-color: {theme.terminal_bg};
            }}
            .terminal:backdrop {{
                background-color: {theme.terminal_bg};
            }}
            .terminal-scrolled {{
                padding-left: 8px;
                padding-right: 8px;
            }}
            paned > separator {{
                background-color: {theme.sash_color};
                min-width: 4px;
                min-height: 4px;
            }}
            paned > separator:backdrop {{
                background-color: {theme.sash_color};
            }}
            .editor-collapsed > separator {{
                min-height: 0;
            }}
            headerbar {{
                background-color: {theme.panel_bg};
                color: {theme.fg_color};
            }}
            headerbar:backdrop {{
                background-color: {theme.panel_bg};
                color: {theme.fg_color};
            }}
            headerbar windowcontrols button {{
                min-width: 36px;
                min-height: 36px;
                padding: 4px;
                margin: 0 2px;
            }}
            headerbar windowcontrols button image {{
                -gtk-icon-size: 16px;
            }}
            headerbar button.flat {{
                min-width: 32px;
                min-height: 32px;
            }}
            headerbar .zen-title {{
                font-family: '{font_family}';
                font-size: 14pt;
                font-weight: normal;
            }}
            popover, popover > contents {{
                background-color: {theme.panel_bg};
                color: {theme.fg_color};
            }}
            popover modelbutton, popover label {{
                color: {theme.fg_color};
            }}
            /* Notebook tab styling - override Adwaita defaults */
            notebook {{
                background-color: {theme.tab_bg};
            }}
            notebook:backdrop {{
                background-color: {theme.tab_bg};
            }}
            notebook > stack {{
                background-color: {theme.editor_bg};
            }}
            notebook > stack:backdrop {{
                background-color: {theme.editor_bg};
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
            /* Override Adwaita's @accent_color and @accent_bg_color */
            @define-color accent_color {theme.accent_color};
            @define-color accent_bg_color {theme.accent_color};
            @define-color accent_fg_color {theme.fg_color};
            /* Override text selection colors globally */
            @define-color theme_selected_bg_color {theme.selection_bg};
            @define-color theme_selected_fg_color {theme.fg_color};
            @define-color theme_unfocused_selected_bg_color {theme.selection_bg};
            /* Explicit selection CSS for GtkTextView and GtkEntry */
            selection {{
                background-color: {theme.selection_bg};
            }}
            /* Focus ring colors */
            @define-color focus_border_color {theme.accent_color};
            /* Terminal header button - underlined and clickable */
            .terminal-header-btn,
            .terminal-header-btn label {{
                color: {theme.fg_color};
                font-family: '{term_font_family}';
                font-size: {PANEL_HEADER_FONT_SIZE}pt;
                font-weight: 500;
                text-decoration: underline;
                padding: 4px 8px;
                min-height: 0;
            }}
            .terminal-header-btn:hover {{
                color: {theme.accent_color};
            }}
            /* Disable scroll overshoot/edge glow effect */
            overshoot {{
                background: none;
                border: none;
                box-shadow: none;
            }}
            overshoot.top, overshoot.bottom, overshoot.left, overshoot.right {{
                background: none;
                border: none;
                box-shadow: none;
            }}
            undershoot {{
                background: none;
            }}
            /* Scrollbar styling */
            scrollbar slider {{
                background-color: alpha({theme.fg_color}, 0.25);
                border-radius: 9999px;
                min-width: 6px;
                min-height: 6px;
            }}
            scrollbar slider:hover {{
                background-color: alpha({theme.fg_color}, 0.4);
            }}
            .terminal-scrollbar,
            .terminal-scrollbar trough {{
                background-color: transparent;
                background-image: none;
                border: none;
                box-shadow: none;
            }}
            /* ── Global button theming ── */
            /* Flat button hover/active/focus */
            button.flat:hover {{
                background-color: {theme.hover_bg};
                color: {theme.fg_color};
            }}
            button.flat:active {{
                background-color: alpha({theme.accent_color}, 0.35);
            }}
            button.flat:checked {{
                background-color: alpha({theme.accent_color}, 0.25);
                color: {theme.accent_color};
            }}
            /* Selected state for toggle buttons (e.g. maximize) */
            button.flat.selected {{
                background-color: alpha({theme.accent_color}, 0.25);
                color: {theme.accent_color};
            }}
            /* Non-flat (raised) buttons */
            button:not(.flat):hover {{
                background-color: {theme.hover_bg};
            }}
            button:not(.flat):active {{
                background-color: alpha({theme.accent_color}, 0.35);
            }}
            button:not(.flat):checked {{
                background-color: alpha({theme.accent_color}, 0.3);
                color: {theme.accent_color};
            }}
            /* Focus ring override */
            button:focus, button:focus-visible {{
                outline-color: {theme.accent_color};
            }}
            /* suggested-action (Save, OK, primary) */
            button.suggested-action {{
                background-color: {theme.accent_color};
                color: {theme.main_bg};
            }}
            button.suggested-action:hover {{
                background-color: alpha({theme.accent_color}, 0.85);
                color: {theme.main_bg};
            }}
            button.suggested-action:active {{
                background-color: alpha({theme.accent_color}, 0.7);
            }}
            /* destructive-action (Delete, Discard, Stop) */
            button.destructive-action {{
                background-color: {theme.git_deleted};
                color: white;
            }}
            button.destructive-action:hover {{
                background-color: alpha({theme.git_deleted}, 0.85);
                color: white;
            }}
            button.destructive-action:active {{
                background-color: alpha({theme.git_deleted}, 0.7);
            }}
            /* CheckButton / ToggleButton indicator */
            checkbutton indicator {{
                border-color: {theme.border_color};
            }}
            checkbutton indicator:checked {{
                background-color: {theme.accent_color};
                border-color: {theme.accent_color};
                color: {theme.main_bg};
            }}
            checkbutton:hover indicator {{
                border-color: {theme.accent_color};
            }}
            /* SpinButton */
            spinbutton {{
                background-color: {theme.main_bg};
                color: {theme.fg_color};
                border-color: {theme.border_color};
            }}
            spinbutton:focus-within {{
                border-color: {theme.accent_color};
            }}
            spinbutton button {{
                color: {theme.fg_color};
            }}
            spinbutton button:hover {{
                background-color: {theme.hover_bg};
            }}
            /* DropDown */
            dropdown {{
                background-color: {theme.main_bg};
                color: {theme.fg_color};
            }}
            dropdown:hover {{
                background-color: {theme.hover_bg};
            }}
            dropdown button {{
                color: {theme.fg_color};
            }}
            /* Switch widget */
            switch {{
                background-color: alpha({theme.fg_dim}, 0.3);
            }}
            switch:checked {{
                background-color: {theme.accent_color};
            }}
            /* Popover menu item selection */
            popover modelbutton:hover {{
                background-color: {theme.hover_bg};
            }}
            popover modelbutton:focus {{
                background-color: {theme.selection_bg};
            }}
            /* SearchBar (Cmd+F find bar) */
            searchbar {{
                background-color: {theme.panel_bg};
                border-bottom: 1px solid {theme.border_color};
            }}
            searchbar entry, searchbar searchentry {{
                background-color: {theme.main_bg};
                color: {theme.fg_color};
                border: 1px solid {theme.border_color};
                border-radius: 4px;
                outline: none;
                outline-color: transparent;
            }}
            searchbar entry:focus-within, searchbar searchentry:focus-within {{
                border-color: {theme.accent_color};
                outline: none;
                outline-color: transparent;
            }}
            searchbar entry > text, searchbar searchentry > text {{
                background: transparent;
                border: none;
                outline: none;
            }}
            searchbar button {{
                outline: none;
                outline-color: transparent;
            }}
            searchbar button:focus {{
                outline: none;
                outline-color: transparent;
            }}
            /* Focus border CSS for panels */
            .panel-unfocused {{
                border: 2px solid {theme.border_color};
                transition: border-color 150ms ease-in-out;
            }}
            .panel-focused {{
                border: 2px solid {theme.border_focus};
                transition: border-color 150ms ease-in-out;
            }}
            /* Nerd Font fallback for button/label icons */
            {self._nerd_font_css(font_family)}
        """
        css_provider.load_from_data(css.encode())

        # Use USER priority (800) to override Adwaita's APPLICATION (600) level styling
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_USER,
        )

    def _nerd_font_css(self, font_family: str) -> str:
        """Return CSS rules for icon font rendering in buttons/labels.

        Uses *font_family* (the user's configured font) as fallback so that
        non-icon text inside buttons still renders in the custom font.
        """
        from icons import get_icon_font_name

        icon_font = get_icon_font_name()
        return f"""
            button label, menubutton label {{
                font-family: "{icon_font}", '{font_family}';
                font-size: 1.15em;
            }}
            .zen-icon {{
                font-family: "{icon_font}", '{font_family}';
            }}
        """

    def _create_layout(self):
        """Create the main IDE layout.

        Layout:
        +------------------+--------------------------------+
        |                  |            Editor              |
        |     TreeView     +--------------------------------+
        |                  |   AI Chat    |    Terminal     |
        +------------------+--------------------------------+

        A lightweight stub titlebar is used here instead of a full HeaderBar
        to avoid the ~13ms HeaderBar realization cost during present→map.
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
        # cost during present→map. The real HeaderBar is swapped in after the
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

        This uses the ComponentFocusManager to coordinate focus between panels.
        When a panel's widget gains GTK focus, it notifies the focus manager.
        """
        from shared.focus_manager import get_component_focus_manager

        focus_mgr = get_component_focus_manager()

        # Helper to create a focus controller that updates both _focused_panel and ComponentFocusManager
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

    def _setup_file_drop_target(self, widget):
        """Set up drag-and-drop target to open external files dragged into the IDE."""
        drop_target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop_target.set_propagation_phase(Gtk.PropagationPhase.BUBBLE)
        drop_target.connect("drop", self._on_file_drop)
        widget.add_controller(drop_target)

    def _on_file_drop(self, drop_target, value, x, y):
        """Handle files/folders dropped from external file managers."""
        from shared.git_ignore_utils import collect_global_patterns
        from shared.settings import set_setting

        if not isinstance(value, Gdk.FileList):
            return False
        files = value.get_files()
        opened = False
        for gfile in files:
            path = gfile.get_path()
            if not path:
                continue
            path = os.path.abspath(path)
            if os.path.isdir(path):
                # Dropped a folder — open it as workspace
                collect_global_patterns([path])
                self.tree_view.load_workspace([path])
                self.set_title(f"Zen IDE — {os.path.basename(path)}")
                set_setting("workspace.workspace_file", "")
                set_setting("workspace.folders", [path])
                self._show_all_panels()
                opened = True
            elif path.endswith((".zen-workspace", ".code-workspace")) and os.path.isfile(path):
                # Dropped a workspace file — load it
                self._load_workspace_file(path)
                opened = True
            elif os.path.isfile(path):
                self.editor_view.open_file(path)
                opened = True
        return opened
