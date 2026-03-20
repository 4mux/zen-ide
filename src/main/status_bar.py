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
import threading
from typing import Callable, Optional

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango

_IS_MACOS = sys.platform == "darwin"

from constants import STATUS_BAR_FONT_FAMILY, STATUS_BAR_HORIZONTAL_PADDING, STATUS_BAR_ITEM_SPACING
from fonts import get_font_settings, subscribe_font_change
from icons import Icons, get_file_icon, get_icon_font_name, icon_font_fallback
from shared.git_manager import get_git_manager
from shared.main_thread import main_thread_call
from shared.settings import get_setting
from themes import (
    get_theme,
    subscribe_settings_change,
    subscribe_theme_change,
)


class StatusBar(Gtk.Box):
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

        # Git branch section
        self._git_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self._git_box.add_css_class("status-git")

        self._git_icon = Gtk.Label(label=Icons.GIT_BRANCH)
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

    def _font_markup(self, text: str, color: str, size: int | None = None, font_family: str | None = None) -> str:
        """Build Pango markup that always uses the fixed status bar font family."""
        font_settings = get_font_settings("editor")
        font_size = size if size is not None else font_settings.get("size", 13)
        if font_family is None:
            font_family = STATUS_BAR_FONT_FAMILY or font_settings["family"]
        font_family = icon_font_fallback(font_family)
        escaped_text = GLib.markup_escape_text(text)
        return f'<span foreground="{color}" font_family="{font_family}" size="{font_size * 1024}" weight="500">{escaped_text}</span>'

    def set_workspace_folders(self, folders: list, workspace_name: str = None, workspace_file: str = None):
        """Set workspace folders for git branch detection."""
        self._workspace_folders = folders
        if workspace_file and os.path.isfile(workspace_file):
            path = workspace_file
            home = os.path.expanduser("~")
            if path.startswith(home):
                path = "~" + path[len(home) :]
            self._workspace_name = path
        elif workspace_name:
            self._workspace_name = workspace_name
        elif folders:
            path = folders[0]
            home = os.path.expanduser("~")
            if path.startswith(home):
                path = "~" + path[len(home) :]
            self._workspace_name = path
        else:
            self._workspace_name = None

    def set_file(self, file_path: Optional[str]):
        """Update the current file display."""
        self._current_file = file_path

        if file_path:
            # Show full path or just filename based on setting
            show_full = get_setting("status_bar.show_full_path", True)
            if show_full:
                home = os.path.expanduser("~")
                if file_path.startswith(home):
                    display_path = "~" + file_path[len(home) :]
                else:
                    display_path = file_path
            else:
                display_path = os.path.basename(file_path)
            self._filepath_label.set_label(display_path)
            self._filepath_box.set_visible(True)

            # Detect file type
            self._file_type = self._detect_file_type(file_path)
            self._filetype_label.set_label(self._file_type)
            self._filetype_icon.set_use_markup(True)
            self._refresh_filetype_icon()

            # Detect encoding
            self.set_encoding(self._detect_encoding(file_path))

            # Show file-specific sections
            self._filetype_box.set_visible(True)
            self._encoding_box.set_visible(True)
            self._position_box.set_visible(True)
            self._percent_box.set_visible(True)
            self._right_box.set_margin_end(0)
            self._modified_box.set_visible(self._modified)

            # Update git branch (async)
            self._update_git_branch(file_path)
        else:
            self._file_type = ""
            self._filetype_label.set_label("")
            self._filetype_icon.set_label("")
            self._filetype_box.set_visible(False)
            self._git_label.set_label("")
            self._git_box.set_visible(False)
            self._encoding_box.set_visible(False)
            self._position_box.set_visible(False)
            self._percent_box.set_visible(False)
            self._right_box.set_margin_end(STATUS_BAR_HORIZONTAL_PADDING)
            self._modified_box.set_visible(False)
            # Show workspace name when no file is open
            if self._workspace_name:
                self._filepath_label.set_label(self._workspace_name)
                self._filepath_box.set_visible(True)
            else:
                self._filepath_label.set_label("")
                self._filepath_box.set_visible(False)

    def set_file_type(self, file_type: str):
        """Set the file type label directly."""
        self._file_type = file_type
        self._filetype_label.set_label(file_type)
        self._filetype_icon.set_label("")

    def _refresh_filetype_icon(self):
        """Re-render the filetype icon with current theme accent color."""
        if not self._current_file:
            return
        icon, _color = get_file_icon(self._current_file)
        font_settings = get_font_settings("editor")
        icon_size = font_settings.get("size", 13) + 4
        icon_font = get_icon_font_name()
        self._filetype_icon.set_markup(self._font_markup(icon, self._accent_color, icon_size, font_family=icon_font))

    def set_modified(self, modified: bool):
        """Update the modified indicator."""
        self._modified = modified
        self._modified_label.set_label("Δ" if modified else "")
        self._modified_box.set_visible(modified)

    def set_inspect_mode(self, active: bool):
        """Show or hide the INSPECT mode indicator."""
        self._inspect_label.set_visible(active)

    def set_position(self, line: int, col: int, total_lines: int):
        """Update cursor position and percentage (throttled to ~30fps)."""
        self._line = line
        self._col = col
        self._pending_total_lines = total_lines
        if not hasattr(self, "_position_update_pending") or not self._position_update_pending:
            self._position_update_pending = True
            GLib.timeout_add(33, self._flush_position_update)

    def _flush_position_update(self):
        """Flush pending position update to UI."""
        self._position_update_pending = False
        self._position_label.set_label(f"{self._line}:{self._col}")
        total_lines = self._pending_total_lines

        # Calculate percentage
        if total_lines <= 1:
            percent_text = "Top"
        elif self._line == 1:
            percent_text = "Top"
        elif self._line >= total_lines:
            percent_text = "Bot"
        else:
            percent = int((self._line / total_lines) * 100)
            percent_text = f"{percent}%"

        self._percent_label.set_label(percent_text)
        return False

    def set_encoding(self, encoding: str):
        """Update encoding display."""
        self._encoding = encoding
        self._encoding_label.set_label(encoding)

    def set_diagnostics(self, errors: int, warnings: int):
        """Update diagnostics (error/warning counts) display."""
        self._errors = errors
        self._warnings = warnings
        self._refresh_diagnostics()

    def _refresh_diagnostics(self):
        """Re-render diagnostic labels with current theme colors."""
        theme = get_theme()
        font_settings = get_font_settings("editor")
        icon_size = font_settings.get("size", 13) + 4
        icon_font = get_icon_font_name()
        # Zero-count diagnostics always use white to match other status bar texts.
        zero_color = "white"

        err_color = theme.term_red if self._errors > 0 else zero_color
        self._error_icon_label.set_markup(self._font_markup(Icons.ERROR_X, err_color, icon_size, font_family=icon_font))
        self._error_count_label.set_markup(self._font_markup(str(self._errors), err_color))

        warn_color = theme.warning_color if self._warnings > 0 else zero_color
        self._warning_icon_label.set_markup(self._font_markup(Icons.WARNING, warn_color, icon_size, font_family=icon_font))
        self._warning_count_label.set_markup(self._font_markup(str(self._warnings), warn_color))

        self._diagnostics_box.set_visible(True)

    def _on_diagnostics_box_clicked(self, gesture, n_press, x, y):
        """Handle click on diagnostics indicator."""
        if self.on_diagnostics_clicked:
            self.on_diagnostics_clicked()

    def _detect_encoding(self, file_path: str) -> str:
        """Detect file encoding by reading initial bytes."""
        try:
            with open(file_path, "rb") as f:
                raw = f.read(4)
            if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
                return "UTF-16"
            if raw.startswith(b"\xef\xbb\xbf"):
                return "UTF-8-BOM"
            # Try decoding as UTF-8
            with open(file_path, "r", encoding="utf-8") as f:
                f.read(8192)
            return "UTF-8"
        except (UnicodeDecodeError, OSError):
            return "Binary"

    def _detect_file_type(self, file_path: str) -> str:
        """Detect file type from extension."""
        ext = os.path.splitext(file_path)[1].lower()
        type_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascriptreact",
            ".tsx": "typescriptreact",
            ".html": "html",
            ".css": "css",
            ".scss": "scss",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".md": "markdown",
            ".rs": "rust",
            ".go": "go",
            ".java": "java",
            ".c": "c",
            ".cpp": "cpp",
            ".h": "c",
            ".hpp": "cpp",
            ".rb": "ruby",
            ".php": "php",
            ".sh": "shell",
            ".bash": "shell",
            ".zsh": "shell",
            ".sql": "sql",
            ".xml": "xml",
            ".toml": "toml",
            ".lua": "lua",
            ".vim": "vim",
            ".swift": "swift",
            ".kt": "kotlin",
            ".scala": "scala",
            ".clj": "clojure",
            ".ex": "elixir",
            ".exs": "elixir",
            ".erl": "erlang",
            ".hs": "haskell",
            ".ml": "ocaml",
            ".r": "r",
            ".jl": "julia",
            ".dart": "dart",
            ".vue": "vue",
            ".svelte": "svelte",
            ".zen_sketch": "sketch",
        }
        # Workspace files use compound extensions
        from constants import WORKSPACE_EXTENSIONS

        basename = os.path.basename(file_path)
        for ws_ext in WORKSPACE_EXTENSIONS:
            if basename.endswith(ws_ext):
                return "workspace"
        return type_map.get(ext, ext.lstrip(".") if ext else "text")

    def _update_git_branch(self, file_path: str):
        """Update git branch in background thread."""

        def _get_branch():
            git = get_git_manager()
            # Try file's own directory first
            file_dir = os.path.dirname(file_path)
            if os.path.isdir(file_dir):
                repo_root = git.get_repo_root(file_dir)
                if repo_root:
                    return git.get_current_branch(repo_root)

            # Fall back to workspace folders
            for folder in self._workspace_folders or []:
                if os.path.isdir(folder):
                    repo_root = git.get_repo_root(folder)
                    if repo_root:
                        return git.get_current_branch(repo_root)

            return None

        def _on_result(branch):
            if branch:
                self._git_branch = branch
                self._git_label.set_label(branch)
                self._git_icon.set_label(Icons.GIT_BRANCH)
                self._git_box.set_visible(True)
            else:
                self._git_branch = None
                self._git_label.set_label("")
                self._git_box.set_visible(False)

        def _thread_func():
            branch = _get_branch()
            main_thread_call(_on_result, branch)

        thread = threading.Thread(target=_thread_func, daemon=True)
        thread.start()
