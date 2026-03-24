"""
Neovim-style confirmation dialog for Zen IDE.
"""

from gi.repository import Gdk, Gtk

from popups.nvim_popup import NvimPopup


class ConfirmDialog(NvimPopup):
    """Neovim-style confirmation dialog with Yes/No options."""

    def __init__(
        self,
        parent: Gtk.Window,
        title: str = "Confirm",
        message: str = "",
        confirm_text: str = "Yes",
        cancel_text: str = "No",
        danger: bool = False,
        on_confirm=None,
        on_cancel=None,
    ):
        self._message = message
        self._confirm_text = confirm_text
        self._cancel_text = cancel_text
        self._danger = danger
        self._on_confirm = on_confirm
        self._on_cancel = on_cancel
        super().__init__(parent, title, width=400)

    def _create_content(self):
        """Create the confirmation dialog UI."""
        msg_label = self._create_message_label(self._message)
        self._content_box.append(msg_label)

        button_box, btns = self._create_button_row(
            (self._cancel_text, lambda: self._close_with_result(False, self._on_cancel)),
            (
                self._confirm_text,
                lambda: self._close_with_result(True, self._on_confirm),
                {"primary": not self._danger, "danger": self._danger},
            ),
        )
        self._cancel_btn, self._confirm_btn = btns
        self._content_box.append(button_box)

        hint_label = Gtk.Label(label="y/n or Tab to switch • Enter to confirm")
        hint_label.add_css_class("nvim-popup-hint")
        hint_label.set_halign(Gtk.Align.CENTER)
        hint_label.set_margin_top(12)
        self._content_box.append(hint_label)

    def _on_key_pressed(self, controller, keyval, keycode, state) -> bool:
        """Handle key press."""
        if keyval == Gdk.KEY_Escape or keyval == Gdk.KEY_n or keyval == Gdk.KEY_N:
            self._close_with_result(False, self._on_cancel)
            return True
        elif keyval == Gdk.KEY_Return or keyval == Gdk.KEY_y or keyval == Gdk.KEY_Y:
            self._close_with_result(True, self._on_confirm)
            return True
        elif keyval == Gdk.KEY_Tab:
            # Switch focus between buttons
            if self._confirm_btn.has_focus():
                self._cancel_btn.grab_focus()
            else:
                self._confirm_btn.grab_focus()
            return True
        return False

    def present(self):
        """Show the dialog and focus confirm button."""
        super().present()
        self._confirm_btn.grab_focus()


def show_confirm(
    parent: Gtk.Window,
    title: str = "Confirm",
    message: str = "",
    confirm_text: str = "Yes",
    cancel_text: str = "No",
    danger: bool = False,
    on_confirm=None,
    on_cancel=None,
):
    """Show a confirmation dialog and return it."""
    from popups.system_dialogs import is_nvim_mode

    if not is_nvim_mode():
        from popups.system_dialogs import system_confirm

        system_confirm(parent, title, message, confirm_text, cancel_text, danger, on_confirm, on_cancel)
        return None
    dialog = ConfirmDialog(parent, title, message, confirm_text, cancel_text, danger, on_confirm, on_cancel)
    dialog.present()
    return dialog
