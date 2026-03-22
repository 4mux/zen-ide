"""Header bar for AI Terminal — shows the active CLI name with a picker trigger."""

from gi.repository import Gtk, Pango

from constants import (
    TERMINAL_HEADER_MARGIN_BOTTOM,
    TERMINAL_HEADER_MARGIN_TOP,
)
from icons import Icons
from shared.ui import ZenButton


class AITerminalHeader:
    """Header for the AI Terminal panel.

    Builds: [<CLI name> ▾] --- [trash btn] [+ btn] [⛶ btn]

    Attributes exposed:
        box          – the Gtk.Box container
        header_btn   – CLI name button (click to switch CLI)
        clear_btn    – clear button
        add_btn      – new chat button
        maximize_btn – maximize button
    """

    def __init__(self, label: str = "AI"):
        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.box.set_margin_start(8)
        self.box.set_margin_end(8)
        self.box.set_margin_top(TERMINAL_HEADER_MARGIN_TOP)
        self.box.set_margin_bottom(TERMINAL_HEADER_MARGIN_BOTTOM)

        self.header_btn = ZenButton(
            label=f"{label} ▾",
            tooltip="Click to switch AI CLI",
        )
        self.header_btn.set_halign(Gtk.Align.START)
        self.header_btn.add_css_class("terminal-header-btn")
        self.box.append(self.header_btn)

        self.spinner_label = Gtk.Label(label="")
        self.spinner_label.set_margin_start(6)
        self.spinner_label.set_visible(False)
        self.box.append(self.spinner_label)

        self.title_label = Gtk.Label(label="")
        self.title_label.set_margin_start(6)
        self.title_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.title_label.set_visible(False)
        self.title_label.add_css_class("dim-label")
        self.box.append(self.title_label)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        self.box.append(spacer)

        self.clear_btn = ZenButton(icon=Icons.TRASH, tooltip="Clear")
        self.box.append(self.clear_btn)

        self.add_btn = ZenButton(icon=Icons.PLUS, tooltip="New AI chat")
        self.box.append(self.add_btn)

        self.maximize_btn = ZenButton(icon=Icons.MAXIMIZE, tooltip="Maximize")
        self.box.append(self.maximize_btn)

        self.apply_header_font()

    def set_label(self, label: str) -> None:
        """Update the CLI name shown in the header button."""
        child = self.header_btn.get_child()
        if child and hasattr(child, "set_text"):
            child.set_text(f"{label} ▾")

    def apply_header_font(self) -> None:
        """Apply terminal font to the header button label."""
        from fonts import get_font_settings

        font_settings = get_font_settings("terminal")
        family = font_settings["family"]

        label = self.header_btn.get_child()
        if label and hasattr(label, "set_attributes"):
            attr_list = Pango.AttrList()
            attr_list.insert(Pango.attr_family_new(family))
            attr_list.insert(Pango.attr_underline_new(Pango.Underline.NONE))
            label.set_attributes(attr_list)
