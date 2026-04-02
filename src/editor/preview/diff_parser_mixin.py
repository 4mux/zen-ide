"""
Diff parsing and line alignment logic for Zen IDE's diff view.
Includes view configuration and theme change handling.
"""

import difflib

from gi.repository import Gdk, GLib, Gtk, GtkSource

from themes import get_theme

# Diff colors as (R, G, B, alpha) for blending with theme background
DIFF_ADD_RGBA = (46, 160, 67, 0.40)
DIFF_DEL_RGBA = (248, 81, 73, 0.40)
DIFF_CHANGE_RGBA = (210, 153, 34, 0.40)
DIFF_WHITESPACE_RGBA = (210, 153, 34, 0.25)


def _diff_gutter_colors():
    """Return gutter colors from the active theme."""
    from themes import get_theme

    theme = get_theme()
    return theme.git_added, theme.git_deleted, theme.git_modified


def _blend_diff_color(rgba_tuple, bg_hex: str) -> str:
    """Blend an RGBA diff color with the theme background to produce an opaque hex color.

    GtkSourceView's style scheme paints an opaque background, so text tag
    paragraph_background with alpha doesn't composite visibly. Pre-blend instead.
    """
    r, g, b, a = rgba_tuple
    # Parse hex bg like "#1e1e2e"
    bg_hex = bg_hex.lstrip("#")
    bg_r = int(bg_hex[0:2], 16)
    bg_g = int(bg_hex[2:4], 16)
    bg_b = int(bg_hex[4:6], 16)
    # Alpha blend: result = fg * alpha + bg * (1 - alpha)
    out_r = int(r * a + bg_r * (1 - a))
    out_g = int(g * a + bg_g * (1 - a))
    out_b = int(b * a + bg_b * (1 - a))
    return f"#{out_r:02x}{out_g:02x}{out_b:02x}"


class DiffParserMixin:
    """Mixin providing diff parsing and line tagging for DiffView."""

    def _apply_diff(self, old_text: str, new_text: str):
        """Apply diff with line-by-line highlighting."""
        old_lines = old_text.splitlines(keepends=True)
        new_lines = new_text.splitlines(keepends=True)

        # Use SequenceMatcher for line-level diff (compare raw lines to detect all changes)
        matcher = difflib.SequenceMatcher(None, old_lines, new_lines)

        # Clear old source marks and set full text
        for buf in (self.left_buffer, self.right_buffer):
            start = buf.get_start_iter()
            end = buf.get_end_iter()
            buf.remove_source_marks(start, end, None)
        self.left_buffer.set_text(old_text)
        self.right_buffer.set_text(new_text)

        self._diff_regions = []

        # Apply diff tags
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue  # No highlighting needed for equal lines
            elif tag == "replace":
                # Check if this is a whitespace-only change
                is_whitespace_only = True
                for offset in range(max(i2 - i1, j2 - j1)):
                    left_idx = i1 + offset if i1 + offset < i2 else None
                    right_idx = j1 + offset if j1 + offset < j2 else None
                    if left_idx is not None and right_idx is not None:
                        if old_lines[left_idx].rstrip() != new_lines[right_idx].rstrip():
                            is_whitespace_only = False
                            break
                    else:
                        is_whitespace_only = False
                        break

                if is_whitespace_only:
                    self._tag_lines(self.left_buffer, i1, i2, "whitespace")
                    self._tag_lines(self.right_buffer, j1, j2, "whitespace")
                    self._diff_regions.append(
                        {
                            "type": "whitespace",
                            "left_start": i1,
                            "left_end": i2,
                            "right_start": j1,
                            "right_end": j2,
                        }
                    )
                else:
                    self._tag_lines(self.left_buffer, i1, i2, "removed")
                    self._tag_lines(self.right_buffer, j1, j2, "added")
                    self._diff_regions.append(
                        {
                            "type": "change",
                            "left_start": i1,
                            "left_end": i2,
                            "right_start": j1,
                            "right_end": j2,
                        }
                    )
            elif tag == "delete":
                self._tag_lines(self.left_buffer, i1, i2, "removed")
                self._diff_regions.append(
                    {
                        "type": "del",
                        "left_start": i1,
                        "left_end": i2,
                        "right_start": j1,
                        "right_end": j2,
                    }
                )
            elif tag == "insert":
                self._tag_lines(self.right_buffer, j1, j2, "added")
                self._diff_regions.append(
                    {
                        "type": "add",
                        "left_start": i1,
                        "left_end": i2,
                        "right_start": j1,
                        "right_end": j2,
                    }
                )

        # Store lines for revert functionality
        self._old_lines = old_lines
        self._new_lines = new_lines

        # Create revert buttons after a short delay to ensure view is laid out
        GLib.idle_add(self._create_revert_buttons)

        # Update minimap with new diff regions
        self._update_minimap()

    def _tag_lines(self, buffer, start_line: int, end_line: int, tag_name: str):
        """Add GtkSource marks to a range of lines for diff background coloring."""
        if start_line >= end_line:
            return

        for line_num in range(start_line, end_line):
            result = buffer.get_iter_at_line(line_num)
            try:
                line_iter = result[1]
            except (TypeError, IndexError):
                line_iter = result
            buffer.create_source_mark(None, tag_name, line_iter)

    def _setup_diff_tags(self):
        """Register GtkSource mark categories for diff line backgrounds.

        Uses GtkSource.MarkAttributes with set_background() — the idiomatic way
        to paint full-line backgrounds in GtkSourceView, unaffected by the style
        scheme's text background.
        """
        theme = get_theme()
        bg = theme.main_bg

        add_bg = _blend_diff_color(DIFF_ADD_RGBA, bg)
        del_bg = _blend_diff_color(DIFF_DEL_RGBA, bg)
        change_bg = _blend_diff_color(DIFF_CHANGE_RGBA, bg)
        ws_bg = _blend_diff_color(DIFF_WHITESPACE_RGBA, bg)

        mark_defs = {
            "removed": del_bg,
            "changed": change_bg,
            "whitespace": ws_bg,
            "added": add_bg,
        }

        for category, hex_color in mark_defs.items():
            attrs = GtkSource.MarkAttributes()
            color = Gdk.RGBA()
            color.parse(hex_color)
            attrs.set_background(color)
            # Register on both views with high priority
            self.left_view.set_mark_attributes(category, attrs, 100)
            self.right_view.set_mark_attributes(category, attrs, 100)

    def update_font_settings(self):
        """Update font on both diff views to match current editor font settings."""
        from editor.source_view_config import configure_source_view_appearance

        for view in (self.left_view, self.right_view):
            if view is None:
                continue
            is_left = view is self.left_view
            attr = "_left_font_provider" if is_left else "_right_font_provider"
            old_provider = getattr(self, attr, None)
            if old_provider:
                view.get_style_context().remove_provider(old_provider)
            provider = configure_source_view_appearance(view)
            setattr(self, attr, provider)

    def _configure_view(self, view, scrolled=None):
        """Configure a source view for diff display."""
        from editor.source_view_config import configure_source_view_appearance

        view.set_show_line_numbers(True)
        view.set_show_line_marks(True)
        view.set_monospace(True)
        view.set_highlight_current_line(False)

        # Add key handler to each view
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        view.add_controller(key_controller)

        # Add click handler to focus editor when diff view is clicked
        click_controller = Gtk.GestureClick()
        click_controller.connect("pressed", self._on_view_clicked)
        view.add_controller(click_controller)

        # Apply shared visual settings (font, spacing, theme, scroll, etc.)
        configure_source_view_appearance(view, scrolled)

    def _on_theme_change(self, theme):
        """Update diff view styles when theme changes."""

        def _apply():
            self._apply_css()
            self._setup_diff_tags()
            # Re-apply style scheme to both views
            from editor.editor_view import _generate_style_scheme

            scheme_id = _generate_style_scheme(theme)
            scheme_manager = GtkSource.StyleSchemeManager.get_default()
            scheme = scheme_manager.get_scheme(scheme_id)
            if scheme:
                if self.left_view:
                    self.left_view.get_buffer().set_style_scheme(scheme)
                if self.right_view:
                    self.right_view.get_buffer().set_style_scheme(scheme)
            # Update indent guide color
            from constants import INDENT_GUIDE_ALPHA

            for v in (self.left_view, self.right_view):
                if v and hasattr(v, "set_guide_color_hex"):
                    v.set_guide_color_hex(theme.indent_guide, alpha=INDENT_GUIDE_ALPHA)
            return False

        GLib.idle_add(_apply)
