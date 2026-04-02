"""Editor settings (tab width, wrap mode, font, etc.) for EditorTab."""

import os

from gi.repository import Gtk, Pango

from constants import DEFAULT_INDENT_WIDTH, EDITOR_LEFT_PADDING, LANG_INDENT_WIDTH
from shared.settings import get_setting


class EditorTabConfigMixin:
    """Mixin providing view configuration and font settings for EditorTab."""

    def _configure_view(self):
        """Configure the source view settings."""
        from editor.source_view_config import configure_source_view_appearance

        view = self.view

        # Batch property changes to avoid per-setter layout invalidation
        view.freeze_notify()
        # Line numbers are drawn by FoldManager's LineNumberFoldRenderer
        view.set_show_line_numbers(False)
        view.set_highlight_current_line(True)
        view.set_auto_indent(True)
        view.set_indent_on_tab(True)
        view.set_tab_width(DEFAULT_INDENT_WIDTH)
        view.set_insert_spaces_instead_of_tabs(True)
        view.set_smart_backspace(True)
        view.set_monospace(True)
        view.set_left_margin(EDITOR_LEFT_PADDING)
        view.set_indent_width(DEFAULT_INDENT_WIDTH)
        view.thaw_notify()

        # Bracket matching
        self.buffer.set_highlight_matching_brackets(True)

        # Apply shared visual settings (font, spacing, whitespace, wrap, theme)
        self.font_css_provider = configure_source_view_appearance(view)

        # Only show native caret when wide_cursor is off — ZenSourceView
        # hides it when drawing its own block cursor.
        if not getattr(view, "_wide_cursor", False):
            view.set_cursor_visible(True)

        # Auto-close brackets & smart indent — must run in CAPTURE phase
        # so we intercept Enter *before* GtkSourceView inserts a newline.
        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect("key-pressed", self._on_key_pressed)
        view.add_controller(key_controller)

        # Click handler: Cmd+Click nav, double-click word, triple-click line
        click_controller = Gtk.GestureClick()
        click_controller.set_button(1)  # Left mouse button
        click_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click_controller.connect("pressed", self._on_click_pressed)
        view.add_controller(click_controller)

        # Right-click: nvim-style context menu (suppress default GtkSourceView menu)
        view.set_extra_menu(None)
        right_click = Gtk.GestureClick()
        right_click.set_button(3)
        right_click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        right_click.connect("pressed", self._on_right_click)
        view.add_controller(right_click)

        # Store reference for navigation callback
        self._cmd_click_callback = None

        # Cmd+hover underline for navigable symbols
        self._setup_hover_underline()

    def apply_font_settings(self):
        """Apply font settings from config."""
        from fonts import get_font_settings

        font_settings = get_font_settings("editor")
        font_family = font_settings["family"]
        font_size = font_settings.get("size", 13)
        font_weight = font_settings.get("weight", "normal")

        css_weight = self._css_font_weight(font_weight)
        letter_spacing = get_setting("editor.letter_spacing", 0)
        letter_spacing_css = f"letter-spacing: {letter_spacing}px;" if letter_spacing else ""
        css = f"""
            textview, textview text {{
                font-family: '{font_family}', monospace;
                font-size: {font_size}pt;
                font-weight: {css_weight};
                {letter_spacing_css}
            }}
        """
        self.font_css_provider.load_from_data(css.encode())

        # Apply font weight via Pango (update stored value for realize handler too)
        self._pending_font_weight = font_weight
        if self.view.get_realized():
            self._apply_pango_font_weight(self.view, font_weight)
            self._apply_ligatures(self.view)

        # Update line spacing
        line_spacing = get_setting("editor.line_spacing", 4)
        above = line_spacing // 2
        below = line_spacing - above
        self.view.set_pixels_above_lines(above)
        self.view.set_pixels_below_lines(below)

    def _on_view_realize_font_weight(self, view):
        """Apply deferred font weight and ligatures once the view is realized."""
        weight = getattr(self, "_pending_font_weight", "normal")
        self._apply_pango_font_weight(view, weight)
        self._apply_ligatures(view)

    # GTK4 CSS only accepts numeric font-weight (100-900) or normal/bold.
    # Use the centralized CSS_WEIGHT_MAP from font_manager.
    @staticmethod
    def _css_font_weight(weight_str: str) -> int:
        """Convert a weight name to a CSS-valid numeric font-weight."""
        from fonts import CSS_WEIGHT_MAP

        return CSS_WEIGHT_MAP.get(weight_str, 400)

    @staticmethod
    def _apply_pango_font_weight(view, weight_str: str):
        """Set font weight on the view's Pango context.

        CSS font-weight alone doesn't reach GtkSourceView's text rendering
        pipeline — Pango font description must be set directly.
        Must be called after the view is realized so the Pango context is final.
        """
        from fonts import PANGO_WEIGHT_MAP

        pango_weight = PANGO_WEIGHT_MAP.get(weight_str, Pango.Weight.NORMAL)
        ctx = view.get_pango_context()
        desc = ctx.get_font_description().copy()
        desc.set_weight(pango_weight)
        ctx.set_font_description(desc)
        view.queue_draw()

    @staticmethod
    def _apply_ligatures(view):
        """Apply font ligature settings via Pango font features.

        When ligatures are enabled, OpenType features 'liga' and 'calt' render
        combined glyphs for sequences like ==, =>, !=, etc.
        Must be called after the view is realized.
        """
        ligatures_enabled = get_setting("editor.font_ligatures", True)
        features = '"liga" 1, "calt" 1' if ligatures_enabled else '"liga" 0, "calt" 0'

        attr_list = Pango.AttrList()
        attr_list.insert(Pango.attr_font_features_new(features))
        ctx = view.get_pango_context()
        ctx.set_font_description(ctx.get_font_description())
        view._ligature_attr_list = attr_list

    def _set_language_from_file(self, file_path: str):
        """Set the source language and per-language indent width based on file."""
        from editor.langs.language_detect import detect_language

        language = detect_language(file_path)
        if language:
            self.buffer.set_language(language)

        # Apply per-language indent width and tab mode
        from constants import TAB_ONLY_LANGS

        ext = os.path.splitext(file_path)[1].lower()
        lang_id = language.get_id() if language else None
        use_tabs = lang_id in TAB_ONLY_LANGS
        indent = LANG_INDENT_WIDTH.get(lang_id) or LANG_INDENT_WIDTH.get(ext) or DEFAULT_INDENT_WIDTH

        # Auto-detect indent width from file content when available
        if not use_tabs:
            text = self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), True)
            if text.strip():
                from editor.indent_guide_levels import detect_indent_width

                indent = detect_indent_width(text, indent)

        self.view.set_tab_width(indent)
        self.view.set_indent_width(indent)
        self.view.set_insert_spaces_instead_of_tabs(not use_tabs)
