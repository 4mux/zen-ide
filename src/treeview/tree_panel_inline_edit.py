"""
CustomTreePanel inline editing mixin.
"""

from typing import Callable, Optional

from gi.repository import Gdk, GLib, Gtk

from shared.ui.zen_entry import ZenEntry
from themes import get_theme


class TreePanelInlineEditMixin:
    """Mixin providing inline-editing methods for CustomTreePanel."""

    def start_inline_edit(
        self,
        item,
        initial_text: str = "",
        on_confirm: Optional[Callable[[str], None]] = None,
        on_cancel: Optional[Callable[[], None]] = None,
        select_without_extension: bool = False,
    ):
        """Start inline editing for a tree item.

        Args:
            item: The tree item to edit
            initial_text: Initial text in the entry
            on_confirm: Callback when user confirms (with new text)
            on_cancel: Callback when user cancels
            select_without_extension: If True, select name without extension
        """
        # Cancel any existing inline edit
        self._cancel_inline_edit()

        self._inline_item = item
        self._inline_on_confirm = on_confirm
        self._inline_on_cancel = on_cancel

        # Create the entry widget — ZenEntry handles font via explorer context
        self._inline_entry = ZenEntry(initial_value=initial_text, font_context="explorer")

        # Additional tree-specific styling (border, background, sizing)
        theme = get_theme()
        border_px = 1
        padding_left_px = 2
        css = f"""
            entry {{
                background-color: {theme.main_bg};
                border: {border_px}px solid {theme.accent_color};
                outline: none;
                padding: 0px {padding_left_px}px;
                margin: 0px;
                min-height: {self.row_height - 2 * border_px}px;
            }}
            entry:focus-within {{
                outline: none;
                border: {border_px}px solid {theme.accent_color};
            }}
        """
        provider = Gtk.CssProvider()
        provider.load_from_string(css)
        self._inline_entry.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # Connect activate signal for Enter key
        self._inline_entry.connect("activate", self._on_inline_activate)

        # Handle Escape key using key-release signal which doesn't interfere with IM
        key_ctrl = Gtk.EventControllerKey.new()
        key_ctrl.connect("key-released", self._on_inline_key_released)
        self._inline_entry.add_controller(key_ctrl)

        # Connect focus-out to cancel
        focus_ctrl = Gtk.EventControllerFocus.new()
        focus_ctrl.connect("leave", self._on_inline_focus_out)
        self._inline_entry.add_controller(focus_ctrl)

        # Calculate position
        if item in self.items:
            index = self.items.index(item)
            y = index * self.row_height

            # Mirror the renderer's x calculation exactly:
            # depth>0: _draw_indent_guides returns LEFT_PADDING + (depth+1)*INDENT_WIDTH
            # depth==0: x stays at LEFT_PADDING
            x = self.LEFT_PADDING
            if item.depth > 0:
                x += (item.depth + 1) * self.INDENT_WIDTH
            x += self.INDENT_WIDTH  # Chevron space
            x += self._icon_column_width  # Icon

            # Shift left by entry border+padding so text inside aligns with rendered text
            entry_x = int(x) - border_px - padding_left_px
            entry_width = max(200, self.drawing_area.get_width() - entry_x)

            self._inline_entry.set_halign(Gtk.Align.START)
            self._inline_entry.set_valign(Gtk.Align.START)
            self._inline_entry.set_margin_start(entry_x)
            self._inline_entry.set_margin_top(int(y))
            self._inline_entry.set_size_request(entry_width, self.row_height)

            # Add to overlay
            self._overlay.add_overlay(self._inline_entry)

            # Focus first, then set selection (combined to avoid focus resetting selection)
            select_end = initial_text.rfind(".") if (select_without_extension and "." in initial_text) else -1

            def _do_focus_and_select():
                if self._inline_entry:
                    self._inline_entry.grab_focus()
                    self._inline_entry.select_region(0, select_end)
                return False

            GLib.idle_add(_do_focus_and_select)

    def _on_inline_activate(self, entry):
        """Handle Enter key via activate signal."""
        self._confirm_inline_edit()

    def _on_inline_key_released(self, controller, keyval, keycode, state):
        """Handle Escape key release in inline entry."""
        if keyval == Gdk.KEY_Escape:
            self._cancel_inline_edit()
            return True
        return False

    def _on_inline_focus_out(self, controller):
        """Handle focus leaving inline entry."""
        GLib.idle_add(lambda: self._cancel_inline_edit() or False)

    def _confirm_inline_edit(self):
        """Confirm inline edit and call callback."""
        if not self._inline_entry:
            return

        text = self._inline_entry.get_text().strip()

        vadj = self.get_vadjustment()
        saved_scroll = vadj.get_value() if vadj else 0

        self.drawing_area.grab_focus()

        on_confirm = self._inline_on_confirm
        self._cleanup_inline_edit()

        if on_confirm:
            on_confirm(text)

        if vadj:
            vadj.set_value(saved_scroll)
            GLib.idle_add(lambda: vadj.set_value(saved_scroll) or False)

    def _cancel_inline_edit(self):
        """Cancel inline edit and call callback."""
        if not self._inline_entry:
            return

        vadj = self.get_vadjustment()
        saved_scroll = vadj.get_value() if vadj else 0

        # Move focus to drawing area BEFORE removing the entry widget.
        # Removing a focused widget causes GTK to auto-transfer focus,
        # which resets the ScrolledWindow scroll position to 0.
        self.drawing_area.grab_focus()

        on_cancel = self._inline_on_cancel
        self._cleanup_inline_edit()

        if on_cancel:
            on_cancel()

        # Double restore: sync handles immediate layout, idle catches deferred
        if vadj:
            vadj.set_value(saved_scroll)
            GLib.idle_add(lambda: vadj.set_value(saved_scroll) or False)

    def _cleanup_inline_edit(self):
        """Remove inline entry widget."""
        if self._inline_entry:
            self._overlay.remove_overlay(self._inline_entry)
            self._inline_entry = None

        self._inline_item = None
        self._inline_on_confirm = None
        self._inline_on_cancel = None
