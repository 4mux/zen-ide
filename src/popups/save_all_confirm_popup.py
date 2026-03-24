"""
Neovim-style save-all confirmation popup for Zen IDE.
"""

from gi.repository import Gdk, Gtk

from popups.nvim_popup import NvimPopup


class SaveAllConfirmPopup(NvimPopup):
    """
    Nvim-style popup for confirming save of multiple files on window close.
    Options: [s]ave All, [d]iscard All, [c]ancel
    """

    def __init__(
        self,
        parent: Gtk.Window,
        filenames: list[str],
        on_save_all=None,
        on_discard_all=None,
        on_cancel=None,
    ):
        self._filenames = filenames
        self._on_save_all = on_save_all
        self._on_discard_all = on_discard_all
        self._on_cancel = on_cancel
        super().__init__(parent, title="Unsaved Changes", width=450, height=-1)

    def _create_content(self):
        """Create the save-all confirmation UI."""
        msg_label = Gtk.Label()
        msg_label.set_markup("<b>Save changes before closing?</b>")
        msg_label.set_halign(Gtk.Align.START)
        self._content_box.append(msg_label)

        # File list (max 5, then "and N more...")
        if len(self._filenames) <= 5:
            files_text = "\n".join(f"  • {f}" for f in self._filenames)
        else:
            files_text = "\n".join(f"  • {f}" for f in self._filenames[:5])
            files_text += f"\n  ... and {len(self._filenames) - 5} more"

        files_label = Gtk.Label(label=files_text)
        files_label.set_halign(Gtk.Align.START)
        files_label.set_margin_top(8)
        files_label.add_css_class("dim-label")
        self._content_box.append(files_label)

        button_box, btns = self._create_button_row(
            ("[S]ave All", self._do_save_all, {"primary": True}),
            ("[D]iscard All", self._do_discard_all, {"danger": True}),
            ("[C]ancel", self._do_cancel),
            default_focus=0,
        )
        self._save_btn, self._discard_btn, self._cancel_btn = btns
        self._content_box.append(button_box)

        hint_bar = self._create_hint_bar([("s", "Save All"), ("d", "Discard All"), ("c/Esc", "Cancel"), ("Tab", "Switch")])
        self._content_box.append(hint_bar)

    def _on_key_pressed(self, controller, keyval, keycode, state) -> bool:
        """Handle key press."""
        if keyval == Gdk.KEY_Escape or keyval == Gdk.KEY_c or keyval == Gdk.KEY_C:
            self._do_cancel()
            return True
        elif keyval in (Gdk.KEY_s, Gdk.KEY_S, Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._do_save_all()
            return True
        elif keyval == Gdk.KEY_d or keyval == Gdk.KEY_D:
            self._do_discard_all()
            return True
        return self._handle_button_navigation(keyval, state)

    def _do_save_all(self):
        """Execute save all action."""
        self._close_with_result("save_all", self._on_save_all)

    def _do_discard_all(self):
        """Execute discard all action."""
        self._close_with_result("discard_all", self._on_discard_all)

    def _do_cancel(self):
        """Execute cancel action."""
        self._close_with_result("cancel", self._on_cancel)

    def present(self):
        super().present()
        self._save_btn.grab_focus()


def show_save_all_confirm(
    parent: Gtk.Window,
    filenames: list[str],
    on_save_all=None,
    on_discard_all=None,
    on_cancel=None,
):
    """
    Show a save-all confirmation popup for multiple unsaved files.

    Args:
        parent: Parent window
        filenames: List of unsaved file names
        on_save_all: Callback when Save All is selected
        on_discard_all: Callback when Discard All is selected
        on_cancel: Callback when Cancel is selected

    Returns:
        The SaveAllConfirmPopup instance, or None for system-style dialog
    """
    from popups.system_dialogs import is_nvim_mode

    if not is_nvim_mode():
        from popups.system_dialogs import system_save_all_confirm

        system_save_all_confirm(parent, filenames, on_save_all, on_discard_all, on_cancel)
        return None
    popup = SaveAllConfirmPopup(parent, filenames, on_save_all, on_discard_all, on_cancel)
    popup.present()
    return popup
