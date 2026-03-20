"""
AI Settings Popup for Zen IDE.

NvimPopup-based dialog with two combo boxes:
1. API Provider selector (Anthropic, Copilot)
2. Model selector (populated based on selected provider)
"""

import datetime
import threading

from gi.repository import Gdk, GLib, Gtk

from popups.nvim_popup import NvimPopup

# Provider constants
PROVIDER_ANTHROPIC_API = "anthropic_api"
PROVIDER_COPILOT_API = "copilot_api"

# Display names for providers
_PROVIDER_DISPLAY = {
    PROVIDER_COPILOT_API: "Copilot API",
    PROVIDER_ANTHROPIC_API: "Anthropic API",
}


def _get_provider_availability() -> dict[str, bool]:
    """Check which providers have API keys configured."""
    from ai import AnthropicHTTPProvider, CopilotHTTPProvider

    return {
        PROVIDER_COPILOT_API: CopilotHTTPProvider().is_available,
        PROVIDER_ANTHROPIC_API: AnthropicHTTPProvider().is_available,
    }


def _fetch_models_for_provider(provider: str) -> list[str]:
    """Fetch available models for a provider (may do network I/O)."""
    from ai import AnthropicHTTPProvider, CopilotHTTPProvider

    if provider == PROVIDER_ANTHROPIC_API:
        return AnthropicHTTPProvider().get_available_models()
    elif provider == PROVIDER_COPILOT_API:
        return CopilotHTTPProvider().get_available_models()
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
        on_setup_api_key=None,
    ):
        """
        Args:
            parent: Parent window.
            current_provider: Currently selected provider ID.
            current_model: Currently selected model name.
            provider_availability: Dict mapping provider ID → bool (key configured).
            on_provider_changed: Callback(provider_id) when provider changes.
            on_model_changed: Callback(model_name) when model changes.
            on_setup_api_key: Callback(provider_id) to open API key setup.
        """
        self._current_provider = current_provider
        self._current_model = current_model
        self._provider_availability = provider_availability
        self._on_provider_changed = on_provider_changed
        self._on_model_changed = on_model_changed
        self._on_setup_api_key = on_setup_api_key

        # Build ordered provider list
        self._provider_ids = [
            PROVIDER_COPILOT_API,
            PROVIDER_ANTHROPIC_API,
        ]

        # Current model list for the selected provider
        self._model_list: list[str] = []
        self._models_fetching = False
        self._status_dialog_open = False
        self._status_popup = None

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
                label += "  ⚙ setup"
            provider_labels.append(label)
            if pid == self._current_provider:
                selected_provider_idx = i

        # Horizontal row: provider dropdown + auth button
        provider_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._content_box.append(provider_row)

        self._provider_dropdown = Gtk.DropDown.new_from_strings(provider_labels)
        self._provider_dropdown.set_selected(selected_provider_idx)
        self._provider_dropdown.set_tooltip_text("Select AI provider")
        self._provider_dropdown.set_hexpand(True)
        provider_row.append(self._provider_dropdown)

        # Authorize / API Key Setup button (on the right of the provider dropdown)
        self._auth_btn = Gtk.Button(label="Auth")
        self._auth_btn.add_css_class("nvim-popup-button")
        self._auth_btn.set_tooltip_text("Authorize / API Key Setup")
        self._auth_btn.connect("clicked", self._on_auth_clicked)
        provider_row.append(self._auth_btn)

        # New: Show status / usage button
        self._status_btn = Gtk.Button(label="Show usage")
        self._status_btn.add_css_class("nvim-popup-button")
        self._status_btn.set_tooltip_text("Show provider usage / credits / limits")
        self._status_btn.connect("clicked", self._on_status_clicked)
        provider_row.append(self._status_btn)

        # Setup button (shown only when provider needs API key)
        self._setup_btn = Gtk.Button(label="  Configure API Key…")
        self._setup_btn.add_css_class("nvim-popup-button")
        self._setup_btn.set_halign(Gtk.Align.START)
        self._setup_btn.set_margin_top(4)
        needs_setup = not self._provider_availability.get(self._current_provider, False)
        self._setup_btn.set_visible(needs_setup)
        self._setup_btn.connect("clicked", self._on_setup_clicked)
        self._content_box.append(self._setup_btn)

        # --- Model combo box ---
        model_label = Gtk.Label(label="Model")
        model_label.set_halign(Gtk.Align.START)
        model_label.add_css_class("nvim-popup-hint")
        model_label.set_margin_top(12)
        self._content_box.append(model_label)

        # Start with "Loading…" placeholder, then fetch real models from API
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

        # Update auth button / status for current provider
        self._update_auth_and_status_buttons()

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
                # API returned no models — show error state
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

        # Update setup button visibility
        needs_setup = not self._provider_availability.get(new_provider, False)
        self._setup_btn.set_visible(needs_setup)

        if new_provider == self._current_provider:
            return

        self._current_provider = new_provider

        # Show loading state while fetching models from API
        self._model_list = []
        self._model_dropdown.disconnect_by_func(self._on_model_selection_changed)
        string_list = Gtk.StringList.new(["Loading models…"])
        self._model_dropdown.set_model(string_list)
        self._model_dropdown.set_selected(0)
        self._model_dropdown.set_sensitive(False)
        self._model_dropdown.connect("notify::selected", self._on_model_selection_changed)

        # Fetch real models in background
        self._fetch_models_async(new_provider)

        # If provider needs setup, open API key popup
        if needs_setup and self._on_setup_api_key:
            self._on_setup_api_key(new_provider)
            return

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

    def _on_setup_clicked(self, button):
        """Handle setup button click."""
        if self._on_setup_api_key:
            self._on_setup_api_key(self._current_provider)

    def _on_auth_clicked(self, button):
        """Handle authorize / API key setup button click."""
        if self._on_setup_api_key:
            self._on_setup_api_key(self._current_provider)

    def _on_status_clicked(self, button):
        """Show provider usage/credits/limits in a small popup."""
        # Determine provider
        selected_idx = self._provider_dropdown.get_selected()
        if selected_idx < len(self._provider_ids):
            provider = self._provider_ids[selected_idx]
        else:
            provider = self._current_provider

        # Track that a child dialog is open so _check_focus_and_close
        # doesn't dismiss us while the status popup has focus.
        self._status_dialog_open = True

        # Fetch info in background to avoid blocking UI
        def fetch_and_show():
            info = self._gather_provider_status(provider)
            GLib.idle_add(self._show_status_dialog, provider, info)

        threading.Thread(target=fetch_and_show, daemon=True).start()

    def _update_auth_and_status_buttons(self):
        """Update auth/config visibility and status button sensitivity."""
        needs_setup = not self._provider_availability.get(self._current_provider, False)
        self._setup_btn.set_visible(needs_setup)
        # Auth button only for providers that support interactive auth (Copilot)
        copilot_idx = self._provider_ids.index(PROVIDER_COPILOT_API)
        # If provider is copilot, enable auth otherwise disable
        selected_idx = self._provider_dropdown.get_selected()
        if selected_idx < len(self._provider_ids) and self._provider_ids[selected_idx] == PROVIDER_COPILOT_API:
            self._auth_btn.set_sensitive(True)
        else:
            self._auth_btn.set_sensitive(False)

        # Status button only enabled if provider available or supports querying
        self._status_btn.set_sensitive(True)

    def _gather_provider_status(self, provider: str) -> dict:
        """Collect provider-specific status. This may perform network requests.

        Additionally, gather lightweight usage/debug information from the local
        ai_debug_log (if available). This provides recent request counts,
        requested max_tokens and response character totals so the popup can show
        an approximate usage summary even when provider billing APIs aren't used.
        """
        from ai import AnthropicHTTPProvider, CopilotHTTPProvider

        status = {"provider": provider, "checked_at": datetime.datetime.utcnow().isoformat() + "Z"}
        try:
            if provider == PROVIDER_ANTHROPIC_API:
                p = AnthropicHTTPProvider()
                status["available"] = p.is_available
                # Try to fetch models as a lightweight API call to verify key and list models
                try:
                    models = p.get_available_models()
                    status["models_count"] = len(models)
                    status["models"] = models[:5]
                except Exception as e:
                    status["models_error"] = str(e)
            elif provider == PROVIDER_COPILOT_API:
                p = CopilotHTTPProvider()
                status["available"] = p.is_available
                try:
                    models = p.get_available_models()
                    status["models_count"] = len(models)
                    status["models"] = models[:5]
                except Exception as e:
                    status["models_error"] = str(e)

                # If Copilot session token caching is present, surface expiry info
                try:
                    expires_at = getattr(CopilotHTTPProvider, "_shared_token_expires_at", 0)
                    session_token = getattr(CopilotHTTPProvider, "_shared_session_token", None)
                    if session_token and expires_at:
                        import time

                        remaining = int(expires_at - time.time())
                        status["copilot_session_expires_in_s"] = max(0, remaining)
                except Exception:
                    pass
            else:
                status["available"] = False
        except Exception as exc:
            status["error"] = str(exc)

        # Augment with recent request/stream summary from ai_debug_log if present.
        try:
            from shared.ai_debug_log import get_ai_debug_log_path

            log_path = get_ai_debug_log_path()
            if log_path and log_path.exists():
                raw = log_path.read_text(encoding="utf-8")
                lines = raw.strip().splitlines()[-1000:]

                total_requests = 0
                total_max_tokens = 0
                total_response_chars = 0
                recent = []

                for ln in lines:
                    # Simple timestamp prefix removal for recent display
                    display_ln = ln
                    if "REQUEST" in ln and f"provider={provider}" in ln:
                        total_requests += 1
                        # Extract max_tokens=N
                        try:
                            if "max_tokens=" in ln:
                                part = ln.split("max_tokens=")[-1].split()[0]
                                total_max_tokens += int(part)
                        except Exception:
                            pass
                        recent.append(display_ln)
                    elif "STREAM_END" in ln and f"provider={provider}" in ln:
                        # Example: ... response_chars=4096 ...
                        try:
                            if "response_chars=" in ln:
                                part = ln.split("response_chars=")[-1].split()[0]
                                total_response_chars += int(part)
                        except Exception:
                            pass
                        recent.append(display_ln)

                status["debug_log"] = {
                    "path": str(log_path),
                    "total_requests": total_requests,
                    "total_max_tokens": total_max_tokens,
                    "total_response_chars": total_response_chars,
                    "recent": recent[-8:],
                }
        except Exception:
            # If anything goes wrong parsing the log, just skip debug info
            pass

        return status

    def _show_status_dialog(self, provider: str, info: dict):
        """Display collected status in a NvimPopup-based dialog.

        Uses the standard NvimPopup base class instead of the deprecated
        Gtk.MessageDialog to avoid focus/modal grab issues in GTK4.
        """
        # Build message text
        lines = [f"Provider: {_PROVIDER_DISPLAY.get(provider, provider)}"]
        if "error" in info:
            lines.append(f"Error: {info['error']}")
        else:
            lines.append(f"Checked at (UTC): {info.get('checked_at')}")
            lines.append(f"Available: {info.get('available')}")
            if "models_count" in info:
                lines.append(f"Models: {info.get('models_count')}")
                if "models" in info:
                    lines.append("Sample: " + ", ".join(info.get("models", [])))
            if "models_error" in info:
                lines.append("Models error: " + info.get("models_error"))

            # Copilot token expiry if present
            if "copilot_session_expires_in_s" in info:
                sec = info.get("copilot_session_expires_in_s", 0)
                lines.append(f"Copilot session token expires in: {sec}s")

            # Debug log summary
            dbg = info.get("debug_log")
            if dbg:
                lines.append("")
                lines.append("Recent activity (from ai_debug_log):")
                lines.append(f"Log path: {dbg.get('path')}")
                lines.append(f"Requests recorded: {dbg.get('total_requests')}")
                lines.append(f"Total requested max_tokens (sum): {dbg.get('total_max_tokens')}")
                lines.append(f"Total response characters (sum): {dbg.get('total_response_chars')}")
                # Provide a rough token estimate (chars/4 heuristic)
                try:
                    est_tokens = int(dbg.get("total_response_chars", 0) / 4)
                    lines.append(f"Estimated response tokens (chars/4): {est_tokens}")
                except Exception:
                    pass
                if dbg.get("recent"):
                    lines.append("")
                    lines.append("Recent log lines:")
                    for r in dbg.get("recent", []):
                        # Truncate recent lines to reasonable length
                        lines.append((r if len(r) <= 240 else (r[:237] + "…")))

        text = "\n".join(lines)

        # Use this popup itself as the transient parent so macOS properly
        # chains the focus: main window → AISettingsPopup → _StatusPopup.
        # Using the main IDE window as parent (a sibling) caused the first
        # click on the OK button to be consumed by macOS for window activation
        # rather than triggering the button, requiring a second click to close.
        parent_window = self

        class _StatusPopup(NvimPopup):
            """Lightweight NvimPopup to display provider status text."""

            def __init__(inner_self, parent, status_text, on_close_cb):
                inner_self._status_text = status_text
                inner_self._on_close_cb = on_close_cb
                inner_self._ok_btn = None
                super().__init__(parent, "Provider Status", width=560)

            def _create_content(inner_self):
                label = Gtk.Label(label=inner_self._status_text)
                label.set_halign(Gtk.Align.START)
                label.set_valign(Gtk.Align.START)
                label.set_wrap(True)
                label.set_max_width_chars(80)
                label.set_selectable(False)
                label.set_focusable(False)
                label.add_css_class("nvim-popup-message")

                scrolled = Gtk.ScrolledWindow()
                scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
                scrolled.set_min_content_height(200)
                scrolled.set_max_content_height(400)
                scrolled.set_focusable(False)
                scrolled.set_child(label)

                inner_self._content_box.append(scrolled)

                # OK button — use a plain Gtk.Button to avoid ToggleButton
                # double-click issues with ZenButton
                ok_btn = Gtk.Button(label="OK")
                ok_btn.add_css_class("nvim-popup-button")
                ok_btn.add_css_class("nvim-popup-button-primary")
                ok_btn.connect("clicked", lambda _btn: inner_self.close())
                ok_btn.set_halign(Gtk.Align.CENTER)
                ok_btn.set_margin_top(8)
                inner_self._content_box.append(ok_btn)
                inner_self._ok_btn = ok_btn

                hint_bar = inner_self._create_hint_bar([("Esc", "close"), ("Enter", "close")])
                hint_bar.set_halign(Gtk.Align.END)
                inner_self._content_box.append(hint_bar)

            def _on_focus_leave(inner_self, controller):
                """Don't auto-close on focus leave — only close via OK/Esc/Enter."""
                pass

            def _on_key_pressed(inner_self, controller, keyval, keycode, state) -> bool:
                if keyval in (Gdk.KEY_Escape, Gdk.KEY_Return):
                    inner_self.close()
                    return True
                return False

            def present(inner_self):
                super().present()
                # Give focus to the OK button so the scrolled area doesn't
                # appear visually selected, and Enter immediately works.
                if inner_self._ok_btn:
                    inner_self._ok_btn.grab_focus()

            def close(inner_self):
                if inner_self._closing:
                    return
                cb = inner_self._on_close_cb
                inner_self._on_close_cb = None  # prevent double-fire
                super().close()
                if cb:
                    cb()

        def _on_status_closed():
            # Delay clearing the flag so _check_focus_and_close doesn't fire
            # before focus has had time to return to AISettingsPopup.
            def _clear_flag():
                self._status_dialog_open = False
                return False

            GLib.timeout_add(150, _clear_flag)

        popup = _StatusPopup(parent_window, text, _on_status_closed)
        self._status_popup = popup  # prevent GC; also used by _dismiss_click_outside guard
        popup.present()

    def _on_focus_leave(self, controller):
        """Override to prevent close when dropdown popover takes focus."""
        GLib.timeout_add(100, self._check_focus_and_close)

    def _dismiss_click_outside(self):
        """Override: ignore clicks that land on the child status popup."""
        if self._closing:
            return False
        # If the status popup is open, its NS window is a legitimate click
        # target — don't let AISettingsPopup's monitor dismiss us for those.
        if getattr(self, "_status_dialog_open", False):
            return False
        return super()._dismiss_click_outside()

    def _check_focus_and_close(self):
        """Close only if focus has truly left this dialog (not to a dropdown popover or child dialog)."""
        if self._closing:
            return False
        # Focus is still inside this window
        if self.get_focus() is not None or self.is_active():
            return False
        # Don't close while a child status dialog is open
        if getattr(self, "_status_dialog_open", False):
            GLib.timeout_add(200, self._check_focus_and_close)
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
        """Update provider availability (e.g. after API key setup)."""
        self._provider_availability = availability

        # Rebuild provider labels
        provider_labels = []
        for pid in self._provider_ids:
            label = _PROVIDER_DISPLAY.get(pid, pid)
            if not availability.get(pid, False):
                label += "  ⚙ setup"
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

        # Update setup button
        needs_setup = not availability.get(self._current_provider, False)
        self._setup_btn.set_visible(needs_setup)


def show_ai_settings(
    parent: Gtk.Window,
    current_provider: str,
    current_model: str,
    provider_availability: dict[str, bool],
    on_provider_changed=None,
    on_model_changed=None,
    on_setup_api_key=None,
) -> AISettingsPopup:
    """Show the AI settings popup.

    Args:
        parent: Parent window.
        current_provider: Currently selected provider ID.
        current_model: Currently selected model name.
        provider_availability: Dict mapping provider ID → bool.
        on_provider_changed: Callback(provider_id) when provider changes.
        on_model_changed: Callback(model_name) when model changes.
        on_setup_api_key: Callback(provider_id) to open API key setup.

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
        on_setup_api_key=on_setup_api_key,
    )
    popup.present()
    return popup
