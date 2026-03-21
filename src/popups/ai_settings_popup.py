"""
AI Settings Popup for Zen IDE.

NvimPopup-based dialog with two combo boxes:
1. CLI Provider selector (Claude CLI, Copilot CLI)
2. Model selector (populated based on selected provider)
"""

import threading

from gi.repository import Gdk, GLib, Gtk

from popups.nvim_popup import NvimPopup

# Provider constants
PROVIDER_CLAUDE_CLI = "claude_cli"
PROVIDER_COPILOT_CLI = "copilot_cli"

# Display names for providers
_PROVIDER_DISPLAY = {
    PROVIDER_CLAUDE_CLI: "Claude CLI",
    PROVIDER_COPILOT_CLI: "Copilot CLI",
}


def _get_provider_availability() -> dict[str, bool]:
    """Check which providers are available."""
    from ai.ai_terminal_view import _find_claude_binary, _find_copilot_binary

    return {
        PROVIDER_CLAUDE_CLI: _find_claude_binary() is not None,
        PROVIDER_COPILOT_CLI: _find_copilot_binary() is not None,
    }


def _fetch_models_for_provider(provider: str) -> list[str]:
    """Fetch available models for a provider."""
    if provider == PROVIDER_CLAUDE_CLI:
        from ai.ai_terminal_view import _CLAUDE_MODELS

        return list(_CLAUDE_MODELS)
    elif provider == PROVIDER_COPILOT_CLI:
        from ai.ai_terminal_view import _COPILOT_MODELS

        return list(_COPILOT_MODELS)
    return []


class AISettingsPopup(NvimPopup):
    """Popup with two combo boxes for selecting AI provider and model."""

    def __init__(
        self,
        parent: Gtk.Window,
        current_provider: str,
        current_model: str,
        provider_availability: dict[str, bool],
        on_provider_changed=None,
        on_model_changed=None,
    ):
        self._current_provider = current_provider
        self._current_model = current_model
        self._provider_availability = provider_availability
        self._on_provider_changed = on_provider_changed
        self._on_model_changed = on_model_changed

        # Build ordered provider list
        self._provider_ids = [
            PROVIDER_CLAUDE_CLI,
            PROVIDER_COPILOT_CLI,
        ]

        # Current model list for the selected provider
        self._model_list: list[str] = []
        self._models_fetching = False

        super().__init__(parent, "AI Settings", width=420)

    def _create_content(self):
        """Create the popup content with two combo boxes."""

        # --- Provider combo box ---
        provider_label = Gtk.Label(label="Provider")
        provider_label.set_halign(Gtk.Align.START)
        provider_label.add_css_class("nvim-popup-hint")
        self._content_box.append(provider_label)

        # Build provider display labels
        provider_labels = []
        selected_provider_idx = 0
        for i, pid in enumerate(self._provider_ids):
            label = _PROVIDER_DISPLAY.get(pid, pid)
            if not self._provider_availability.get(pid, False):
                label += "  (not installed)"
            provider_labels.append(label)
            if pid == self._current_provider:
                selected_provider_idx = i

        self._provider_dropdown = Gtk.DropDown.new_from_strings(provider_labels)
        self._provider_dropdown.set_selected(selected_provider_idx)
        self._provider_dropdown.set_tooltip_text("Select AI provider")
        self._provider_dropdown.set_hexpand(True)
        self._content_box.append(self._provider_dropdown)

        # --- Model combo box ---
        model_label = Gtk.Label(label="Model")
        model_label.set_halign(Gtk.Align.START)
        model_label.add_css_class("nvim-popup-hint")
        model_label.set_margin_top(12)
        self._content_box.append(model_label)

        # Start with "Loading…" placeholder, then fetch real models
        self._model_list = []
        self._model_dropdown = Gtk.DropDown.new_from_strings(["Loading models…"])
        self._model_dropdown.set_sensitive(False)
        self._model_dropdown.set_tooltip_text("Select model")
        self._content_box.append(self._model_dropdown)

        # Connect signals AFTER initial selection to avoid spurious callbacks
        self._provider_dropdown.connect("notify::selected", self._on_provider_selection_changed)
        self._model_dropdown.connect("notify::selected", self._on_model_selection_changed)

        # Hint bar
        hint_bar = self._create_hint_bar([("Esc", "close")])
        hint_bar.set_halign(Gtk.Align.END)
        hint_bar.set_margin_top(12)
        self._content_box.append(hint_bar)

        # Fetch real models in background
        self._fetch_models_async(self._current_provider)

    def _select_model_in_dropdown(self, model_name: str):
        """Select a model in the model dropdown by name."""
        if not self._model_list:
            return
        try:
            idx = self._model_list.index(model_name)
            self._model_dropdown.set_selected(idx)
        except ValueError:
            # Model not in list — select first
            self._model_dropdown.set_selected(0)

    def _rebuild_model_dropdown(self, models: list[str], select_model: str = None):
        """Rebuild the model dropdown with a new list of models."""
        self._model_list = models
        labels = models if models else ["(no models)"]

        # Block the signal handler while rebuilding
        self._model_dropdown.disconnect_by_func(self._on_model_selection_changed)

        string_list = Gtk.StringList.new(labels)
        self._model_dropdown.set_model(string_list)

        if select_model:
            self._select_model_in_dropdown(select_model)
        elif models:
            self._model_dropdown.set_selected(0)

        # Reconnect signal
        self._model_dropdown.connect("notify::selected", self._on_model_selection_changed)

    def _fetch_models_async(self, provider: str):
        """Fetch models for a provider in a background thread."""
        if self._models_fetching:
            return
        self._models_fetching = True

        def fetch():
            models = _fetch_models_for_provider(provider)
            GLib.idle_add(self._on_models_fetched, provider, models)

        threading.Thread(target=fetch, daemon=True).start()

    def _on_models_fetched(self, provider: str, models: list[str]):
        """Handle fetched models (main thread)."""
        self._models_fetching = False

        # Only update if still showing the same provider
        selected_idx = self._provider_dropdown.get_selected()
        if selected_idx < len(self._provider_ids) and self._provider_ids[selected_idx] == provider:
            if models:
                self._model_dropdown.set_sensitive(True)
                self._rebuild_model_dropdown(models, self._current_model)
            else:
                # No models — show error state
                self._model_list = []
                self._model_dropdown.disconnect_by_func(self._on_model_selection_changed)
                string_list = Gtk.StringList.new(["(failed to load models)"])
                self._model_dropdown.set_model(string_list)
                self._model_dropdown.set_selected(0)
                self._model_dropdown.set_sensitive(False)
                self._model_dropdown.connect("notify::selected", self._on_model_selection_changed)

    def _on_provider_selection_changed(self, dropdown, _param):
        """Handle provider combo box selection change."""
        selected_idx = dropdown.get_selected()
        if selected_idx >= len(self._provider_ids):
            return

        new_provider = self._provider_ids[selected_idx]

        if new_provider == self._current_provider:
            return

        self._current_provider = new_provider

        # Show loading state while fetching models
        self._model_list = []
        self._model_dropdown.disconnect_by_func(self._on_model_selection_changed)
        string_list = Gtk.StringList.new(["Loading models…"])
        self._model_dropdown.set_model(string_list)
        self._model_dropdown.set_selected(0)
        self._model_dropdown.set_sensitive(False)
        self._model_dropdown.connect("notify::selected", self._on_model_selection_changed)

        # Fetch real models in background
        self._fetch_models_async(new_provider)

        # Notify callback
        if self._on_provider_changed:
            self._on_provider_changed(new_provider)

    def _on_model_selection_changed(self, dropdown, _param):
        """Handle model combo box selection change."""
        selected_idx = dropdown.get_selected()
        if not self._model_list or selected_idx >= len(self._model_list):
            return

        new_model = self._model_list[selected_idx]
        if new_model == self._current_model:
            return

        self._current_model = new_model

        if self._on_model_changed:
            self._on_model_changed(new_model)

    def _on_focus_leave(self, controller):
        """Override to prevent close when dropdown popover takes focus."""
        GLib.timeout_add(100, self._check_focus_and_close)

    def _check_active_and_close(self):
        """Override: don't close while a dropdown popover is open."""
        if self._closing:
            return False
        if self.get_property("is-active"):
            return False
        for dropdown in (self._provider_dropdown, self._model_dropdown):
            popover = self._find_popover(dropdown)
            if popover is not None and popover.get_visible():
                return False
        return super()._check_active_and_close()

    def _check_focus_and_close(self):
        """Close only if focus has truly left this dialog (not to a dropdown popover)."""
        if self._closing:
            return False
        # Focus is still inside this window
        if self.get_focus() is not None or self.is_active():
            return False
        # Check if either dropdown's internal popover is currently visible
        for dropdown in (self._provider_dropdown, self._model_dropdown):
            popover = self._find_popover(dropdown)
            if popover is not None and popover.get_visible():
                GLib.timeout_add(200, self._check_focus_and_close)
                return False
        self._result = None
        self.close()
        return False

    @staticmethod
    def _find_popover(widget):
        """Recursively find a Gtk.Popover in the widget's child tree."""
        child = widget.get_first_child()
        while child:
            if isinstance(child, Gtk.Popover):
                return child
            found = AISettingsPopup._find_popover(child)
            if found:
                return found
            child = child.get_next_sibling()
        return None

    def _on_key_pressed(self, controller, keyval, keycode, state) -> bool:
        """Handle key press."""
        if keyval == Gdk.KEY_Escape:
            self._result = None
            self.close()
            return True
        return False

    def present(self):
        """Show the dialog."""
        super().present()
        self._provider_dropdown.grab_focus()

    def update_provider_availability(self, availability: dict[str, bool]):
        """Update provider availability."""
        self._provider_availability = availability

        # Rebuild provider labels
        provider_labels = []
        for pid in self._provider_ids:
            label = _PROVIDER_DISPLAY.get(pid, pid)
            if not availability.get(pid, False):
                label += "  (not installed)"
            provider_labels.append(label)

        # Block signal, rebuild, reselect, reconnect
        self._provider_dropdown.disconnect_by_func(self._on_provider_selection_changed)
        string_list = Gtk.StringList.new(provider_labels)
        self._provider_dropdown.set_model(string_list)

        try:
            idx = self._provider_ids.index(self._current_provider)
            self._provider_dropdown.set_selected(idx)
        except ValueError:
            pass

        self._provider_dropdown.connect("notify::selected", self._on_provider_selection_changed)


def show_ai_settings(
    parent: Gtk.Window,
    current_provider: str,
    current_model: str,
    provider_availability: dict[str, bool],
    on_provider_changed=None,
    on_model_changed=None,
) -> AISettingsPopup:
    """Show the AI settings popup.

    Args:
        parent: Parent window.
        current_provider: Currently selected provider ID.
        current_model: Currently selected model name.
        provider_availability: Dict mapping provider ID → bool.
        on_provider_changed: Callback(provider_id) when provider changes.
        on_model_changed: Callback(model_name) when model changes.

    Returns:
        The popup instance.
    """
    popup = AISettingsPopup(
        parent=parent,
        current_provider=current_provider,
        current_model=current_model,
        provider_availability=provider_availability,
        on_provider_changed=on_provider_changed,
        on_model_changed=on_model_changed,
    )
    popup.present()
    return popup
