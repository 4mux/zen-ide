"""Debug Console — REPL-style expression evaluator widget.

Provides a text-based console for program output and expression evaluation
during debug sessions. Supports command history and auto-scroll.
"""

from gi.repository import Gdk, Gtk

from themes import get_theme


class DebugConsole(Gtk.Box):
    """REPL-style debug console with output display and expression input."""

    def __init__(self, on_evaluate: callable = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_evaluate = on_evaluate
        self._history: list[str] = []
        self._history_index = -1

        theme = get_theme()

        # Output text view (scrollable, read-only)
        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_vexpand(True)
        self._scroll.set_hexpand(True)
        self._scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.append(self._scroll)

        self._output = Gtk.TextView()
        self._output.set_editable(False)
        self._output.set_cursor_visible(False)
        self._output.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._output.set_monospace(True)
        self._output.add_css_class("debug-console-output")
        self._scroll.set_child(self._output)

        # Create text tags for different output categories
        buf = self._output.get_buffer()
        buf.create_tag("stdout", foreground=theme.fg_color)
        buf.create_tag("stderr", foreground=theme.term_red)
        buf.create_tag("console", foreground=theme.fg_dim)
        buf.create_tag("result", foreground=theme.syntax_string)
        buf.create_tag("error", foreground=theme.term_red)
        buf.create_tag("prompt", foreground=theme.accent_color)

        # Input entry
        input_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        input_box.set_margin_top(2)
        input_box.set_margin_start(4)
        input_box.set_margin_end(4)
        input_box.set_margin_bottom(4)
        self.append(input_box)

        prompt_label = Gtk.Label(label=">")
        prompt_label.add_css_class("debug-console-prompt")
        input_box.append(prompt_label)

        self._input = Gtk.Entry()
        self._input.set_hexpand(True)
        self._input.set_placeholder_text("Evaluate expression...")
        self._input.add_css_class("debug-console-input")
        input_box.append(self._input)

        # Key handler for input
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self._input.add_controller(key_ctrl)

        # Enter to evaluate
        self._input.connect("activate", self._on_activate)

    def append_output(self, text: str, category: str = "stdout") -> None:
        """Append text to the output area with the given category tag."""
        buf = self._output.get_buffer()
        end_iter = buf.get_end_iter()

        tag_name = category if category in ("stdout", "stderr", "console", "result", "error", "prompt") else "stdout"
        buf.insert_with_tags_by_name(end_iter, text, tag_name)

        # Auto-scroll to bottom
        mark = buf.get_insert()
        buf.place_cursor(buf.get_end_iter())
        self._output.scroll_mark_onscreen(mark)

    def clear(self) -> None:
        """Clear all output."""
        buf = self._output.get_buffer()
        buf.set_text("")

    def focus_input(self) -> None:
        """Focus the input entry."""
        self._input.grab_focus()

    def _on_activate(self, entry) -> None:
        """Handle Enter key — evaluate expression."""
        text = entry.get_text().strip()
        if not text:
            return

        # Add to history
        if not self._history or self._history[-1] != text:
            self._history.append(text)
        self._history_index = -1

        # Show the expression in output
        self.append_output(f"> {text}\n", "prompt")

        # Evaluate via callback
        if self._on_evaluate:
            result = self._on_evaluate(text)
            if result is not None:
                self.append_output(f"{result}\n", "result")

        entry.set_text("")

    def _on_key_pressed(self, controller, keyval, keycode, state) -> bool:
        """Handle Up/Down for history navigation."""
        if keyval == Gdk.KEY_Up:
            if self._history:
                if self._history_index == -1:
                    self._history_index = len(self._history) - 1
                elif self._history_index > 0:
                    self._history_index -= 1
                self._input.set_text(self._history[self._history_index])
                self._input.set_position(-1)
            return True
        elif keyval == Gdk.KEY_Down:
            if self._history_index >= 0:
                self._history_index += 1
                if self._history_index >= len(self._history):
                    self._history_index = -1
                    self._input.set_text("")
                else:
                    self._input.set_text(self._history[self._history_index])
                    self._input.set_position(-1)
            return True
        return False
