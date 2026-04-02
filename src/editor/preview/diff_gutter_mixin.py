"""
Revert gutter renderer, minimap, and revert button handling for Zen IDE's diff view.
"""

from gi.repository import Gdk, GLib, Graphene, Gtk, GtkSource

from constants import DIFF_MINIMAP_WIDTH
from icons import ICON_FONT_FAMILY, IconsManager
from popups.confirm_dialog import show_confirm
from themes import get_theme


class RevertGutterRenderer(GtkSource.GutterRendererText):
    """Custom gutter renderer that shows clickable revert arrows at diff region starts."""

    __gtype_name__ = "RevertGutterRenderer"

    def __init__(self, diff_view):
        super().__init__()
        self._diff_view = diff_view
        self._revert_lines = {}  # line_num -> region_idx (0-based)
        self.set_alignment_mode(GtkSource.GutterRendererAlignmentMode.CELL)
        self.set_xpad(6)
        # Use markup to add color to the revert icon
        self.set_markup("", -1)

        # Make renderer focusable/clickable
        self.set_focusable(True)
        self.set_can_focus(True)

        # Connect signals - more reliable than overriding do_ methods in PyGObject
        self.connect("query-activatable", self._on_query_activatable)
        self.connect("activate", self._on_activate)

    def set_revert_lines(self, revert_lines: dict):
        """Set which lines have revert buttons."""
        self._revert_lines = revert_lines
        self.queue_draw()

    def _on_query_activatable(self, renderer, iter, area):
        """Signal handler: check if a line is clickable."""
        line = iter.get_line()
        result = line in self._revert_lines
        return result

    def _on_activate(self, renderer, iter, area, button, state, n_presses):
        """Signal handler: handle click on gutter."""
        line = iter.get_line()
        if line in self._revert_lines:
            region_idx = self._revert_lines[line]
            self._diff_view._on_gutter_revert_clicked(region_idx)

    def do_query_data(self, lines, line):
        """Query what to render for a given line."""
        # line is 0-based in GtkSource 5
        if line in self._revert_lines:
            # Use markup to color the revert icon orange for visibility
            self.set_markup(
                f'<span font_family="{ICON_FONT_FAMILY}" foreground="{get_theme().warning_color}" weight="bold">{IconsManager.UNDO_ARROW}</span>',
                -1,
            )
        else:
            # Use space to maintain consistent column width
            self.set_text(" ", -1)


class DiffMinimap(Gtk.Widget):
    """Vertical minimap strip showing diff region locations with click-to-jump."""

    def __init__(self, diff_view):
        super().__init__()
        self._diff_view = diff_view
        self._total_lines = 0
        self._diff_regions = []
        self._viewport_start = 0.0
        self._viewport_end = 0.0
        self._drag_pending = False
        self._drag_pending_y = 0.0

        self.set_size_request(DIFF_MINIMAP_WIDTH, -1)
        self.set_vexpand(True)
        self.set_hexpand(False)

        click = Gtk.GestureClick()
        click.set_button(1)
        click.connect("pressed", self._on_click)
        self.add_controller(click)

        drag = Gtk.GestureDrag()
        drag.set_button(1)
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        self.add_controller(drag)

    def update(self, total_lines, diff_regions):
        """Update minimap data and redraw."""
        self._total_lines = total_lines
        self._diff_regions = diff_regions
        self.queue_draw()

    def update_viewport(self, start_frac, end_frac):
        """Update the viewport indicator position."""
        self._viewport_start = max(0.0, min(1.0, start_frac))
        self._viewport_end = max(0.0, min(1.0, end_frac))
        self.queue_draw()

    def do_snapshot(self, snapshot):
        width = self.get_width()
        height = self.get_height()

        # Background
        from shared.utils import hex_to_rgb_float

        theme = get_theme()
        r, g, b = hex_to_rgb_float(theme.panel_bg)
        rect = Graphene.Rect()
        bg_color = Gdk.RGBA()
        bg_color.red, bg_color.green, bg_color.blue, bg_color.alpha = r, g, b, 1.0
        rect.init(0, 0, width, height)
        snapshot.append_color(bg_color, rect)

        if self._total_lines == 0 or height == 0:
            return

        # Draw diff region markers
        marker_color = Gdk.RGBA()
        for region in self._diff_regions:
            rtype = region["type"]
            start = region["right_start"]
            end = region["right_end"]

            if rtype == "del":
                end = start + 1

            y_start = (start / self._total_lines) * height
            y_end = (end / self._total_lines) * height
            y_h = max(y_end - y_start, 2)

            if rtype == "add":
                ar, ag, ab = hex_to_rgb_float(theme.git_added)
                marker_color.red, marker_color.green, marker_color.blue, marker_color.alpha = ar, ag, ab, 0.8
            elif rtype == "del":
                dr, dg, db = hex_to_rgb_float(theme.git_deleted)
                marker_color.red, marker_color.green, marker_color.blue, marker_color.alpha = dr, dg, db, 0.8
            elif rtype == "change":
                mr, mg, mb = hex_to_rgb_float(theme.git_modified)
                marker_color.red, marker_color.green, marker_color.blue, marker_color.alpha = mr, mg, mb, 0.8
            elif rtype == "whitespace":
                mr, mg, mb = hex_to_rgb_float(theme.git_modified)
                marker_color.red, marker_color.green, marker_color.blue, marker_color.alpha = mr, mg, mb, 0.6
            else:
                continue

            rect.init(2, y_start, width - 4, y_h)
            snapshot.append_color(marker_color, rect)

        # Viewport indicator
        if self._viewport_end > self._viewport_start:
            vy_start = self._viewport_start * height
            vy_end = self._viewport_end * height
            fr, fg_, fb = hex_to_rgb_float(theme.fg_color)

            vp_color = Gdk.RGBA()
            vp_color.red, vp_color.green, vp_color.blue, vp_color.alpha = fr, fg_, fb, 0.12
            rect.init(0, vy_start, width, vy_end - vy_start)
            snapshot.append_color(vp_color, rect)

            # Border lines as thin rectangles
            border_color = Gdk.RGBA()
            border_color.red, border_color.green, border_color.blue, border_color.alpha = fr, fg_, fb, 0.3
            rect.init(0, vy_start, width, 1)
            snapshot.append_color(border_color, rect)
            rect.init(0, vy_end - 1, width, 1)
            snapshot.append_color(border_color, rect)

    def _on_click(self, gesture, n_press, x, y):
        """Jump to the clicked position in the diff."""
        self._jump_to_y(y)

    def _on_drag_begin(self, gesture, start_x, start_y):
        """Start dragging — jump to initial position."""
        self._drag_start_y = start_y
        self._jump_to_y(start_y)

    def _on_drag_update(self, gesture, offset_x, offset_y):
        """Continue dragging — throttle to avoid lag."""
        self._drag_pending_y = self._drag_start_y + offset_y
        if not self._drag_pending:
            self._drag_pending = True
            GLib.idle_add(self._flush_drag)

    def _flush_drag(self):
        """Process pending drag position on next idle frame."""
        self._drag_pending = False
        self._jump_to_y(self._drag_pending_y)
        return GLib.SOURCE_REMOVE

    def _jump_to_y(self, y):
        """Scroll the diff view to the line corresponding to y position."""
        if self._total_lines == 0:
            return
        height = self.get_allocated_height()
        if height == 0:
            return
        frac = max(0.0, min(1.0, y / height))
        target_line = int(frac * self._total_lines)
        self._diff_view._scroll_to_line(target_line)


class DiffGutterMixin:
    """Mixin providing revert gutter and minimap methods for DiffView."""

    def _create_revert_buttons(self):
        """Set up revert markers in gutter renderers for each diff region."""
        if not self._diff_regions:
            if self._left_revert_renderer:
                self._left_revert_renderer.set_revert_lines({})
            if self._right_revert_renderer:
                self._right_revert_renderer.set_revert_lines({})
            return False

        # Build maps of line -> region_idx for each side
        left_revert_lines = {}  # For deletions: show in left gutter
        right_revert_lines = {}  # For additions/changes: show in right gutter

        for idx, region in enumerate(self._diff_regions):
            region_type = region["type"]
            if region_type == "del":
                # Deletions: revert marker in left pane
                left_revert_lines[region["left_start"]] = idx
            else:
                # Additions, changes, whitespace: revert marker in right pane
                right_revert_lines[region["right_start"]] = idx

        # Update gutter renderers
        if self._left_revert_renderer:
            self._left_revert_renderer.set_revert_lines(left_revert_lines)
        if self._right_revert_renderer:
            self._right_revert_renderer.set_revert_lines(right_revert_lines)

        return False

    def _on_left_gutter_click(self, gesture, n_press, x, y):
        """Handle click on left gutter - revert deletions."""
        if n_press != 1:
            return
        self._handle_gutter_click(self.left_view, self._left_revert_renderer, y)

    def _on_right_gutter_click(self, gesture, n_press, x, y):
        """Handle click on right gutter - revert additions/changes."""
        if n_press != 1:
            return
        self._handle_gutter_click(self.right_view, self._right_revert_renderer, y)

    def _handle_gutter_click(self, view, renderer, y):
        """Convert click position to line and trigger revert if applicable."""
        if not renderer or not renderer._revert_lines:
            return

        # Get buffer coordinates from window coordinates
        # The y coordinate is relative to the gutter widget
        buffer_x, buffer_y = view.window_to_buffer_coords(Gtk.TextWindowType.LEFT, 0, int(y))

        # Get the text iter at this position
        result = view.get_iter_at_location(buffer_x, buffer_y)
        try:
            # GTK4 returns (bool, iter)
            success, iter_at = result
            if not success:
                return
        except (TypeError, ValueError):
            iter_at = result

        line = iter_at.get_line()

        # Check if this line has a revert button
        if line in renderer._revert_lines:
            region_idx = renderer._revert_lines[line]
            self._on_gutter_revert_clicked(region_idx)

    def _on_gutter_revert_clicked(self, region_idx):
        """Handle click on revert gutter icon."""
        if region_idx >= len(self._diff_regions):
            return

        region = self._diff_regions[region_idx]
        self._show_revert_confirmation(region, region_idx)

    def _show_revert_confirmation(self, region, region_idx):
        """Show confirmation dialog before reverting."""
        region_type = region["type"]
        right_start = region["right_start"] + 1
        right_end = region["right_end"]

        if region_type == "add":
            desc = f"Remove added lines {right_start}-{right_end}"
        elif region_type == "del":
            desc = f"Restore deleted lines at line {right_start}"
        elif region_type == "whitespace":
            desc = f"Revert whitespace changes at lines {right_start}-{right_end}"
        else:
            desc = f"Revert changes at lines {right_start}-{right_end}"

        show_confirm(
            parent=self.get_root(),
            title="Revert Change?",
            message=f"{desc}\n\nThis will discard your local changes for this section.",
            confirm_text="Revert",
            cancel_text="Cancel",
            danger=True,
            on_confirm=lambda: self._revert_region(region),
        )

    def _revert_region(self, region):
        """Revert a single diff region to the commit version."""
        if not self._current_file_path:
            return

        left_start = region["left_start"]
        left_end = region["left_end"]
        right_start = region["right_start"]
        right_end = region["right_end"]

        # Build new content by replacing the changed region
        new_lines = list(self._new_lines)
        old_region_lines = self._old_lines[left_start:left_end]

        # Replace the right-side lines with the left-side (commit) lines
        new_lines[right_start:right_end] = old_region_lines

        # Write back to file
        new_content = "".join(new_lines)
        try:
            with open(self._current_file_path, "w", encoding="utf-8") as f:
                f.write(new_content)
        except Exception:
            return

        # Update current content and refresh diff
        self._current_content = new_content

        # Notify callback if set (to refresh editor)
        if self._on_revert_callback:
            self._on_revert_callback(self._current_file_path)

        # Freeze scroll position during re-render so it never visually jumps
        self._freeze_scroll_for(lambda: self._apply_diff(self._commit_content, self._current_content))

    def _update_minimap(self):
        """Update minimap with current diff regions."""
        if not self._minimap:
            return
        total_lines = max(self.right_buffer.get_line_count(), 1)
        self._minimap.update(total_lines, self._diff_regions)
        # Schedule viewport update after layout settles
        GLib.idle_add(self._update_minimap_viewport)
        return False

    def _update_minimap_viewport(self):
        """Update the minimap viewport indicator from right scroll position."""
        if not self._minimap or self._minimap._total_lines == 0:
            return
        adj = self._right_scroll.get_vadjustment()
        upper = adj.get_upper()
        if upper <= 0:
            return
        start_frac = adj.get_value() / upper
        end_frac = (adj.get_value() + adj.get_page_size()) / upper
        self._minimap.update_viewport(start_frac, end_frac)
        return False

    def _freeze_scroll_for(self, action):
        """Run action while keeping both scroll positions pinned and views hidden.

        Hides the views via opacity during the buffer rebuild so GTK never
        paints an intermediate frame (empty buffer / missing diff marks).
        """
        right_adj = self._right_scroll.get_vadjustment()
        left_adj = self._left_scroll.get_vadjustment()
        saved_right = right_adj.get_value()
        saved_left = left_adj.get_value()

        self._scroll_frozen_value = (saved_left, saved_right)

        # Hide both panes so no intermediate state is painted
        self._left_scroll.set_opacity(0)
        self._right_scroll.set_opacity(0)

        action()

        # Clamp to new upper bounds (buffer may have fewer lines after revert)
        right_max = max(0, right_adj.get_upper() - right_adj.get_page_size())
        left_max = max(0, left_adj.get_upper() - left_adj.get_page_size())
        right_adj.set_value(min(saved_right, right_max))
        left_adj.set_value(min(saved_left, left_max))

        def _thaw():
            right_max = max(0, right_adj.get_upper() - right_adj.get_page_size())
            left_max = max(0, left_adj.get_upper() - left_adj.get_page_size())
            right_adj.set_value(min(saved_right, right_max))
            left_adj.set_value(min(saved_left, left_max))
            self._scroll_frozen_value = None
            # Reveal once layout and diff marks are fully settled
            self._left_scroll.set_opacity(1)
            self._right_scroll.set_opacity(1)
            return False

        GLib.idle_add(_thaw)

    def _on_right_scroll(self, adj):
        """Sync left scroll to match right scroll."""
        if self._syncing_scroll or self._scroll_frozen_value is not None:
            return
        self._syncing_scroll = True
        left_adj = self._left_scroll.get_vadjustment()
        left_adj.set_value(adj.get_value())
        self._syncing_scroll = False
        if not self._viewport_update_pending:
            self._viewport_update_pending = True
            GLib.idle_add(self._flush_viewport_update)

    def _on_left_scroll(self, adj):
        """Sync right scroll to match left scroll."""
        if self._syncing_scroll or self._scroll_frozen_value is not None:
            return
        self._syncing_scroll = True
        right_adj = self._right_scroll.get_vadjustment()
        right_adj.set_value(adj.get_value())
        self._syncing_scroll = False
        if not self._viewport_update_pending:
            self._viewport_update_pending = True
            GLib.idle_add(self._flush_viewport_update)

    def _flush_viewport_update(self):
        """Process pending viewport update on next idle frame."""
        self._viewport_update_pending = False
        self._update_minimap_viewport()
        return GLib.SOURCE_REMOVE

    def _scroll_to_line(self, line):
        """Scroll the right view to center on a specific line (instant, no animation)."""
        line = max(0, min(line, self.right_buffer.get_line_count() - 1))
        target_iter = self.right_buffer.get_iter_at_line(line)
        if isinstance(target_iter, tuple):
            target_iter = target_iter[1]
        y, line_height = self.right_view.get_line_yrange(target_iter)
        adj = self._right_scroll.get_vadjustment()
        page = adj.get_page_size()
        if page <= 0:
            return
        target = y - (page - line_height) / 2
        adj.set_value(max(0.0, min(target, adj.get_upper() - page)))
