"""
CustomTreePanel renderer mixin — drawing logic for the tree.
Uses GtkSnapshot API for hardware-accelerated rendering.
"""

from gi.repository import Graphene, Gsk, Pango

from shared.utils import hex_to_rgba, tuple_to_gdk_rgba
from treeview.tree_icons import ICON_COLORS, get_git_status_colors


class TreePanelRendererMixin:
    """Mixin providing drawing/rendering methods for CustomTreePanel."""

    def _get_icon_for_item(self, item):
        """Get icon character and color for an item."""
        if item.is_dir:
            icon = self._icon_map.get("folder_open" if item.expanded else "folder_closed", "📁")
            color = ICON_COLORS.get("folder", "#dcb67a")
            return icon, color

        # Check special names
        name_key = f"name_{item.name}"
        if name_key in self._icon_map:
            icon = self._icon_map[name_key]
            color = ICON_COLORS.get(item.name, ICON_COLORS["default"])
            return icon, color

        # Check extension
        ext = item.path.suffix.lower()
        ext_key = f"ext_{ext}"
        if ext_key in self._icon_map:
            icon = self._icon_map[ext_key]
            color = ICON_COLORS.get(ext, ICON_COLORS["default"])
            return icon, color

        return self._icon_map.get("default", "📄"), ICON_COLORS["default"]

    def _on_snapshot(self, snapshot, width, height):
        """Draw the tree using GtkSnapshot."""
        # Clear background
        rect = Graphene.Rect()
        rect.init(0, 0, width, height)
        snapshot.append_color(tuple_to_gdk_rgba(self.bg_color), rect)

        if not self.items:
            return

        # Get scroll position
        vadj = self.get_vadjustment()
        scroll_y = vadj.get_value() if vadj else 0

        # Calculate visible range
        first_visible = int(scroll_y / self.row_height)
        last_visible = int((scroll_y + height) / self.row_height) + 1

        # Create Pango layout once, reuse for all items
        pango_ctx = self.drawing_area.get_pango_context()
        layout = Pango.Layout.new(pango_ctx)

        # Cache text/icon metrics — constant across rows, only changes on font change
        if self._cached_text_height is None:
            layout.set_font_description(self.text_font_desc)
            layout.set_text("Ay", -1)
            text_ink, text_logical = layout.get_pixel_extents()
            self._cached_text_height = text_logical.height
            # Ink center relative to layout origin (where visible text pixels center)
            self._cached_text_ink_center = text_ink.y + text_ink.height / 2

            layout.set_font_description(self.icon_font_desc)
            layout.set_text("\uf07b", -1)  # measure with actual icon glyph
            icon_ink, icon_logical = layout.get_pixel_extents()
            self._cached_icon_height = icon_logical.height
            # Ink center relative to layout origin (where visible icon pixels center)
            self._cached_icon_ink_center = icon_ink.y + icon_ink.height / 2

        # Draw visible items
        for i in range(max(0, first_visible), min(len(self.items), last_visible)):
            self._draw_item(snapshot, layout, i, self.items[i], width)

        # Draw drop indicator
        if self._drop_target_item is not None and self._drop_position:
            self._draw_drop_indicator(snapshot, width)

    def _draw_item(self, snapshot, layout, index, item, width):
        """Draw a single tree item using GtkSnapshot."""
        y = index * self.row_height
        rect = Graphene.Rect()
        point = Graphene.Point()

        # Selection/hover background
        if self._is_item_selected(item):
            if self.drawing_area.has_focus() and not self._cursor_blinker.cursor_visible:
                if item != self.selected_item:
                    rect.init(0, y, width, self.row_height)
                    snapshot.append_color(tuple_to_gdk_rgba(self.selected_bg), rect)
            else:
                rect.init(0, y, width, self.row_height)
                snapshot.append_color(tuple_to_gdk_rgba(self.selected_bg), rect)
        elif item == self.hover_item:
            rect.init(0, y, width, self.row_height)
            snapshot.append_color(tuple_to_gdk_rgba(self.hover_bg), rect)

        x = self.LEFT_PADDING

        text_height = self._cached_text_height
        text_y = y + (self.row_height - text_height) / 2

        # Align icon so its ink (visible pixels) center matches the text ink center.
        # On Linux, Nerd Font icon glyphs sit at different positions within their
        # logical rect than text glyphs, so logical-rect centering causes misalignment.
        text_ink_center_y = text_y + self._cached_text_ink_center
        icon_y = text_ink_center_y - self._cached_icon_ink_center

        # Draw indent guides
        if item.depth > 0:
            x = self._draw_indent_guides(snapshot, item, x, y)

        # Set icon font for chevron and icon
        layout.set_font_description(self.icon_font_desc)

        # Draw chevron for directories
        if item.is_dir:
            chevron = self.chevron_expanded if item.expanded else self.chevron_collapsed
            color = tuple_to_gdk_rgba(self.ignored_color if item.git_status == "I" else self.chevron_color)
            layout.set_text(chevron, -1)
            snapshot.save()
            point.init(x, icon_y)
            snapshot.translate(point)
            snapshot.append_layout(layout, color)
            snapshot.restore()
        x += self.INDENT_WIDTH

        # Draw icon
        icon_char, icon_color = self._get_icon_for_item(item)
        color = tuple_to_gdk_rgba(self.ignored_color if item.git_status == "I" else hex_to_rgba(icon_color))
        layout.set_text(icon_char.strip(), -1)
        snapshot.save()
        point.init(x, icon_y)
        snapshot.translate(point)
        snapshot.append_layout(layout, color)
        snapshot.restore()
        x += self._icon_column_width

        # Determine text color
        if item.git_status == "M":
            text_color = self.modified_color
        elif item.git_status == "I":
            text_color = self.ignored_color
        elif item.git_status and item.git_status in get_git_status_colors():
            text_color = hex_to_rgba(get_git_status_colors()[item.git_status])
        elif self._is_modified_dir(item):
            text_color = self.modified_color
        else:
            text_color = self.fg_color

        # Draw name
        layout.set_font_description(self.text_font_desc)
        layout.set_text(item.name, -1)
        snapshot.save()
        point.init(x, text_y)
        snapshot.translate(point)
        snapshot.append_layout(layout, tuple_to_gdk_rgba(text_color))
        snapshot.restore()

        # Draw git status hint
        if item.git_status and not item.is_dir and item.git_status != "I":
            hint_text = f"[{item.git_status}]"
            layout.set_text(hint_text, -1)
            _, logical_rect = layout.get_pixel_extents()
            hint_width = logical_rect.width
            hint_x = width - hint_width - 8

            if item.git_status == "M":
                hint_color = self.modified_color
            else:
                hint_color = hex_to_rgba(get_git_status_colors().get(item.git_status, "#808080"))

            # Background pill (rounded rectangle)
            bg_color = (hint_color[0] * 0.25, hint_color[1] * 0.25, hint_color[2] * 0.25, 1.0)
            pill_rect = Graphene.Rect()
            pill_rect.init(hint_x - 4, text_y - 1, hint_width + 8, logical_rect.height + 2)
            rounded = Gsk.RoundedRect()
            rounded.init_from_rect(pill_rect, 3)
            snapshot.push_rounded_clip(rounded)
            snapshot.append_color(tuple_to_gdk_rgba(bg_color), pill_rect)
            snapshot.pop()

            # Hint text
            snapshot.save()
            point.init(hint_x, text_y)
            snapshot.translate(point)
            snapshot.append_layout(layout, tuple_to_gdk_rgba(hint_color))
            snapshot.restore()

    def _draw_indent_guides(self, snapshot, item, start_x, y):
        """Draw minimal indent guides using GtkSnapshot."""
        # Build guide info by walking up the parent chain
        show_line = []
        current = item.parent
        depth = item.depth - 1

        while current and depth >= 0:
            show_line.append(not current.is_last)
            current = current.parent
            depth -= 1

        show_line.reverse()

        x = start_x
        row_top = y
        row_bottom = y + self.row_height
        row_mid = y + self.row_height // 2

        # Batch all indent guide lines into a single path
        builder = Gsk.PathBuilder.new()

        # Draw vertical lines for each ancestor level
        for draw_line in show_line:
            line_x = x + self.INDENT_WIDTH // 2
            if draw_line:
                builder.move_to(line_x + 0.5, row_top)
                builder.line_to(line_x + 0.5, row_bottom)
            x += self.INDENT_WIDTH

        # Draw the final connector
        line_x = x + self.INDENT_WIDTH // 2

        if item.is_last:
            # Corner └
            builder.move_to(line_x + 0.5, row_top)
            builder.line_to(line_x + 0.5, row_mid)
            builder.move_to(line_x + 0.5, row_mid)
            builder.line_to(x + self.INDENT_WIDTH, row_mid)
        else:
            # Continuation │
            builder.move_to(line_x + 0.5, row_top)
            builder.line_to(line_x + 0.5, row_bottom)

        x += self.INDENT_WIDTH

        path = builder.to_path()
        stroke = Gsk.Stroke.new(1.0)
        snapshot.append_stroke(path, stroke, tuple_to_gdk_rgba(self.guide_color))

        return x

    def _draw_drop_indicator(self, snapshot, width):
        """Draw a visual indicator showing where the item will be dropped."""
        if not self._drop_target_item or not self._drop_position:
            return
        try:
            index = self.items.index(self._drop_target_item)
        except ValueError:
            return

        from themes import get_theme

        accent = hex_to_rgba(get_theme().accent_color)

        if self._drop_position == "into":
            # Highlight the folder row with a border
            y = index * self.row_height
            rect = Graphene.Rect()

            # Semi-transparent fill
            fill_color = (accent[0], accent[1], accent[2], 0.2)
            rect.init(0, y, width, self.row_height)
            snapshot.append_color(tuple_to_gdk_rgba(fill_color), rect)

            # Border
            border_rect = Graphene.Rect()
            border_rect.init(0.5, y + 0.5, width - 1, self.row_height - 1)
            rounded = Gsk.RoundedRect()
            rounded.init_from_rect(border_rect, 0)
            accent_rgba = tuple_to_gdk_rgba(accent)
            snapshot.append_border(
                rounded,
                [1, 1, 1, 1],
                [accent_rgba, accent_rgba, accent_rgba, accent_rgba],
            )
        else:
            # Draw a line between rows
            if self._drop_position == "before":
                line_y = index * self.row_height
            else:
                line_y = (index + 1) * self.row_height
            indent = self.LEFT_PADDING + self._drop_target_item.depth * self.INDENT_WIDTH
            accent_rgba = tuple_to_gdk_rgba(accent)

            # Horizontal line
            builder = Gsk.PathBuilder.new()
            builder.move_to(indent, line_y)
            builder.line_to(width, line_y)
            path = builder.to_path()
            stroke = Gsk.Stroke.new(2.0)
            snapshot.append_stroke(path, stroke, accent_rgba)

            # Small circle at the left end
            builder = Gsk.PathBuilder.new()
            builder.add_circle(Graphene.Point().init(indent, line_y), 3)
            path = builder.to_path()
            snapshot.append_fill(path, Gsk.FillRule.WINDING, accent_rgba)
