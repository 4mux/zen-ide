"""
AI Chat Terminal View for Zen IDE GTK.

Uses a DrawingArea-based canvas (ChatCanvas) to render AI output with
ANSI color support and pixel-smooth scrolling.  Communicates with AI
providers via direct HTTP streaming (Anthropic, Copilot APIs)
and supports agentic tool use (read/write/edit files, search, run commands).
"""

import json
import re
import textwrap
import time
from pathlib import Path
from typing import Callable, Optional

from gi.repository import Gdk, GLib, Gtk, Pango

from ai import AnthropicHTTPProvider, CopilotHTTPProvider
from ai.chat_canvas import ChatCanvas
from ai.terminal_markdown_renderer import TerminalMarkdownRenderer
from ai.tool_definitions import tools_for_anthropic, tools_for_copilot
from ai.tool_executor import ToolExecutor
from icons import Icons, icon_font_fallback
from shared.focus_manager import get_component_focus_manager
from shared.gtk_event_utils import is_button_click
from shared.settings import get_setting, get_settings, set_setting
from shared.ui import ZenButton
from themes import get_theme

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_THINKING_MARKER = "\u200b"
_CONTENT_MARKER = "\u200c"
_MAX_TOOL_ITERATIONS = 25
# Hard ceiling on tool-use rounds even in yolo mode.  Configurable via
# ``ai.max_tool_rounds`` (default 200).  Prevents runaway loops from
# burning tokens indefinitely.
_DEFAULT_MAX_TOOL_ROUNDS = 200
_STALE_REQUEST_TIMEOUT_S = 90  # Cancel request if no data received for this long


def _hex_to_ansi_fg(hex_color: str) -> str:
    """Convert a hex color like '#61ffca' to ANSI 24-bit foreground escape code."""
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return f"\033[38;2;{r};{g};{b}m"


from shared.utils import handle_word_nav_keypress


class AIChatTerminalView(Gtk.Box):
    """AI chat view using DrawingArea canvas for pixel-smooth scrolling.

    Uses ChatCanvas (DrawingArea + GtkSnapshot) to render ANSI-styled text
    from AI HTTP provider output with smooth pixel-based scrolling.
    """

    # Provider constants
    PROVIDER_ANTHROPIC_API = "anthropic_api"
    PROVIDER_COPILOT_API = "copilot_api"
    _HTTP_PROVIDERS = frozenset({PROVIDER_ANTHROPIC_API, PROVIDER_COPILOT_API})
    COMPONENT_ID = "ai_chat"
    _SCROLL_RESTORE_ATTEMPTS = 4
    _SCROLL_BOTTOM_EPSILON = 2.0

    def __init__(
        self,
        session_id: str = None,
        show_header: bool = True,
        show_pane_header: bool = False,
        get_workspace_folders: Callable = None,
        get_current_file: Callable = None,
        on_processing_state_change: Callable = None,
        on_message_sent: Callable = None,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        self.session_id = session_id or "default"
        self._show_header = show_header
        self._show_pane_header = show_pane_header

        # Callbacks for vertical stack management (set by AIChatTabs)
        self.on_add_chat = None  # Called when + button is clicked
        self.on_close_chat = None  # Called when × button is clicked
        self.on_maximize_chat = None  # Called when maximize button is clicked
        self.on_tab_actions = None  # Called when session title is clicked (show context menu)

        # Session display info (for pane header title in vertical mode)
        self._display_num = 1  # The session number (1, 2, 3, ...)
        self._display_name = None  # Custom name from first message
        self._session_title_label = None  # Label widget for title

        # Callbacks
        self.get_workspace_folders = get_workspace_folders
        self.get_current_file = get_current_file
        self.on_processing_state_change = on_processing_state_change
        self.on_message_sent = on_message_sent

        # Message history for tab title inference
        self.messages = []

        # Chat messages file for persistence (set by AIChatTabs)
        self.chat_messages_file: Optional[Path] = None
        self.MAX_MESSAGES = 100

        # Current provider/model
        self._current_provider = self.PROVIDER_COPILOT_API

        # Initialize with settings
        settings = get_settings()

        # State
        self._is_processing = False
        self._response_buffer = []  # Capture response chunks
        # Ordered display buffer for resize re-render: list of
        # ("stream", bytes) | ("action", str_ansi_text) | ("reset",) tuples.
        # Captures everything rendered during the current AI turn so the
        # resize handler can faithfully replay it.
        self._display_buffer: list[tuple] = []

        # Markdown renderer for AI output
        self._md_renderer = TerminalMarkdownRenderer(
            terminal_width_fn=lambda: self.terminal.get_column_count() if hasattr(self, "terminal") else 80
        )
        self._last_content_was_action = False
        self._assistant_block_started = False

        # HTTP provider state
        self._http_provider = None  # Active HTTP provider instance (AnthropicHTTPProvider or CopilotHTTPProvider)
        self._http_streaming = False  # True while an HTTP stream is active
        self._tool_iteration_count = 0  # Track tool use iterations per message
        self._api_request_count = 0  # Track API requests for current user message
        self._auto_continue_count = 0  # Track consecutive auto-continues to prevent infinite loops
        self._current_tool_calls: list[dict] = []  # Accumulated tool calls for current assistant turn

        # Track terminal column count for resize re-rendering
        self._last_column_count = 80
        self._resize_rerender_source = None
        self._resize_poll_source = None

        # Spinner state
        self._spinner_source = None
        self._spinner_frame = 0
        self._spinner_start_time = None
        self._stale_watchdog_source = None  # Watchdog timer to cancel stale requests

        # Thinking text state
        self._in_thinking = False
        self._thinking_line_start = -1  # Line index where thinking block begins
        self._thinking_partial_line = ""
        self._thinking_pending_blanks = 0  # Trailing blank lines not yet rendered
        self._thinking_deferred: list[tuple[str, bool]] = []
        self._thinking_defer_source: int | None = None
        self._accumulated_thinking = ""  # Raw thinking text for persistence
        self._thinking_throttle_buffer = ""  # Buffered thinking text awaiting flush
        self._thinking_throttle_source: int | None = None  # GLib timer for throttled flush
        # Thinking blocks: [{text: str, expanded: bool, toggle_line: int}]
        self._thinking_blocks: list[dict] = []
        self._is_rerender = False
        self._rerender_block_index = 0
        self._focus_input_source = None
        self._scroll_generation = 0
        self._pending_restore_scroll_mode = "none"
        self._auto_scroll_engaged = False  # Sticky flag: keep scrolling during streaming
        self._auto_scroll_paused = False  # True when user scrolls away mid-stream
        self._auto_scroll_handlers: list[int] = []  # vadjustment signal handler IDs
        self._auto_scroll_idle_id: int | None = None  # coalesced idle scroll source
        self._auto_scroll_gen = 0  # generation counter for programmatic set_value calls
        self._resize_restoring = False  # suppress auto-scroll during resize restore

        # Check HTTP provider availability (API keys configured)
        self._anthropic_api_available = AnthropicHTTPProvider().is_available
        self._copilot_api_available = CopilotHTTPProvider().is_available

        # Set provider from settings or auto-detect
        provider_setting = settings.get("ai", {}).get("provider", "")
        if provider_setting == "anthropic_api" and self._anthropic_api_available:
            self._current_provider = self.PROVIDER_ANTHROPIC_API
        elif provider_setting == "copilot_api" and self._copilot_api_available:
            self._current_provider = self.PROVIDER_COPILOT_API
        else:
            # Auto-detect: prefer Copilot API > Anthropic
            if self._copilot_api_available:
                self._current_provider = self.PROVIDER_COPILOT_API
            elif self._anthropic_api_available:
                self._current_provider = self.PROVIDER_ANTHROPIC_API

        # Update model after provider is set
        self._current_model = self._get_model_from_settings(settings)

        self._create_ui()
        self._apply_theme()

        # Apply fonts on init (synchronous to avoid layout jump)
        self._apply_font_to_input()

    def _create_ui(self):
        # Claim ai_chat panel focus when clicking anywhere in this view.
        # BUBBLE phase so child buttons (maximize, close, etc.) receive the
        # full press→release sequence first — matching terminal_view.
        click_ctrl = Gtk.GestureClick.new()
        click_ctrl.connect("pressed", self._on_panel_click)
        self.add_controller(click_ctrl)

        # Header with provider selector (optional)
        if self._show_header:
            header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            header.set_margin_start(8)
            header.set_margin_end(8)
            header.set_margin_top(4)
            header.set_margin_bottom(4)

            # Provider dropdown — build list of available providers
            self._provider_list = []  # Maps dropdown index → provider constant
            provider_labels = []
            if self._copilot_api_available:
                self._provider_list.append(self.PROVIDER_COPILOT_API)
                provider_labels.append("Copilot API")
            if self._anthropic_api_available:
                self._provider_list.append(self.PROVIDER_ANTHROPIC_API)
                provider_labels.append("Anthropic API")
            # Always show HTTP options even if unconfigured
            if self.PROVIDER_COPILOT_API not in self._provider_list:
                self._provider_list.append(self.PROVIDER_COPILOT_API)
                provider_labels.append("Copilot API ⚠")
            if self.PROVIDER_ANTHROPIC_API not in self._provider_list:
                self._provider_list.append(self.PROVIDER_ANTHROPIC_API)
                provider_labels.append("Anthropic API ⚠")

            self.provider_dropdown = Gtk.DropDown.new_from_strings(provider_labels)
            self.provider_dropdown.set_tooltip_text("Select AI provider")
            # Select current provider in dropdown
            try:
                selected_idx = self._provider_list.index(self._current_provider)
            except ValueError:
                selected_idx = 0
            self.provider_dropdown.set_selected(selected_idx)
            self.provider_dropdown.connect("notify::selected", self._on_provider_changed)
            header.append(self.provider_dropdown)

            # Spacer
            spacer = Gtk.Box()
            spacer.set_hexpand(True)
            header.append(spacer)

            # Clear button
            clear_btn = ZenButton(icon=Icons.TRASH, tooltip="Clear terminal")
            clear_btn.connect("clicked", self._on_clear)
            header.append(clear_btn)

            # Stop button (hidden by default)
            self.stop_btn = ZenButton(icon="󰓛", tooltip="Stop AI", variant="danger")
            self.stop_btn.set_visible(False)
            self.stop_btn.connect("clicked", self._on_stop)
            header.append(self.stop_btn)

            self.append(header)
        else:
            self.stop_btn = None

        # Per-pane header for vertical stack mode (independent chat controls)
        if self._show_pane_header:
            self._build_pane_header()
        else:
            self._pane_header = None
            self._close_btn = None
            self._maximize_btn = None

        # Main content: ChatCanvas + input
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content_box.set_vexpand(True)
        content_box.set_overflow(Gtk.Overflow.HIDDEN)

        # ChatCanvas (DrawingArea) for AI output — pixel-smooth scrolling
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.set_margin_start(0)
        scrolled.set_margin_end(0)
        # Clip children that extend beyond the viewport to prevent visual overflow
        scrolled.set_overflow(Gtk.Overflow.HIDDEN)
        self._scrolled_window = scrolled

        self.terminal = ChatCanvas()
        self.terminal.set_hexpand(True)
        self.terminal.set_vexpand(True)
        self._configure_terminal()
        self._setup_terminal_context_menu()
        self._setup_terminal_copy_shortcut()
        self._setup_terminal_resize_handler()
        self.terminal.attach_to_scrolled_window(scrolled)

        scrolled.set_child(self.terminal)

        # Overlay to host the scroll-state indicator on top of the chat
        overlay = Gtk.Overlay()
        overlay.set_child(scrolled)
        overlay.set_hexpand(True)
        overlay.set_vexpand(True)
        self._scroll_indicator = self._build_scroll_indicator()
        overlay.add_overlay(self._scroll_indicator)
        content_box.append(overlay)

        self.append(content_box)

        # Input area at bottom
        self.input_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        input_box = self.input_box
        input_box.set_margin_start(4)
        input_box.set_margin_end(4)
        input_box.set_margin_top(4)
        input_box.set_margin_bottom(8)

        # Multi-line input with scrolling
        self.input_scroll = Gtk.ScrolledWindow()
        self.input_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.input_scroll.set_min_content_height(40)
        self.input_scroll.set_max_content_height(100)
        self.input_scroll.set_propagate_natural_height(True)
        self.input_scroll.set_hexpand(True)

        from ai.block_cursor_text_view import BlockCursorTextView

        self.input_field = BlockCursorTextView()
        self.input_field.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.input_field.add_css_class("ai-input")

        # Key controller for Enter and Cmd+Backspace - use CAPTURE phase
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.input_field.add_controller(key_ctrl)

        self.input_scroll.set_child(self.input_field)

        input_box.append(self.input_scroll)

        self.append(input_box)

    def _build_pane_header(self):
        """Build per-pane header for vertical stack mode (like terminal_view)."""

        self._pane_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._pane_header.set_margin_start(8)
        self._pane_header.set_margin_end(8)
        self._pane_header.set_margin_top(4)
        self._pane_header.set_margin_bottom(4)

        # Combined AI settings button (provider + model in one)
        provider_name = self._get_provider_display_name()
        model_name = self._current_model or ""
        combined = f"{provider_name} · {model_name}" if model_name else provider_name
        self._ai_settings_btn = ZenButton(label=combined, tooltip="AI settings")
        self._ai_settings_btn.set_halign(Gtk.Align.START)
        self._ai_settings_btn.add_css_class("header-button")
        self._ai_settings_btn.connect("clicked", self._on_pane_ai_settings_clicked)
        self._pane_header.append(self._ai_settings_btn)

        # Session title label (shows "Chat N" or custom name from first message)
        self._session_title_label = ZenButton(label=self._get_session_title(), tooltip="Tab actions")
        self._session_title_label.set_halign(Gtk.Align.START)
        self._session_title_label.add_css_class("session-title")
        self._session_title_label.connect("clicked", self._on_session_title_clicked)
        self._pane_header.append(self._session_title_label)

        # Spacer to push buttons to the right
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        self._pane_header.append(spacer)

        # Add chat button
        self._add_btn = ZenButton(icon=Icons.PLUS, tooltip="New chat")
        self._add_btn.connect("clicked", lambda b: self._on_add_clicked())
        self._pane_header.append(self._add_btn)

        # Maximize button
        self._maximize_btn = ZenButton(icon=Icons.MAXIMIZE, tooltip="Maximize")
        self._maximize_btn.connect("clicked", self._on_pane_maximize_clicked)
        self._pane_header.append(self._maximize_btn)

        # Close chat button (×) — hidden by default, shown when stacked
        self._close_btn = ZenButton(icon=Icons.CLOSE, tooltip="Close chat")
        self._close_btn.connect("clicked", lambda b: self._on_close_clicked())
        self._close_btn.set_visible(False)
        self._pane_header.append(self._close_btn)

        self.append(self._pane_header)
        # Re-order so header is first
        self.reorder_child_after(self._pane_header, None)

    def _on_pane_ai_settings_clicked(self, button):
        """Show AI settings popup with two combo boxes (provider + model)."""
        from popups.ai_settings_popup import show_ai_settings

        parent = self.get_root()
        if not parent:
            return

        availability = {
            self.PROVIDER_COPILOT_API: self._copilot_api_available,
            self.PROVIDER_ANTHROPIC_API: self._anthropic_api_available,
        }

        self._ai_settings_popup = show_ai_settings(
            parent=parent,
            current_provider=self._current_provider,
            current_model=self._current_model or "",
            provider_availability=availability,
            on_provider_changed=self._on_ai_settings_provider_changed,
            on_model_changed=self._on_ai_settings_model_changed,
            on_setup_api_key=self._on_ai_settings_setup_key,
        )

    def _on_ai_settings_provider_changed(self, provider):
        """Handle provider change from AI settings popup."""
        if provider != self._current_provider:
            self._current_provider = provider
            self._current_model = self._get_model_from_settings(get_settings())
            self._save_provider_preference()
            self._update_pane_header_labels()

    def _on_ai_settings_model_changed(self, model):
        """Handle model change from AI settings popup."""
        if model != self._current_model:
            self._current_model = model
            self._save_model_preference()
            self._update_pane_header_labels()

    def _on_ai_settings_setup_key(self, provider):
        """Handle API key setup request from AI settings popup."""
        # Close the settings popup first
        if hasattr(self, "_ai_settings_popup") and self._ai_settings_popup:
            self._ai_settings_popup.close()
            self._ai_settings_popup = None
        self._show_api_key_setup(provider)

    def _is_http_provider_available(self, provider: str) -> bool:
        """Check if an HTTP provider has its API key configured."""
        if provider == self.PROVIDER_ANTHROPIC_API:
            return self._anthropic_api_available
        if provider == self.PROVIDER_COPILOT_API:
            return self._copilot_api_available
        return False

    def _show_api_key_setup(self, provider: str):
        """Show the API key setup popup for an HTTP provider."""
        from popups.api_key_setup_popup import show_api_key_setup

        parent = self.get_root()
        if not parent:
            return

        show_api_key_setup(
            parent=parent,
            provider=provider,
            on_complete=self._on_api_key_configured,
        )

    def _on_api_key_configured(self, provider: str):
        """Called after user successfully saves an API key."""
        # Refresh availability
        self._anthropic_api_available = AnthropicHTTPProvider().is_available
        self._copilot_api_available = CopilotHTTPProvider().is_available

        # Switch to the newly configured provider
        self._current_provider = provider
        self._current_model = self._get_model_from_settings(get_settings())
        self._save_provider_preference()
        self._update_pane_header_labels()

        # Rebuild provider dropdown if it exists
        if hasattr(self, "provider_dropdown") and self.provider_dropdown:
            self._rebuild_provider_dropdown()

    def _update_pane_header_labels(self):
        """Update pane header labels after provider/model change."""
        if hasattr(self, "_ai_settings_btn") and self._ai_settings_btn:
            provider_name = self._get_provider_display_name()
            model_name = self._current_model or ""
            combined = f"{provider_name} · {model_name}" if model_name else provider_name
            self._ai_settings_btn.set_label(combined)

    def _rebuild_provider_dropdown(self):
        """Rebuild provider dropdown labels to reflect current availability."""
        if not hasattr(self, "provider_dropdown") or not self.provider_dropdown:
            return

        self._provider_list = []
        provider_labels = []
        if self._copilot_api_available:
            self._provider_list.append(self.PROVIDER_COPILOT_API)
            provider_labels.append("Copilot API")
        if self._anthropic_api_available:
            self._provider_list.append(self.PROVIDER_ANTHROPIC_API)
            provider_labels.append("Anthropic API")
        if self.PROVIDER_COPILOT_API not in self._provider_list:
            self._provider_list.append(self.PROVIDER_COPILOT_API)
            provider_labels.append("Copilot API ⚠")
        if self.PROVIDER_ANTHROPIC_API not in self._provider_list:
            self._provider_list.append(self.PROVIDER_ANTHROPIC_API)
            provider_labels.append("Anthropic API ⚠")

        # Replace the model in the dropdown
        model = Gtk.StringList.new(provider_labels)
        self.provider_dropdown.set_model(model)

        # Select current provider
        try:
            selected_idx = self._provider_list.index(self._current_provider)
            self.provider_dropdown.set_selected(selected_idx)
        except ValueError:
            pass

    def _on_add_clicked(self):
        """Handle + button click."""
        if self.on_add_chat:
            self.on_add_chat()

    def _on_close_clicked(self):
        """Handle × button click."""
        if self.on_close_chat:
            self.on_close_chat(self)

    def _on_session_title_clicked(self, button):
        """Handle session title click - show tab actions context menu."""
        if self.on_tab_actions:
            self.on_tab_actions(self, button)

    def _on_pane_maximize_clicked(self, button):
        """Toggle maximize state from the pane header."""
        self._is_maximized = not getattr(self, "_is_maximized", False)
        if self._is_maximized:
            button.add_css_class("selected")
            button.set_tooltip_text("Restore")
        else:
            button.remove_css_class("selected")
            button.set_tooltip_text("Maximize")
        if self.on_maximize_chat:
            self.on_maximize_chat("ai_chat", self)

    def _on_panel_click(self, gesture, n_press, x, y):
        """Handle click on chat area to update focused component state (BUBBLE phase)."""
        # Deny so this gesture does not claim the sequence away from buttons
        # that have already handled the press in the TARGET phase.
        gesture.set_state(Gtk.EventSequenceState.DENIED)

        picked_widget = self.pick(x, y, Gtk.PickFlags.DEFAULT)
        if is_button_click(picked_widget):
            return
        fm = get_component_focus_manager()
        already_focused = fm.get_current_focus() == self.COMPONENT_ID
        fm.set_focus(self.COMPONENT_ID)
        clicked_terminal = self._is_within_widget_tree(picked_widget, self.terminal)
        if clicked_terminal:
            # ChatCanvas is non-focusable — don't try to grab focus on it.
            # Text selection works via GestureDrag, copy via panel-level key handler.
            self._cancel_pending_input_focus()
        # Only auto-focus input when the initial click is outside the output area.
        if not already_focused and n_press == 1 and not clicked_terminal:
            self._schedule_input_focus()

    @staticmethod
    def _is_within_widget_tree(widget, ancestor) -> bool:
        """Return True when widget is ancestor or a descendant of it."""
        current = widget
        while current is not None:
            if current is ancestor:
                return True
            current = current.get_parent()
        return False

    def _schedule_input_focus(self):
        if self._focus_input_source is not None:
            GLib.source_remove(self._focus_input_source)
        self._focus_input_source = GLib.timeout_add(150, self._focus_input_from_timeout)

    def _cancel_pending_input_focus(self):
        if self._focus_input_source is not None:
            GLib.source_remove(self._focus_input_source)
            self._focus_input_source = None

    def _focus_input_from_timeout(self):
        self._focus_input_source = None
        self.focus_input()
        return False

    def _begin_scroll_generation(self):
        generation = getattr(self, "_scroll_generation", 0) + 1
        self._scroll_generation = generation
        return generation

    def _is_scroll_generation_current(self, generation) -> bool:
        return generation is None or generation == getattr(self, "_scroll_generation", 0)

    def _request_restore_scroll_mode(self, scroll_mode: str):
        priority = {"none": 0, "preserve": 1, "bottom": 2}
        current_mode = getattr(self, "_pending_restore_scroll_mode", "none")
        if priority.get(scroll_mode, 0) >= priority.get(current_mode, 0):
            self._pending_restore_scroll_mode = scroll_mode

    def _schedule_scroll_action(self, scroll_mode: str, scroll_state=None, delay_ms: int = 0):
        if scroll_mode == "none":
            return None
        generation = self._begin_scroll_generation()
        attempts = self._SCROLL_RESTORE_ATTEMPTS if scroll_mode in {"bottom", "preserve"} else 1
        if delay_ms > 0:
            GLib.timeout_add(delay_ms, self._apply_scroll_action, scroll_mode, scroll_state, attempts, generation)
        else:
            GLib.idle_add(self._apply_scroll_action, scroll_mode, scroll_state, attempts, generation)
        return generation

    def _apply_scroll_action(self, scroll_mode: str, scroll_state, attempts_remaining: int, generation: int):
        if not self._is_scroll_generation_current(generation):
            return False
        if scroll_mode == "preserve":
            return self._restore_scroll_state(scroll_state, attempts_remaining, generation)
        if scroll_mode == "bottom":
            return self.scroll_to_bottom(attempts_remaining, generation)
        return False

    def _get_terminal_vadjustment(self):
        if hasattr(self, "_scrolled_window") and self._scrolled_window is not None:
            return self._scrolled_window.get_vadjustment()
        return None

    def _is_near_bottom(self) -> bool:
        """Check if the viewport is at or near the bottom."""
        adj = self._get_terminal_vadjustment()
        if adj is None:
            return True
        max_value = max(adj.get_upper() - adj.get_page_size(), 0)
        return (max_value - adj.get_value()) <= self._SCROLL_BOTTOM_EPSILON

    # -- Scroll-state indicator ------------------------------------------

    def _build_scroll_indicator(self) -> Gtk.Button:
        """Build the floating pill that shows auto-scroll state."""

        btn = Gtk.Button()
        btn.set_halign(Gtk.Align.CENTER)
        btn.set_valign(Gtk.Align.END)
        btn.set_margin_bottom(8)
        btn.set_visible(False)
        btn.set_can_focus(False)
        btn.add_css_class("scroll-indicator")
        btn.connect("clicked", self._on_scroll_indicator_clicked)
        self._scroll_indicator_css = None
        self._scroll_indicator_spinner_source = None
        self._scroll_indicator_spinner_frame = 0
        return btn

    def _on_scroll_indicator_clicked(self, _btn):
        """Jump to bottom and re-engage auto-scroll when indicator is clicked."""
        self._auto_scroll_paused = False
        self._auto_scroll_gen += 1
        adj = self._get_terminal_vadjustment()
        if adj is not None:
            max_val = max(adj.get_upper() - adj.get_page_size(), 0)
            adj.set_value(max_val)
        self._update_scroll_indicator()

    def _update_scroll_indicator(self):
        """Show/hide and style the floating scroll-state pill."""
        if not hasattr(self, "_scroll_indicator"):
            return

        indicator = self._scroll_indicator
        if not self._is_processing:
            indicator.set_visible(False)
            self._stop_scroll_indicator_spinner()
            return

        theme = get_theme()
        accent = theme.accent_color
        panel_bg = theme.panel_bg
        fg = theme.fg_color

        if self._auto_scroll_paused:
            indicator.set_label(f"{Icons.ARROW_DOWN}  Jump to bottom")
            indicator.set_visible(True)
            css_cls = "paused"
            self._stop_scroll_indicator_spinner()
        else:
            frame = SPINNER_FRAMES[self._scroll_indicator_spinner_frame % len(SPINNER_FRAMES)]
            req_count = getattr(self, "_api_request_count", 0)
            suffix = f" · {req_count} reqs" if req_count > 1 else ""
            indicator.set_label(f"{frame}  Thinking{suffix}")
            indicator.set_visible(True)
            css_cls = "following"
            self._start_scroll_indicator_spinner()

        icon_font = icon_font_fallback("system-ui")
        from fonts import get_font_settings

        editor_family = get_font_settings("ai_chat").get("family", "monospace")

        css = Gtk.CssProvider()
        css.load_from_data(
            f"""
            .scroll-indicator {{
                font-family: "{icon_font}", "{editor_family}", system-ui;
                font-size: 10pt;
                min-height: 0;
                padding: 3px 12px;
                border-radius: 12px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.3);
            }}
            .scroll-indicator.following {{
                background-color: alpha({panel_bg}, 0.85);
                color: alpha({fg}, 0.5);
            }}
            .scroll-indicator.paused {{
                background-color: {accent};
                color: #ffffff;
            }}
        """.encode()
        )

        ctx = indicator.get_style_context()
        if self._scroll_indicator_css is not None:
            ctx.remove_provider(self._scroll_indicator_css)
        ctx.add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_USER + 3)
        self._scroll_indicator_css = css

        indicator.remove_css_class("following")
        indicator.remove_css_class("paused")
        indicator.add_css_class(css_cls)

    def _start_scroll_indicator_spinner(self):
        """Start animating the spinner in the 'Thinking' scroll indicator."""
        if self._scroll_indicator_spinner_source is not None:
            return
        self._scroll_indicator_spinner_source = GLib.timeout_add(80, self._tick_scroll_indicator_spinner)

    def _stop_scroll_indicator_spinner(self):
        """Stop the scroll indicator spinner animation."""
        if self._scroll_indicator_spinner_source is not None:
            GLib.source_remove(self._scroll_indicator_spinner_source)
            self._scroll_indicator_spinner_source = None
        self._scroll_indicator_spinner_frame = 0

    def _tick_scroll_indicator_spinner(self):
        """Advance the scroll indicator spinner frame."""
        self._scroll_indicator_spinner_frame += 1
        frame = SPINNER_FRAMES[self._scroll_indicator_spinner_frame % len(SPINNER_FRAMES)]
        req_count = getattr(self, "_api_request_count", 0)
        suffix = f" · {req_count} reqs" if req_count > 1 else ""
        self._scroll_indicator.set_label(f"{frame}  Thinking{suffix}")
        return True  # Keep running

    def _engage_auto_scroll(self):
        """Start auto-scrolling during AI streaming.

        Connects to ``notify::upper`` to scroll to bottom whenever content
        grows, and to ``value-changed`` with a generation counter to detect
        when the user scrolls away manually.
        """
        if self._auto_scroll_engaged:
            return
        if not get_setting("ai.auto_scroll_on_output", True):
            return
        adj = self._get_terminal_vadjustment()
        if adj is None:
            return
        self._auto_scroll_engaged = True
        self._auto_scroll_paused = False
        self._auto_scroll_gen = 0
        self._auto_scroll_handlers = [
            adj.connect("notify::upper", self._on_upper_changed),
            adj.connect("value-changed", self._on_auto_scroll_value_changed),
        ]
        self._update_scroll_indicator()

    def _disengage_auto_scroll(self):
        """Stop auto-scrolling: disconnect all auto-scroll signal handlers."""
        if not self._auto_scroll_engaged:
            return
        self._auto_scroll_engaged = False
        adj = self._get_terminal_vadjustment()
        if adj is not None:
            for hid in self._auto_scroll_handlers:
                try:
                    adj.disconnect(hid)
                except Exception:
                    pass
        self._auto_scroll_handlers.clear()
        if self._auto_scroll_idle_id is not None:
            GLib.source_remove(self._auto_scroll_idle_id)
            self._auto_scroll_idle_id = None
        self._update_scroll_indicator()

    def _on_upper_changed(self, adj, _pspec):
        """Schedule a scroll-to-bottom when content height grows.

        Defers the actual ``set_value`` to an idle handler so all
        vadjustment properties (upper, page_size) are settled after
        layout before we compute the scroll target.  Scrolling
        synchronously inside ``notify::upper`` can read stale
        ``page_size``, producing a wrong max_val that shifts the
        viewport and makes content appear to vanish for a frame.
        """
        if self._resize_restoring or self._auto_scroll_paused:
            return
        if self._auto_scroll_idle_id is None:
            self._auto_scroll_idle_id = GLib.idle_add(self._do_auto_scroll)

    def _on_auto_scroll_value_changed(self, adj):
        """Detect user-initiated scroll during streaming.

        If the value change was caused by our own ``set_value`` call
        (generation counter > 0), skip it.  Otherwise the user or GTK
        layout changed the value — if we're now far from the bottom,
        pause auto-scroll.  If paused and user scrolls back near the
        bottom, re-engage.
        """
        if self._resize_restoring:
            return
        if self._auto_scroll_gen > 0:
            self._auto_scroll_gen -= 1
            return
        if not self._auto_scroll_engaged:
            return
        max_val = max(adj.get_upper() - adj.get_page_size(), 0)
        page = adj.get_page_size()
        if page <= 0:
            return
        distance = max_val - adj.get_value()
        if self._auto_scroll_paused:
            # Re-engage when user scrolls back near the bottom (within 20% of viewport)
            if distance <= page * 0.2:
                self._auto_scroll_paused = False
                self._auto_scroll_gen += 1
                adj.set_value(max_val)
                self._update_scroll_indicator()
        else:
            # Pause when user scrolls away (more than 30% of viewport)
            if distance > page * 0.3:
                self._auto_scroll_paused = True
                self._update_scroll_indicator()

    def _maybe_auto_scroll(self):
        """Schedule a coalesced scroll-to-bottom as backup after each feed.

        ``notify::upper`` is the primary trigger, but if the signal is
        delayed or the layout hasn't run yet, this ensures we catch up.
        """
        if not self._auto_scroll_engaged or self._auto_scroll_paused:
            return
        if self._auto_scroll_idle_id is not None:
            return
        self._auto_scroll_idle_id = GLib.idle_add(self._do_auto_scroll)

    def _do_auto_scroll(self):
        """Scroll to bottom (idle callback)."""
        self._auto_scroll_idle_id = None
        if not self._auto_scroll_engaged or self._auto_scroll_paused:
            return False
        adj = self._get_terminal_vadjustment()
        if adj is None:
            return False
        max_val = max(adj.get_upper() - adj.get_page_size(), 0)
        if max_val > adj.get_value() + 0.5:
            self._auto_scroll_gen += 1
            adj.set_value(max_val)
        return False

    def _capture_scroll_state(self):
        """Capture enough scroll state to restore the viewport after reflow.

        Uses line-based anchoring: captures which buffer line is at the
        top of the viewport and the sub-line pixel offset.  This is far
        more stable across resize than fraction-based approaches because
        the same buffer line maps to the same content regardless of how
        wrapping changes.
        """
        # During active resize, the canvas has a stable anchor that is
        # independent of vadjustment (which may be stale/clamped).
        # Use it directly for the most accurate state.
        canvas_anchor = getattr(self.terminal, "_resize_scroll_anchor", None)
        if canvas_anchor is not None:
            return {
                "anchor_line": canvas_anchor["anchor_line"],
                "anchor_offset": canvas_anchor["anchor_offset"],
                "at_bottom": canvas_anchor["at_bottom"],
            }

        vadjustment = self._get_terminal_vadjustment()
        if vadjustment is None:
            return None

        max_value = max(vadjustment.get_upper() - vadjustment.get_page_size(), 0)
        value = max(0, min(vadjustment.get_value(), max_value))
        at_bottom = (max_value - value) <= self._SCROLL_BOTTOM_EPSILON

        # Line-based anchor from the canvas
        anchor_line, anchor_offset = self.terminal.get_scroll_anchor()

        return {
            "anchor_line": anchor_line,
            "anchor_offset": anchor_offset,
            "at_bottom": at_bottom,
        }

    def _restore_scroll_state(self, scroll_state, attempts_remaining, generation=None):
        """Restore the viewport after a resize-triggered re-render.

        Uses line-based anchoring: looks up where the anchor buffer line
        now lives in the new wrap map and applies the sub-line pixel
        offset.  This keeps the same content visible regardless of how
        wrapping changed during resize.
        """
        if not self._is_scroll_generation_current(generation):
            return False

        vadjustment = self._get_terminal_vadjustment()
        if vadjustment is None or not scroll_state:
            return False

        max_value = max(vadjustment.get_upper() - vadjustment.get_page_size(), 0)

        if scroll_state["at_bottom"]:
            target = max_value
        elif max_value <= 0 and attempts_remaining > 1:
            GLib.idle_add(self._restore_scroll_state, scroll_state, attempts_remaining - 1, generation)
            return False
        else:
            # Line-based restoration: find where the anchor line is now
            anchor_line = scroll_state.get("anchor_line", 0)
            anchor_offset = scroll_state.get("anchor_offset", 0.0)
            line_y = self.terminal.get_y_for_line(anchor_line)
            target = line_y + anchor_offset

        target = max(0, min(target, max_value))
        if abs(vadjustment.get_value() - target) > 0.5:
            vadjustment.set_value(target)

        if attempts_remaining > 1:
            GLib.idle_add(self._restore_scroll_state, scroll_state, attempts_remaining - 1, generation)
        return False

    def _configure_terminal(self):
        """Configure ChatCanvas settings — colors and font."""
        theme = get_theme()

        # Font
        self._apply_terminal_font()

        # Colors
        fg = Gdk.RGBA()
        fg.parse(theme.fg_color)
        bg = Gdk.RGBA()
        bg.parse(theme.panel_bg)
        selection_bg = Gdk.RGBA()
        selection_bg.parse(theme.selection_bg)

        self.terminal.set_colors(fg, bg, selection_bg=selection_bg)

    def _apply_terminal_font(self):
        """Apply font to ChatCanvas."""
        from fonts import get_font_settings
        from icons import ICON_FONT_FAMILY

        font_settings = get_font_settings("ai_chat")
        font_family = font_settings["family"]
        font_size = font_settings.get("size", 13)

        family_with_icons = f"{font_family}, {ICON_FONT_FAMILY}"
        font_desc = Pango.FontDescription.from_string(f"{family_with_icons} {font_size}")
        self.terminal.set_font(font_desc)

    def _lighten(self, hex_color: str, amount: float) -> str:
        """Lighten a hex color by a given amount."""
        hex_color = hex_color.lstrip("#")
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        r = min(255, int(r + (255 - r) * amount))
        g = min(255, int(g + (255 - g) * amount))
        b = min(255, int(b + (255 - b) * amount))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _setup_terminal_context_menu(self):
        """Setup right-click context menu."""
        gesture = Gtk.GestureClick()
        gesture.set_button(3)
        gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        gesture.connect("pressed", self._on_terminal_right_click)
        self.terminal.add_controller(gesture)

    def _on_terminal_right_click(self, gesture, n_press, x, y):
        """Handle right-click on terminal - show nvim-style context menu."""
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)

        from popups.nvim_context_menu import show_context_menu

        has_selection = self.terminal.get_has_selection()

        items = [
            {"label": "Copy", "action": "copy", "icon": Icons.COPY, "enabled": has_selection},
            {"label": "Select All", "action": "select_all", "icon": Icons.SELECT_ALL},
            {"label": "---"},
            {"label": "Clear", "action": "clear", "icon": Icons.TRASH},
        ]

        def on_select(action):
            if action == "copy":
                self._copy_selection()
            elif action == "select_all":
                self.terminal.select_all()
            elif action == "clear":
                self.terminal.reset(True, True)
                self._thinking_blocks.clear()
                self.terminal.clear_clickable_lines()

        parent = self.get_root()
        if parent:
            show_context_menu(parent, items, on_select, x, y, source_widget=self.terminal)

    def _setup_terminal_copy_shortcut(self):
        """Setup Cmd+C / Ctrl+Shift+C keyboard shortcut for copy.

        Installed on the panel at CAPTURE phase so it works regardless of
        which child widget has GTK focus (ChatCanvas is non-focusable).
        Only consumes the event when the terminal actually has a selection.
        """
        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect("key-pressed", self._on_terminal_key_pressed)
        self.add_controller(key_controller)

    def _on_terminal_key_pressed(self, controller, keyval, keycode, state):
        """Handle keyboard shortcuts in terminal.

        Only consumes the event when the terminal has a selection AND the
        input field does not have focus, so that normal Cmd+C in the input
        field is not intercepted.
        """
        # Check for Cmd+C (macOS) or Ctrl+Shift+C (Linux)
        ctrl = state & Gdk.ModifierType.CONTROL_MASK
        shift = state & Gdk.ModifierType.SHIFT_MASK
        meta = state & Gdk.ModifierType.META_MASK  # Cmd key on macOS

        if keyval == Gdk.KEY_c:
            # Cmd+C on macOS or Ctrl+Shift+C on Linux
            if meta or (ctrl and shift):
                # If the input field has focus AND has its own text selection,
                # let GTK's built-in copy handler run on the text view.
                if self.input_field.has_focus():
                    buf = self.input_field.get_buffer()
                    if buf.get_has_selection():
                        return False
                if self.terminal.get_has_selection():
                    self._copy_selection()
                    return True

        return False

    def _copy_selection(self):
        """Copy terminal selection to clipboard.

        Writes directly to both the GTK clipboard and the OS system
        clipboard synchronously to avoid the race condition that made
        Cmd+C unreliable when the async read-back/flush pipeline was
        used.
        """
        if not self.terminal.get_has_selection():
            return
        text = self.terminal.get_selected_text()
        if not text:
            return
        # GTK clipboard (for in-app paste)
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(text)
        # System clipboard (survives app exit)
        from shared.utils import copy_to_system_clipboard

        copy_to_system_clipboard(text)

    def _setup_terminal_resize_handler(self):
        """Setup handler to re-render code blocks on terminal resize."""
        self._last_column_count = self.terminal.get_column_count()
        # Poll column count periodically when mapped
        self.terminal.connect("map", self._start_resize_polling)
        self.terminal.connect("unmap", self._stop_resize_polling)
        self._resize_poll_source = None

    def _start_resize_polling(self, widget):
        """Start polling for column count changes."""
        if self._resize_poll_source is None:
            # Poll every 60ms for smooth real-time resize animation.
            # The canvas soft-wraps visually on every frame, so this
            # polling only triggers markdown re-rendering (code blocks,
            # tables) to reflow at the new width.
            self._resize_poll_source = GLib.timeout_add(60, self._poll_column_count)

    def _stop_resize_polling(self, widget):
        """Stop polling for column count changes."""
        if self._resize_poll_source:
            GLib.source_remove(self._resize_poll_source)
            self._resize_poll_source = None

    def _poll_column_count(self):
        """Poll terminal column count and debounce re-render on change.

        The ChatCanvas soft-wraps visually in real-time, so content never
        overflows during resize.  This debounced re-render reformats
        structured content (code blocks, tables) through the markdown
        pipeline at the new terminal width for optimal layout.

        Uses a 300ms debounce so the re-render only fires once the resize
        has settled (user stopped dragging).  During continuous drag the
        soft-wrap keeps content readable without any re-render.
        """
        if not hasattr(self, "terminal"):
            return False

        new_cols = self.terminal.get_column_count()

        if new_cols != self._last_column_count:
            self._last_column_count = new_cols
            # Cancel any pending re-render and reschedule (debounce).
            # 300ms ensures we only re-render after the resize settles,
            # avoiding repeated expensive full re-renders during drag.
            if self._resize_rerender_source:
                GLib.source_remove(self._resize_rerender_source)
            self._resize_rerender_source = GLib.timeout_add(300, self._rerender_on_resize)

        return True  # Continue polling

    def _rerender_on_resize(self):
        """Re-render all messages after terminal resize.

        Uses ChatCanvas batch mode: height updates are suppressed during
        reset+re-render so the scroll position never sees an intermediate
        height of 0, eliminating the visible jump.

        Scroll restoration uses line-based anchoring: we capture which
        buffer line is at the top of the viewport (plus the sub-line
        pixel offset), re-render, then look up where that same buffer
        line lives in the new wrap map and restore the offset.  This is
        robust because the anchor line refers to the same content
        regardless of how wrapping changes at the new width.

        During processing (streaming), also re-feeds the partial response
        buffer through the markdown renderer at the new width so the UI
        stays responsive to resize even while loading.
        """
        self._resize_rerender_source = None

        # Only re-render if we have messages to show
        if not self.messages:
            return False

        # Clear canvas and re-render all messages
        if hasattr(self, "terminal"):
            # Capture scroll state before reset (line-based anchor).
            scroll_state = self._capture_scroll_state()

            # Suppress auto-scroll interference during the entire
            # rerender + scroll-restore window.
            self._resize_restoring = True

            # Batch: suppress height changes during reset+re-render
            self.terminal.begin_batch()
            self.terminal.reset()
            self.terminal.clear_clickable_lines()
            # Preserve thinking block expanded/collapsed state during resize
            self._is_rerender = True
            self._rerender_block_index = 0
            self._do_restore_messages(scroll_mode="none")
            self._is_rerender = False

            if self._is_processing and self._display_buffer:
                # Re-process the streaming response at the new width.
                # Replay the display buffer which contains both stream
                # chunks and pre-rendered action text (tool call displays).
                self._md_renderer.reset()
                self._update_renderer_colors()
                self._in_thinking = False
                self._thinking_partial_line = ""
                self._thinking_pending_blanks = 0
                self._thinking_line_start = -1
                self._accumulated_thinking = ""
                self._thinking_throttle_buffer = ""
                # Trim thinking blocks to only those from completed
                # messages (re-rendered above); the display buffer replay
                # will re-create blocks for the in-progress response.
                saved_block_count = getattr(self, "_rerender_block_index", len(self._thinking_blocks))
                self._thinking_blocks = self._thinking_blocks[:saved_block_count]
                if self._thinking_throttle_source is not None:
                    GLib.source_remove(self._thinking_throttle_source)
                    self._thinking_throttle_source = None
                self._last_content_was_action = False

                # Group consecutive stream entries and replay in order
                stream_bytes: list[bytes] = []

                def _flush_stream():
                    """Process accumulated stream bytes through the rendering pipeline."""
                    nonlocal stream_bytes
                    if not stream_bytes:
                        return
                    raw_text = b"".join(stream_bytes).decode("utf-8", errors="replace")
                    stream_bytes = []
                    if not raw_text:
                        return
                    segments = self._split_thinking_segments(raw_text)
                    for kind, segment_text in segments:
                        if kind == "thinking":
                            self._feed_thinking_text(segment_text)
                        else:
                            if self._in_thinking:
                                self._collapse_thinking_block()
                                segment_text = "\n" + segment_text.lstrip("\n")
                            segment_text = self._normalize_action_spacing(segment_text)
                            formatted = self._md_renderer.feed(segment_text)
                            if formatted:
                                lines = formatted.split("\n")
                                canvas_text = "\n".join(f"\r{line}" for line in lines)
                                self.terminal.feed(canvas_text)

                for entry in self._display_buffer:
                    if entry[0] == "stream":
                        stream_bytes.append(entry[1])
                    elif entry[0] == "action":
                        # Flush any pending stream content first
                        _flush_stream()
                        # Feed the pre-rendered action text through _append_text
                        # so cross-call newline normalisation applies.
                        self._append_text(entry[1])
                    elif entry[0] == "reset":
                        # Flush stream, then reset renderer state
                        _flush_stream()
                        self._md_renderer.reset()
                        self._last_content_was_action = False
                        self._in_thinking = False
                        self._thinking_deferred.clear()
                        self._accumulated_thinking = ""
                        self._thinking_throttle_buffer = ""

                # Flush any remaining stream content
                _flush_stream()

            self.terminal.end_batch()

            # Re-show spinner immediately after rerender so there's no gap
            if self._spinner_source and hasattr(self, "terminal"):
                frame = SPINNER_FRAMES[self._spinner_frame % len(SPINNER_FRAMES)]
                theme = get_theme()
                dim_color = theme.term_cyan or theme.accent_color
                ansi_fg = _hex_to_ansi_fg(dim_color)
                req_count = getattr(self, "_api_request_count", 0)
                req_suffix = f" · {req_count} reqs" if req_count > 1 else ""
                self.terminal.feed(f"\r{ansi_fg}Thinking...{req_suffix} {frame}\033[0m")

            # Restore scroll position using line-based anchor.
            # end_batch() already rebuilt the wrap map and set the
            # correct content height via _eagerly_update_height().
            # Force vadjustment.upper to match so set_value() isn't
            # clamped by a stale upper bound.
            #
            # Clear any pending canvas-level resize anchor so it
            # doesn't interfere with our own scroll restoration.
            self.terminal._resize_scroll_anchor = None
            if self.terminal._resize_settle_id is not None:
                GLib.source_remove(self.terminal._resize_settle_id)
                self.terminal._resize_settle_id = None
            vadjustment = self._get_terminal_vadjustment()
            if vadjustment and scroll_state:
                _, content_height = self.terminal.get_size_request()
                if content_height > 0:
                    vadjustment.set_upper(float(content_height))

                max_value = max(vadjustment.get_upper() - vadjustment.get_page_size(), 0)
                if scroll_state["at_bottom"]:
                    target = max_value
                else:
                    anchor_line = scroll_state.get("anchor_line", 0)
                    anchor_offset = scroll_state.get("anchor_offset", 0.0)
                    line_y = self.terminal.get_y_for_line(anchor_line)
                    target = line_y + anchor_offset

                target = max(0, min(target, max_value))
                self._auto_scroll_gen += 1
                vadjustment.set_value(target)

            # Clear suppression flag after scroll restore is done.
            self._resize_restoring = False

        return False  # Don't repeat

    def _apply_theme(self):
        """Apply theme colors."""
        theme = get_theme()

        css = f"""
        .ai-input {{
            background-color: {theme.hover_bg};
            color: {theme.fg_color};
            padding: 8px;
            border-radius: 4px;
        }}
        .ai-input text {{
            background-color: {theme.hover_bg};
            color: {theme.fg_color};
        }}
        .ai-input > text > selection,
        .ai-input > text > selection:focus-within {{
            background-color: {theme.selection_bg};
            color: {theme.fg_color};
        }}
        """

        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode())
        # Use USER+1 priority to override Adwaita defaults and window_layout CSS
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)

        # Also apply selection CSS directly to the input widget for maximum reliability
        if hasattr(self, "input_field"):
            sel_css = Gtk.CssProvider()
            sel_css.load_from_data(
                f"""
                textview > text > selection,
                textview > text > selection:focus-within {{
                    background-color: {theme.selection_bg};
                    color: {theme.fg_color};
                }}
            """.encode()
            )
            self.input_field.get_style_context().add_provider(sel_css, Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)

    def _on_provider_changed(self, dropdown, param):
        """Handle provider selection change."""
        selected = dropdown.get_selected()
        old_provider = self._current_provider
        if hasattr(self, "_provider_list") and selected < len(self._provider_list):
            new_provider = self._provider_list[selected]
        else:
            new_provider = self.PROVIDER_COPILOT_API

        # If HTTP provider is not configured, show API key setup
        if new_provider in self._HTTP_PROVIDERS and not self._is_http_provider_available(new_provider):
            # Revert dropdown selection
            try:
                old_idx = self._provider_list.index(old_provider)
                dropdown.set_selected(old_idx)
            except (ValueError, AttributeError):
                pass
            self._show_api_key_setup(new_provider)
            return

        self._current_provider = new_provider

        # If provider changed, update model and save preferences
        if old_provider != self._current_provider:
            # Load model preference for new provider
            self._current_model = self._get_model_from_settings(get_settings())
            # Save provider preference
            self._save_provider_preference()

    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Handle key press in input field."""
        if self._is_processing:
            return True
        # Enter without Shift sends message
        if keyval == Gdk.KEY_Return and not (state & Gdk.ModifierType.SHIFT_MASK):
            self._on_send(None)
            return True

        # Handle Cmd+Backspace (delete to start of line)
        if keyval == Gdk.KEY_BackSpace and (state & Gdk.ModifierType.META_MASK):
            self._delete_to_line_start()
            return True

        # Option+Left/Right/Backspace: word navigation treating _ as word char
        buf = self.input_field.get_buffer()
        if handle_word_nav_keypress(buf, keyval, state):
            return True

        return False

    def _delete_to_line_start(self):
        """Delete text from cursor to beginning of current line in the input field."""
        buffer = self.input_field.get_buffer()
        cursor_iter = buffer.get_iter_at_mark(buffer.get_insert())
        line_start = cursor_iter.copy()
        line_start.set_line_offset(0)

        if not cursor_iter.equal(line_start):
            buffer.delete(line_start, cursor_iter)

    def _on_send(self, button):
        """Send the user's message to the AI provider."""
        if self._is_processing:
            return
        buffer = self.input_field.get_buffer()
        start, end = buffer.get_bounds()
        message = buffer.get_text(start, end, False).strip()

        if not message:
            return

        # Check if current provider needs setup before sending
        if not self._is_http_provider_available(self._current_provider):
            # Show API key setup popup and send message after completion
            self._pending_message = message
            self._show_api_key_setup_with_callback(self._current_provider)
            return

        # Prevent duplicate sends immediately (before any async work)
        self._is_processing = True

        # Clear input
        buffer.set_text("")

        # Store message for history
        self.messages.append({"role": "user", "content": message})

        # Save messages to file
        self._save_chat_messages()

        # Notify message sent (for tab title inference)
        if self.on_message_sent:
            self.on_message_sent()

        # Run the AI provider
        self._run_ai_http(message)

    def _show_api_key_setup_with_callback(self, provider: str):
        """Show API key setup with callback to send pending message after completion."""
        from popups.api_key_setup_popup import show_api_key_setup

        parent = self.get_root()
        if not parent:
            # Widget not yet realized, schedule for later
            GLib.idle_add(self._show_api_key_setup_with_callback, provider)
            return

        def on_complete(configured_provider: str):
            self._on_api_key_configured(configured_provider)
            # Send the pending message now that provider is configured
            if hasattr(self, "_pending_message") and self._pending_message:
                message = self._pending_message
                self._pending_message = None
                # Clear input and send
                self.input_field.get_buffer().set_text("")
                self.messages.append({"role": "user", "content": message})
                self._save_chat_messages()
                if self.on_message_sent:
                    self.on_message_sent()
                self._run_ai_http(message)

        show_api_key_setup(
            parent=parent,
            provider=provider,
            on_complete=on_complete,
        )

    def _build_prompt_with_context(self, user_message: str) -> str:
        """Build the final user message content.

        Conversation history is already sent as structured API messages
        in _run_ai_http(), so we do NOT duplicate it here.  The focused
        file is already part of the system prompt as well.

        This method exists as a thin hook in case per-message metadata
        needs to be injected in the future.
        """
        return user_message

    # ------------------------------------------------------------------
    # HTTP provider streaming
    # ------------------------------------------------------------------

    def _run_ai_http(self, message: str):
        """Run an HTTP-based AI provider.

        Streams responses via direct API calls in a background thread,
        feeding chunks to the rendering pipeline. Supports tool use
        with an agentic loop that executes tools and continues.
        """
        # Build message with context
        message_with_context = self._build_prompt_with_context(message)

        # Show user message
        prefix = "\n" if self._has_terminal_content() else ""
        theme = get_theme()
        user_color = theme.chat_user_fg or theme.term_cyan or theme.accent_color
        ansi_fg = _hex_to_ansi_fg(user_color)
        quoted = self._wrap_with_bar(message)
        self.terminal.begin_block("user")
        self._append_text(f"{prefix}{ansi_fg}{quoted}\033[0m\n\n\r")

        # Start processing state
        self._is_processing = True
        self._engage_auto_scroll()
        self.scroll_to_bottom()
        self.input_box.set_visible(False)
        self._response_buffer = []
        self._display_buffer = []
        self._displayed_chars = 0
        self._last_data_time = time.monotonic()
        self._md_renderer.reset()
        self._last_content_was_action = False
        self._in_thinking = False
        self._thinking_line_start = -1
        self._thinking_partial_line = ""
        self._thinking_pending_blanks = 0
        self._thinking_deferred = []
        self._accumulated_thinking = ""
        self._thinking_throttle_buffer = ""
        self._assistant_block_started = False
        self._tool_iteration_count = 0
        self._api_request_count = 0
        self._auto_continue_count = 0
        self._current_tool_calls = []
        self._accumulated_response_text = ""  # Accumulate text across tool-use turns
        if self._thinking_defer_source is not None:
            GLib.source_remove(self._thinking_defer_source)
            self._thinking_defer_source = None
        if self._thinking_throttle_source is not None:
            GLib.source_remove(self._thinking_throttle_source)
            self._thinking_throttle_source = None
        self._update_renderer_colors()
        if self.stop_btn:
            self.stop_btn.set_visible(True)

        self._start_spinner()

        if self.on_processing_state_change:
            self.on_processing_state_change(True)

        # Build conversation messages for the API
        api_messages = []
        for msg in self.messages[:-1]:  # Exclude current (already appended by caller)
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                api_messages.append({"role": role, "content": content})
        api_messages.append({"role": "user", "content": message_with_context})

        # Create provider instance
        if self._current_provider == self.PROVIDER_ANTHROPIC_API:
            self._http_provider = AnthropicHTTPProvider()
        else:
            self._http_provider = CopilotHTTPProvider()

        self._http_streaming = True
        self._http_full_response = ""

        # Resolve tool definitions based on provider
        if self._current_provider == self.PROVIDER_ANTHROPIC_API:
            tools = tools_for_anthropic()
        else:
            tools = tools_for_copilot()

        # Create tool executor with workspace root
        workspace_folders = []
        if self.get_workspace_folders:
            workspace_folders = self.get_workspace_folders() or []
        workspace_root = workspace_folders[0] if workspace_folders else str(Path.home())
        self._tool_executor = ToolExecutor(workspace_root)

        # Build system prompt with workspace context
        system_parts = [
            "You are a coding assistant integrated into Zen IDE.",
            "You have tools to read, write, edit files, search code, and run commands.",
            "Use tools to fulfill the user's requests — make real changes, don't just suggest them.",
            "When editing files, prefer edit_file for surgical changes over write_file.",
        ]
        if workspace_folders:
            system_parts.append(f"Working directories: {', '.join(workspace_folders)}")
        current_file = self.get_current_file() if self.get_current_file else None
        if current_file:
            system_parts.append(f"Currently focused file: {current_file}")

        # Yolo mode: tell the model there is NO tool use limit
        yolo_mode = get_setting("ai.yolo_mode", True)
        if yolo_mode:
            system_parts.append(
                "\nIMPORTANT: There is NO tool use limit. You have UNLIMITED tool calls per response. "
                "Never stop mid-task to say you've reached a limit. Never output '[Tool use limit reached]' or similar. "
                "Never say '[Stopped]' or indicate you are stopping due to tool limits. "
                "Always complete the full task in a single response, using as many tool calls as needed. "
                "If a task requires 50, 100, or even 200 tool calls, just keep going until the task is fully done."
            )
        else:
            system_parts.append(
                f"\nYou have a limit of {_MAX_TOOL_ITERATIONS} tool calls per response. "
                "If you reach the limit, stop and let the user know they can say 'continue' to resume."
            )

        system_prompt = "\n".join(system_parts)

        # Use higher max_tokens in yolo mode to avoid premature truncation
        max_tokens = 32768 if yolo_mode else 16384

        self._api_request_count += 1
        self._http_provider.send_message_stream(
            messages=api_messages,
            model=self._current_model,
            system_prompt=system_prompt,
            tools=tools,
            on_chunk=self._make_on_chunk(),
            on_complete=self._make_on_complete(),
            on_error=self._make_on_error(),
            on_tool_use=self._make_on_tool_use(),
            max_tokens=max_tokens,
        )

    def _make_on_chunk(self):
        """Create thread-safe on_chunk callback."""

        def on_chunk(text):
            if not self._http_streaming:
                return
            GLib.idle_add(self._on_http_chunk, text)

        return on_chunk

    def _make_on_complete(self):
        """Create thread-safe on_complete callback."""

        def on_complete(full_response):
            self._http_full_response = full_response
            GLib.idle_add(self._on_http_finished)

        return on_complete

    def _make_on_error(self):
        """Create thread-safe on_error callback."""

        def on_error(error_msg):
            GLib.idle_add(self._on_http_error, error_msg)

        return on_error

    def _make_on_tool_use(self):
        """Create thread-safe on_tool_use callback."""

        def on_tool_use(tool_calls, text_response):
            GLib.idle_add(self._on_tool_use, tool_calls, text_response)

        return on_tool_use

    def _on_tool_use(self, tool_calls: list[dict], text_response: str):
        """Handle tool use requests from AI (main thread).

        Displays each tool call, then offloads the actual execution to a
        background thread to avoid blocking the GTK main loop.  Results
        are dispatched back to the main thread to continue the conversation.
        Wrapped in try/except to guarantee _finish_processing() on failure.
        """
        if not self._is_processing or not self._http_provider:
            return

        try:
            # Accumulate any text the AI produced before requesting tool use.
            # The provider resets its text buffer for each new turn, so we
            # must capture intermediate text here to avoid losing it when
            # the final on_complete fires with only the last turn's text.
            if text_response:
                self._accumulated_response_text += text_response

            self._tool_iteration_count += len(tool_calls)
            yolo_mode = get_setting("ai.yolo_mode", True)
            max_rounds = get_setting("ai.max_tool_rounds", _DEFAULT_MAX_TOOL_ROUNDS) if yolo_mode else _MAX_TOOL_ITERATIONS
            if self._tool_iteration_count > max_rounds:
                limit_label = (
                    f"[Safety limit of {max_rounds} tool rounds reached — send 'continue' to resume]"
                    if yolo_mode
                    else "[Tool use limit reached — send 'continue' to resume, "
                    "or enable yolo_mode in settings for unlimited tool use]"
                )
                self._append_text(f"\n{limit_label}\n")
                msg = {"role": "assistant", "content": self._accumulated_response_text + f"\n{limit_label}"}
                if self._current_tool_calls:
                    msg["tool_calls_display"] = self._current_tool_calls[:]
                self.messages.append(msg)
                self._save_chat_messages()
                self._http_streaming = False
                self._http_provider = None
                self._finish_processing()
                return

            # Clean up spinner and thinking state before displaying tool calls
            self._stop_spinner()
            if self._in_thinking:
                self._collapse_thinking_block()

            # Display each tool call on the main thread (UI work)
            theme = get_theme()
            action_color = theme.term_yellow or theme.accent_color
            ansi_action = _hex_to_ansi_fg(action_color)
            is_anthropic = self._current_provider == self.PROVIDER_ANTHROPIC_API

            # Prepare tool call metadata and display them now (main thread)
            prepared_calls = []
            for tc in tool_calls:
                name = tc.get("name", "")
                inp = tc.get("input", {})
                tc_id = tc.get("id", "")

                from shared.ai_debug_log import ai_log

                ai_log.tool_use(name, inp)

                # Accumulate for persistence so resize re-render can replay them
                self._current_tool_calls.append({"name": name, "input": inp})

                # Display the tool call (UI — must be on main thread)
                display = self._format_tool_display(name, inp)
                action_ansi = f"\n\n{ansi_action}{display}\033[0m\n"
                self._display_buffer.append(("action", action_ansi))
                self._append_text(action_ansi)

                prepared_calls.append({"name": name, "input": inp, "id": tc_id})

            # Execute tools in a background thread to avoid blocking the UI.
            # subprocess.run and file I/O can take seconds (up to 30s timeout).
            import threading

            executor = self._tool_executor

            def _run_tools():
                tool_results = []
                try:
                    for pc in prepared_calls:
                        result = executor.execute(pc["name"], pc["input"])
                        from shared.ai_debug_log import ai_log

                        ai_log.tool_result(pc["name"], ok=True, chars=len(result) if result else 0)
                        if is_anthropic:
                            tool_results.append({"tool_use_id": pc["id"], "content": result})
                        else:
                            tool_results.append({"tool_call_id": pc["id"], "content": result})
                except Exception as e:
                    from shared.ai_debug_log import ai_log

                    ai_log.tool_result(pc["name"] if prepared_calls else "unknown", ok=False)
                    GLib.idle_add(self._on_tool_execution_error, e)
                    return

                # Dispatch results back to main thread
                GLib.idle_add(self._on_tool_results_ready, tool_results)

            threading.Thread(target=_run_tools, daemon=True).start()

        except Exception as e:
            print(f"[ZenIDE] Error in _on_tool_use: {e}")
            try:
                self._append_text(f"\n[Tool execution error: {e}]\n")
            except Exception:
                pass
            self._http_streaming = False
            self._http_provider = None
            self._finish_processing()

    def _on_tool_results_ready(self, tool_results: list[dict]):
        """Handle tool results after background execution (main thread).

        Resets rendering state and continues the AI conversation.
        """
        if not self._is_processing or not self._http_provider:
            return

        try:
            # Reset rendering state for next response chunk
            self._md_renderer.reset()
            self._last_content_was_action = False
            self._in_thinking = False
            self._thinking_deferred.clear()
            self._accumulated_thinking = ""
            self._thinking_throttle_buffer = ""
            if self._thinking_throttle_source is not None:
                GLib.source_remove(self._thinking_throttle_source)
                self._thinking_throttle_source = None
            # Record state reset so resize re-render replays correctly
            self._display_buffer.append(("reset",))

            # Continue the conversation with tool results
            self._api_request_count += 1
            self._http_provider.continue_with_tool_results(
                tool_results=tool_results,
                on_chunk=self._make_on_chunk(),
                on_complete=self._make_on_complete(),
                on_error=self._make_on_error(),
                on_tool_use=self._make_on_tool_use(),
            )
        except Exception as e:
            print(f"[ZenIDE] Error in _on_tool_results_ready: {e}")
            try:
                self._append_text(f"\n[Tool execution error: {e}]\n")
            except Exception:
                pass
            self._http_streaming = False
            self._http_provider = None
            self._finish_processing()

    def _on_tool_execution_error(self, error: Exception):
        """Handle errors from background tool execution (main thread)."""
        print(f"[ZenIDE] Error in background tool execution: {error}")
        try:
            self._append_text(f"\n[Tool execution error: {error}]\n")
        except Exception:
            pass
        self._http_streaming = False
        self._http_provider = None
        self._finish_processing()

    @staticmethod
    def _format_tool_display(name: str, inp: dict) -> str:
        """Format a tool call for display in the chat.

        Uses tree-style box-drawing characters:
        - Single line detail:   └ detail
        - Multi-line detail:    │ line1
                                │ line2
                                └ line3
        """
        labels = {
            "read_file": ("Reading", inp.get("file_path", "")),
            "write_file": ("Writing", inp.get("file_path", "")),
            "edit_file": ("Editing", inp.get("file_path", "")),
            "list_files": ("Listing", inp.get("pattern", "")),
            "search_files": ("Searching", inp.get("pattern", "")),
            "run_command": ("Running", inp.get("command", "")),
        }
        action, detail = labels.get(name, (name, str(inp)))

        # Split detail into lines and format with box-drawing chars.
        # Returns just the action block content (no leading/trailing blank
        # lines).  Callers are responsible for paragraph spacing via
        # _append_text which normalises gaps to exactly 1 blank line.
        lines = detail.split("\n") if detail else [""]
        if len(lines) == 1:
            # Single line: just use └
            return f"{action}\n └ {lines[0]}"
        else:
            # Multiple lines: use │ for all but last, └ for last
            formatted_lines = []
            for i, line in enumerate(lines):
                if i < len(lines) - 1:
                    formatted_lines.append(f" │ {line}")
                else:
                    formatted_lines.append(f" └ {line}")
            return f"{action}\n" + "\n".join(formatted_lines)

    def _on_http_chunk(self, text: str):
        """Handle a streaming chunk from an HTTP provider (main thread)."""
        if not self._is_processing or not self._http_streaming:
            return
        try:
            # In yolo mode, strip model-generated tool limit messages
            if get_setting("ai.yolo_mode", True):
                text = self._TOOL_LIMIT_PATTERNS.sub("", text)
                if not text.strip(_THINKING_MARKER + _CONTENT_MARKER):
                    return
            self._last_data_time = time.monotonic()
            # Capture raw chunk so _rerender_on_resize can replay the stream
            # at the new terminal width without losing in-progress content.
            self._response_buffer.append(text.encode("utf-8"))
            self._display_buffer.append(("stream", text.encode("utf-8")))
            self._render_stream_chunk(text, allow_first_token_fast_path=True)
        except Exception as e:
            print(f"[ZenIDE] Error in _on_http_chunk: {e}")
            # Don't abort processing for a single bad chunk — the stream
            # may still complete normally.

    def _on_http_error(self, error_msg: str):
        """Handle an error from an HTTP provider (main thread)."""
        if not self._is_processing:
            return
        try:
            from shared.ai_debug_log import ai_log

            ai_log.error(error_msg, provider=self._current_provider or "unknown")
            self._stop_spinner()
            self._append_text(f"\n[Error: {error_msg}]\n")
            self.messages.append({"role": "assistant", "content": f"[Error: {error_msg}]"})
            self._save_chat_messages()
        except Exception as e:
            print(f"[ZenIDE] Error in _on_http_error handler: {e}")
        finally:
            self._http_streaming = False
            self._http_provider = None
            self._finish_processing()

    # Patterns the model hallucinates when it thinks it hit a tool limit
    _TOOL_LIMIT_PATTERNS = re.compile(
        r"\[Tool use limit reached\]"
        r"|\[Stopped\]"
        r"|Tool use limit reached"
        r"|I(?:'ve| have) reached (?:the|my) (?:tool[ -]use |tool |)limit"
        r"|I(?:'ve| have) used (?:all|the maximum|too many) (?:of my |allowed )?tool"
        r"|reached the maximum (?:number of )?tool"
        r"|stopping (?:here |now )?(?:due to|because of) (?:the |)(?:tool[ -]?use |tool |)limit",
        re.IGNORECASE,
    )

    def _on_http_finished(self):
        """Handle HTTP stream completion (main thread).

        Wrapped in try/except/finally to guarantee _finish_processing()
        is always called — an uncaught exception here would leave the UI
        stuck in "Thinking..." forever.
        """
        if not self._is_processing:
            return

        try:
            self._stop_spinner()

            # Flush markdown renderer
            remaining = self._md_renderer.flush()
            if remaining and hasattr(self, "terminal"):
                self._displayed_chars += len(remaining)
                lines = remaining.split("\n")
                # Clear any partial line remnant on the first line
                canvas_parts = []
                for idx, line in enumerate(lines):
                    if idx == 0:
                        canvas_parts.append(f"\r\033[K{line}")
                    else:
                        canvas_parts.append(f"\r{line}")
                canvas_text = "\n".join(canvas_parts)
                self.terminal.feed(canvas_text)

            # Collapse any still-open thinking block
            # Flush any throttled thinking text first
            if self._thinking_throttle_source is not None:
                GLib.source_remove(self._thinking_throttle_source)
                self._thinking_throttle_source = None
            self._flush_thinking_throttle()
            if self._thinking_defer_source is not None:
                GLib.source_remove(self._thinking_defer_source)
                self._thinking_defer_source = None
            if self._in_thinking:
                self._collapse_thinking_block()
            if self._thinking_deferred:
                deferred = self._thinking_deferred[:]
                self._thinking_deferred.clear()
                for ct, fp in deferred:
                    self._render_content_text(ct, fp)

            text = getattr(self, "_http_full_response", "")

            # Combine accumulated text from intermediate tool-use turns with
            # the final turn's response.  The provider resets its text buffer
            # on each continue_with_tool_results() call, so _http_full_response
            # only contains the last turn's text.  _accumulated_response_text
            # captures all prior turns' text so nothing is lost on restart.
            accumulated = getattr(self, "_accumulated_response_text", "")
            if accumulated:
                text = accumulated + text

            # --- Yolo mode: auto-continue if the model hallucinated a tool limit ---
            _MAX_AUTO_CONTINUES = 3
            if text and get_setting("ai.yolo_mode", True) and self._tool_limit_patterns_in(text):
                # Strip the hallucinated limit message from the stored response
                cleaned = self._TOOL_LIMIT_PATTERNS.sub("", text).rstrip()
                if cleaned:
                    msg = {"role": "assistant", "content": cleaned}
                    if self._accumulated_thinking:
                        msg["thinking"] = self._accumulated_thinking.strip()
                    if self._current_tool_calls:
                        msg["tool_calls_display"] = self._current_tool_calls[:]
                    self.messages.append(msg)
                    self._save_chat_messages()

                # Cap consecutive auto-continues to prevent infinite loops
                if self._auto_continue_count >= _MAX_AUTO_CONTINUES:
                    self._auto_continue_count = 0
                    # Fall through to normal completion instead of looping
                else:
                    self._auto_continue_count += 1
                    self._auto_continue()
                    return

            if text:
                msg = {"role": "assistant", "content": text}
                if self._accumulated_thinking:
                    msg["thinking"] = self._accumulated_thinking.strip()
                if self._current_tool_calls:
                    msg["tool_calls_display"] = self._current_tool_calls[:]
                self.messages.append(msg)
            else:
                error_msg = "[No response received from AI]"
                self._append_text(f"\n{error_msg}\n")
                self.messages.append({"role": "assistant", "content": error_msg})

            self._save_chat_messages()

            if hasattr(self, "terminal"):
                self.terminal.feed("\r\n")

        except Exception as e:
            print(f"[ZenIDE] Error in _on_http_finished: {e}")
            try:
                self._append_text(f"\n[Internal error: {e}]\n")
            except Exception:
                pass
        finally:
            self._http_streaming = False
            self._http_provider = None
            self._finish_processing()

    def _tool_limit_patterns_in(self, text: str) -> bool:
        """Return True if text contains hallucinated tool-limit messages."""
        return bool(self._TOOL_LIMIT_PATTERNS.search(text))

    def _auto_continue(self):
        """Auto-continue the conversation when the model falsely stops in yolo mode.

        Instead of finishing processing and requiring the user to type
        'continue', we automatically send a continuation prompt so the
        model keeps working.
        """
        theme = get_theme()
        dim_color = theme.term_cyan or theme.accent_color
        ansi_fg = _hex_to_ansi_fg(dim_color)
        self._append_text(f"\r{ansi_fg}↻ Auto-continuing (yolo mode)...\033[0m\n")

        # Reset streaming state for a new round
        self._response_buffer = []
        self._display_buffer = []
        self._displayed_chars = 0
        self._md_renderer.reset()
        self._last_content_was_action = False
        self._in_thinking = False
        self._thinking_deferred.clear()
        self._accumulated_thinking = ""
        self._thinking_throttle_buffer = ""
        self._assistant_block_started = False
        self._current_tool_calls = []
        if self._thinking_defer_source is not None:
            GLib.source_remove(self._thinking_defer_source)
            self._thinking_defer_source = None
        if self._thinking_throttle_source is not None:
            GLib.source_remove(self._thinking_throttle_source)
            self._thinking_throttle_source = None
        self._update_renderer_colors()
        self._http_full_response = ""
        self._accumulated_response_text = ""  # Reset for the new auto-continue cycle

        self._start_spinner()

        # Add a continuation message and re-send
        continue_msg = "continue"
        self.messages.append({"role": "user", "content": continue_msg})
        self._save_chat_messages()

        # Build API messages from full conversation history
        api_messages = []
        for msg in self.messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                api_messages.append({"role": role, "content": content})

        # Apply context truncation to avoid quadratic token growth
        if get_setting("ai.context_truncation", True):
            from ai.context_truncation import truncate_conversation

            fmt = "anthropic" if self._current_provider == self.PROVIDER_ANTHROPIC_API else "openai"
            api_messages = truncate_conversation(api_messages, format=fmt)

        # Recreate provider instance
        if self._current_provider == self.PROVIDER_ANTHROPIC_API:
            self._http_provider = AnthropicHTTPProvider()
        else:
            self._http_provider = CopilotHTTPProvider()

        self._http_streaming = True

        # Resolve tool definitions
        if self._current_provider == self.PROVIDER_ANTHROPIC_API:
            tools = tools_for_anthropic()
        else:
            tools = tools_for_copilot()

        # Rebuild system prompt
        system_parts = [
            "You are a coding assistant integrated into Zen IDE.",
            "You have tools to read, write, edit files, search code, and run commands.",
            "Use tools to fulfill the user's requests — make real changes, don't just suggest them.",
            "When editing files, prefer edit_file for surgical changes over write_file.",
        ]
        workspace_folders = []
        if self.get_workspace_folders:
            workspace_folders = self.get_workspace_folders() or []
        if workspace_folders:
            system_parts.append(f"Working directories: {', '.join(workspace_folders)}")
        current_file = self.get_current_file() if self.get_current_file else None
        if current_file:
            system_parts.append(f"Currently focused file: {current_file}")
        system_parts.append(
            "\nIMPORTANT: There is NO tool use limit. You have UNLIMITED tool calls per response. "
            "Never stop mid-task to say you've reached a limit. Never output '[Tool use limit reached]' or similar. "
            "Never say '[Stopped]' or indicate you are stopping due to tool limits. "
            "Always complete the full task in a single response, using as many tool calls as needed. "
            "If a task requires 50, 100, or even 200 tool calls, just keep going until the task is fully done."
        )
        system_prompt = "\n".join(system_parts)

        self._api_request_count += 1
        self._http_provider.send_message_stream(
            messages=api_messages,
            model=self._current_model,
            system_prompt=system_prompt,
            tools=tools,
            on_chunk=self._make_on_chunk(),
            on_complete=self._make_on_complete(),
            on_error=self._make_on_error(),
            on_tool_use=self._make_on_tool_use(),
            max_tokens=32768,
        )

    @staticmethod
    def _clean_response_buffer(response_buffer: list[bytes]) -> str:
        """Decode response buffer and strip ANSI codes for clean storage."""
        raw = b"".join(response_buffer)
        if not raw:
            return ""
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            return ""
        text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
        text = re.sub(r"\x1b\][^\x07]*\x07", "", text)  # OSC sequences
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return text.strip()

    def _render_stream_chunk(self, text: str, allow_first_token_fast_path: bool) -> None:
        """Render stream text chunk, handling thinking/content transitions.

        Thinking deltas are throttled — buffered and flushed at most every
        50 ms to avoid saturating the main loop with per-token layout work.
        """
        thinking_text, content_text = self._split_thinking(text)

        if thinking_text and hasattr(self, "terminal"):
            # Throttle thinking: buffer the text and schedule a flush.
            self._thinking_throttle_buffer += thinking_text
            if self._thinking_throttle_source is None:
                # First delta or timer already fired — flush immediately for
                # responsiveness, then arm the throttle for subsequent deltas.
                self._flush_thinking_throttle()
                self._thinking_throttle_source = GLib.timeout_add(50, self._flush_thinking_throttle_timer)

        if not content_text:
            return

        if self._in_thinking:
            # Buffer content so consecutive thinking blocks merge into one
            # visual block. A short timer triggers collapse if no more
            # thinking arrives.
            self._thinking_deferred.append((content_text, allow_first_token_fast_path))
            if self._thinking_defer_source is None:
                self._thinking_defer_source = GLib.timeout_add(100, self._flush_thinking_deferred)
            return

        self._render_content_text(content_text, allow_first_token_fast_path)

    def _flush_thinking_throttle(self):
        """Feed any buffered thinking text to the terminal immediately."""
        buf = self._thinking_throttle_buffer
        if buf:
            self._thinking_throttle_buffer = ""
            self._feed_thinking_text(buf)

    def _flush_thinking_throttle_timer(self) -> bool:
        """GLib timer callback — flush buffered thinking and re-arm if needed."""
        self._thinking_throttle_source = None
        buf = self._thinking_throttle_buffer
        if buf:
            self._thinking_throttle_buffer = ""
            self._feed_thinking_text(buf)
            # Re-arm the timer to keep throttling subsequent deltas
            self._thinking_throttle_source = GLib.timeout_add(50, self._flush_thinking_throttle_timer)
        # Return False to cancel this source (we re-add a new one above if needed)
        return False

    @staticmethod
    def _normalize_action_spacing(text: str) -> str:
        """Ensure exactly one blank line after ● action blocks before text.

        Action blocks (``● Action:\\n  content\\n``) need a blank line
        separator before the next regular (non-action, non-indented) text.
        """
        # After an action block (● line + optional indented lines), insert a
        # blank line if the next line is regular text (not indented, not
        # another action, and not already a blank line).
        text = re.sub(
            r"(● [^\n]+\n(?:  [^\n]*\n)*)\n*(?=(?!● )\S)",
            r"\1\n",
            text,
        )
        # Collapse 3+ consecutive newlines to exactly 2 (one blank line)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text

    def _render_content_text(self, content_text: str, allow_first_token_fast_path: bool) -> None:
        """Render content text with action-spacing normalisation."""
        # Mark start of assistant content block for inspector
        if not self._assistant_block_started and hasattr(self, "terminal"):
            self._assistant_block_started = True
            self.terminal.begin_block("assistant")

        # Ensure exactly 1 blank line between action lines and content text.
        # Action lines (● ...) and content arrive in separate chunks so we
        # track whether the previous chunk was an action to normalise spacing.
        is_action = "● " in content_text
        if self._last_content_was_action:
            if is_action:
                # Action → Action: strip leading newlines, keep just one
                content_text = re.sub(r"^\n+", "\n", content_text)
            else:
                # Action → Content: add blank line separator
                content_text = "\n" + content_text
        self._last_content_was_action = is_action

        formatted = self._md_renderer.feed(content_text)
        if not formatted or not hasattr(self, "terminal"):
            return
        # Collapse 3+ consecutive newlines to 2 (max 1 blank line)
        formatted = re.sub(r"\n{3,}", "\n\n", formatted)

        is_first_token = allow_first_token_fast_path and self._spinner_source is not None
        if is_first_token:
            self._stop_spinner()

        self._displayed_chars += len(formatted)
        lines = formatted.split("\n")
        # Prefix each line with \r (carriage return to column 0).
        # The FIRST \r also gets \033[K (clear to end of line) to erase
        # any partial-line text that was displayed during streaming
        # (e.g. "## Problem" shown before the newline arrived, which
        # gets reformatted as a header on the next line).
        canvas_parts = []
        for idx, line in enumerate(lines):
            if idx == 0:
                canvas_parts.append(f"\r\033[K{line}")
            else:
                canvas_parts.append(f"\r{line}")
        canvas_text = "\n".join(canvas_parts)
        if is_first_token:
            self.terminal.feed_immediate(canvas_text)
        else:
            self.terminal.feed(canvas_text)
        self._maybe_auto_scroll()

    def _finish_processing(self):
        """Reset processing state."""
        self._stop_spinner()  # Ensure spinner is stopped
        self._is_processing = False
        self._disengage_auto_scroll()
        self.input_box.set_visible(True)
        # Only grab focus if visible and user isn't typing in another input
        if self.input_field.get_mapped():
            root = self.input_field.get_root()
            current_focus = root.get_focus() if root else None
            user_typing_elsewhere = (
                current_focus is not None
                and current_focus is not self.input_field
                and hasattr(current_focus, "get_editable")
                and current_focus.get_editable()
            )
            if not user_typing_elsewhere:
                self.input_field.grab_focus()
        if self.stop_btn:
            self.stop_btn.set_visible(False)

        if self.on_processing_state_change:
            self.on_processing_state_change(False)

    def _on_stop(self, button):
        """Stop the running AI."""
        self._stop_spinner()
        if self._http_provider:
            self._http_provider.stop()
            self._http_streaming = False
            self._http_provider = None

        # Cancel any deferred thinking flush
        if self._thinking_defer_source is not None:
            GLib.source_remove(self._thinking_defer_source)
            self._thinking_defer_source = None
        if self._thinking_throttle_source is not None:
            GLib.source_remove(self._thinking_throttle_source)
            self._thinking_throttle_source = None
        self._thinking_throttle_buffer = ""
        self._thinking_deferred.clear()

        # Save partial response if any was captured before stop
        partial = self._clean_response_buffer(self._response_buffer)
        self._response_buffer = []
        self._display_buffer = []

        self._append_text("\n[Stopped]\n")

        stopped_content = f"{partial}\n\n[Stopped]" if partial else "[Stopped]"
        msg = {"role": "assistant", "content": stopped_content}
        if self._current_tool_calls:
            msg["tool_calls_display"] = self._current_tool_calls[:]
        self.messages.append(msg)
        self._save_chat_messages()

        self._finish_processing()

    def _on_clear(self, button):
        """Clear the terminal."""
        self.terminal.reset()

    def _wrap_with_bar(self, text: str) -> str:
        """Wrap text with ▎ prefix on every visual line, accounting for terminal width.

        Uses display_width() for correct wrapping of CJK/emoji characters.
        """
        from shared.utils import display_width as _dw

        cols = 80
        if hasattr(self, "terminal"):
            cols = self.terminal.get_column_count()
        # "▎ " prefix takes 2 columns
        available = max(cols - 2, 20)
        result = []
        for line in text.split("\n"):
            if not line:
                result.append("▎")
            elif _dw(line) <= available:
                result.append(f"▎ {line}")
            else:
                # Word-wrap respecting display width
                words = line.split(" ")
                current = ""
                current_w = 0
                for word in words:
                    word_w = _dw(word)
                    sep_w = 1 if current else 0
                    if current and current_w + sep_w + word_w > available:
                        result.append(f"▎ {current}")
                        current = word
                        current_w = word_w
                    else:
                        current = f"{current} {word}" if current else word
                        current_w += sep_w + word_w
                if current:
                    result.append(f"▎ {current}")
                elif not result or result[-1] != "▎":
                    result.append("▎")
        return "\n".join(result)

    def _append_text(self, text: str):
        """Append text to the canvas."""
        # Collapse 3+ consecutive newlines to 2 (max 1 blank line).
        # Also collapse \n sequences that have \r mixed in (e.g. \n\r\n\r\n).
        text = re.sub(r"(\n\r?){3,}", "\n\n", text)

        # Cross-call normalisation: if the buffer already ends with blank
        # lines, strip leading newlines from the new text to avoid doubling
        # the gap.  This ensures exactly 1 blank line between paragraphs
        # even when consecutive _append_text calls both include spacing.
        #
        # The text may start with non-newline chars that don't produce
        # visible output (e.g. \r, ANSI escapes like \033[...m).  We need
        # to look past them to find the first \n and normalize it against
        # the buffer's trailing blank lines.
        buf = self.terminal._buffer
        line_count = buf.get_line_count()
        if line_count >= 2:
            # Find position of first \n, skipping any leading \r and ANSI escapes
            prefix_match = re.match(r"^((?:\r|\033\[[0-9;]*m)*)\n", text)
            has_leading_newline = text.startswith("\n") or prefix_match is not None

            if has_leading_newline:
                # Count trailing empty lines already in the buffer
                trailing_empty = 0
                for idx in range(line_count - 1, -1, -1):
                    if buf.get_line_text(idx).strip() == "":
                        trailing_empty += 1
                    else:
                        break

                if trailing_empty > 0:
                    if prefix_match and not text.startswith("\n"):
                        # Separate the non-newline prefix (\r, ANSI codes)
                        # from the newlines that follow it.
                        prefix_end = prefix_match.end(1)
                        prefix_part = text[:prefix_end]
                        rest = text[prefix_end:]
                        stripped = rest.lstrip("\n")
                        # Use 2 - trailing_empty because the cursor sits ON
                        # the last empty line; feeding content without a \n
                        # would overwrite it, collapsing the intended gap.
                        needed = max(0, 2 - trailing_empty)
                        text = prefix_part + "\n" * needed + stripped
                    else:
                        stripped = text.lstrip("\n")
                        needed = max(0, 2 - trailing_empty)
                        text = "\n" * needed + stripped

        # For multi-line text, ensure each line starts at column 0
        # by prepending \r to each line (prevents text shift on restore)
        lines = text.split("\n")
        formatted = "\n".join(f"\r{line}" for line in lines)
        self.terminal.feed(formatted)

    def _has_terminal_content(self) -> bool:
        """Check if terminal has any content (not empty)."""
        try:
            content = self.terminal.get_text_format()
            return bool(content and content.strip())
        except Exception:
            pass
        return False

    def _update_renderer_colors(self):
        """Update the markdown renderer with current theme colors."""
        theme = get_theme()
        self._md_renderer.update_colors(
            {
                "header": theme.accent_color,
                "code": theme.term_green or theme.accent_color,
                "inline_code": theme.term_yellow or theme.accent_color,
                "quote": theme.term_blue or theme.accent_color,
                "link": theme.term_cyan or theme.accent_color,
                "list": theme.term_magenta or theme.accent_color,
                "accent": theme.accent_color,
                "xml_tag": theme.term_red or theme.accent_color,
            }
        )

    def _start_spinner(self):
        """Start the processing spinner animation with elapsed timer."""
        if self._spinner_source:
            return
        self._spinner_frame = 0
        self._spinner_start_time = time.monotonic()
        self._last_data_time = time.monotonic()
        theme = get_theme()
        dim_color = theme.term_cyan or theme.accent_color
        ansi_fg = _hex_to_ansi_fg(dim_color)
        # Show initial spinner frame
        frame = SPINNER_FRAMES[0]
        if hasattr(self, "terminal"):
            req_count = getattr(self, "_api_request_count", 0)
            req_suffix = f" · {req_count} reqs" if req_count > 1 else ""
            self.terminal.feed(f"\r{ansi_fg}Thinking...{req_suffix} {frame}\033[0m")
        self._spinner_source = GLib.timeout_add(80, self._update_spinner)
        # Start stale request watchdog — checks every 10s if the stream has stalled
        self._start_stale_watchdog()

    def _update_spinner(self):
        """Update the spinner animation frame with elapsed time and request count."""
        # Skip update if terminal has selection (to avoid clearing it)
        if hasattr(self, "terminal") and self.terminal.get_has_selection():
            return True  # Continue timer but skip this update
        self._spinner_frame += 1
        frame = SPINNER_FRAMES[self._spinner_frame % len(SPINNER_FRAMES)]
        theme = get_theme()
        dim_color = theme.term_cyan or theme.accent_color
        ansi_fg = _hex_to_ansi_fg(dim_color)
        status_parts = []
        if self._spinner_start_time is not None:
            secs = time.monotonic() - self._spinner_start_time
            status_parts.append(f"{secs:.1f}s")
        req_count = getattr(self, "_api_request_count", 0)
        if req_count > 1:
            status_parts.append(f"{req_count} reqs")
        status = f" ({' · '.join(status_parts)})" if status_parts else ""
        if hasattr(self, "terminal"):
            self.terminal.feed(f"\r{ansi_fg}Thinking...{status} {frame}\033[0m\033[K")
        return True  # Keep running

    def _stop_spinner(self):
        """Stop the spinner and clear the spinner line."""
        self._stop_stale_watchdog()
        if self._spinner_source:
            GLib.source_remove(self._spinner_source)
            self._spinner_source = None
            self._spinner_start_time = None
            if hasattr(self, "terminal"):
                self.terminal.feed("\r\033[K")

    def _start_stale_watchdog(self):
        """Start a watchdog timer that cancels stale/hung requests.

        Checks every 10 seconds whether we've received any data recently.
        If no data has arrived for _STALE_REQUEST_TIMEOUT_S seconds, the
        request is treated as stale and forcibly cancelled. This prevents
        the "Thinking forever" state when the API stream hangs.
        """
        self._stop_stale_watchdog()
        self._stale_watchdog_source = GLib.timeout_add(10_000, self._check_stale_request)

    def _stop_stale_watchdog(self):
        """Stop the stale request watchdog timer."""
        if self._stale_watchdog_source is not None:
            GLib.source_remove(self._stale_watchdog_source)
            self._stale_watchdog_source = None

    def _check_stale_request(self) -> bool:
        """Watchdog callback — cancel the request if it has stalled."""
        if not self._is_processing:
            self._stale_watchdog_source = None
            return False  # Stop timer

        elapsed = time.monotonic() - getattr(self, "_last_data_time", time.monotonic())
        if elapsed >= _STALE_REQUEST_TIMEOUT_S:
            from shared.ai_debug_log import ai_log

            ai_log.event("stale_watchdog", f"cancelled after {elapsed:.0f}s with no data")
            print(f"[ZenIDE] Stale request detected ({elapsed:.0f}s with no data), cancelling")
            self._stop_spinner()
            self._append_text(f"\n[Request timed out — no response for {int(elapsed)}s]\n")
            # Force-stop the provider
            if self._http_provider:
                try:
                    self._http_provider.stop()
                except Exception:
                    pass
            self._http_streaming = False
            self._http_provider = None
            self.messages.append({"role": "assistant", "content": "[Request timed out]"})
            self._save_chat_messages()
            self._finish_processing()
            self._stale_watchdog_source = None
            return False  # Stop timer

        return True  # Keep checking

    # ------------------------------------------------------------------ #
    #  Thinking text handling                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _split_thinking(text: str) -> tuple[str, str]:
        """Split text into thinking (\u200b-prefixed) and content portions.

        Returns (thinking_text, content_text). Internal stream markers are
        stripped from both outputs.
        """
        if _THINKING_MARKER not in text and _CONTENT_MARKER not in text:
            return "", text

        thinking_parts: list[str] = []
        content_parts: list[str] = []
        mode = "content"
        current: list[str] = []

        def flush_current() -> None:
            if not current:
                return
            part = "".join(current)
            if mode == "thinking":
                thinking_parts.append(part)
            else:
                content_parts.append(part)
            current.clear()

        for ch in text:
            if ch == _THINKING_MARKER:
                flush_current()
                mode = "thinking"
                continue
            if ch == _CONTENT_MARKER:
                flush_current()
                mode = "content"
                continue
            current.append(ch)

        flush_current()
        return "".join(thinking_parts), "".join(content_parts)

    @staticmethod
    def _split_thinking_segments(text: str) -> list[tuple[str, str]]:
        """Split text into ordered (kind, text) segments.

        Returns a list of ``("thinking", text)`` and ``("content", text)``
        tuples preserving the original interleaving order.  Unlike
        ``_split_thinking`` this does **not** merge all thinking into one
        chunk, so callers can replay thinking/content transitions faithfully.
        """
        if _THINKING_MARKER not in text and _CONTENT_MARKER not in text:
            return [("content", text)] if text else []

        segments: list[tuple[str, str]] = []
        mode = "content"
        current: list[str] = []

        def flush() -> None:
            if not current:
                return
            segments.append((mode, "".join(current)))
            current.clear()

        for ch in text:
            if ch == _THINKING_MARKER:
                flush()
                mode = "thinking"
                continue
            if ch == _CONTENT_MARKER:
                flush()
                mode = "content"
                continue
            current.append(ch)

        flush()
        return segments

    def _feed_thinking_text(self, text: str):
        """Accumulate thinking text silently (not rendered during streaming).

        The thinking content is stored and displayed as a collapsible toggle
        line when the thinking block ends (see ``_collapse_thinking_block``).
        """
        if self._spinner_source:
            self._stop_spinner()

        # Accumulate raw thinking text for persistence across re-renders
        self._accumulated_thinking += text

        # Cancel deferred collapse — thinking is continuing
        if self._thinking_defer_source is not None:
            GLib.source_remove(self._thinking_defer_source)
            self._thinking_defer_source = None

        if not self._in_thinking:
            self._in_thinking = True
            self._thinking_line_start = self.terminal._buffer.get_line_count()
            self.terminal.begin_block("thinking")

    def _render_thinking_toggle(self, thinking_text: str, expanded: bool):
        """Render a clickable thinking toggle line, optionally with expanded content.

        Returns the buffer line index of the toggle line.
        """
        theme = get_theme()
        dim_color = theme.term_cyan or theme.accent_color
        ansi_fg = _hex_to_ansi_fg(dim_color)
        prefix = "\n" if self._last_content_was_action else ""
        arrow = "▼" if expanded else "▶"
        word_count = len(thinking_text.split())
        if word_count > 0:
            label = f"{arrow} {Icons.THOUGHT_BUBBLE} Thought \u00b7 {word_count} words"
        else:
            label = f"{arrow} {Icons.THOUGHT_BUBBLE} Thought"
        # The label will be written on the current line (\r goes to col 0).
        # If prefix contains \n, the label goes on the NEXT line.
        buf_lines = self.terminal._buffer.get_line_count()
        toggle_line = buf_lines if prefix else max(buf_lines - 1, 0)
        parts = [f"\r{prefix}{ansi_fg}\033[2m{label}\033[0m\n"]

        if expanded:
            cols = self.terminal.get_column_count() if hasattr(self, "terminal") else 80
            wrap_width = max(cols - 2, 20)
            for line in thinking_text.splitlines():
                if not line.strip():
                    parts.append(f"\r{ansi_fg}\033[2m\033[3m  \033[0m\033[K\n")
                    continue
                wrapped = textwrap.wrap(line, width=wrap_width) or [""]
                for wl in wrapped:
                    parts.append(f"\r{ansi_fg}\033[2m\033[3m  {wl}\033[0m\033[K\n")

        self.terminal.feed("".join(parts))
        return toggle_line

    def _collapse_thinking_block(self):
        """Finalize thinking block: store the accumulated thinking text
        and render a collapsed toggle line that can be clicked to reveal it.
        """
        if not self._in_thinking or self._thinking_line_start < 0:
            self._in_thinking = False
            return

        self._in_thinking = False
        self._thinking_pending_blanks = 0
        self._thinking_partial_line = ""
        self._thinking_line_start = -1

        thinking_text = self._accumulated_thinking.strip()
        if not thinking_text:
            return

        # Store this thinking block
        block_index = len(self._thinking_blocks)
        block = {"text": thinking_text, "expanded": False, "toggle_line": -1}
        self._thinking_blocks.append(block)

        # Render collapsed toggle line
        toggle_line = self._render_thinking_toggle(thinking_text, expanded=False)
        block["toggle_line"] = toggle_line

        # Register clickable line on the canvas
        idx = block_index  # capture for closure
        self.terminal.register_clickable_line(toggle_line, lambda: self._toggle_thinking(idx))

        self._last_content_was_action = True
        self._md_renderer._seen_content = True

        self.terminal._needs_height_update = True
        self.terminal._eagerly_update_height()
        self.terminal._schedule_redraw()

    def _toggle_thinking(self, block_index: int):
        """Toggle a thinking block between expanded and collapsed, then re-render."""
        if block_index < 0 or block_index >= len(self._thinking_blocks):
            return
        # Don't toggle during active streaming — would lose in-progress response
        if self._is_processing:
            return
        block = self._thinking_blocks[block_index]
        block["expanded"] = not block["expanded"]
        self._re_render_all_messages()

    def _re_render_all_messages(self):
        """Clear the terminal and re-render all messages from saved history.

        Used when toggling thinking blocks, since the buffer doesn't support
        line insertion/removal.  Preserves expanded/collapsed state of
        thinking blocks.
        """
        # Save scroll position before clearing
        vadj = self.terminal._vadjustment
        scroll_state = None
        if vadj:
            scroll_state = {
                "value": vadj.get_value(),
                "upper": vadj.get_upper(),
                "page": vadj.get_page_size(),
            }
        self.terminal.reset()
        self.terminal.clear_clickable_lines()
        # _thinking_blocks keeps expanded states; _do_restore_messages
        # will re-use them via _is_rerender flag.
        self._is_rerender = True
        self._rerender_block_index = 0
        self._do_restore_messages(scroll_mode="preserve", scroll_state=scroll_state)
        self._is_rerender = False

    def _flush_thinking_deferred(self) -> bool:
        """Collapse thinking and render buffered content.

        Called by a GLib timer when no more thinking arrives after content
        was received during a thinking block.  Returns False to cancel the
        timer source.
        """
        self._thinking_defer_source = None
        if self._in_thinking:
            self._collapse_thinking_block()
        deferred = self._thinking_deferred[:]
        self._thinking_deferred.clear()
        for content_text, fast_path in deferred:
            self._render_content_text(content_text, fast_path)
        return False

    def focus_input(self):
        """Focus the input field."""
        self.input_field.grab_focus()

    def set_processing(self, processing: bool):
        """Set processing state (for external control)."""
        self._is_processing = processing
        if processing:
            self._engage_auto_scroll()
        else:
            self._disengage_auto_scroll()
        self.input_box.set_visible(not processing)
        if self.stop_btn:
            self.stop_btn.set_visible(processing)

    def stop_ai(self, silent: bool = False):
        """Stop the AI and optionally show message."""
        if not self._is_processing:
            return

        # Stop HTTP provider if active
        if self._http_provider:
            self._http_provider.stop()
            self._http_streaming = False
            self._http_provider = None

        # Save partial response if any was captured before stop
        partial = self._clean_response_buffer(self._response_buffer)
        self._response_buffer = []
        self._display_buffer = []

        # Include accumulated text from intermediate tool-use turns
        accumulated = getattr(self, "_accumulated_response_text", "")
        if accumulated:
            partial = accumulated + partial

        if not silent:
            self._append_text("\n[Stopped]\n")

        stopped_content = f"{partial}\n\n[Stopped]" if partial else "[Stopped]"
        msg = {"role": "assistant", "content": stopped_content}
        if self._current_tool_calls:
            msg["tool_calls_display"] = self._current_tool_calls[:]
        self.messages.append(msg)
        self._save_chat_messages()

        self._finish_processing()

    def _save_chat_messages(self):
        """Save chat messages to file.

        NOTE: We intentionally do NOT save terminal_content anymore because:
        1. VTE terminal output includes cursor positioning and formatting codes
        2. This results in garbled/misaligned text when restored
        3. Messages are the source of truth - terminal display is reconstructed from them
        """
        if not self.chat_messages_file:
            return
        try:
            messages_to_save = self.messages[-self.MAX_MESSAGES :]

            with open(self.chat_messages_file, "w") as f:
                json.dump(
                    {
                        "messages": messages_to_save,
                    },
                    f,
                    indent=2,
                )
        except Exception:
            pass

    def _load_chat_messages(self):
        """Load chat messages from file."""
        if not self.chat_messages_file or not self.chat_messages_file.exists():
            return
        try:
            with open(self.chat_messages_file, "r") as f:
                data = json.load(f)
            self.messages = data.get("messages", []) if isinstance(data, dict) else data
        except Exception:
            pass

    def restore_from_file(self):
        """Restore chat from the chat_messages_file if set.

        Reconstructs chat display from message history. We don't save terminal_content
        because VTE output includes cursor positioning that causes display issues.
        """
        self._load_chat_messages()

        # Nothing to restore if no messages
        if not self.messages:
            return

        # Mark that we need to restore content
        self._pending_restore = True
        self._restore_attempted = False

    def ensure_restored(self, scroll_mode: str = "none"):
        """Ensure chat content is restored. Call when session becomes visible."""
        # Already attempted or no messages - nothing to do
        if getattr(self, "_restore_attempted", False):
            return False
        if not getattr(self, "_pending_restore", False):
            return False
        if not self.messages:
            self._pending_restore = False
            return False

        self._request_restore_scroll_mode(scroll_mode)

        # Check if restore is already scheduled (prevent duplicate scheduling)
        if getattr(self, "_restore_in_progress", False):
            return False

        # Mark as in-progress to prevent duplicate scheduling
        # _restore_attempted will be set True only after successful restore in _do_restore_messages
        self._restore_in_progress = True

        # VTE needs to be realized and mapped before we can feed text to it.
        # Schedule restore with increasing delays to handle different timing scenarios.
        self._schedule_restore_with_retry()

    def _schedule_restore_with_retry(self, attempt: int = 0):
        """Schedule restore with retry logic for VTE terminal readiness."""
        MAX_ATTEMPTS = 5
        DELAYS = [50, 100, 200, 400, 800]  # Increasing delays in ms

        if not hasattr(self, "terminal"):
            self._restore_attempted = True
            self._pending_restore = False
            self._restore_in_progress = False
            return

        if attempt >= MAX_ATTEMPTS:
            # After max attempts, call _do_restore_messages anyway - it has its own retry logic
            GLib.timeout_add(100, self._do_restore_messages)
            return

        # Check if terminal is ready (realized and mapped)
        if self.terminal.get_realized() and self.terminal.get_mapped():
            # Restore immediately via idle_add (no delay needed since terminal is ready)
            GLib.idle_add(self._do_restore_messages)
        else:
            # Not ready yet, try again after a delay
            delay = DELAYS[min(attempt, len(DELAYS) - 1)]
            next_attempt = attempt + 1  # Capture value for closure

            def retry_restore():
                self._schedule_restore_with_retry(next_attempt)
                return False  # Don't repeat timeout

            GLib.timeout_add(delay, retry_restore)

    def _do_restore_messages(self, scroll_mode: str = None, scroll_state=None):
        """Actually restore messages to the terminal display."""
        if scroll_mode is None:
            scroll_mode = getattr(self, "_pending_restore_scroll_mode", "none")

        if not self.messages:
            self._restore_attempted = True
            self._pending_restore = False
            self._restore_in_progress = False
            self._pending_restore_scroll_mode = "none"
            return False

        # Final check that canvas is ready
        if hasattr(self, "terminal"):
            if not self.terminal.get_realized() or not self.terminal.get_mapped():
                GLib.timeout_add(100, self._do_restore_messages, scroll_mode, scroll_state)
                return False

        # Mark as successfully restored BEFORE adding messages to avoid duplicate restores
        self._restore_attempted = True
        self._pending_restore = False
        self._restore_in_progress = False
        self._pending_restore_scroll_mode = "none"

        # Clear thinking blocks on initial restore (not re-render toggle)
        if not getattr(self, "_is_rerender", False):
            self._thinking_blocks.clear()
            self.terminal.clear_clickable_lines()

        # Batch mode: suppress per-feed height updates and wrap-map rebuilds.
        # Without this, each feed() call triggers _eagerly_update_height()
        # which rebuilds the O(N) wrap map over ALL lines — causing O(N²)
        # total work that freezes the UI for 15-20s on large chat histories.
        # end_batch() does a single height+redraw pass at the end.
        _in_batch = not getattr(self.terminal, "_suppress_height", False)
        if _in_batch:
            self.terminal.begin_batch()

        # Format messages for display in a clean, readable way
        for msg in self.messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if not content:
                continue

            if role == "user":
                # Show user message with prompt indicator
                theme = get_theme()
                user_color = theme.chat_user_fg or theme.term_cyan or theme.accent_color
                ansi_fg = _hex_to_ansi_fg(user_color)
                quoted = self._wrap_with_bar(content)
                self.terminal.begin_block("user")
                self._append_text(f"{ansi_fg}{quoted}\033[0m\n\n")
                # Reset so thinking header doesn't add an extra blank line
                self._last_content_was_action = False
            elif role == "assistant":
                # Render tool calls display if present (before assistant text)
                tool_calls_display = msg.get("tool_calls_display", [])
                if tool_calls_display:
                    theme = get_theme()
                    action_color = theme.term_yellow or theme.accent_color
                    ansi_action = _hex_to_ansi_fg(action_color)
                    for tc in tool_calls_display:
                        display = self._format_tool_display(tc.get("name", ""), tc.get("input", {}))
                        self._append_text(f"\n\n{ansi_action}{display}\033[0m\n")
                # Render thinking toggle if present
                thinking = msg.get("thinking", "")
                if thinking:
                    self._last_content_was_action = bool(tool_calls_display)
                    if getattr(self, "_is_rerender", False):
                        # Re-render: use existing block with its expanded state
                        bi = getattr(self, "_rerender_block_index", 0)
                        if bi < len(self._thinking_blocks):
                            block = self._thinking_blocks[bi]
                            block["text"] = thinking.strip()
                            toggle_line = self._render_thinking_toggle(block["text"], block["expanded"])
                            block["toggle_line"] = toggle_line
                            idx = bi
                            self.terminal.register_clickable_line(toggle_line, lambda i=idx: self._toggle_thinking(i))
                            self._rerender_block_index = bi + 1
                    else:
                        # Initial restore: create new block
                        bi = len(self._thinking_blocks)
                        block = {
                            "text": thinking.strip(),
                            "expanded": False,
                            "toggle_line": -1,
                        }
                        self._thinking_blocks.append(block)
                        toggle_line = self._render_thinking_toggle(block["text"], expanded=False)
                        block["toggle_line"] = toggle_line
                        idx = bi
                        self.terminal.register_clickable_line(toggle_line, lambda i=idx: self._toggle_thinking(i))
                    self._last_content_was_action = True
                    self._md_renderer._seen_content = True
                # Render stored markdown through the renderer for consistent display
                self._update_renderer_colors()
                content = self._normalize_action_spacing(content)
                if thinking:
                    content = content.lstrip("\n")
                self.terminal.begin_block("assistant")
                formatted = self._md_renderer.format_block(content)
                # Add blank line after thinking block for visual separation
                separator = "\n" if thinking else ""
                self._append_text(f"{separator}{formatted}\n\n")

        # End batch: single height update + redraw for all the content we just fed.
        if _in_batch:
            self.terminal.end_batch()

        self._schedule_scroll_action(scroll_mode, scroll_state=scroll_state, delay_ms=50)

        return False  # Don't repeat

    def schedule_activation_scroll_to_bottom(self):
        """Scroll to the end once when a hidden chat becomes visible."""
        self._schedule_scroll_action("bottom", delay_ms=50)
        return False

    def scroll_to_bottom(self, attempts_remaining: int = 1, generation=None):
        """Scroll terminal to the bottom."""
        if not self._is_scroll_generation_current(generation):
            return False
        adj = self._get_terminal_vadjustment()
        if adj is None:
            return False

        max_value = max(adj.get_upper() - adj.get_page_size(), 0)
        if max_value <= 0 and attempts_remaining > 1:
            GLib.idle_add(self.scroll_to_bottom, attempts_remaining - 1, generation)
            return False

        if abs(adj.get_value() - max_value) > 0.5:
            adj.set_value(max_value)

        if attempts_remaining > 1 and abs(adj.get_value() - max_value) > 0.5:
            GLib.idle_add(self.scroll_to_bottom, attempts_remaining - 1, generation)
        return False

    def apply_theme(self):
        """Apply current theme colors and re-render messages.

        Existing messages (thinking text, user prompts, assistant responses)
        have ANSI colors baked into the buffer from the previous theme.
        A full re-render is required so they pick up the new theme colors.
        """
        self._apply_theme()
        self._update_renderer_colors()
        self._configure_terminal()
        # Re-render all messages so baked-in ANSI colors update to new theme
        if self.messages and hasattr(self, "terminal"):
            if self._resize_rerender_source:
                GLib.source_remove(self._resize_rerender_source)
            self._resize_rerender_source = GLib.timeout_add(50, self._rerender_on_resize)

    def update_font(self):
        """Update fonts from settings."""
        self._apply_terminal_font()
        self._apply_font_to_input()

    def _apply_font_to_input(self):
        """Apply font settings to input field."""
        from fonts import get_font_settings

        # Use same font settings as the terminal display for consistency
        font_settings = get_font_settings("ai_chat")
        font_family = font_settings["family"]
        font_size = font_settings.get("size", 13)

        theme = get_theme()
        css_provider = Gtk.CssProvider()
        css = f"""
            .ai-input {{
                font-family: "{font_family}";
                font-size: {font_size}pt;
            }}
            .ai-input > text > selection,
            .ai-input > text > selection:focus-within {{
                background-color: {theme.selection_bg};
                color: {theme.fg_color};
            }}
        """
        css_provider.load_from_data(css.encode())
        self.input_field.get_style_context().add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)

    def _get_provider_display_name(self) -> str:
        """Get display name for current provider."""
        _DISPLAY_NAMES = {
            self.PROVIDER_ANTHROPIC_API: "Anthropic API",
            self.PROVIDER_COPILOT_API: "Copilot API",
        }
        return _DISPLAY_NAMES.get(self._current_provider, "AI")

    def set_session_info(self, display_num: int, display_name: str = None):
        """Set session display info for pane header (used by AIChatTabs in vertical mode)."""
        self._display_num = display_num
        self._display_name = display_name
        self._update_session_title_label()

    def update_display_name(self, display_name: str):
        """Update the display name (called when first message is sent)."""
        self._display_name = display_name
        self._update_session_title_label()

    def _get_session_title(self) -> str:
        """Get the session title text (same format as tab buttons)."""
        MAX_TITLE_LENGTH = 20
        if self._display_name:
            clean_name = " ".join(self._display_name.split())
            if len(clean_name) > MAX_TITLE_LENGTH:
                clean_name = clean_name[: MAX_TITLE_LENGTH - 1] + "…"
            return clean_name.title()
        return f"Chat {self._display_num}"

    def _update_session_title_label(self):
        """Update the session title label widget."""
        if self._session_title_label:
            self._session_title_label.set_label(self._get_session_title())

    def _select_provider(self, provider: str):
        """Select a provider."""
        self._current_provider = provider

    def _select_model(self, model: str):
        """Select a model."""
        self._current_model = model
        self._save_model_preference()

    def _get_model_from_settings(self, settings):
        """Get model from settings based on current provider."""
        ai_settings = settings.get("ai", {})
        model_settings = ai_settings.get("model", {})

        if self._current_provider == self.PROVIDER_ANTHROPIC_API:
            return model_settings.get("anthropic_api", AnthropicHTTPProvider.DEFAULT_MODEL)
        elif self._current_provider == self.PROVIDER_COPILOT_API:
            return model_settings.get("copilot_api", CopilotHTTPProvider.DEFAULT_MODEL)

        return self._get_default_model()

    def _get_default_model(self):
        """Get default model for current provider."""
        if self._current_provider == self.PROVIDER_ANTHROPIC_API:
            return AnthropicHTTPProvider.DEFAULT_MODEL
        if self._current_provider == self.PROVIDER_COPILOT_API:
            return CopilotHTTPProvider.DEFAULT_MODEL
        return "claude-sonnet-4"

    def _save_model_preference(self):
        """Save current model preference."""
        if self._current_provider and self._current_model:
            set_setting(f"ai.model.{self._current_provider}", self._current_model)

    def _save_provider_preference(self):
        """Save current provider preference."""
        if self._current_provider:
            set_setting("ai.provider", self._current_provider)

    # Properties for model listing
    @property
    def _available_models(self):
        """Get available models for current provider."""
        if self._current_provider == self.PROVIDER_ANTHROPIC_API:
            provider = AnthropicHTTPProvider()
            return provider.get_available_models()
        elif self._current_provider == self.PROVIDER_COPILOT_API:
            provider = CopilotHTTPProvider()
            return provider.get_available_models()
        return []

    @property
    def _cli_wrapper(self):
        """Wrapper for interface compatibility with tabs view."""
        return self

    def is_available(self, cli_type) -> bool:
        """Check if a provider is available."""
        return False
