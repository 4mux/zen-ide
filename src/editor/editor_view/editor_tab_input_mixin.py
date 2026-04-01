"""Key/mouse event handling and shortcuts for EditorTab."""

from gi.repository import GLib, Gtk

from constants import BRACKET_SCOPE_LANGS
from shared.settings import get_setting

from .core import _iter_at_line


class EditorTabInputMixin:
    """Mixin providing key press, click, and context menu handling for EditorTab."""

    # Bracket pairs for auto-close
    BRACKET_PAIRS = {
        "(": ")",
        "[": "]",
        "{": "}",
        '"': '"',
        "'": "'",
        "`": "`",
    }
    CLOSE_BRACKETS = set(BRACKET_PAIRS.values())

    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Handle key press for auto-close brackets and word navigation."""
        import platform

        from gi.repository import Gdk

        # Inline completion (ghost text): handle before everything else
        ic = self._inline_completion
        if ic is not None and ic.is_active:
            if ic.handle_key(keyval, state):
                return True

        # Lazy-init inline completion on first keypress (any key — on non-US
        # keyboards like Italian Mac, characters like # may have keyval > 127)
        if self._inline_completion is None:
            self._ensure_inline_completion()

        # Autocomplete: delegate keys when popup is visible
        ac = self._ensure_autocomplete()
        if ac.is_visible():
            if ac.handle_key(keyval, state):
                return True

        # Tab to navigate autocomplete parameter tab stops
        if keyval == Gdk.KEY_Tab and ac.has_active_tab_stops():
            return ac.advance_tab_stop()

        # Escape clears active tab stops
        if keyval == Gdk.KEY_Escape and ac.has_active_tab_stops():
            ac.clear_tab_stops()
            return True

        # Ctrl+Space or Cmd+Space triggers autocomplete
        is_ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        is_cmd = bool(state & Gdk.ModifierType.META_MASK)
        is_shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        is_alt = bool(state & Gdk.ModifierType.ALT_MASK)
        if (
            keyval == Gdk.KEY_space
            and (is_ctrl or (platform.system() == "Darwin" and is_cmd))
            and not is_shift
            and not is_alt
        ):
            self._ensure_autocomplete().show(force=True)
            return True

        # Ctrl+Shift+[ — toggle fold at cursor
        if is_ctrl and is_shift and keyval == Gdk.KEY_bracketleft and not is_alt:
            fm = getattr(self, "_fold_manager", None)
            if fm and fm.toggle_fold_at_cursor():
                return True

        # Alt+\ triggers inline AI completion manually
        if is_alt and keyval == Gdk.KEY_backslash and not is_cmd and not is_ctrl:
            ic = self._ensure_inline_completion()
            if ic:
                ic.trigger_now()
            return True

        # Handle Cmd+Backspace to delete to start of line on macOS
        if platform.system() == "Darwin":
            is_cmd = bool(state & Gdk.ModifierType.META_MASK)
            if is_cmd and keyval == Gdk.KEY_BackSpace:
                self._delete_current_line()
                return True

        # Handle Option+Left/Right for word navigation on macOS
        # GTK default behavior swaps words; override to move by word instead
        if platform.system() == "Darwin":
            is_alt = bool(state & Gdk.ModifierType.ALT_MASK)
            is_shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
            # Exclude Cmd modifier - Cmd+Option combos should pass through
            is_cmd = bool(state & Gdk.ModifierType.META_MASK)

            # Cmd+Shift+Left: select to first non-whitespace (smart home)
            if is_cmd and is_shift and keyval == Gdk.KEY_Left:
                cursor = self.buffer.get_insert()
                it = self.buffer.get_iter_at_mark(cursor)
                line_start = it.copy()
                line_start.set_line_offset(0)
                # Find first non-whitespace character on the line
                first_nonws = line_start.copy()
                while not first_nonws.ends_line() and first_nonws.get_char() in (" ", "\t"):
                    first_nonws.forward_char()
                # If cursor is already at or before first non-ws, go to column 0
                target = first_nonws if it.compare(first_nonws) > 0 else line_start
                self.buffer.move_mark(cursor, target)
                self.view.scroll_mark_onscreen(cursor)
                return True

            # Cmd+Left: jump to first non-whitespace (smart home)
            if is_cmd and not is_shift and keyval == Gdk.KEY_Left:
                cursor = self.buffer.get_insert()
                it = self.buffer.get_iter_at_mark(cursor)
                line_start = it.copy()
                line_start.set_line_offset(0)
                first_nonws = line_start.copy()
                while not first_nonws.ends_line() and first_nonws.get_char() in (" ", "\t"):
                    first_nonws.forward_char()
                target = first_nonws if it.compare(first_nonws) > 0 else line_start
                self.buffer.place_cursor(target)
                self.view.scroll_mark_onscreen(self.buffer.get_insert())
                return True

            if is_alt and not is_cmd:
                from shared.utils import handle_word_nav_keypress

                if handle_word_nav_keypress(self.buffer, keyval, state):
                    return True

        # Smart indentation on Enter for Python
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not is_ctrl and not is_alt:
            if self._handle_smart_indent():
                return True

        char = chr(keyval) if 32 <= keyval < 127 else None
        if not char:
            return False

        cursor = self.buffer.get_insert()
        it = self.buffer.get_iter_at_mark(cursor)

        # Auto-close bracket/quote
        if get_setting("editor.auto_close_brackets", True) and char in self.BRACKET_PAIRS:
            close_char = self.BRACKET_PAIRS[char]
            # For quotes, don't auto-close if we're inside a word
            if char in ('"', "'", "`"):
                before = it.copy()
                if before.backward_char():
                    prev_char = before.get_char()
                    if prev_char.isalnum():
                        return False
            # Check if next char is already the close char (skip over it)
            next_char = it.get_char() if not it.is_end() else ""
            if char == close_char and next_char == close_char:
                # Skip over existing close char
                end = it.copy()
                end.forward_char()
                self.buffer.place_cursor(end)
                return True

            # Insert pair
            self.buffer.begin_user_action()
            self.buffer.insert_at_cursor(char + close_char)
            # Move cursor between the pair
            cursor_iter = self.buffer.get_iter_at_mark(self.buffer.get_insert())
            cursor_iter.backward_char()
            self.buffer.place_cursor(cursor_iter)
            self.buffer.end_user_action()
            return True

        # Skip over close bracket if typed
        if get_setting("editor.auto_close_brackets", True) and char in self.CLOSE_BRACKETS:
            next_char = it.get_char() if not it.is_end() else ""
            if next_char == char:
                end = it.copy()
                end.forward_char()
                self.buffer.place_cursor(end)
                return True

        return False

    # ------------------------------------------------------------------
    # Smart indentation helpers
    # ------------------------------------------------------------------

    _DEDENT_KEYWORDS = frozenset(("return", "break", "continue", "pass", "raise"))

    def _handle_smart_indent(self):
        """Add extra indent after openers or dedent after closers/keywords.

        Handles Python (``:``, openers, dedent keywords) and brace-based
        languages (``{`` / ``}``).

        Returns True if the event was consumed, False to let GtkSourceView
        handle it with its default auto-indent behaviour.
        """
        lang = self.buffer.get_language()
        if not lang:
            return False
        lang_id = lang.get_id()

        is_python = lang_id in ("python", "python3")
        is_brace_lang = lang_id in BRACKET_SCOPE_LANGS
        if not is_python and not is_brace_lang:
            return False

        cursor = self.buffer.get_insert()
        it = self.buffer.get_iter_at_mark(cursor)

        # Text from start-of-line to cursor
        line_start = it.copy()
        line_start.set_line_offset(0)
        line_text = self.buffer.get_text(line_start, it, False)

        # Current indentation
        stripped = line_text.lstrip()
        indent_len = len(line_text) - len(stripped)
        indent_str = line_text[:indent_len]
        indent_width = self.view.get_indent_width()
        if indent_width <= 0:
            indent_width = self.view.get_tab_width()
        one_level = " " * indent_width

        new_indent = None

        if is_python:
            code = self._strip_python_comment(stripped)
            if code.endswith(":") or code.endswith(("(", "[", "{")):
                new_indent = indent_str + one_level
            else:
                first_word = code.split()[0] if code else ""
                if first_word in self._DEDENT_KEYWORDS:
                    if indent_len >= indent_width:
                        new_indent = indent_str[:-indent_width]
                    else:
                        new_indent = ""
        else:
            code = self._strip_line_comment(stripped)
            if code.endswith(("{", "(", "[")):
                new_indent = indent_str + one_level
            elif code in ("}", "},", "});", ");", "]", "],", "]);"):
                if indent_len >= indent_width:
                    new_indent = indent_str[:-indent_width]
                else:
                    new_indent = ""

        if new_indent is None:
            return False

        self.buffer.begin_user_action()
        self.buffer.delete_selection(True, True)
        self.buffer.insert_at_cursor("\n" + new_indent)
        self.buffer.end_user_action()
        self.view.scroll_mark_onscreen(self.buffer.get_insert())
        return True

    @staticmethod
    def _strip_python_comment(code):
        """Return *code* with any trailing ``# …`` comment removed."""
        in_string = None
        for i, ch in enumerate(code):
            if in_string:
                if ch == in_string:
                    in_string = None
            elif ch in ("'", '"'):
                in_string = ch
            elif ch == "#":
                return code[:i].rstrip()
        return code.rstrip()

    @staticmethod
    def _strip_line_comment(code):
        """Return *code* with any trailing ``// …`` comment removed."""
        in_string = None
        prev = ""
        for i, ch in enumerate(code):
            if in_string:
                if ch == in_string and prev != "\\":
                    in_string = None
            elif ch in ("'", '"', "`"):
                in_string = ch
            elif ch == "/" and prev == "/" and not in_string:
                return code[: i - 1].rstrip()
            prev = ch
        return code.rstrip()

    def _delete_current_line(self):
        """Delete text from cursor to start of line (Cmd+Backspace)."""
        cursor = self.buffer.get_insert()
        cursor_iter = self.buffer.get_iter_at_mark(cursor)
        line = cursor_iter.get_line()
        line_start = _iter_at_line(self.buffer, line)

        if cursor_iter.equal(line_start):
            if line == 0:
                return
            prev_end = cursor_iter.copy()
            prev_end.backward_char()
            self.buffer.begin_user_action()
            self.buffer.delete(prev_end, cursor_iter)
            self.buffer.end_user_action()
        else:
            self.buffer.begin_user_action()
            self.buffer.delete(line_start, cursor_iter)
            self.buffer.end_user_action()

    def _on_right_click(self, gesture, n_press, x, y):
        """Show nvim-style context menu on right-click."""
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        from popups.nvim_context_menu import show_context_menu

        has_selection = self.buffer.get_has_selection()
        clipboard = self.view.get_clipboard()
        can_paste = clipboard is not None

        from icons import IconsManager

        items = [
            {"label": "Cut", "action": "cut", "icon": IconsManager.CUT, "enabled": has_selection},
            {"label": "Copy", "action": "copy", "icon": IconsManager.COPY, "enabled": has_selection},
            {"label": "Paste", "action": "paste", "icon": IconsManager.PASTE, "enabled": can_paste},
            {"label": "---"},
            {"label": "Select All", "action": "select_all", "icon": IconsManager.SELECT_ALL},
        ]

        def on_select(action):
            if action == "cut":
                self.view.emit("cut-clipboard")
            elif action == "copy":
                self.view.emit("copy-clipboard")
            elif action == "paste":
                self.view.emit("paste-clipboard")
            elif action == "select_all":
                self.buffer.select_range(self.buffer.get_start_iter(), self.buffer.get_end_iter())

        parent = self.view.get_root()
        show_context_menu(parent, items, on_select, x, y, source_widget=self.view)

    def _on_click_pressed(self, gesture, n_press, x, y):
        """Handle click events - Cmd+Click for navigation, double-click selects word, etc."""
        import platform

        from gi.repository import Gdk

        # Dismiss diagnostics popover on any click
        if hasattr(self, "_diag_popover") and self._diag_popover:
            self._diag_popover.popdown()

        # Dismiss inline completion ghost text on any click
        ic = self._inline_completion
        if ic is not None and ic.is_active:
            ic.dismiss()

        # Get modifier state early — Cmd+Click navigation has highest priority
        state = gesture.get_current_event_state()
        if platform.system() == "Darwin":
            is_cmd_click = bool(state & Gdk.ModifierType.META_MASK)
        else:
            is_cmd_click = bool(state & Gdk.ModifierType.CONTROL_MASK)

        if n_press == 1 and is_cmd_click:
            bx, by = self.view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
            over_text, it = self.view.get_iter_at_location(bx, by)
            if over_text and self._cmd_click_callback:
                gesture.set_state(Gtk.EventSequenceState.CLAIMED)
                self._cmd_click_callback(self.buffer, self.view, self.file_path, it)
                return True

        # Breakpoint toggling is handled by BreakpointGutterRenderer

        # Single click on diagnostic underline: show popover
        if n_press == 1 and hasattr(self, "_diag_error_tag"):
            bx, by = self.view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
            over, it = self.view.get_iter_at_location(bx, by)
            if over and (it.has_tag(self._diag_error_tag) or it.has_tag(self._diag_warning_tag)):
                line_1 = it.get_line() + 1
                if it.get_line() in self.view._fold_unsafe_lines:
                    return False
                self.buffer.place_cursor(it)
                self.view.grab_focus()
                loc = self.view.get_iter_location(it)
                _, wy = self.view.buffer_to_window_coords(Gtk.TextWindowType.WIDGET, loc.x, loc.y)
                gesture.set_state(Gtk.EventSequenceState.CLAIMED)
                self._show_line_diagnostics_popover(line_1, int(x), int(wy), loc.height)
                return True

        # Single click on color swatch: open color picker
        if n_press == 1 and self._color_preview:
            hit = self._color_preview.hit_test(x, y)
            if hit:
                gesture.set_state(Gtk.EventSequenceState.CLAIMED)
                self._open_color_picker(*hit)
                return True

        # Triple-click: select entire line
        if n_press == 3:
            bx, by = self.view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
            _over, it = self.view.get_iter_at_location(bx, by)
            start = it.copy()
            start.set_line_offset(0)
            end = it.copy()
            if not end.ends_line():
                end.forward_to_line_end()
            if not end.is_end():
                end.forward_char()
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.buffer.select_range(start, end)
            return

        # Double-click: expand selection to include underscores
        if n_press == 2:
            bx, by = self.view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
            _over_text, it = self.view.get_iter_at_location(bx, by)
            ch = it.get_char()
            if ch and (ch.isalnum() or ch == "_"):
                offset = it.get_offset()
                GLib.idle_add(self._select_word_at_offset, offset)
            return

    def _select_word_at_offset(self, offset):
        """Expand selection to include underscores (deferred from double-click)."""
        it = self.buffer.get_iter_at_offset(offset)
        ch = it.get_char()
        if not ch or not (ch.isalnum() or ch == "_"):
            return False
        start = it.copy()
        end = it.copy()
        while True:
            if start.is_start():
                break
            start.backward_char()
            if not (start.get_char().isalnum() or start.get_char() == "_"):
                start.forward_char()
                break
        while not end.is_end():
            if not (end.get_char().isalnum() or end.get_char() == "_"):
                break
            end.forward_char()
        if not start.equal(end):
            self.buffer.select_range(start, end)
        return False

    def set_cmd_click_callback(self, callback):
        """Set the callback for Cmd+Click navigation."""
        self._cmd_click_callback = callback

    def _open_color_picker(self, line, col, hex_str):
        """Open a color picker popup for the swatch at (line, col) with current hex_str."""
        from ..color_preview_renderer import ColorPreviewRenderer

        r, g, b, a = ColorPreviewRenderer._parse_color(hex_str)
        if r is None:
            return

        from popups.color_picker_popup import ColorPickerPopup

        with_alpha = len(hex_str.lstrip("#")) == 8
        window = self.view.get_root()

        def on_apply(new_hex, ln=line, c=col, old=hex_str):
            self._apply_color(new_hex, ln, c, old)

        popup = ColorPickerPopup(window, hex_str, with_alpha, on_apply)
        popup.present()

    def _apply_color(self, new_hex, line, col, old_hex):
        """Apply selected color back into the buffer."""
        from ..color_preview_renderer import ColorPreviewRenderer

        buf = self.buffer
        start = ColorPreviewRenderer._iter_at_line_offset(buf, line, col)
        end = ColorPreviewRenderer._iter_at_line_offset(buf, line, col + len(old_hex))
        if start is None or end is None:
            return

        buf.begin_user_action()
        buf.delete(start, end)
        insert_iter = ColorPreviewRenderer._iter_at_line_offset(buf, line, col)
        if insert_iter:
            buf.insert(insert_iter, new_hex)
        buf.end_user_action()
