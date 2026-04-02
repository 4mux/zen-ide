"""Shared visual configuration for ZenSourceView instances.

Used by both the main editor and the diff view to ensure consistent
font, spacing, whitespace, style scheme, and scroll behavior.
"""

from gi.repository import Gtk, GtkSource, Pango

from fonts import CSS_WEIGHT_MAP, PANGO_WEIGHT_MAP, get_font_settings
from shared.settings import get_setting
from themes import get_theme


def configure_source_view_appearance(view, scrolled=None):
    """Apply editor visual settings (font, spacing, wrap, whitespace, theme, scroll).

    Parameters
    ----------
    view : ZenSourceView
        The source view to configure.
    scrolled : Gtk.ScrolledWindow | None
        If provided and ``editor.scroll_past_end`` is enabled, sets a dynamic
        bottom margin so the user can scroll past the last line.
    """
    theme = get_theme()

    # -- Style scheme --------------------------------------------------------
    from editor.editor_view import _generate_style_scheme

    scheme_id = _generate_style_scheme(theme)
    scheme = GtkSource.StyleSchemeManager.get_default().get_scheme(scheme_id)
    if scheme:
        view.get_buffer().set_style_scheme(scheme)

    # -- Indent guide color --------------------------------------------------
    from constants import INDENT_GUIDE_ALPHA

    if hasattr(view, "set_guide_color_hex"):
        view.set_guide_color_hex(theme.indent_guide, alpha=INDENT_GUIDE_ALPHA)

    # -- Font ----------------------------------------------------------------
    font_settings = get_font_settings("editor")
    font_family = font_settings["family"]
    font_size = font_settings.get("size", 13)
    font_weight = font_settings.get("weight", "normal")
    css_weight = CSS_WEIGHT_MAP.get(font_weight, 400)
    letter_spacing = get_setting("editor.letter_spacing", 0)
    letter_spacing_css = f"letter-spacing: {letter_spacing}px;" if letter_spacing else ""

    css_provider = Gtk.CssProvider()
    css = f"""
        textview, textview text {{
            font-family: '{font_family}', monospace;
            font-size: {font_size}pt;
            font-weight: {css_weight};
            {letter_spacing_css}
        }}
    """
    css_provider.load_from_data(css.encode())
    view.get_style_context().add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)

    # Apply font weight via Pango once realized
    def _on_realize(v):
        pango_weight = PANGO_WEIGHT_MAP.get(font_weight, Pango.Weight.NORMAL)
        ctx = v.get_pango_context()
        desc = ctx.get_font_description().copy()
        desc.set_weight(pango_weight)
        ctx.set_font_description(desc)
        _apply_ligatures(v)

    view.connect("realize", _on_realize)

    # -- Line spacing --------------------------------------------------------
    line_spacing = get_setting("editor.line_spacing", 4)
    above = line_spacing // 2
    below = line_spacing - above
    view.set_pixels_above_lines(above)
    view.set_pixels_below_lines(below)

    # -- Whitespace drawing --------------------------------------------------
    space_drawer = view.get_space_drawer()
    if get_setting("editor.show_whitespace", False):
        space_drawer.set_types_for_locations(
            GtkSource.SpaceLocationFlags.LEADING,
            GtkSource.SpaceTypeFlags.SPACE | GtkSource.SpaceTypeFlags.TAB,
        )
        space_drawer.set_types_for_locations(
            GtkSource.SpaceLocationFlags.TRAILING,
            GtkSource.SpaceTypeFlags.NONE,
        )
        space_drawer.set_types_for_locations(
            GtkSource.SpaceLocationFlags.INSIDE_TEXT,
            GtkSource.SpaceTypeFlags.NONE,
        )
        space_drawer.set_enable_matrix(True)
    else:
        space_drawer.set_enable_matrix(False)

    # -- Word wrap -----------------------------------------------------------
    if get_setting("editor.word_wrap", False):
        view.set_wrap_mode(Gtk.WrapMode.WORD)
    else:
        view.set_wrap_mode(Gtk.WrapMode.NONE)

    # -- Scroll past end -----------------------------------------------------
    if scrolled and get_setting("editor.scroll_past_end", True):

        def _update_scroll_past_end(*_args):
            h = scrolled.get_height()
            if h > 0:
                view.set_bottom_margin(max(h // 2, 200))

        vadj = scrolled.get_vadjustment()
        vadj.connect("notify::page-size", _update_scroll_past_end)

    return css_provider


def _apply_ligatures(view):
    """Apply font ligature settings via Pango font features."""
    ligatures_enabled = get_setting("editor.font_ligatures", True)
    features = '"liga" 1, "calt" 1' if ligatures_enabled else '"liga" 0, "calt" 0'
    attr_list = Pango.AttrList()
    attr_list.insert(Pango.attr_font_features_new(features))
    ctx = view.get_pango_context()
    ctx.set_font_description(ctx.get_font_description())
    view._ligature_attr_list = attr_list
