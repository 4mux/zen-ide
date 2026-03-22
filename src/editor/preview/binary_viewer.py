"""
Binary file viewer for Zen IDE.
Displays binary file contents in a hex dump format (read-only).
"""

from gi.repository import Gtk

from fonts import get_font_settings
from themes import get_theme, subscribe_theme_change

# Max bytes to load for hex view (10 MB)
MAX_BINARY_SIZE = 10 * 1024 * 1024
BYTES_PER_ROW = 16


def is_binary_file(file_path: str, sample_size: int = 8192) -> bool:
    """Detect if a file is binary by checking for null bytes in a sample."""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(sample_size)
        return b"\x00" in chunk
    except (OSError, IOError):
        return False


def _format_hex_dump(data: bytes) -> str:
    """Format binary data as a hex dump string.

    Format: OFFSET  | HH HH HH ... | ASCII
    """
    lines = []
    for offset in range(0, len(data), BYTES_PER_ROW):
        row = data[offset : offset + BYTES_PER_ROW]

        # Offset column
        addr = f"{offset:08X}"

        # Hex column
        hex_parts = []
        for i, byte in enumerate(row):
            hex_parts.append(f"{byte:02X}")
            if i == 7:
                hex_parts.append("")  # extra space at midpoint
        hex_str = " ".join(hex_parts).ljust(3 * BYTES_PER_ROW + 1)

        # ASCII column
        ascii_chars = []
        for byte in row:
            if 0x20 <= byte <= 0x7E:
                ascii_chars.append(chr(byte))
            else:
                ascii_chars.append(".")
        ascii_str = "".join(ascii_chars)

        lines.append(f"{addr}  │ {hex_str}│ {ascii_str}")

    return "\n".join(lines)


class BinaryViewer(Gtk.Box):
    """Read-only hex dump viewer for binary files."""

    def __init__(self, file_path: str):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.file_path = file_path
        self._css_provider = None

        # Hex dump content
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        self._text_view = Gtk.TextView()
        self._text_view.set_editable(False)
        self._text_view.set_cursor_visible(False)
        self._text_view.set_monospace(True)
        self._text_view.set_left_margin(12)
        self._text_view.set_right_margin(12)
        self._text_view.set_top_margin(8)
        self._text_view.set_bottom_margin(8)
        self._text_view.set_wrap_mode(Gtk.WrapMode.NONE)

        scrolled.set_child(self._text_view)
        self.append(scrolled)

        # Load and display content
        self._load_content()
        self._apply_theme()
        subscribe_theme_change(lambda _name: self._apply_theme())

    def _load_content(self):
        """Read binary file and display hex dump."""
        try:
            with open(self.file_path, "rb") as f:
                data = f.read(MAX_BINARY_SIZE)
            dump = _format_hex_dump(data)
            self._text_view.get_buffer().set_text(dump)
        except OSError as e:
            self._text_view.get_buffer().set_text(f"Error reading file: {e}")

    def _apply_theme(self):
        """Apply current theme colors and font."""

        theme = get_theme()
        font_settings = get_font_settings("editor")
        font_family = font_settings["family"]
        font_size = font_settings.get("size", 13)

        css = f"""
            textview, textview text {{
                background-color: {theme.main_bg};
                color: {theme.fg_color};
                font-family: '{font_family}';
                font-size: {font_size}pt;
            }}
        """
        if self._css_provider:
            self.get_style_context().remove_provider(self._css_provider)
        self._css_provider = Gtk.CssProvider()
        self._css_provider.load_from_data(css.encode())
        self.get_style_context().add_provider(self._css_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        self._text_view.get_style_context().add_provider(self._css_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
