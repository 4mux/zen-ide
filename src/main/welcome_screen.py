"""
Welcome Screen for Zen IDE.
Shown as the default editor tab when no files are open.
"""

from pathlib import Path

from gi.repository import GLib, Gtk

from fonts import get_font_settings, subscribe_font_change
from icons import Icons
from shared.settings.keybindings import KeyBindings
from themes import get_theme, subscribe_theme_change


def _escape_markup(text: str) -> str:
    """Escape text for Pango markup."""
    return GLib.markup_escape_text(text)


def _format_logo(logo_text: str, accent_color: str) -> str:
    """Add background color to block-char runs to eliminate 1px inter-glyph gaps."""
    parts: list[str] = []
    i = 0
    while i < len(logo_text):
        if logo_text[i] == "█":
            j = i + 1
            while j < len(logo_text) and logo_text[j] == "█":
                j += 1
            parts.append(f'<span background="{accent_color}">{logo_text[i:j]}</span>')
            i = j
        else:
            j = i + 1
            while j < len(logo_text) and logo_text[j] != "█":
                j += 1
            parts.append(GLib.markup_escape_text(logo_text[i:j]))
            i = j
    return "".join(parts)


def _get_version() -> str:
    """Read version from pyproject.toml at the project root."""
    try:
        # src/main/welcome_screen.py -> src/main/ -> src/ -> project root
        project_root = Path(__file__).parent.parent.parent
        toml_path = project_root / "pyproject.toml"

        if toml_path.exists():
            content = toml_path.read_text()
            for line in content.splitlines():
                if line.strip().startswith("version"):
                    return line.split("=")[1].strip().strip("\"'")
    except Exception:
        pass
    return "unknown"


LOGO = """    ███████╗███████╗███╗   ██╗    ██╗██████╗ ███████╗
    ╚══███╔╝██╔════╝████╗  ██║    ██║██╔══██╗██╔════╝
      ███╔╝ █████╗  ██╔██╗ ██║    ██║██║  ██║█████╗
     ███╔╝  ██╔══╝  ██║╚██╗██║    ██║██║  ██║██╔══╝
    ███████╗███████╗██║ ╚████║    ██║██████╔╝███████╗
    ╚══════╝╚══════╝╚═╝  ╚═══╝    ╚═╝╚═════╝ ╚══════╝"""


class WelcomeScreen(Gtk.ScrolledWindow):
    """Welcome screen widget shown when no files are open."""

    def __init__(self):
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._font_size = 14  # Default font size
        self._create_ui()
        subscribe_theme_change(lambda _theme: self._create_ui())
        subscribe_font_change(lambda: self._create_ui())

    def apply_font_settings(self, font_size: int = None):
        """Apply new font size and recreate UI."""
        if font_size is not None:
            self._font_size = font_size
        # Remove old content and recreate with new size
        self._create_ui()

    def _create_ui(self):
        theme = get_theme()
        version = _get_version()
        font_size = self._font_size
        font_family = get_font_settings("editor")["family"]

        # Main container - set vexpand/hexpand to fill available space
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.set_halign(Gtk.Align.FILL)
        content.set_valign(Gtk.Align.FILL)
        content.set_hexpand(True)
        content.set_vexpand(True)
        content.set_margin_top(40)
        content.set_margin_bottom(40)
        content.set_margin_start(40)
        content.set_margin_end(40)
        content.set_spacing(10)

        # Logo - use a specific monospace font that supports box drawing
        logo_label = Gtk.Label()
        formatted_logo = _format_logo(LOGO, theme.accent_color)
        logo_label.set_markup(
            f'<span font_family="{font_family}" size="{font_size * 1024}" foreground="{theme.accent_color}">{formatted_logo}</span>'
        )
        logo_label.set_halign(Gtk.Align.START)
        logo_label.set_xalign(0)
        content.append(logo_label)

        # Version
        version_label = Gtk.Label()
        version_label.set_markup(
            f'<span font_family="{font_family}" size="{font_size * 1024}" foreground="{theme.fg_color}">'
            f"                        v{version}</span>"
        )
        version_label.set_halign(Gtk.Align.START)
        version_label.set_xalign(0)
        content.append(version_label)

        # Spacer
        spacer1 = Gtk.Box()
        spacer1.set_size_request(-1, 10)
        content.append(spacer1)

        # Welcome text
        welcome_label = Gtk.Label()
        welcome_label.set_markup(
            f'<span font_family="{font_family}" size="{font_size * 1024}" foreground="{theme.fg_color}">'
            f"    Welcome to Zen IDE - A Minimalist Opinionated IDE</span>"
        )
        welcome_label.set_halign(Gtk.Align.START)
        welcome_label.set_xalign(0)
        content.append(welcome_label)

        # Separator
        sep_label = Gtk.Label()
        sep_label.set_markup(
            f'<span font_family="{font_family}" size="{font_size * 1024}" foreground="{theme.fg_color}">    {"═" * 51}</span>'
        )
        sep_label.set_halign(Gtk.Align.START)
        sep_label.set_xalign(0)
        content.append(sep_label)

        # Made with love
        love_label = Gtk.Label()
        love_label.set_markup(
            f'<span font_family="{font_family}" size="{font_size * 1024}" foreground="{theme.fg_color}">'
            f'                    Made with <span font_family="ZenIcons">{Icons.HEART}</span> in 🇬🇧</span>'
        )
        love_label.set_halign(Gtk.Align.START)
        love_label.set_xalign(0)
        content.append(love_label)

        # Spacer
        spacer2 = Gtk.Box()
        spacer2.set_size_request(-1, 20)
        content.append(spacer2)

        # Shortcuts sections
        for category, shortcuts in KeyBindings.get_shortcut_categories():
            # Category header - escape & and other special chars
            escaped_cat = _escape_markup(category)
            cat_label = Gtk.Label()
            cat_label.set_markup(
                f'<span font_family="{font_family}" size="{font_size * 1024}" foreground="{theme.fg_color}">'
                f"    {escaped_cat}:</span>"
            )
            cat_label.set_halign(Gtk.Align.START)
            cat_label.set_xalign(0)
            content.append(cat_label)

            # Underline
            underline = "─" * len(category)
            underline_label = Gtk.Label()
            underline_label.set_markup(
                f'<span font_family="{font_family}" size="{font_size * 1024}" foreground="{theme.fg_color}">'
                f"    {underline}</span>"
            )
            underline_label.set_halign(Gtk.Align.START)
            underline_label.set_xalign(0)
            content.append(underline_label)

            # Shortcuts
            for name, key in shortcuts:
                # Format key with padding before putting in markup
                padded_key = f"{key:<20}"
                escaped_key = _escape_markup(padded_key)
                escaped_desc = _escape_markup(name)
                line_label = Gtk.Label()
                line_label.set_markup(
                    f'<span font_family="{font_family}" size="{font_size * 1024}" foreground="{theme.fg_color}">'
                    f"    • {escaped_key} {escaped_desc}</span>"
                )
                line_label.set_halign(Gtk.Align.START)
                line_label.set_xalign(0)
                content.append(line_label)

            # Section spacer
            section_spacer = Gtk.Box()
            section_spacer.set_size_request(-1, 10)
            content.append(section_spacer)

        # Apply background via CSS
        css_provider = Gtk.CssProvider()
        css = f"""
            .welcome-screen {{
                background-color: {theme.main_bg};
            }}
        """
        css_provider.load_from_data(css.encode())
        self.get_style_context().add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.add_css_class("welcome-screen")

        self.set_child(content)
