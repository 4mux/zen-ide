"""
Ghost text renderer for inline AI suggestions.

Renders AI-suggested code as a visual overlay using GtkSnapshot.
Ghost text is NOT inserted into the buffer — it's drawn on top of the
editor view during snapshot. This preserves the undo stack (GTK4's
set_enable_undo(False) clears undo history, so we avoid it entirely).

Accepting ghost text inserts it into the buffer as a normal undoable
user action (begin_user_action / end_user_action).
"""

from gi.repository import Gdk, Graphene, Gtk, GtkSource, Pango


class GhostTextRenderer:
    """Renders AI suggestions as a visual overlay — never modifies the buffer for display."""

    def __init__(self, view: GtkSource.View):
        self._view = view
        self._buffer: GtkSource.Buffer = view.get_buffer()
        self._ghost_text = ""
        self._cursor_offset = -1
        self._active = False
        # Guard flag to prevent re-entrant buffer-changed handling during accept
        self._inserting = False
        self._ghost_color = None
        # Tag to push existing code below multiline ghost text
        self._spacing_tag = self._buffer.create_tag("ghost_spacing", pixels_below_lines=0)
        # Register with view for snapshot rendering
        view._ghost_text_renderer = self

    @property
    def is_active(self) -> bool:
        """Whether ghost text is currently displayed."""
        return self._active and bool(self._ghost_text)

    @property
    def text(self) -> str:
        """The current ghost text string."""
        return self._ghost_text if self._active else ""

    def show(self, text: str):
        """Show ghost text at the current cursor position (visual only — no buffer changes)."""
        if not text:
            return

        self.clear()

        cursor_mark = self._buffer.get_insert()
        cursor_iter = self._buffer.get_iter_at_mark(cursor_mark)
        offset = cursor_iter.get_offset()

        # Strip prefix overlap so ghost text doesn't repeat what the user typed
        text = self._strip_prefix_overlap(text, offset)
        if not text:
            return

        self._ghost_text = text
        self._cursor_offset = offset
        self._active = True
        self._apply_spacing()
        self._view.queue_draw()

    def append(self, text: str):
        """Append more text to the current ghost text (for streaming display).

        If no ghost text is active, starts a new one at the current cursor.
        """
        if not text:
            return
        if not self._active:
            self.show(text)
        else:
            self._ghost_text += text
            self._apply_spacing()
            self._view.queue_draw()

    def clear(self):
        """Remove ghost text (visual only — no buffer changes)."""
        if not self._active:
            self._ghost_text = ""
            return
        self._remove_spacing()
        self._active = False
        self._ghost_text = ""
        self._cursor_offset = -1
        self._view.queue_draw()

    def accept(self) -> str:
        """Accept the full ghost text — inserts into buffer as a normal undoable action."""
        if not self._active or not self._ghost_text:
            return ""

        text = self._ghost_text
        offset = self._cursor_offset

        # Clear visual state first
        self._remove_spacing()
        self._active = False
        self._ghost_text = ""
        self._cursor_offset = -1

        # Safety: strip any remaining prefix overlap before inserting
        text = self._strip_prefix_overlap(text, offset)
        if not text:
            self._view.queue_draw()
            return ""

        # Insert into buffer as a normal undoable action
        self._inserting = True
        try:
            self._buffer.begin_user_action()
            insert_iter = self._buffer.get_iter_at_offset(offset)
            self._buffer.insert(insert_iter, text)
            end_iter = self._buffer.get_iter_at_offset(offset + len(text))
            self._buffer.place_cursor(end_iter)
            self._buffer.end_user_action()
        except Exception:
            pass
        finally:
            self._inserting = False

        self._view.queue_draw()
        return text

    def accept_word(self) -> str:
        """Accept the first word of ghost text as a normal undoable action."""
        if not self._active or not self._ghost_text:
            return ""

        # Find end of first word
        idx = 0
        n = len(self._ghost_text)
        while idx < n and self._ghost_text[idx] in (" ", "\t"):
            idx += 1
        while idx < n and self._ghost_text[idx] not in (" ", "\t", "\n"):
            idx += 1
        if idx == 0:
            idx = 1

        word = self._ghost_text[:idx]
        remaining = self._ghost_text[idx:]
        offset = self._cursor_offset

        # Remove spacing before modifying the buffer
        self._remove_spacing()

        # Insert word into buffer as a normal undoable action
        self._inserting = True
        try:
            self._buffer.begin_user_action()
            insert_iter = self._buffer.get_iter_at_offset(offset)
            self._buffer.insert(insert_iter, word)
            new_offset = offset + len(word)
            end_iter = self._buffer.get_iter_at_offset(new_offset)
            self._buffer.place_cursor(end_iter)
            self._buffer.end_user_action()
        except Exception:
            pass
        finally:
            self._inserting = False

        if remaining:
            self._ghost_text = remaining
            self._cursor_offset = offset + len(word)
            self._apply_spacing()
        else:
            self._active = False
            self._ghost_text = ""
            self._cursor_offset = -1

        self._view.queue_draw()
        return word

    def accept_line(self) -> str:
        """Accept the first line of ghost text as a normal undoable action."""
        if not self._active or not self._ghost_text:
            return ""

        newline_idx = self._ghost_text.find("\n")
        if newline_idx == -1:
            return self.accept()

        line = self._ghost_text[: newline_idx + 1]
        remaining = self._ghost_text[newline_idx + 1 :]
        offset = self._cursor_offset

        # Remove spacing before modifying the buffer
        self._remove_spacing()

        # Insert line into buffer as a normal undoable action
        self._inserting = True
        try:
            self._buffer.begin_user_action()
            insert_iter = self._buffer.get_iter_at_offset(offset)
            self._buffer.insert(insert_iter, line)
            new_offset = offset + len(line)
            end_iter = self._buffer.get_iter_at_offset(new_offset)
            self._buffer.place_cursor(end_iter)
            self._buffer.end_user_action()
        except Exception:
            pass
        finally:
            self._inserting = False

        if remaining:
            self._ghost_text = remaining
            self._cursor_offset = offset + len(line)
            self._apply_spacing()
        else:
            self._active = False
            self._ghost_text = ""
            self._cursor_offset = -1

        self._view.queue_draw()
        return line

    # -- Prefix overlap stripping --

    def _strip_prefix_overlap(self, text: str, offset: int) -> str:
        """Strip characters from text that overlap with already-typed text.

        When AI returns 'response = ...' but user already typed 'respo',
        strips the 'respo' prefix so ghost text becomes 'nse = ...'.
        Inserting 'nse = ...' after 'respo' produces the correct 'response = ...'.
        """
        if not text or offset < 0:
            return text
        cursor_iter = self._buffer.get_iter_at_offset(offset)
        line_start = cursor_iter.copy()
        line_start.set_line_offset(0)
        typed = self._buffer.get_text(line_start, cursor_iter, False)
        if not typed:
            return text
        max_check = min(len(typed), len(text))
        for length in range(max_check, 0, -1):
            if text.startswith(typed[-length:]):
                return text[length:]
        return text

    # -- Spacing helpers for multiline ghost text --

    def _apply_spacing(self):
        """Add vertical space below the cursor line for multiline ghost text.

        Uses a GtkTextTag with pixels-below-lines to push existing code down,
        preventing overlap with the ghost text overlay.
        """
        extra_lines = self._ghost_text.count("\n")
        if extra_lines < 1 or self._cursor_offset < 0:
            self._remove_spacing()
            return

        # Clamp offset to current buffer length (buffer may have changed)
        char_count = self._buffer.get_char_count()
        if self._cursor_offset > char_count:
            self._cursor_offset = char_count

        cursor_iter = self._buffer.get_iter_at_offset(self._cursor_offset)
        # Skip if cursor is on a fold-affected line (Pango crash risk)
        fold_unsafe = getattr(self._view, "_fold_unsafe_lines", set())
        if cursor_iter.get_line() in fold_unsafe:
            self._remove_spacing()
            return
        cursor_loc = self._view.get_iter_location(cursor_iter)
        line_height = cursor_loc.height

        self._spacing_tag.props.pixels_below_lines = extra_lines * line_height

        # Apply tag to entire cursor line
        line_start = cursor_iter.copy()
        line_start.set_line_offset(0)
        line_end = cursor_iter.copy()
        if not line_end.ends_line():
            line_end.forward_to_line_end()
        self._buffer.apply_tag(self._spacing_tag, line_start, line_end)

    def _remove_spacing(self):
        """Remove vertical spacing tag from the entire buffer."""
        self._spacing_tag.props.pixels_below_lines = 0
        start = self._buffer.get_start_iter()
        end = self._buffer.get_end_iter()
        self._buffer.remove_tag(self._spacing_tag, start, end)

    def draw(self, snapshot):
        """Render ghost text as a visual overlay using GtkSnapshot.

        Called from ZenSourceView.do_snapshot() after the normal text is rendered.
        """
        if not self._active or not self._ghost_text or self._cursor_offset < 0:
            return

        view = self._view
        buf = self._buffer

        # Validate stored offset against current buffer length to avoid
        # using a stale offset after buffer modifications.
        char_count = buf.get_char_count()
        if self._cursor_offset > char_count:
            self._cursor_offset = char_count

        cursor_iter = buf.get_iter_at_offset(self._cursor_offset)
        cursor_loc = view.get_iter_location(cursor_iter)
        cursor_x, cursor_y = view.buffer_to_window_coords(Gtk.TextWindowType.WIDGET, cursor_loc.x, cursor_loc.y)
        line_height = cursor_loc.height

        # Left margin x — start of the text at column 0
        line_start_iter = cursor_iter.copy()
        line_start_iter.set_line_offset(0)
        left_loc = view.get_iter_location(line_start_iter)
        left_x, _ = view.buffer_to_window_coords(Gtk.TextWindowType.WIDGET, left_loc.x, 0)

        ghost_color = self._get_ghost_color()
        context = view.get_pango_context()
        font_desc = context.get_font_description()

        lines = self._ghost_text.split("\n")
        for i, line_text in enumerate(lines):
            if not line_text and i > 0 and i < len(lines) - 1:
                continue

            layout = Pango.Layout.new(context)
            layout.set_text(line_text, -1)
            if font_desc:
                italic_desc = font_desc.copy()
                italic_desc.set_style(Pango.Style.ITALIC)
                layout.set_font_description(italic_desc)

            if i == 0:
                x, y = float(cursor_x), float(cursor_y)
            else:
                x, y = float(left_x), float(cursor_y + i * line_height)

            point = Graphene.Point()
            point.x = x
            point.y = y
            snapshot.save()
            snapshot.translate(point)
            snapshot.append_layout(layout, ghost_color)
            snapshot.restore()

    def _get_ghost_color(self) -> Gdk.RGBA:
        """Get the ghost text color from the current theme (cached)."""
        if self._ghost_color is None:
            from themes import get_theme

            theme = get_theme()
            self._ghost_color = Gdk.RGBA()
            self._ghost_color.parse(theme.fg_dim)
            self._ghost_color.alpha = 0.55
        return self._ghost_color

    def update_theme(self):
        """Invalidate cached color when the theme changes."""
        self._ghost_color = None
        if self._active:
            self._view.queue_draw()
