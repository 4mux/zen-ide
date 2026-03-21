"""
Neovim-style Popup Base Class for Zen IDE.

All floating popups in Zen IDE MUST inherit from NvimPopup to maintain
consistent styling, keyboard handling, and behavior. No exceptions.

Features:
- Centered floating windows with borders (default)
- Anchored positioning relative to any widget via anchor_widget + anchor_rect
- Non-modal, non-focus-stealing mode for inline popups (e.g. autocomplete)
- Vim-style navigation (j/k, Enter to confirm, Escape to close)
- Clean minimal design with theme integration
- Keyboard-centric interaction
"""

import sys

from gi.repository import Gdk, Graphene, Gsk, Gtk

from fonts import get_font_settings
from shared.settings import get_setting
from shared.ui import ZenButton
from themes import get_theme, subscribe_theme_change, unsubscribe_theme_change

# macOS-specific flag for removing rounded corners (AppKit imported lazily)
_IS_MACOS = sys.platform == "darwin"


class _BorderOverlay(Gtk.Widget):
    """Draws the popup border using GtkSnapshot"""

    def __init__(self, popup):
        super().__init__()
        self._popup = popup

    def do_snapshot(self, snapshot):
        from shared.utils import hex_to_rgb_float

        width = self.get_width()
        height = self.get_height()
        if width <= 0 or height <= 0:
            return

        theme = get_theme()
        radius = get_setting("popup.border_radius", 0)
        half = 0.5
        line_gap = 3
        y_top = self._popup._title_half_height + half

        # Fill the strip above the border with the editor background
        if self._popup._title_half_height > 0:
            er, eg, eb = hex_to_rgb_float(theme.main_bg)
            bg = Gdk.RGBA()
            bg.red, bg.green, bg.blue, bg.alpha = er, eg, eb, 1.0
            fill_h = self._popup._title_half_height + 1
            if radius > 0:
                b = Gsk.PathBuilder.new()
                b.move_to(radius, 0)
                b.line_to(width - radius, 0)
                b.svg_arc_to(radius, radius, 0, False, True, width, radius)
                b.line_to(width, fill_h)
                b.line_to(0, fill_h)
                b.line_to(0, radius)
                b.svg_arc_to(radius, radius, 0, False, True, radius, 0)
                b.close()
                snapshot.append_fill(b.to_path(), Gsk.FillRule.WINDING, bg)
            else:
                snapshot.append_color(bg, Graphene.Rect().init(0, 0, width, fill_h))

        # Border colour and stroke
        r, g, b = hex_to_rgb_float(theme.border_focus)
        border_color = Gdk.RGBA()
        border_color.red, border_color.green, border_color.blue, border_color.alpha = r, g, b, 1.0
        stroke = Gsk.Stroke.new(1.0)

        y_bot = height - half
        x_left = half
        x_right = width - half

        # Title gap
        gap_start = gap_end = 0
        if self._popup._title_label:
            alloc = self._popup._title_label.get_allocation()
            if alloc.width > 1:
                gap_start = alloc.x - 2
                gap_end = alloc.x + alloc.width + 2

        # Outer border
        snapshot.append_stroke(
            self._border_path(x_left, y_top, x_right, y_bot, radius, gap_start, gap_end),
            stroke,
            border_color,
        )

        # Inner border (parallel line inset by line_gap)
        inner_r = max(0, radius - line_gap)
        snapshot.append_stroke(
            self._border_path(
                x_left + line_gap,
                y_top + line_gap,
                x_right - line_gap,
                y_bot - line_gap,
                inner_r,
                gap_start,
                gap_end,
            ),
            stroke,
            border_color,
        )

    @staticmethod
    def _border_path(x_left, y_top, x_right, y_bot, r, gap_start=0, gap_end=0):
        """Build a rounded-rect path, optionally with a title gap on the top edge."""
        has_gap = gap_start < gap_end and gap_start > x_left + r and gap_end < x_right - r
        pb = Gsk.PathBuilder.new()

        if has_gap:
            pb.move_to(gap_end, y_top)
        else:
            pb.move_to(x_left + r, y_top)

        # Top edge → top-right corner
        pb.line_to(x_right - r, y_top)
        if r > 0:
            pb.svg_arc_to(r, r, 0, False, True, x_right, y_top + r)
        # Right edge → bottom-right corner
        pb.line_to(x_right, y_bot - r)
        if r > 0:
            pb.svg_arc_to(r, r, 0, False, True, x_right - r, y_bot)
        # Bottom edge → bottom-left corner
        pb.line_to(x_left + r, y_bot)
        if r > 0:
            pb.svg_arc_to(r, r, 0, False, True, x_left, y_bot - r)
        # Left edge → top-left corner
        pb.line_to(x_left, y_top + r)
        if r > 0:
            pb.svg_arc_to(r, r, 0, False, True, x_left + r, y_top)

        if has_gap:
            pb.line_to(gap_start, y_top)
        else:
            pb.close()

        return pb.to_path()


class NvimPopup(Gtk.Window):
    """
    Base class for Neovim-style floating popups.

    ALL popups in Zen IDE MUST inherit from this class to ensure consistent:
    - Styling (dark floating window with accent border)
    - Keyboard handling (Escape to close, vim-style navigation)
    - Centering on parent window (default) or anchored positioning
    - Modal behavior (default) or non-modal inline mode

    Subclasses should:
    - Override _create_content() to add their specific UI
    - Override _on_key_pressed() for custom key handling (call super first)
    - Use self._content_box to add widgets

    Anchor mode (anchor_widget is set):
        The popup positions itself relative to anchor_widget + anchor_rect
        instead of centering on the parent. Use set_anchor_rect() to update
        the position dynamically (e.g. follow cursor movement).

    Non-focus-stealing mode (steal_focus=False):
        The popup does not steal keyboard focus from the parent/editor.
        Useful for inline popups like autocomplete where typing must continue.
        close() hides instead of destroying (popup is reusable).
    """

    def __init__(
        self,
        parent: Gtk.Window,
        title: str = "",
        width: int = 400,
        height: int = -1,
        anchor_widget: Gtk.Widget = None,
        anchor_rect: Gdk.Rectangle = None,
        modal: bool = True,
        steal_focus: bool = True,
    ):
        """
        Initialize the popup.

        Args:
            parent: Parent window to attach to
            title: Optional title shown in header
            width: Popup width in pixels (-1 for natural size)
            height: Popup height in pixels (-1 for natural size)
            anchor_widget: Widget to anchor to (None = center on parent)
            anchor_rect: Rectangle relative to anchor_widget for positioning
            modal: Whether the popup is modal (blocks parent interaction)
            steal_focus: Whether presenting the popup steals keyboard focus
        """
        super().__init__()
        self.add_css_class("nvim-popup-window")
        self.set_transient_for(parent)
        # On Linux, avoid GTK's modal system — it blocks parent input events
        # entirely, preventing click-outside-to-close detection.  We handle
        # dismiss-on-click-outside ourselves via a parent gesture instead.
        self.set_modal(modal and _IS_MACOS)
        self.set_decorated(False)
        self.set_resizable(False)

        # Also set decorated=False on the surface after realization (macOS fix)
        self.connect("realize", self._on_realize_disable_decorations)

        # Make window background match editor bg so macOS decorations blend in
        self.connect("realize", self._setup_macos_window)

        self._parent = parent
        self._title = title
        self._width = width
        self._height = height
        self._result = None
        self._css_provider = None
        self._closing = False
        self._anchor_widget = anchor_widget
        self._anchor_rect = anchor_rect
        self._modal = modal
        self._steal_focus = steal_focus
        self._ns_window = None  # macOS NSWindow reference (set on first present)
        self._parent_ns_window = None  # parent's NSWindow (for focus restore)
        self._macos_click_monitor = None  # NSEvent monitor for click-outside
        self._linux_popover = None  # Gtk.Popover used for anchor positioning on Linux

        # Half the title label height — used to push the frame down
        # so the title straddles the border (half inside, half outside)
        _, font_size = self._get_popup_font()
        self._title_half_height = int((font_size + 1) * 0.75) if self._title else 0

        self._create_base_ui()
        self._apply_styles()
        self._setup_keyboard()
        self._setup_click_outside()
        self._create_content()

        # Re-apply styles when theme changes (e.g. live preview)
        self._theme_change_cb = lambda _theme: (self._apply_styles(), self._border_area.queue_draw())
        subscribe_theme_change(self._theme_change_cb)

    def _create_base_ui(self):
        """Create Neovim-style popup with GtkSnapshot-drawn border and overlay title.

        The frame fills the entire window (no margin-top) so the popup
        background is uniform.  The GtkSnapshot border is drawn at y=title_half_height
        and the title label (valign=START) straddles that line — half above,
        half below — exactly like Neovim.  Because the frame bg is the same
        everywhere, the title's transparent CSS background blends seamlessly.
        """
        overlay = Gtk.Overlay()
        self.set_child(overlay)

        # Frame fills the full window — uniform dark background
        self._outer_frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._outer_frame.add_css_class("nvim-popup-frame")
        overlay.set_child(self._outer_frame)

        self._main_box = self._outer_frame

        # Content area — extra top margin when title present to clear the
        # border line + title that straddles it
        top_margin = (self._title_half_height * 2 + 19) if self._title else 8
        self._content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._content_box.set_margin_start(12)
        self._content_box.set_margin_end(12)
        self._content_box.set_margin_top(top_margin)
        self._content_box.set_margin_bottom(12)
        self._outer_frame.append(self._content_box)

        # Border overlay — draws the border with a gap for the title
        self._title_label = None
        self._border_area = _BorderOverlay(self)
        self._border_area.set_can_target(False)
        overlay.add_overlay(self._border_area)

        # Title overlaid so it straddles the top border (half in, half out)
        if self._title:
            self._title_label = Gtk.Label(label=f" {self._title} ")
            self._title_label.add_css_class("nvim-popup-title")
            self._title_label.set_halign(Gtk.Align.CENTER)
            self._title_label.set_valign(Gtk.Align.START)
            overlay.add_overlay(self._title_label)
            self._title_label.set_can_target(False)
            # Redraw border when title size is known
            self._title_label.connect("notify::allocation", lambda *_: self._border_area.queue_draw())

    def _on_realize_disable_decorations(self, widget):
        """Disable decorations on the surface after realization (macOS fix for rounded corners)."""
        surface = self.get_surface()
        if surface and hasattr(surface, "set_decorated"):
            surface.set_decorated(False)

    def _setup_macos_window(self, widget):
        """Set up the macOS NSWindow to match editor background."""
        if not _IS_MACOS:
            return

        # Delay to next idle tick so the NSWindow is fully created and mapped
        from gi.repository import GLib

        GLib.idle_add(self._apply_macos_square_corners)

    def _apply_macos_square_corners(self):
        """Apply borderless style to NSWindow for square corners on macOS."""
        try:
            from AppKit import NSApp, NSColor, NSWindowStyleMaskBorderless

            ns_window = NSApp.keyWindow()
            if ns_window is not None:
                self._ns_window = ns_window  # Store for repositioning
                ns_window.setStyleMask_(NSWindowStyleMaskBorderless)
                ns_window.setHasShadow_(False)
                # Use main_bg (editor background) so any residual decoration
                # pixels blend in rather than showing as a grey line.
                theme = get_theme()
                from shared.utils import hex_to_rgb_float

                r, g, b = hex_to_rgb_float(theme.main_bg)
                ns_window.setOpaque_(True)
                ns_window.setBackgroundColor_(NSColor.colorWithRed_green_blue_alpha_(r, g, b, 1.0))
        except Exception:
            pass
        return False  # Don't repeat idle_add

    def _get_popup_font(self) -> tuple[str, int]:
        """Get the editor font family and size for popup styling."""
        settings = get_font_settings("editor")
        return settings["family"], settings["size"]

    def _get_icon_font(self) -> str:
        """Get the icon font name for icon labels."""
        from icons import get_icon_font_name

        return get_icon_font_name()

    def _apply_styles(self):
        """Apply Neovim-like styles to the popup."""
        theme = get_theme()
        font_family, font_size = self._get_popup_font()
        border_radius = get_setting("popup.border_radius", 0)

        from shared.utils import blend_hex_colors, ensure_text_contrast, hex_to_rgba_css

        # More translucent backgrounds (0.75 = 75% opacity)
        panel_bg_translucent = hex_to_rgba_css(theme.panel_bg, 0.75)
        main_bg_translucent = hex_to_rgba_css(theme.main_bg, 0.80)
        primary_button_bg = ensure_text_contrast(theme.accent_color, "#ffffff")
        primary_button_hover_bg = ensure_text_contrast(blend_hex_colors(primary_button_bg, "#000000", 0.08), "#ffffff")

        # Remove old provider before re-applying
        if self._css_provider:
            Gtk.StyleContext.remove_provider_for_display(
                Gdk.Display.get_default(),
                self._css_provider,
            )

        self._css_provider = Gtk.CssProvider()
        css = f"""
            /* Base window - match editor bg so any decoration pixels blend in */
            window.nvim-popup-window {{
                background-color: {theme.main_bg};
                font-family: "{font_family}";
                font-size: {font_size}pt;
                border-radius: {border_radius}px;
                border: none;
                box-shadow: none;
            }}

            window.nvim-popup-window.csd {{
                background-color: {theme.main_bg};
                border-radius: {border_radius}px;
                border: none;
                box-shadow: none;
            }}

            window.nvim-popup-window decoration,
            window.nvim-popup-window.csd decoration,
            window.nvim-popup-window.csd.popup decoration,
            window.nvim-popup-window.popup decoration {{
                all: unset;
                background: {theme.main_bg};
                background-color: {theme.main_bg};
                background-image: none;
                border: none;
                border-image: none;
                box-shadow: none;
                outline: none;
                margin: 0;
                padding: 0;
                min-height: 0;
                min-width: 0;
            }}

            window.nvim-popup-window decoration shadow {{
                all: unset;
                box-shadow: none;
                background: {theme.main_bg};
                margin: 0;
                padding: 0;
            }}

            window.nvim-popup-window.popup {{
                background-color: {theme.main_bg};
                border-radius: {border_radius}px;
                border: none;
                box-shadow: none;
                margin: 0;
                padding: 0;
            }}

            window.nvim-popup-window headerbar,
            window.nvim-popup-window .titlebar {{
                min-height: 0;
                border: none;
                box-shadow: none;
                background: {theme.main_bg};
                margin: 0;
                padding: 0;
            }}

            /* Remove all border-radius from child elements */
            window.nvim-popup-window * {{
                border-radius: {border_radius}px;
            }}

            /* Linux popover for anchor positioning — transparent chrome */
            popover.nvim-popup-popover,
            popover.nvim-popup-popover > contents {{
                background: transparent;
                background-color: transparent;
                border: none;
                box-shadow: none;
                padding: 0;
                margin: 0;
                min-height: 0;
                min-width: 0;
            }}

            /* Frame — no CSS border; border drawn by GtkSnapshot overlay */
            .nvim-popup-frame {{
                border-radius: {border_radius}px;
                background-color: {panel_bg_translucent};
            }}

            /* Title overlaid on the top border line — transparent background */
            .nvim-popup-title {{
                font-weight: 500;
                font-size: {font_size + 1}pt;
                color: {theme.accent_color};
                background-color: transparent;
                padding: 0 8px;
            }}

            .nvim-popup-separator {{
                background-color: {theme.border_color};
                min-height: 1px;
            }}

            /* Content styling */
            .nvim-popup-message {{
                color: {theme.fg_color};
            }}

            .nvim-popup-hint {{
                color: {theme.fg_dim};
                font-size: {int(font_size * 0.85)}pt;
            }}

            /* Input field - slightly translucent */
            .nvim-popup-input {{
                background-color: {main_bg_translucent};
                color: {theme.fg_color};
                border: 1px solid {theme.border_color};
                border-radius: {border_radius}px;
                padding: 8px;
                font-family: "{font_family}";
                outline: none;
                outline-width: 0;
            }}

            .nvim-popup-input:focus-within {{
                border-color: {theme.accent_color};
                outline: none;
                outline-width: 0;
            }}

            .nvim-popup-input > text {{
                outline: none;
                outline-width: 0;
                background: transparent;
                border: none;
                font-family: "{font_family}";
                font-size: {font_size}pt;
                color: {theme.fg_color};
            }}

            /* List styling */
            .nvim-popup-list {{
                background-color: transparent;
                border-radius: {border_radius}px;
            }}

            .nvim-popup-list row {{
                border-radius: {border_radius}px;
                outline: none;
            }}

            .nvim-popup-list row:focus,
            .nvim-popup-list row:focus-visible {{
                outline: none;
            }}

            .nvim-popup-list row:selected {{
                background-color: {theme.selection_bg};
                border-radius: {border_radius}px;
                outline: none;
            }}

            .nvim-popup-list row:hover {{
                background-color: {theme.hover_bg};
                border-radius: {border_radius}px;
            }}

            .nvim-popup-list-item {{
                padding: 3px 8px;
                border-radius: {border_radius}px;
                outline: none;
            }}

            .nvim-popup-list-item:focus,
            .nvim-popup-list-item:focus-visible {{
                outline: none;
            }}

            .nvim-popup-list-item:selected {{
                background-color: {theme.selection_bg};
                border-radius: {border_radius}px;
                outline: none;
            }}

            .nvim-popup-list-item:hover {{
                background-color: {theme.hover_bg};
                border-radius: {border_radius}px;
            }}

            /* Override text colors on selected rows for readability */
            .nvim-popup-list row:selected label,
            .nvim-popup-list-item:selected label {{
                color: {theme.fg_color};
            }}

            .nvim-popup-list row:selected .nvim-popup-keybind,
            .nvim-popup-list-item:selected .nvim-popup-keybind {{
                color: {theme.fg_color};
                background-color: transparent;
                border-color: {theme.fg_dim};
            }}

            .nvim-popup-list-item-text {{
                color: {theme.fg_color};
                font-family: "{self._get_icon_font()}", "{font_family}", system-ui;
            }}

            .nvim-popup-list-item-hint {{
                color: {theme.fg_dim};
                font-size: {int(font_size * 0.9)}pt;
            }}

            .nvim-popup-list-item-icon {{
                color: {theme.accent_color};
                margin-right: 8px;
                font-size: {font_size}pt;
                font-family: "{self._get_icon_font()}", "{font_family}", system-ui;
            }}

            /* Button styling */
            .nvim-popup-button {{
                background-color: {theme.main_bg};
                color: {theme.fg_color};
                border: 1px solid {theme.border_color};
                border-radius: {border_radius}px;
                padding: 4px 12px;
                min-width: 70px;
                font-family: "{font_family}";
                font-size: {font_size}pt;
            }}

            .nvim-popup-button > label {{
                font-family: "{font_family}";
                font-size: {font_size}pt;
            }}

            .nvim-popup-button:hover {{
                background-color: {theme.hover_bg};
            }}

            .nvim-popup-button-primary {{
                background-color: {primary_button_bg};
                color: #ffffff;
                border: none;
                font-weight: bold;
            }}

            .nvim-popup-button-primary:hover {{
                background-color: {primary_button_hover_bg};
            }}

            .nvim-popup-button-primary:focus,
            .nvim-popup-button-primary:focus-visible {{
                background-color: {primary_button_bg};
                color: #ffffff;
                outline: 2px solid {theme.fg_color};
                outline-offset: 2px;
            }}

            .nvim-popup-button-danger {{
                background-color: {theme.git_deleted};
                color: white;
                border: none;
            }}

            .nvim-popup-button-danger:focus,
            .nvim-popup-button-danger:focus-visible {{
                background-color: {theme.git_deleted};
                color: white;
                outline: 2px solid {theme.fg_color};
                outline-offset: 2px;
            }}

            .nvim-popup-button:focus,
            .nvim-popup-button:focus-visible {{
                outline: 2px solid {theme.accent_color};
                outline-offset: 2px;
            }}

            /* DropDown styling (e.g. project filter, AI settings combos) */
            .nvim-popup-window dropdown {{
                font-family: "{font_family}";
                font-size: {font_size}pt;
            }}

            .nvim-popup-window dropdown > button {{
                font-family: "{font_family}";
                font-size: {font_size}pt;
                background-color: {theme.main_bg};
                color: {theme.fg_color};
                border: 1px solid {theme.border_color};
                border-radius: {border_radius}px;
                padding: 4px 12px;
            }}

            .nvim-popup-window dropdown > button > box > label {{
                font-family: "{font_family}";
                font-size: {font_size}pt;
            }}

            /* DropDown popover — the results list that opens when you click the combo.
               GTK4 renders the dropdown items in a separate popover window,
               so we must target it globally (not scoped under .nvim-popup-window). */
            dropdown popover {{
                font-family: "{font_family}";
                font-size: {int(font_size * 0.85)}pt;
            }}

            dropdown popover > contents {{
                background-color: {theme.panel_bg};
                border: 1px solid {theme.border_color};
                border-radius: {border_radius}px;
            }}

            dropdown popover listview {{
                font-family: "{font_family}";
                font-size: {int(font_size * 0.85)}pt;
                background-color: transparent;
            }}

            dropdown popover listview > row {{
                font-family: "{font_family}";
                font-size: {int(font_size * 0.85)}pt;
                background-color: transparent;
                color: {theme.fg_color};
                border-radius: {border_radius}px;
                outline: none;
            }}

            dropdown popover listview > row:selected {{
                background-color: {theme.selection_bg};
                border-radius: {border_radius}px;
                outline: none;
            }}

            dropdown popover listview > row:hover {{
                background-color: {theme.hover_bg};
                border-radius: {border_radius}px;
            }}

            dropdown popover listview > row > cell {{
                font-family: "{font_family}";
                font-size: {int(font_size * 0.85)}pt;
                color: {theme.fg_color};
            }}

            dropdown popover listview > row > cell > label {{
                font-family: "{font_family}";
                font-size: {int(font_size * 0.85)}pt;
                color: {theme.fg_color};
            }}

            dropdown popover listview > row label {{
                font-family: "{font_family}";
                font-size: {int(font_size * 0.85)}pt;
                color: {theme.fg_color};
            }}

            dropdown popover listview > row:selected label {{
                color: {theme.fg_color};
            }}

            /* Also style the checkmark/indicator in DropDown rows */
            dropdown popover listview > row image {{
                color: {theme.accent_color};
            }}

            /* Keybind hint */
            .nvim-popup-keybind {{
                font-family: "{font_family}";
                font-size: {int(font_size * 0.85)}pt;
                color: {theme.fg_dim};
                background-color: {theme.main_bg};
                padding: 2px 6px;
                border-radius: {border_radius}px;
                border: 1px solid {theme.border_color};
            }}

            /* File name/path styling */
            .nvim-popup-file-name {{
                font-weight: 500;
                color: {theme.fg_color};
            }}

            .nvim-popup-file-path {{
                color: {theme.fg_dim};
                font-size: {int(font_size * 0.9)}pt;
            }}

            row:selected .nvim-popup-file-name,
            row:selected .nvim-popup-file-path {{
                color: {theme.fg_color};
            }}

            /* Search entry - slightly translucent */
            .nvim-popup-search {{
                background-color: {main_bg_translucent};
                color: {theme.fg_color};
                border: 1px solid {theme.border_color};
                border-radius: {border_radius}px;
                padding: 8px;
                font-family: "{font_family}";
                outline: none;
                outline-width: 0;
            }}

            .nvim-popup-search:focus-within {{
                border-color: {theme.accent_color};
                border-radius: {border_radius}px;
                outline: none;
                outline-width: 0;
            }}

            .nvim-popup-search > text {{
                outline: none;
                outline-width: 0;
                background: transparent;
                border: none;
            }}

            /* ScrolledWindow and all children */
            scrolledwindow {{
                border-radius: {border_radius}px;
            }}

            scrolledwindow undershoot {{
                border-radius: {border_radius}px;
            }}

            scrolledwindow overshoot {{
                border-radius: {border_radius}px;
            }}

            listbox {{
                border-radius: {border_radius}px;
            }}

            listbox row {{
                border-radius: {border_radius}px;
                outline: none;
            }}

            listbox row:focus,
            listbox row:focus-visible {{
                outline: none;
            }}

            /* ListView selection (used by FontPickerDialog etc.) */
            .nvim-popup-list > row:selected {{
                background-color: {theme.selection_bg};
                border-radius: {border_radius}px;
                outline: none;
            }}

            .nvim-popup-list > row:hover {{
                background-color: {theme.hover_bg};
                border-radius: {border_radius}px;
            }}

            /* Status/count label */
            .nvim-popup-status {{
                color: {theme.fg_dim};
                font-size: {int(font_size * 0.85)}pt;
            }}
        """
        self._css_provider.load_from_data(css.encode())

        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            self._css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_USER,
        )

    def _setup_keyboard(self):
        """Setup keyboard event handling."""
        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

    def _setup_click_outside(self):
        """Setup click-outside-to-close behavior."""
        if self._parent and self._steal_focus:
            # Only add focus-leave auto-close for focus-stealing (modal) popups.
            # Non-focus-stealing popups manage their own dismiss logic.
            focus_controller = Gtk.EventControllerFocus()
            focus_controller.connect("leave", self._on_focus_leave)
            self.add_controller(focus_controller)
            if not _IS_MACOS:
                # On Linux, GTK4 focus-leave can be unreliable for detecting
                # clicks outside the popup (especially on Wayland).  Monitor
                # the window's is-active property as a fallback — it reliably
                # fires when the user clicks on another window or the desktop.
                self.connect("notify::is-active", self._on_active_changed)

    def _on_focus_leave(self, controller):
        """Handle focus leaving the popup window - close it."""
        if self._closing:
            return
        self._result = None
        self.close()

    def _on_active_changed(self, window, pspec):
        """Handle window losing active state (Linux fallback for click-outside).

        Use a short delay before closing — dropdown popovers and child dialogs
        temporarily steal the active state and return it immediately.
        """
        if self._closing or self.get_property("is-active"):
            return
        from gi.repository import GLib

        GLib.timeout_add(150, self._check_active_and_close)

    def _check_active_and_close(self):
        """Close if the popup is still inactive after the delay.

        Only close when the *parent* window is active — that means the user
        clicked on the parent (i.e. "clicked outside" the popup).  If both
        the popup and the parent are inactive the user switched to a
        different application and the popup should stay open.
        """
        if self._closing:
            return False
        if self.get_property("is-active"):
            return False
        # If the parent window is also inactive, the user switched apps —
        # don't dismiss the popup.
        if self._parent and not self._parent.is_active():
            return False
        self._result = None
        self.close()
        return False

    def _install_macos_click_monitor(self):
        """Install an NSEvent local monitor to detect clicks outside the popup on macOS."""
        if self._macos_click_monitor or self._closing:
            return False  # already installed or closing
        try:
            from AppKit import NSEvent, NSLeftMouseDownMask, NSRightMouseDownMask

            mask = NSLeftMouseDownMask | NSRightMouseDownMask

            def _on_mouse_down(event):
                ns_win = self._ns_window
                if ns_win and not self._closing:
                    if event.window() != ns_win:
                        from gi.repository import GLib

                        GLib.idle_add(self._dismiss_click_outside)
                return event

            self._macos_click_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(mask, _on_mouse_down)
        except Exception:
            pass
        return False  # don't repeat idle_add

    def _dismiss_click_outside(self):
        """Dismiss the popup triggered by a click outside (macOS)."""
        if self._closing:
            return False
        self._result = None
        self.close()
        return False  # don't repeat idle_add

    def _remove_macos_click_monitor(self):
        """Remove the NSEvent click monitor if installed."""
        if self._macos_click_monitor:
            try:
                from AppKit import NSEvent

                NSEvent.removeMonitor_(self._macos_click_monitor)
            except Exception:
                pass
            self._macos_click_monitor = None

    def _create_content(self):
        """
        Create the popup content. Override in subclasses.

        Use self._content_box to add widgets.
        """
        pass

    def _has_text_entry_focus(self) -> bool:
        """Check if a text entry widget currently has keyboard focus."""
        focus = self.get_focus()
        return isinstance(focus, (Gtk.Text, Gtk.Entry, Gtk.SearchEntry))

    def _on_key_pressed(self, controller, keyval, keycode, state) -> bool:
        """
        Handle key press events. Override in subclasses for custom handling.

        Args:
            controller: The key controller
            keyval: The key value
            keycode: The key code
            state: Modifier state

        Returns:
            True if the key was handled, False otherwise
        """
        if keyval == Gdk.KEY_Escape:
            self._result = None
            self.close()
            return True
        return False

    def close(self):
        """Close the popup.

        For non-focus-stealing popups (steal_focus=False), hides instead of
        destroying so the popup can be reused via popup()/popdown().
        """
        if self._closing:
            return
        if self._linux_popover:
            if not self._steal_focus:
                self._linux_popover.popdown()
                return
            self._closing = True
            if self._theme_change_cb:
                unsubscribe_theme_change(self._theme_change_cb)
                self._theme_change_cb = None
            self._linux_popover.popdown()
            self._linux_popover.unparent()
            self._linux_popover = None
            return
        if not self._steal_focus:
            self.set_visible(False)
            return
        self._closing = True
        self._remove_macos_click_monitor()
        if self._theme_change_cb:
            unsubscribe_theme_change(self._theme_change_cb)
            self._theme_change_cb = None
        super().close()

    def _center_on_parent(self):
        """Center the popup on the parent window."""
        # GTK4 handles this automatically with set_transient_for
        pass

    def present(self):
        """Show the popup."""
        if self._width > 0:
            self.set_default_size(self._width, self._height if self._height > 0 else -1)

        # Re-show existing Linux popover
        if self._linux_popover:
            if self._anchor_rect:
                self._linux_popover.set_pointing_to(self._anchor_rect)
            self._linux_popover.popup()
            if not self._steal_focus:
                from gi.repository import GLib

                GLib.idle_add(self._restore_parent_focus)
            return

        # Capture parent's NSWindow before presenting — needed for both
        # anchor positioning (coordinate conversion) and focus restore.
        if _IS_MACOS and (not self._steal_focus or self._anchor_widget):
            try:
                from AppKit import NSApp

                self._parent_ns_window = NSApp.keyWindow()
            except Exception:
                self._parent_ns_window = None

        # On Linux, use Gtk.Popover for anchor-positioned popups.
        # Gtk.Window cannot be positioned on Wayland (no API), and X11
        # XMoveWindow has timing issues.  Gtk.Popover uses xdg_popup on
        # Wayland and works reliably on both X11 and Wayland.
        if not _IS_MACOS and self._anchor_widget and self._anchor_rect:
            self._present_via_popover()
            return

        super().present()
        self._center_on_parent()

        if self._anchor_widget and self._anchor_rect:
            self._position_at_anchor()

        if not self._steal_focus:
            # On macOS, immediately restore parent as key window to prevent
            # visible focus bounce (cursor/line-highlight flicker in editor).
            # The idle_add fallback below handles edge cases where the
            # synchronous restore isn't sufficient.
            if _IS_MACOS and self._parent_ns_window:
                try:
                    self._parent_ns_window.makeKeyWindow()
                except Exception:
                    pass
            from gi.repository import GLib

            GLib.idle_add(self._restore_parent_focus)

        # On macOS, GTK4 focus-leave is unreliable for detecting clicks
        # outside the popup.  Install an NSEvent local monitor that fires
        # for every mouse-down in the app — if the click targets a window
        # other than this popup, dismiss it.
        if _IS_MACOS and self._steal_focus:
            from gi.repository import GLib

            GLib.idle_add(self._install_macos_click_monitor)

    def popup(self):
        """Show the popup (alias for present, popover-compatible API)."""
        self.present()

    def popdown(self):
        """Hide the popup without destroying it."""
        if self._linux_popover:
            self._linux_popover.popdown()
            return
        self.set_visible(False)

    def set_anchor_rect(self, rect: Gdk.Rectangle):
        """Update the anchor rectangle for positioned popups.

        Args:
            rect: Rectangle relative to anchor_widget (x, y, width, height)
        """
        self._anchor_rect = rect
        if self._linux_popover:
            self._linux_popover.set_pointing_to(rect)

    def _present_via_popover(self):
        """Present popup content via Gtk.Popover on Linux.

        Gtk.Window cannot be reliably positioned on Wayland (no API) and X11
        XMoveWindow has timing issues.  Gtk.Popover creates an xdg_popup
        surface on Wayland which supports precise positioning, and works
        correctly on X11 as well.
        """
        content = self.get_child()
        if not content:
            return

        # Detach content from the Window and move it into the Popover
        self.set_child(None)
        if self._width > 0:
            content.set_size_request(self._width, self._height if self._height > 0 else -1)

        popover = Gtk.Popover()
        popover.set_parent(self._anchor_widget)
        popover.set_pointing_to(self._anchor_rect)
        popover.set_has_arrow(False)
        popover.set_autohide(self._steal_focus)
        popover.set_child(content)
        popover.add_css_class("nvim-popup-popover")

        # Keyboard handling — mirror the controller attached to the Window
        if self._steal_focus:
            key_controller = Gtk.EventControllerKey()
            key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            key_controller.connect("key-pressed", self._on_key_pressed)
            popover.add_controller(key_controller)

        popover.connect("closed", self._on_popover_closed)

        self._linux_popover = popover
        popover.popup()

        if not self._steal_focus:
            from gi.repository import GLib

            GLib.idle_add(self._restore_parent_focus)

    def _on_popover_closed(self, popover):
        """Handle Gtk.Popover closed signal (autohide click-outside)."""
        if self._closing:
            return
        self._result = None
        self.close()

    def _position_at_anchor(self):
        """Reposition the popup relative to anchor_widget + anchor_rect."""
        if not self._anchor_widget or not self._anchor_rect:
            return False
        # Linux anchor positioning is handled via Gtk.Popover
        if _IS_MACOS:
            self._macos_position_at_anchor()
        return False

    def _macos_position_at_anchor(self):
        """Position popup at anchor using macOS AppKit APIs."""
        try:
            from AppKit import NSApp, NSPoint, NSScreen

            ns_window = getattr(self, "_ns_window", None)
            if not ns_window:
                # Try to find our window (should be key after present)
                ns_window = NSApp.keyWindow()
                if ns_window:
                    self._ns_window = ns_window

            parent_ns = self._parent_ns_window
            if not ns_window or not parent_ns:
                return

            # Compute anchor position in parent window coordinates
            root = self._anchor_widget.get_root()
            if not root:
                return

            point = Graphene.Point()
            point.x = float(self._anchor_rect.x)
            point.y = float(self._anchor_rect.y)
            success, result = self._anchor_widget.compute_point(root, point)
            if not success:
                return

            # Convert GTK coords (top-left origin) to macOS screen coords (bottom-left origin)
            parent_frame = parent_ns.frame()
            content_rect = parent_ns.contentRectForFrameRect_(parent_frame)
            title_bar_height = parent_frame.size.height - content_rect.size.height

            screen_x = content_rect.origin.x + result.x
            # GTK y grows downward; macOS y grows upward from bottom of screen
            anchor_screen_y = content_rect.origin.y + content_rect.size.height - result.y - title_bar_height

            popup_frame = ns_window.frame()
            popup_h = popup_frame.size.height
            popup_w = popup_frame.size.width

            # Default: position below the anchor point
            screen_y = anchor_screen_y - popup_h

            # Clamp to visible screen bounds (excludes menu bar and dock)
            screen = parent_ns.screen() or NSScreen.mainScreen()
            if screen:
                vf = screen.visibleFrame()
                s_bottom = vf.origin.y
                s_top = vf.origin.y + vf.size.height
                s_left = vf.origin.x
                s_right = vf.origin.x + vf.size.width

                # If popup goes below visible area, flip above the anchor
                if screen_y < s_bottom:
                    screen_y = anchor_screen_y
                # If popup goes above visible area, clamp to top
                if screen_y + popup_h > s_top:
                    screen_y = s_top - popup_h
                # Final clamp to bottom
                if screen_y < s_bottom:
                    screen_y = s_bottom
                # Horizontal: keep within visible area
                if screen_x + popup_w > s_right:
                    screen_x = s_right - popup_w
                if screen_x < s_left:
                    screen_x = s_left

            ns_window.setFrameOrigin_(NSPoint(screen_x, screen_y))
        except Exception:
            pass

    def _restore_parent_focus(self):
        """Return keyboard focus to parent window/editor after presenting."""
        if _IS_MACOS and self._parent_ns_window:
            try:
                self._parent_ns_window.makeKeyWindow()
            except Exception:
                pass
        elif self._anchor_widget:
            self._anchor_widget.grab_focus()
        elif self._parent:
            self._parent.present()
        return False

    # Helper methods for subclasses

    def _create_keybind_hint(self, key: str, action: str) -> Gtk.Box:
        """
        Create a keybind hint widget showing key -> action.

        Args:
            key: The key combination (e.g., "Enter", "Esc", "j/k")
            action: The action description (e.g., "confirm", "close")

        Returns:
            A Gtk.Box with the hint
        """
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        key_label = Gtk.Label(label=key)
        key_label.add_css_class("nvim-popup-keybind")
        box.append(key_label)

        action_label = Gtk.Label(label=action)
        action_label.add_css_class("nvim-popup-hint")
        box.append(action_label)

        return box

    def _create_hint_bar(self, hints: list[tuple[str, str]]) -> Gtk.Box:
        """
        Create a hint bar with multiple keybind hints.

        Args:
            hints: List of (key, action) tuples

        Returns:
            A Gtk.Box with all hints
        """
        hint_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        hint_box.set_halign(Gtk.Align.CENTER)
        hint_box.set_margin_top(8)

        for key, action in hints:
            hint_box.append(self._create_keybind_hint(key, action))

        return hint_box

    def _create_message_label(self, text: str, wrap: bool = True) -> Gtk.Label:
        """
        Create a styled message label.

        Args:
            text: The message text
            wrap: Whether to wrap text

        Returns:
            A styled Gtk.Label
        """
        label = Gtk.Label(label=text)
        label.set_halign(Gtk.Align.START)
        label.add_css_class("nvim-popup-message")
        if wrap:
            label.set_wrap(True)
            label.set_max_width_chars(70)
        return label

    def _create_input_entry(self, placeholder: str = "", initial_value: str = "") -> Gtk.Entry:
        """
        Create a styled input entry.

        Args:
            placeholder: Placeholder text
            initial_value: Initial value

        Returns:
            A styled ZenEntry (Gtk.Entry subclass)
        """
        from shared.ui.zen_entry import ZenEntry

        entry = ZenEntry(placeholder=placeholder, initial_value=initial_value)
        entry.add_css_class("nvim-popup-input")
        return entry

    def _create_search_entry(self, placeholder: str = "Search...") -> Gtk.SearchEntry:
        """
        Create a styled search entry.

        Args:
            placeholder: Placeholder text

        Returns:
            A styled ZenSearchEntry (Gtk.SearchEntry subclass)
        """
        from shared.ui.zen_entry import ZenSearchEntry

        entry = ZenSearchEntry(placeholder=placeholder)
        entry.add_css_class("nvim-popup-search")
        return entry

    def _create_scrolled_listbox(
        self,
        min_height: int = 200,
        max_height: int = 400,
    ) -> tuple[Gtk.ScrolledWindow, Gtk.ListBox]:
        """
        Create a scrolled listbox for selection lists.

        Args:
            min_height: Minimum content height
            max_height: Maximum content height

        Returns:
            Tuple of (ScrolledWindow, ListBox)
        """
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(min_height)
        scrolled.set_max_content_height(max_height)

        listbox = Gtk.ListBox()
        listbox.add_css_class("nvim-popup-list")
        listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        scrolled.set_child(listbox)

        return scrolled, listbox

    def _create_button(
        self,
        label: str,
        primary: bool = False,
        danger: bool = False,
    ) -> Gtk.Button:
        """
        Create a styled button.

        Args:
            label: Button label
            primary: Use primary (accent) style
            danger: Use danger (red) style

        Returns:
            A styled ZenButton
        """
        variant = "danger" if danger else ("primary" if primary else "flat")
        button = ZenButton(label=label, variant=variant)
        button.add_css_class("nvim-popup-button")

        if danger:
            button.add_css_class("nvim-popup-button-danger")
        elif primary:
            button.add_css_class("nvim-popup-button-primary")

        return button

    def _create_status_label(self, text: str = "") -> Gtk.Label:
        """
        Create a status label (e.g., for result counts).

        Args:
            text: Initial text

        Returns:
            A styled Gtk.Label
        """
        label = Gtk.Label(label=text)
        label.set_halign(Gtk.Align.START)
        label.add_css_class("nvim-popup-status")
        return label
