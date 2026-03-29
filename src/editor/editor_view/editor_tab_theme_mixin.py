"""Theme/CSS integration for EditorTab."""

from gi.repository import GLib, Gtk, GtkSource

from shared.settings import get_setting
from shared.utils import hex_to_gdk_rgba
from themes import get_theme

from .core import _parse_hex_color
from .highlighting import _generate_style_scheme


class EditorTabThemeMixin:
    """Mixin providing theme application and diagnostic underline management for EditorTab."""

    # -- Diagnostic wavy underlines --

    def _setup_diagnostic_underline_tags(self):
        """Create text tags for diagnostics (background only; wave drawn in ZenSourceView)."""
        theme = get_theme()
        err_color = theme.term_red
        warn_color = theme.term_yellow

        self._diag_error_tag = self.buffer.create_tag(
            "diag_error_underline",
            background_rgba=hex_to_gdk_rgba(err_color, 0.12),
        )
        self._diag_warning_tag = self.buffer.create_tag(
            "diag_warning_underline",
            background_rgba=hex_to_gdk_rgba(warn_color, 0.12),
        )
        # Store wave colors on the view for custom wavy line drawing
        self.view._diag_error_wave_rgba = _parse_hex_color(err_color) + (1.0,)
        self.view._diag_warning_wave_rgba = _parse_hex_color(warn_color) + (1.0,)

    def _update_diagnostic_underline_colors(self, theme):
        """Update diagnostic underline colors when theme changes."""
        err_hex = theme.term_red
        warn_hex = theme.term_yellow
        if hasattr(self, "_diag_error_tag"):
            self._diag_error_tag.props.background_rgba = hex_to_gdk_rgba(err_hex, 0.12)
        if hasattr(self, "_diag_warning_tag"):
            self._diag_warning_tag.props.background_rgba = hex_to_gdk_rgba(warn_hex, 0.12)
        # Sync wave colors on the view
        self.view._diag_error_wave_rgba = _parse_hex_color(err_hex) + (1.0,)
        self.view._diag_warning_wave_rgba = _parse_hex_color(warn_hex) + (1.0,)

    def _clear_diagnostic_underlines(self):
        """Remove all diagnostic underline tags from the buffer."""
        # Use fresh iterators for each remove_tag call — GtkSourceBuffer's
        # internal re-highlighting may invalidate iterators after tag changes.
        self.buffer.remove_tag(self._diag_error_tag, self.buffer.get_start_iter(), self.buffer.get_end_iter())
        self.buffer.remove_tag(self._diag_warning_tag, self.buffer.get_start_iter(), self.buffer.get_end_iter())

    def _show_line_diagnostics_popover(self, line_1: int, click_x: int, click_y: int, line_height: int = 20):
        """Show a popover with diagnostics for the clicked gutter line."""
        from gi.repository import Gdk

        from shared.diagnostics_manager import SEVERITY_ERROR, get_diagnostics_manager
        from themes import get_theme

        all_diags = get_diagnostics_manager().get_diagnostics(self.file_path) if self.file_path else []
        diags = [d for d in all_diags if d.line <= line_1 <= (d.end_line if d.end_line > 0 else d.line)]
        if not diags:
            return

        # Dismiss any existing diagnostics popover
        if hasattr(self, "_diag_popover") and self._diag_popover:
            self._diag_popover.unparent()
            self._diag_popover = None

        from fonts import get_font_settings
        from icons import ICON_FONT_FAMILY, IconsManager

        theme = get_theme()
        err_color = theme.term_red
        warn_color = theme.term_yellow
        fg = theme.fg_color
        bg = theme.main_bg

        font_settings = get_font_settings("editor")
        font_family = font_settings["family"]
        font_size = font_settings.get("size", 16)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        content_box.set_margin_start(8)
        content_box.set_margin_end(8)
        content_box.set_margin_top(6)
        content_box.set_margin_bottom(6)

        for d in diags:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            color = err_color if d.severity == SEVERITY_ERROR else warn_color
            icon = IconsManager.ERROR_X if d.severity == SEVERITY_ERROR else IconsManager.WARNING
            icon_label = Gtk.Label()
            icon_label.set_use_markup(True)
            icon_label.set_markup(f'<span font_family="{ICON_FONT_FAMILY}" foreground="{color}">{icon}</span>')
            row.append(icon_label)

            code_part = f" <span foreground='{color}'>[{d.code}]</span>" if d.code else ""
            msg_label = Gtk.Label()
            msg_label.set_use_markup(True)
            msg_label.set_markup(f'<span foreground="{fg}">{GLib.markup_escape_text(d.message)}{code_part}</span>')
            msg_label.set_wrap(True)
            msg_label.set_max_width_chars(80)
            msg_label.set_halign(Gtk.Align.START)
            row.append(msg_label)
            content_box.append(row)

        popover = Gtk.Popover()
        popover.set_child(content_box)
        popover.set_parent(self.view)
        popover.set_autohide(False)
        popover.set_can_focus(False)
        popover.add_css_class("zen-diagnostics-popover")

        rect = Gdk.Rectangle()
        rect.x = click_x
        rect.y = click_y + line_height
        rect.width = 1
        rect.height = 1
        popover.set_pointing_to(rect)
        popover.set_position(Gtk.PositionType.BOTTOM)

        # Apply theme colors via inline CSS
        css = f"""
        popover.zen-diagnostics-popover > contents {{
            background-color: {bg};
            border: 1px solid {theme.accent_color};
            border-radius: 4px;
            font-family: '{font_family}';
            font-size: {font_size}pt;
        }}
        """
        provider = Gtk.CssProvider()
        provider.load_from_string(css)
        popover.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # Clean up on close
        def on_closed(_popover):
            _popover.unparent()
            if hasattr(self, "_diag_popover") and self._diag_popover is _popover:
                self._diag_popover = None
                if hasattr(self, "_diag_popover_key_handler"):
                    self.view.remove_controller(self._diag_popover_key_handler)
                    self._diag_popover_key_handler = None

        popover.connect("closed", on_closed)

        # Dismiss on any key press so the user can type immediately
        key_ctrl = Gtk.EventControllerKey()

        def on_key_pressed(_ctrl, _keyval, _keycode, _state):
            if hasattr(self, "_diag_popover") and self._diag_popover:
                self._diag_popover.popdown()
            return False  # propagate the key event to the editor

        key_ctrl.connect("key-pressed", on_key_pressed)
        self.view.add_controller(key_ctrl)
        self._diag_popover_key_handler = key_ctrl

        self._diag_popover = popover
        popover.popup()
        self.view.grab_focus()

    def _apply_theme(self):
        """Apply the current theme to the source view."""
        theme = get_theme()

        # Generate custom style scheme from theme's syntax colors
        scheme_id = _generate_style_scheme(theme)
        scheme_manager = GtkSource.StyleSchemeManager.get_default()
        scheme = scheme_manager.get_scheme(scheme_id)
        if scheme:
            self.buffer.set_style_scheme(scheme)

        # Apply background color via CSS (remove old provider to avoid accumulation)
        if hasattr(self, "_theme_css_provider"):
            self.view.get_style_context().remove_provider(self._theme_css_provider)
        css_provider = Gtk.CssProvider()
        self._theme_css_provider = css_provider
        css = f"""
            textview text {{
                background-color: {theme.main_bg};
                color: {theme.fg_color};
            }}
            textview.view {{
                background-color: {theme.main_bg};
            }}
        """
        css_provider.load_from_data(css.encode())
        self.view.get_style_context().add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)

        # Set indent guide color from theme (user settings can override)
        from constants import INDENT_GUIDE_ALPHA

        if hasattr(self.view, "set_guide_color_hex"):
            guide_color = get_setting("editor.indent_guide_color", "") or theme.indent_guide
            guide_alpha = get_setting("editor.indent_guide_alpha", -1)
            if guide_alpha < 0:
                guide_alpha = INDENT_GUIDE_ALPHA
            self.view.set_guide_color_hex(guide_color, alpha=guide_alpha)

        # Update semantic highlight tag colors
        from ..semantic_highlight import update_semantic_colors

        update_semantic_colors(self, theme)

        # Update diagnostic underline colors
        self._update_diagnostic_underline_colors(theme)

        # Update inline completion ghost text colors
        if getattr(self, "_inline_completion", None) is not None:
            self._inline_completion.update_theme()
