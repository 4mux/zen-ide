"""
Neovim-style save confirmation popup for Zen IDE.
"""

from gi.repository import Gdk, Gtk

from popups.nvim_popup import NvimPopup


class SaveConfirmPopup(NvimPopup):
    """
    Neovim-style save confirmation popup.

    Shows a prompt asking if user wants to save, discard, or cancel
    when closing an unsaved file.
    """

    def __init__(
        self,
        parent: Gtk.Window,
        filename: str = "Untitled",
        on_save=None,
        on_discard=None,
        on_cancel=None,
    ):
        self._filename = filename
        self._on_save = on_save
        self._on_discard = on_discard
        self._on_cancel = on_cancel
        super().__init__(parent, title="Unsaved Changes", width=400)

    def _create_content(self):
        """Create the save confirmation UI."""
        msg_label = self._create_message_label(f'Save changes to "{self._filename}"?')
        self._content_box.append(msg_label)

        detail_label = Gtk.Label(label="Your changes will be lost if you don't save them.")
        detail_label.set_halign(Gtk.Align.START)
        detail_label.add_css_class("nvim-popup-hint")
        detail_label.set_margin_top(4)
        self._content_box.append(detail_label)

        button_box, btns = self._create_button_row(
            ("Cancel", self._do_cancel),
            ("Don't Save", self._do_discard),
            ("Save", self._do_save, {"primary": True}),
        )
        self._cancel_btn, self._discard_btn, self._save_btn = btns
        self._content_box.append(button_box)

        hint_label = Gtk.Label(label="c/Esc=cancel  d=don't save  s/Enter=save  Tab=switch")
        hint_label.add_css_class("nvim-popup-hint")
        hint_label.set_halign(Gtk.Align.CENTER)
        hint_label.set_margin_top(12)
        self._content_box.append(hint_label)

    def _on_key_pressed(self, controller, keyval, keycode, state) -> bool:
        """Handle key press."""
        if keyval == Gdk.KEY_Escape or keyval == Gdk.KEY_c or keyval == Gdk.KEY_C:
            self._do_cancel()
            return True
        elif keyval in (Gdk.KEY_d, Gdk.KEY_D):
            self._do_discard()
            return True
        elif keyval in (Gdk.KEY_s, Gdk.KEY_S, Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._do_save()
            return True
        return self._handle_button_navigation(keyval, state)

    def _do_save(self):
        """Execute save action."""
        self._close_with_result("save", self._on_save)

    def _do_discard(self):
        """Execute don't save action."""
        self._close_with_result("discard", self._on_discard)

    def _do_cancel(self):
        """Execute cancel action."""
        self._close_with_result("cancel", self._on_cancel)

    def present(self):
        """Show the dialog and focus the Save button."""
        super().present()
        self._save_btn.grab_focus()


def show_save_confirm(
    parent: Gtk.Window,
    filename: str = "Untitled",
    on_save=None,
    on_discard=None,
    on_cancel=None,
):
    """
    Show a save confirmation popup.

    Args:
        parent: Parent window
        filename: Name of the file being closed
        on_save: Callback when Save is selected
        on_discard: Callback when Don't Save is selected
        on_cancel: Callback when Cancel is selected

    Returns:
        The SaveConfirmPopup instance, or None for system-style dialog
    """
    from popups.system_dialogs import is_nvim_mode

    if not is_nvim_mode():
        from popups.system_dialogs import system_save_confirm

        system_save_confirm(parent, filename, on_save, on_discard, on_cancel)
        return None
    popup = SaveConfirmPopup(parent, filename, on_save, on_discard, on_cancel)
    popup.present()
    return popup
