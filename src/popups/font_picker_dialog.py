"""
Font picker dialog for Zen IDE.
Supports target selection and search.
"""

from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from gi.repository import Gdk, Gio, GLib, GObject, Gtk

from fonts import get_font_settings
from popups.nvim_context_menu import show_context_menu
from popups.nvim_popup import NvimPopup
from shared.utils import get_pango_font_map

_FOCUS_CHECK_DELAY_MS = 100


def _get_resources_fonts() -> List[str]:
    """Get font family names from the resources folder.

    Reads actual font family names registered with the OS font system
    (via CoreText on macOS, fontconfig on Linux).

    Returns:
        List of unique font family names found in resources.
    """
    resources_path = Path(__file__).parent.parent.parent / "resources"
    if not resources_path.exists():
        return []

    font_files = list(resources_path.glob("*.ttf")) + list(resources_path.glob("*.otf"))
    if not font_files:
        return []

    # Get the set of font stems from resource files (without weight suffix)
    resource_stems = set()
    for font_file in font_files:
        name = font_file.stem
        for suffix in (
            "-Bold",
            "-Light",
            "-Regular",
            "-Medium",
            "-Thin",
            "-ExtraBold",
            "-ExtraLight",
            "-SemiBold",
            "-Italic",
            "-BoldItalic",
            "-LightItalic",
            "-MediumItalic",
            "-ThinItalic",
            "-ExtraBoldItalic",
            "-ExtraLightItalic",
            "-SemiBoldItalic",
        ):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        resource_stems.add(name.lower())

    # Match against actual Pango font families
    font_families = set()
    try:
        font_map = get_pango_font_map()
        for family in font_map.list_families():
            family_name = family.get_name()
            # Check if this Pango family matches a resource font stem
            normalized = family_name.replace(" ", "").lower()
            if normalized in resource_stems:
                font_families.add(family_name)
    except Exception:
        pass

    return sorted(font_families)


def _get_all_system_fonts() -> List[str]:
    """Get all fonts available on the system.

    Returns:
        Sorted list of font family names.
    """
    try:
        font_map = get_pango_font_map()
        families = font_map.list_families()
        return sorted([f.get_name() for f in families], key=str.lower)
    except Exception:
        return []


def _get_all_fonts() -> List[str]:
    """Get combined list of all fonts (system + resources)."""
    fonts = set()

    # Add all system fonts
    fonts.update(_get_all_system_fonts())

    # Add resources fonts
    fonts.update(_get_resources_fonts())

    return sorted(fonts, key=str.lower)


class FontPickerDialog(NvimPopup):
    """Font picker dialog with target selection and searchable font list."""

    # Target definitions: (key, display_label)
    TARGETS = [
        ("editor", "Editor"),
        ("terminal", "Terminal"),
        ("explorer", "Explorer"),
        ("ai_chat", "AI Chat"),
        ("markdown_preview", "Markdown Preview"),
    ]

    def __init__(
        self,
        parent: Gtk.Window,
        on_apply: Optional[Callable[[str, str, int, str], None]] = None,
    ):
        """Initialize the font picker dialog.

        Args:
            parent: Parent window
            on_apply: Callback(family, weight, size, target_key) for live preview
        """
        self.on_apply = on_apply
        self._updating_ui = False
        self._preview_applied = False
        self._sub_popup = None

        # Store original settings for cancel/revert
        self.original_settings: Dict[str, Dict] = {}
        for key, _ in self.TARGETS:
            if key != "all":
                self.original_settings[key] = get_font_settings(key).copy()

        # Get all fonts and monospace set
        self.all_fonts = _get_all_fonts()
        self.filtered_fonts = list(self.all_fonts)

        # Create the font list store
        self._font_store = Gio.ListStore.new(FontItem)
        self._filter_model = None
        self._selection_model = None

        super().__init__(parent, title="Font Settings", width=500, height=550)

        self._load_current_selection()

    def _create_content(self):
        """Create the dialog UI."""

        # Target selection
        self._selected_target_idx = 0

        target_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        target_label = Gtk.Label(label="Apply to:")
        target_box.append(target_label)

        self._target_button = self._create_button(self.TARGETS[0][1])
        self._target_button.set_hexpand(True)
        self._target_button.connect("clicked", self._on_target_button_clicked)
        target_box.append(self._target_button)
        self._content_box.append(target_box)

        # Font family label
        family_label = Gtk.Label(label="Font Family:")
        family_label.set_halign(Gtk.Align.START)
        family_label.set_margin_top(8)
        self._content_box.append(family_label)

        # Search entry
        self.search_entry = self._create_search_entry("Search fonts...")
        self.search_entry.connect("search-changed", self._on_search_changed)
        self._content_box.append(self.search_entry)

        # Populate the font store
        for font in self.all_fonts:
            self._font_store.append(FontItem(font))

        # Create filter model
        self._filter_model = Gtk.FilterListModel(model=self._font_store)
        self._custom_filter = Gtk.CustomFilter.new(self._filter_func, None)
        self._filter_model.set_filter(self._custom_filter)

        # Create selection model
        self._selection_model = Gtk.SingleSelection(model=self._filter_model)
        self._selection_model.connect("selection-changed", self._on_font_selected)

        # Create list view with factory
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_factory_setup)
        factory.connect("bind", self._on_factory_bind)

        # Font list in scrolled window
        self.font_list = Gtk.ListView(model=self._selection_model, factory=factory)
        self.font_list.add_css_class("nvim-popup-list")

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(self.font_list)
        scroll.set_vexpand(True)
        scroll.set_min_content_height(200)
        scroll.set_max_content_height(250)
        self._content_box.append(scroll)

        # Size row
        size_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        size_box.set_margin_top(10)
        size_label = Gtk.Label(label="Size:")
        size_box.append(size_label)

        self.size_spin = Gtk.SpinButton()
        self.size_spin.set_range(6, 72)
        self.size_spin.set_increments(1, 5)
        self.size_spin.set_value(14)
        self.size_spin.connect("value-changed", self._on_size_changed)
        size_box.append(self.size_spin)

        self._content_box.append(size_box)

        # Button row
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        button_box.set_halign(Gtk.Align.CENTER)
        button_box.set_margin_top(8)

        cancel_btn = self._create_button("Cancel")
        cancel_btn.connect("clicked", self._on_cancel)
        button_box.append(cancel_btn)

        ok_btn = self._create_button("Apply", primary=True)
        ok_btn.connect("clicked", self._on_ok)
        button_box.append(ok_btn)

        self._content_box.append(button_box)

        # Focus search entry so typing works immediately
        self.search_entry.grab_focus()

    def _filter_func(self, item, user_data) -> bool:
        """Filter function for the font list."""
        search_text = self.search_entry.get_text().lower()
        if not search_text:
            return True
        return search_text in item.name.lower()

    def _on_factory_setup(self, factory, list_item):
        """Setup callback for list item factory."""
        name_label = Gtk.Label()
        name_label.set_halign(Gtk.Align.START)
        name_label.set_margin_start(10)
        name_label.set_margin_end(10)
        name_label.set_margin_top(4)
        name_label.set_margin_bottom(4)

        list_item.set_child(name_label)

    def _on_factory_bind(self, factory, list_item):
        """Bind callback for list item factory."""
        name_label = list_item.get_child()
        item = list_item.get_item()
        name_label.set_text(item.name)

    def _load_current_selection(self):
        """Load current font settings for the selected target."""
        self._updating_ui = True
        try:
            target_key = self.TARGETS[self._selected_target_idx][0]

            settings = get_font_settings(target_key)
            family = settings.get("family", "")
            size = settings.get("size", 14)

            # Select font in list
            if family:
                for i in range(self._filter_model.get_n_items()):
                    item = self._filter_model.get_item(i)
                    if item.name.lower() == family.lower():
                        self._selection_model.set_selected(i)
                        # Scroll to selection without stealing focus from search entry
                        GLib.idle_add(lambda pos=i: self.font_list.scroll_to(pos, Gtk.ListScrollFlags.NONE, None) or False)
                        break

            # Set size
            self.size_spin.set_value(size)
        finally:
            self._updating_ui = False

    def _on_target_button_clicked(self, button):
        """Show context menu for target selection."""
        # Create menu items in the correct format
        items = [{"label": label, "action": key} for key, label in self.TARGETS]

        # Get parent window
        parent_window = self.get_transient_for() or self.get_root()

        menu = show_context_menu(
            parent=parent_window,
            items=items,
            on_select=self._on_target_selected,
            source_widget=self._target_button,
            title="Apply to",
        )

        if menu:
            self._sub_popup = menu

            # Connect to the appropriate signal based on popup type
            from popups.nvim_popup import NvimPopup

            if isinstance(menu, NvimPopup):
                menu.connect("close-request", self._on_sub_popup_closing)
            else:
                # SystemContextMenu (Gtk.Popover) uses "closed" signal
                menu.connect("closed", self._on_sub_popup_closing)

    def _on_target_selected(self, action):
        """Handle target selection from context menu."""
        # Don't clear _sub_popup here - let the close signal handler do it
        for i, (key, label) in enumerate(self.TARGETS):
            if key == action:
                self._selected_target_idx = i
                self._target_button.set_label(label)
                self._load_current_selection()
                break

    def _on_sub_popup_closing(self, *args):
        """Handle sub-popup closing — clear reference and restore focus."""
        if not self._closing:
            # Delay clearing _sub_popup until after focus is restored to prevent race condition
            GLib.idle_add(self._restore_focus_and_clear_sub_popup)
        else:
            self._sub_popup = None
        return False

    def _restore_focus_and_clear_sub_popup(self):
        """Restore focus to search entry and clear sub-popup reference."""
        if not self._closing:
            self.search_entry.grab_focus()
        self._sub_popup = None
        return False

    def _on_search_changed(self, entry):
        """Filter font list based on search text."""
        # Reapply the filter
        self._custom_filter.changed(Gtk.FilterChange.DIFFERENT)

    def _on_font_selected(self, selection, position, n_items):
        """Handle font list selection change."""
        if not self._updating_ui:
            self._apply_preview()

    def _on_size_changed(self, spin):
        """Handle size spin change."""
        if not self._updating_ui:
            self._apply_preview()

    def _get_current_selection(self) -> Tuple[str, str, int]:
        """Get current font selection.

        Returns:
            Tuple of (family, weight, size)
        """
        # Family
        selected_pos = self._selection_model.get_selected()
        if selected_pos != Gtk.INVALID_LIST_POSITION:
            item = self._selection_model.get_selected_item()
            family = item.name if item else ""
        else:
            family = ""

        weight = "normal"

        # Size
        size = int(self.size_spin.get_value())

        return family, weight, size

    def _apply_preview(self):
        """Apply current selection as live preview."""
        if not self.on_apply or self._updating_ui:
            return

        family, weight, size = self._get_current_selection()
        if not family:
            return

        target_key = self.TARGETS[self._selected_target_idx][0]

        self._preview_applied = True
        self.on_apply(family, weight, size, target_key)

    def _on_ok(self, button):
        """Apply settings and close."""
        family, weight, size = self._get_current_selection()
        if family and self.on_apply:
            target_key = self.TARGETS[self._selected_target_idx][0]
            self.on_apply(family, weight, size, target_key)

        self.close()

    def _on_cancel(self, button):
        """Revert to original settings and close."""
        try:
            if self.on_apply and self._preview_applied:
                for target_key, settings in self.original_settings.items():
                    self.on_apply(
                        settings.get("family", ""),
                        settings.get("weight", "normal"),
                        settings.get("size", 14),
                        target_key,
                    )
        finally:
            self.close()

    def _on_focus_leave(self, controller):
        """Override to prevent close when dropdown/spinbutton popovers take focus."""
        # For font picker, we never auto-close on focus leave - only on ESC or button clicks
        # This prevents issues with the "Apply to" dropdown
        return

    def _on_active_changed(self, window, pspec):
        """Override to prevent auto-close when window loses active state."""
        # Don't auto-close for font picker - only manual close via buttons/ESC
        return

    def _check_active_and_close(self):
        """Override to prevent delayed close on inactive state."""
        # Don't auto-close for font picker
        return False

    def _check_focus_and_close(self):
        """Close only if focus has truly left this dialog."""
        if self._sub_popup is not None:
            return False
        if self.get_focus() is not None or self.is_active():
            return False
        self._result = None
        self.close()
        return False

    def _dismiss_click_outside(self):
        """Override to prevent close when sub-popup is open."""
        if self._sub_popup is not None:
            return False
        return super()._dismiss_click_outside()

    def _setup_keyboard(self):
        """Use CAPTURE phase so Escape is caught before child widgets consume it."""
        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Handle key presses - ESC to close, arrows for navigation."""
        if keyval == Gdk.KEY_Escape:
            self._on_cancel(None)
            return True
        elif keyval == Gdk.KEY_Down:
            self._move_selection(1)
            return True
        elif keyval == Gdk.KEY_Up:
            self._move_selection(-1)
            return True
        elif keyval == Gdk.KEY_Return:
            self._on_ok(None)
            return True

        # Redirect printable keys to search entry when list has focus
        if not self._has_text_entry_focus() and Gdk.keyval_to_unicode(keyval) > 0:
            self.search_entry.grab_focus()
            return False

        return False

    def _move_selection(self, delta: int):
        """Move font list selection up or down."""
        n_items = self._filter_model.get_n_items()
        if n_items == 0:
            return
        current = self._selection_model.get_selected()
        if current == Gtk.INVALID_LIST_POSITION:
            new_pos = 0
        else:
            new_pos = max(0, min(n_items - 1, current + delta))
        self._selection_model.set_selected(new_pos)
        self.font_list.scroll_to(new_pos, Gtk.ListScrollFlags.NONE, None)

    # Font popup fix: Override all auto-closing mechanisms to prevent
    # dialog from closing when "Apply to" combo box is clicked

    def _on_focus_leave(self):
        """Override to prevent auto-closing on focus leave."""
        return

    def _on_active_changed(self, window, active):
        """Override to prevent auto-closing on active state change."""
        return

    def _check_active_and_close(self):
        """Override to prevent delayed auto-closing."""
        return


class FontItem(GObject.Object):
    """A font item for the list store."""

    def __init__(self, name: str):
        super().__init__()
        self._name = name

    @property
    def name(self) -> str:
        return self._name


def show_font_picker(
    parent: Gtk.Window,
    on_apply: Optional[Callable[[str, str, int, str], None]] = None,
) -> None:
    """Show the font picker dialog.

    Args:
        parent: Parent window
        on_apply: Callback(family, weight, size, target_key) for live preview and apply
    """
    dialog = FontPickerDialog(parent, on_apply)
    dialog.present()
