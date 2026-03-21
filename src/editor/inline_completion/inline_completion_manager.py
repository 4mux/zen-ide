"""
Inline completion manager — coordinates ghost text suggestions.

Handles the full lifecycle: debounced triggering after keystrokes,
context gathering, AI provider calls, ghost text display, and
keyboard interactions (Tab to accept, Escape to dismiss).
"""

import time

from gi.repository import GLib

from shared.settings import get_setting

from .context_gatherer import gather_context
from .ghost_text_renderer import GhostTextRenderer
from .inline_completion_provider import InlineCompletionProvider

# Debounce delay before requesting a completion (ms)
_DEFAULT_TRIGGER_DELAY_MS = 500


class AdaptiveDebounce:
    """Adjusts debounce delay based on typing speed.

    Fast typing (short inter-key intervals) → longer delay (user hasn't paused).
    Slow typing (long intervals) → shorter delay (user is thinking).
    """

    def __init__(self, min_ms: int = 300, max_ms: int = 800, window_size: int = 5):
        self._min_ms = min_ms
        self._max_ms = max_ms
        self._timestamps: list[float] = []
        self._window = window_size

    def record_keystroke(self):
        now = time.monotonic()
        self._timestamps.append(now)
        if len(self._timestamps) > self._window:
            self._timestamps = self._timestamps[-self._window :]

    def get_delay_ms(self) -> int:
        if len(self._timestamps) < 2:
            return self._max_ms
        intervals = [self._timestamps[i] - self._timestamps[i - 1] for i in range(1, len(self._timestamps))]
        avg = sum(intervals) / len(intervals)
        # Fast typing (avg < 100ms) → longer delay (user hasn't paused yet)
        if avg < 0.1:
            return self._max_ms
        # Slow typing (avg > 500ms) → shorter delay (user is thinking)
        if avg > 0.5:
            return self._min_ms
        # Linear interpolation between extremes
        t = (avg - 0.1) / 0.4
        return int(self._max_ms - t * (self._max_ms - self._min_ms))


class InlineCompletionManager:
    """Manages AI inline completions for an editor tab."""

    def __init__(self, editor_tab):
        self._tab = editor_tab
        self._renderer = GhostTextRenderer(editor_tab.view)
        self._provider = InlineCompletionProvider()
        self._trigger_timer_id = None
        self._enabled = True
        self._debounce = AdaptiveDebounce()

        # Multi-suggestion state
        self._suggestions: list[str] = []
        self._suggestion_index = 0

        # Connect to buffer changes to trigger completions
        self._changed_handler_id = editor_tab.buffer.connect("changed", self._on_buffer_changed)

    def is_enabled(self) -> bool:
        """Check if inline suggestions are enabled in settings."""
        if not get_setting("ai.is_enabled", True):
            return False
        return get_setting("ai.show_inline_suggestions", True)

    @property
    def is_active(self) -> bool:
        """Whether ghost text is currently visible."""
        return self._renderer.is_active

    def handle_key(self, keyval, state) -> bool:
        """Handle a key press when ghost text is visible.

        Returns True if the key was consumed (ghost text action taken).
        Called from EditorTab._on_key_pressed before other key handling.
        """
        if not self._renderer.is_active:
            return False

        from gi.repository import Gdk

        # Tab: accept full suggestion
        if keyval == Gdk.KEY_Tab:
            self.accept()
            return True

        # Escape: dismiss suggestion
        if keyval == Gdk.KEY_Escape:
            self.dismiss()
            return True

        # Cmd+Right / Ctrl+Right: accept word
        import platform

        is_mod = (
            bool(state & Gdk.ModifierType.META_MASK)
            if platform.system() == "Darwin"
            else bool(state & Gdk.ModifierType.CONTROL_MASK)
        )
        if is_mod and keyval == Gdk.KEY_Right:
            self.accept_word()
            return True

        # Alt+] / Alt+[: cycle through alternative suggestions
        is_alt = bool(state & Gdk.ModifierType.ALT_MASK)
        if is_alt and keyval == Gdk.KEY_bracketright:
            self.cycle_next()
            return True
        if is_alt and keyval == Gdk.KEY_bracketleft:
            self.cycle_prev()
            return True

        # Any other key: dismiss ghost text (user is typing)
        self.dismiss()
        return False

    def accept(self):
        """Accept the full ghost text suggestion."""
        text = self._renderer.accept()
        if text:
            pass

    def accept_word(self):
        """Accept the next word of the ghost text."""
        word = self._renderer.accept_word()
        if word:
            pass

    def cycle_next(self):
        """Show the next alternative suggestion (Alt+]).

        If only one suggestion is available, requests alternatives from the API.
        """
        if len(self._suggestions) <= 1:
            self._request_alternatives()
            return
        self._suggestion_index = (self._suggestion_index + 1) % len(self._suggestions)
        self._renderer.clear()
        self._renderer.show(self._suggestions[self._suggestion_index])

    def cycle_prev(self):
        """Show the previous alternative suggestion (Alt+[).

        If only one suggestion is available, requests alternatives from the API.
        """
        if len(self._suggestions) <= 1:
            self._request_alternatives()
            return
        self._suggestion_index = (self._suggestion_index - 1) % len(self._suggestions)
        self._renderer.clear()
        self._renderer.show(self._suggestions[self._suggestion_index])

    def _request_alternatives(self):
        """Request multiple alternative completions from the provider."""
        if not self.is_enabled():
            return

        context = gather_context(self._tab)
        self._provider.request_alternatives(
            context,
            on_results=self._on_alternatives_received,
            on_error=self._on_completion_error,
            n=3,
        )

    def _on_alternatives_received(self, completions: list[str]):
        """Handle multiple alternative completions (called on the main thread)."""
        if not completions or not self.is_enabled():
            return

        self._suggestions = completions
        # Show the second suggestion (first is likely similar to what's already showing)
        self._suggestion_index = 1 if len(completions) > 1 else 0
        self._renderer.clear()
        self._renderer.show(self._suggestions[self._suggestion_index])

    def trigger_now(self):
        """Manually trigger an inline completion request (bypasses debounce)."""
        self._cancel_pending()
        if not self.is_enabled():
            return
        self._trigger_completion()

    def dismiss(self):
        """Dismiss the current ghost text suggestion."""
        self._cancel_pending()
        self._renderer.clear()
        self._suggestions.clear()
        self._suggestion_index = 0

    def _on_buffer_changed(self, buffer):
        """Handle buffer text changes — trigger completion after adaptive delay."""
        # Skip if our own ghost text operations caused the change
        if self._renderer._inserting:
            return

        # Record keystroke for adaptive debouncing
        self._debounce.record_keystroke()

        # Clear any existing ghost text immediately
        if self._renderer.is_active:
            self._renderer.clear()

        # Cancel pending requests
        self._cancel_pending()

        # Don't trigger if disabled
        if not self.is_enabled():
            return

        # Use adaptive delay based on typing speed
        delay = self._debounce.get_delay_ms()
        self._trigger_timer_id = GLib.timeout_add(delay, self._trigger_completion)

    def _trigger_completion(self):
        """Request an AI completion (called after debounce)."""
        self._trigger_timer_id = None

        if not self.is_enabled():
            return False

        # Don't trigger if autocomplete popup is visible
        if hasattr(self._tab, "_autocomplete") and self._tab._autocomplete.is_visible():
            return False

        # Gather context
        context = gather_context(self._tab)

        # Skip if prefix line is empty (nothing typed yet)
        prefix_line = context.prefix.split("\n")[-1] if context.prefix else ""
        if not prefix_line.strip():
            return False

        # Don't trigger after trailing whitespace on complete-looking lines.
        # Adding a space/tab after a finished statement (e.g. "return True ")
        # causes the chat model to hallucinate irrelevant completions.
        # Allow continuation when line ends with operators/brackets that
        # clearly expect more code (e.g. "x = ", "if (", "items.").
        if prefix_line and prefix_line[-1] in (" ", "\t"):
            rstripped = prefix_line.rstrip()
            if rstripped:
                last_char = rstripped[-1]
                _CONTINUATION_CHARS = frozenset("=([{,.:+-*/%\\|&<>!^~@#")
                if last_char not in _CONTINUATION_CHARS:
                    return False

        # Request completion with streaming support
        self._provider.request_completion(
            context,
            on_result=self._on_completion_received,
            on_error=self._on_completion_error,
            on_chunk=self._on_streaming_chunk,
        )

        return False  # Don't repeat GLib timer

    def _on_completion_received(self, text: str):
        """Handle a completion result (called on the main thread).

        When streaming was used, this is called with the final cleaned text
        to replace any partial ghost text with the properly cleaned version.
        """
        if not text or not self.is_enabled():
            return

        # Don't show if autocomplete popup is visible
        if hasattr(self._tab, "_autocomplete") and self._tab._autocomplete.is_visible():
            return

        # Store suggestion for cycling
        if not self._suggestions or self._suggestions[0] != text:
            self._suggestions = [text]
            self._suggestion_index = 0

        # Replace any streaming ghost text with the final cleaned version
        self._renderer.clear()
        self._renderer.show(text)
        self._tab.view.queue_draw()

    def _on_streaming_chunk(self, chunk: str):
        """Handle a streaming chunk — append to ghost text progressively."""
        if not chunk or not self.is_enabled():
            return
        if hasattr(self._tab, "_autocomplete") and self._tab._autocomplete.is_visible():
            return
        self._renderer.append(chunk)

    def _on_completion_error(self, error: str):
        """Handle a completion error."""

    def _cancel_pending(self):
        """Cancel pending timer and in-flight request."""
        if self._trigger_timer_id is not None:
            GLib.source_remove(self._trigger_timer_id)
            self._trigger_timer_id = None
        self._provider.cancel()

    def update_theme(self):
        """Update ghost text styling when the theme changes."""
        self._renderer.update_theme()

    def destroy(self):
        """Clean up resources."""
        self._cancel_pending()
        self._renderer.clear()
        if self._changed_handler_id and self._tab.buffer.handler_is_connected(self._changed_handler_id):
            self._tab.buffer.disconnect(self._changed_handler_id)
            self._changed_handler_id = None
