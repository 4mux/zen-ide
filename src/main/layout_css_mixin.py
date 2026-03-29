"""Layout CSS generation mixin — full theme CSS for the IDE window."""

from gi.repository import Gdk, Gtk


class LayoutCssMixin:
    """Mixin: CSS generation and theme application for the IDE window."""

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
        # On startup, zen_ide_window.py already set the correct value, so the first
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
                background-color: {theme.main_bg};
            }}
            notebook > stack:backdrop {{
                background-color: {theme.main_bg};
            }}
            notebook > header {{
                background-color: {theme.tab_bg};
                border: none;
                box-shadow: none;
            }}
            notebook > header:backdrop {{
                background-color: {theme.tab_bg};
                border: none;
                box-shadow: none;
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
            notebook > header > box {{
                background-color: {theme.tab_bg};
                padding: 0;
                margin: 0;
            }}
            notebook > header button {{
                background: transparent;
                border: none;
                box-shadow: none;
                outline: none;
            }}
            notebook > header button:hover {{
                background: transparent;
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
            /* ── Debug panel ── */
            .debug-panel {{
                background-color: {theme.panel_bg};
                color: {theme.fg_color};
                font-family: '{font_family}';
                font-size: 9pt;
            }}
            .debug-toolbar {{
                background-color: {theme.panel_bg};
                border-bottom: 1px solid {theme.border_color};
            }}
            .debug-toolbar-btn {{
                color: {theme.fg_color};
            }}
            .debug-status {{
                color: {theme.fg_dim};
                font-size: 9pt;
            }}
            /* Call stack */
            .debug-stack-list {{
                background-color: {theme.panel_bg};
                color: {theme.fg_color};
                font-family: '{font_family}';
                font-size: 9pt;
            }}
            .debug-stack-list row {{
                background-color: transparent;
                color: {theme.fg_color};
                padding: 2px 4px;
            }}
            .debug-stack-list row:selected {{
                background-color: {theme.selection_bg};
            }}
            .debug-stack-list row:hover {{
                background-color: {theme.hover_bg};
            }}
            .debug-stack-list .dim-label {{
                color: {theme.fg_dim};
            }}
            .debug-panel .dim-label {{
                color: {theme.fg_dim};
                font-family: '{font_family}';
                font-size: 9pt;
            }}
            /* Breakpoints list */
            .debug-bp-list {{
                background-color: {theme.panel_bg};
                color: {theme.fg_color};
                font-family: '{font_family}';
                font-size: 9pt;
            }}
            .debug-bp-list row {{
                background-color: transparent;
                color: {theme.fg_color};
                padding: 1px 4px;
            }}
            .debug-bp-list row:hover {{
                background-color: {theme.hover_bg};
            }}
            /* Debug console */
            .debug-console-output {{
                background-color: {theme.panel_bg};
                color: {theme.fg_color};
                font-family: '{font_family}';
                font-size: 9pt;
            }}
            .debug-console-output text {{
                background-color: {theme.panel_bg};
                color: {theme.fg_color};
            }}
            .debug-console-prompt {{
                color: {theme.accent_color};
                font-family: '{font_family}';
                font-size: 9pt;
            }}
            .debug-console-input {{
                background-color: {theme.main_bg};
                color: {theme.fg_color};
                border: 1px solid {theme.border_color};
                border-radius: 4px;
                font-family: '{font_family}';
                font-size: 9pt;
            }}
            .debug-console-input:focus-within {{
                border-color: {theme.accent_color};
            }}
            .debug-console-input > text {{
                background: transparent;
                color: {theme.fg_color};
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
