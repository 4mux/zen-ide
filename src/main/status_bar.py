"""
Nvim-style status bar for Zen IDE.

A minimal, informative status bar with:
- Mode indicator with Zen icon (left)
- Git branch (left)
- Filename (center-left)
- Encoding (right)
- File type (right)
- Position percentage (right)
"""

import os
import sys
from typing import Callable, Optional

from gi.repository import Gdk, GdkPixbuf, Gtk, Pango

_IS_MACOS = sys.platform == "darwin"

from constants import STATUS_BAR_FONT_FAMILY, STATUS_BAR_HORIZONTAL_PADDING, STATUS_BAR_ITEM_SPACING
from fonts import get_font_settings, subscribe_font_change
from icons import IconsManager, get_icon_font_name
from main.status_indicators_mixin import StatusIndicatorsMixin
from shared.settings import get_setting
from themes import (
    get_theme,
    subscribe_settings_change,
    subscribe_theme_change,
)


class StatusBar(StatusIndicatorsMixin, Gtk.Box):
    """Nvim-style status bar widget."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.add_css_class("nvim-status-bar")
        self.set_spacing(0)
        self.set_margin_top(3)

        self._current_file: Optional[str] = None
        self._git_branch: Optional[str] = None
        self._encoding: str = "utf-8"
        self._file_type: str = ""
        self._accent_color: str = "#ffffff"
        self._position_percent: int = 0
        self._line: int = 1
        self._col: int = 1
        self._modified: bool = False
        self._errors: int = 0
        self._warnings: int = 0
        self._workspace_folders: list = []
        self._workspace_name: Optional[str] = None
        self._css_provider: Gtk.CssProvider | None = None

        # Load Zen icon
        self._zen_icon_pixbuf = self._load_zen_icon()

        # Create sections
        self._create_widgets()
        self._apply_theme()

        # Subscribe to theme changes
        subscribe_theme_change(lambda t: self._apply_theme())

        # Subscribe to font settings changes
        subscribe_settings_change(self._on_settings_change)
        subscribe_font_change(self._on_font_change)

    def _on_settings_change(self, key: str, value):
        """Handle settings changes."""
        if key.startswith("editor.font") or key.startswith("fonts.editor"):
            self._apply_theme()
        elif key.startswith("status_bar."):
            self._apply_spacing()

    def _on_font_change(self, component: str, settings: dict):
        """Handle font changes from FontManager (e.g. Cmd+/- zoom)."""
        if component == "editor":
            self._apply_theme()

    def _apply_spacing(self):
        """Apply spacing settings to status bar boxes."""
        item_spacing = self._get_item_spacing()
        inner_spacing = self._get_inner_spacing()
        self._right_box.set_spacing(item_spacing)
        self._diagnostics_box.set_spacing(inner_spacing)
        self._filetype_box.set_spacing(inner_spacing)

    def _load_zen_icon(self) -> Optional[GdkPixbuf.Pixbuf]:
        """Load the Zen icon for the mode indicator."""
        from shared.utils import get_resource_path

        icon_path = get_resource_path("zen_icon.png")

        if os.path.exists(icon_path):
            try:
                return GdkPixbuf.Pixbuf.new_from_file_at_scale(icon_path, 24, 24, True)
            except Exception:
                pass
        return None

    def _get_item_spacing(self) -> int:
        """Get spacing between status bar items from settings."""
        return get_setting("status_bar.item_spacing", STATUS_BAR_ITEM_SPACING)

    def _get_inner_spacing(self) -> int:
        """Get spacing within status bar items from settings."""
        return get_setting("status_bar.inner_spacing", 10)

    def _create_widgets(self):
        """Create all status bar widgets."""
        item_spacing = self._get_item_spacing()
        inner_spacing = self._get_inner_spacing()

        # === LEFT SECTION ===
        left_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        left_box.set_hexpand(False)
        self.append(left_box)

        # Mode indicator (Zen icon + NORMAL)
        self._mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._mode_box.add_css_class("status-mode")
        self._mode_box.set_margin_start(0)
        self._mode_box.set_margin_end(0)

        # Zen icon
        if self._zen_icon_pixbuf:
            texture = Gdk.Texture.new_for_pixbuf(self._zen_icon_pixbuf)
            self._mode_icon = Gtk.Picture.new_for_paintable(texture)
            self._mode_icon.set_size_request(18, 18)
            self._mode_box.append(self._mode_icon)
        else:
            # Fallback to text "Z"
            self._mode_icon = Gtk.Label(label="Z")
            self._mode_icon.add_css_class("status-mode-icon")
            self._mode_box.append(self._mode_icon)

        # Mode label hidden until true nvim keyboard support
        self._mode_label = Gtk.Label(label="")
        self._mode_label.add_css_class("status-mode-text")
        self._mode_label.set_visible(False)

        left_box.append(self._mode_box)

        # Inspect mode indicator (shown when widget inspector is active)
        self._inspect_label = Gtk.Label(label="INSPECT")
        self._inspect_label.add_css_class("status-inspect-mode")
        self._inspect_label.set_margin_start(8)
        self._inspect_label.set_visible(False)
        left_box.append(self._inspect_label)

        # Debug mode indicator (shown during active debug session)
        self._debug_label = Gtk.Label(label="DEBUG")
        self._debug_label.add_css_class("status-debug-mode")
        self._debug_label.set_margin_start(8)
        self._debug_label.set_visible(False)
        left_box.append(self._debug_label)

        # Git branch section
        self._git_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self._git_box.add_css_class("status-git")

        self._git_icon = Gtk.Label(label=IconsManager.GIT_BRANCH)
        self._git_icon.add_css_class("status-git-icon")
        self._git_box.append(self._git_icon)

        self._git_label = Gtk.Label(label="")
        self._git_label.add_css_class("status-git-text")
        self._git_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._git_label.set_max_width_chars(20)
        self._git_box.append(self._git_label)

        left_box.append(self._git_box)

        # File path section
        self._filepath_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._filepath_box.add_css_class("status-filepath")

        self._filepath_label = Gtk.Label(label="")
        self._filepath_label.add_css_class("status-filepath-text")
        self._filepath_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self._filepath_label.set_hexpand(False)
        self._filepath_box.append(self._filepath_label)
        self._filepath_box.set_visible(False)

        left_box.append(self._filepath_box)

        # === CENTER SPACER ===
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        self.append(spacer)

        # === RIGHT SECTION ===
        self._right_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=item_spacing)
        self._right_box.set_hexpand(False)
        self._right_box.set_margin_end(0)
        self.append(self._right_box)

        # Encoding section
        # Diagnostics section (error/warning counts)
        # Outer box separates error group from warning group with inner_spacing
        self._diagnostics_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=inner_spacing)
        self._diagnostics_box.add_css_class("status-diagnostics")

        # Error group: icon + count with tight spacing
        icon_text_gap = 4
        error_group = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=icon_text_gap)
        error_group.set_valign(Gtk.Align.CENTER)

        self._error_icon_label = Gtk.Label(label="")
        self._error_icon_label.add_css_class("status-diagnostics-icon")
        self._error_icon_label.set_use_markup(True)
        self._error_icon_label.set_valign(Gtk.Align.CENTER)
        error_group.append(self._error_icon_label)

        self._error_count_label = Gtk.Label(label="")
        self._error_count_label.add_css_class("status-diagnostics-text")
        self._error_count_label.set_use_markup(True)
        self._error_count_label.set_valign(Gtk.Align.CENTER)
        error_group.append(self._error_count_label)

        self._diagnostics_box.append(error_group)

        # Warning group: icon + count with tight spacing
        warning_group = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=icon_text_gap)
        warning_group.set_valign(Gtk.Align.CENTER)

        self._warning_icon_label = Gtk.Label(label="")
        self._warning_icon_label.add_css_class("status-diagnostics-icon")
        self._warning_icon_label.set_use_markup(True)
        self._warning_icon_label.set_valign(Gtk.Align.CENTER)
        warning_group.append(self._warning_icon_label)

        self._warning_count_label = Gtk.Label(label="")
        self._warning_count_label.add_css_class("status-diagnostics-text")
        self._warning_count_label.set_use_markup(True)
        self._warning_count_label.set_valign(Gtk.Align.CENTER)
        warning_group.append(self._warning_count_label)

        self._diagnostics_box.append(warning_group)

        # Initialize with zero counts (visible immediately)
        self.set_diagnostics(0, 0)

        # Make diagnostics clickable
        self.on_diagnostics_clicked: Callable | None = None
        click = Gtk.GestureClick()
        click.connect("released", self._on_diagnostics_box_clicked)
        self._diagnostics_box.add_controller(click)
        self._diagnostics_box.set_cursor_from_name("pointer")

        self._right_box.append(self._diagnostics_box)

        self._encoding_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._encoding_box.add_css_class("status-encoding")

        self._encoding_label = Gtk.Label(label="utf-8")
        self._encoding_label.add_css_class("status-encoding-text")
        self._encoding_box.append(self._encoding_label)

        self._right_box.append(self._encoding_box)

        # Modified indicator
        self._modified_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._modified_box.add_css_class("status-modified")

        self._modified_label = Gtk.Label(label="")
        self._modified_label.add_css_class("status-modified-text")
        self._modified_box.append(self._modified_label)

        self._right_box.append(self._modified_box)

        # File type section
        self._filetype_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=inner_spacing)
        self._filetype_box.set_valign(Gtk.Align.CENTER)
        self._filetype_box.add_css_class("status-filetype")

        self._filetype_icon = Gtk.Label(label="")  # File icon placeholder
        self._filetype_icon.add_css_class("status-filetype-icon")
        self._filetype_icon.set_valign(Gtk.Align.CENTER)
        self._filetype_box.append(self._filetype_icon)

        self._filetype_label = Gtk.Label(label="")
        self._filetype_label.add_css_class("status-filetype-text")
        self._filetype_label.set_valign(Gtk.Align.CENTER)
        self._filetype_box.append(self._filetype_label)

        self._right_box.append(self._filetype_box)

        # Line/Col section
        self._position_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._position_box.add_css_class("status-position")

        self._position_label = Gtk.Label(label="1:1")
        self._position_label.add_css_class("status-position-text")
        self._position_box.append(self._position_label)

        self._right_box.append(self._position_box)

        # Percentage section
        self._percent_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._percent_box.add_css_class("status-percent")

        self._percent_label = Gtk.Label(label="Top")
        self._percent_label.add_css_class("status-percent-text")
        self._percent_box.append(self._percent_label)

        self._right_box.append(self._percent_box)

    def _apply_theme(self):
        """Apply theme colors to the status bar."""
        theme = get_theme()
        font_settings = get_font_settings("editor")
        font_family = STATUS_BAR_FONT_FAMILY or font_settings["family"]
        font_size = font_settings.get("size", 13)
        is_zen_dark = theme.name == "zen_dark"

        # macOS CoreText renders wider glyphs / metrics; tighten horizontal padding
        right_h_pad = 4 if _IS_MACOS else 10
        right_item_spacing = 2 if _IS_MACOS else STATUS_BAR_ITEM_SPACING
        self._right_box.set_spacing(right_item_spacing)

        # Zen Dark: full blue status bar with white text/icons.
        status_fg = "white" if is_zen_dark else theme.accent_color

        # Right sections
        right_bg = theme.accent_color if is_zen_dark else theme.border_color

        # Filetype section (accent)
        self._accent_color = status_fg

        icon_font = get_icon_font_name()
        icon_fallback = f"'{icon_font}', '{font_family}'"

        css = f"""
            .nvim-status-bar {{
                background-color: {right_bg};
                min-height: 28px;
            }}
            .nvim-status-bar label {{
                font-family: {icon_fallback};
                font-weight: 500;
            }}

            .status-mode {{
                background-color: transparent;
                padding: 3px 6px 3px {6 + STATUS_BAR_HORIZONTAL_PADDING}px;
                font-family: {icon_fallback};
                font-size: {font_size}pt;
                font-weight: 500;
            }}
            .status-mode-text {{
                color: white;
            }}
            .status-mode-icon {{
                color: white;
                font-weight: 500;
            }}

            .status-inspect-mode {{
                color: {theme.main_bg};
                background-color: {theme.accent_color};
                padding: 2px 8px;
                font-family: {icon_fallback};
                font-size: {font_size - 1}pt;
                font-weight: 700;
            }}

            .status-debug-mode {{
                color: {theme.main_bg};
                background-color: {theme.warning_color};
                padding: 2px 8px;
                font-family: {icon_fallback};
                font-size: {font_size - 1}pt;
                font-weight: 700;
            }}

            .status-git {{
                background-color: {right_bg};
                padding: 3px 12px;
                font-family: {icon_fallback};
                font-size: {font_size}pt;
            }}
            .nvim-status-bar .status-git-icon {{
                color: {status_fg};
                font-size: {font_size + 4}pt;
                font-family: '{icon_font}';
            }}
            .status-git-text {{
                color: {status_fg};
            }}

            .status-filepath {{
                background-color: {right_bg};
                padding: 3px 6px;
                font-family: {icon_fallback};
                font-size: {font_size}pt;
            }}
            .status-filepath-text {{
                color: white;
            }}

            .status-encoding {{
                background-color: {right_bg};
                padding: 3px {right_h_pad}px;
                font-family: {icon_fallback};
                font-size: {font_size}pt;
            }}
            .status-encoding-text {{
                color: white;
            }}

            .status-diagnostics {{
                background-color: {right_bg};
                padding: 3px {right_h_pad}px;
                font-family: {icon_fallback};
                font-size: {font_size}pt;
            }}
            .nvim-status-bar .status-diagnostics-icon {{
                color: white;
                font-size: {font_size + 4}pt;
                font-family: '{icon_font}';
            }}
            .status-diagnostics-text {{
                color: white;
            }}

            .status-modified {{
                background-color: {right_bg};
                padding: 3px {right_h_pad}px;
                font-family: {icon_fallback};
                font-size: {font_size}pt;
            }}
            .status-modified-text {{
                color: white;
            }}

            .status-filetype {{
                background-color: {right_bg};
                padding: 3px {right_h_pad}px;
                font-family: {icon_fallback};
                font-size: {font_size}pt;
            }}
            .nvim-status-bar .status-filetype-icon {{
                color: {status_fg};
                font-size: {font_size + 4}pt;
                font-family: '{icon_font}';
            }}
            .status-filetype-text {{
                color: {status_fg};
            }}

            .status-position {{
                background-color: {right_bg};
                padding: 3px {right_h_pad}px;
                font-family: {icon_fallback};
                font-size: {font_size}pt;
            }}
            .status-position-text {{
                color: white;
            }}

            .status-percent {{
                background-color: {right_bg};
                padding: 3px {STATUS_BAR_HORIZONTAL_PADDING}px 3px 6px;
                font-family: {icon_fallback};
                font-size: {font_size}pt;
                font-weight: 500;
            }}
            .status-percent-text {{
                color: white;
            }}
        """

        display = Gdk.Display.get_default()
        if self._css_provider is not None:
            Gtk.StyleContext.remove_provider_for_display(display, self._css_provider)
        self._css_provider = Gtk.CssProvider()
        self._css_provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_display(
            display,
            self._css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_USER + 1,
        )

        # Re-render Pango-markup labels so they pick up new theme colors
        self._refresh_diagnostics()
        if self._current_file:
            self._refresh_filetype_icon()
