"""
CustomTreePanel — file explorer tree panel built on ZenTree.

Extends the shared ZenTree with file icons, git status, drag-and-drop,
inline editing, and filesystem data loading.
"""

import sys
from typing import Callable, Dict, List, Optional, Set

from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk, Pango

from icons import IconsManager
from shared.settings import get_setting
from shared.ui.zen_tree import ZenTree
from shared.utils import hex_to_rgba, tuple_to_gdk_rgba
from themes import get_theme
from treeview.tree_icons import (
    CHEVRON_COLOR,
    ICON_COLORS,
    get_git_status_colors,
    get_icon_set,
)
from treeview.tree_item import TreeItem
from treeview.tree_panel_data_mixin import TreePanelDataMixin
from treeview.tree_panel_drag_mixin import TreePanelDragMixin
from treeview.tree_panel_inline_edit_mixin import TreePanelInlineEditMixin

_PRIMARY_MOD = Gdk.ModifierType.META_MASK if sys.platform == "darwin" else Gdk.ModifierType.CONTROL_MASK


class CustomTreePanel(
    TreePanelDragMixin,
    TreePanelInlineEditMixin,
    TreePanelDataMixin,
    ZenTree,
):
    """Custom drawn file explorer tree control."""

    def __init__(self, tree_view):
        self.tree_view = tree_view
        super().__init__(font_context="explorer")

        # Git status tracking
        self._git_modified_files: Set[str] = set()
        self._git_status_map: Dict[str, str] = {}
        self._modified_dirs: Set[str] = set()

        # Additional colors (git, ignored)
        self._setup_extra_colors()

        # Icon setup
        self._setup_icons()

        # Inline editing state
        self._inline_entry: Optional[Gtk.Entry] = None
        self._inline_item: Optional[TreeItem] = None
        self._inline_on_confirm: Optional[Callable[[str], None]] = None
        self._inline_on_cancel: Optional[Callable[[], None]] = None

        # Drag-and-drop state
        self._drag_source_item: Optional[TreeItem] = None
        self._drop_target_item: Optional[TreeItem] = None
        self._drop_position: Optional[str] = None
        self._drag_start_y: float = 0.0
        self._drag_activated: bool = False
        self._drag_start_scroll_y: float = 0.0

        # Gitignore pattern cache
        self._pattern_cache: Dict[Optional[str], tuple] = {}

        # Additional event controllers (right-click, drag)
        self._setup_extra_controllers()

    # ── Setup ──────────────────────────────────────────────────

    def _setup_extra_colors(self):
        """Setup explorer-specific colors (git status, ignored)."""
        theme = get_theme()
        self.modified_color = hex_to_rgba(theme.tree_modified_fg)
        self.ignored_color = hex_to_rgba(theme.tree_ignored_fg or theme.fg_dim)

    def _setup_icons(self):
        """Setup icon mappings."""
        from icons import get_icon_font_name

        file_icons, name_icons, folder_closed, folder_open = get_icon_set()
        self._icon_map = {
            "folder_closed": folder_closed,
            "folder_open": folder_open,
            "default": IconsManager.FILE + " ",
        }
        self._icon_map.update({f"ext_{k}": v for k, v in file_icons.items()})
        self._icon_map.update({f"name_{k}": v for k, v in name_icons.items()})

    def _setup_extra_controllers(self):
        """Setup right-click and drag event controllers."""
        # Right-click context menu
        right_click = Gtk.GestureClick.new()
        right_click.connect("pressed", self._on_right_click)
        right_click.set_button(3)
        self.drawing_area.add_controller(right_click)

        # Internal drag gesture for file reordering
        drag_gesture = Gtk.GestureDrag()
        drag_gesture.connect("drag-begin", self._on_gesture_drag_begin)
        drag_gesture.connect("drag-update", self._on_gesture_drag_update)
        drag_gesture.connect("drag-end", self._on_gesture_drag_end)
        self.drawing_area.add_controller(drag_gesture)

        # External drop target for files from outside the IDE
        self._setup_external_drop_target()

    # ── Theme & Settings overrides ─────────────────────────────

    def _on_theme_change(self, theme):
        self._setup_extra_colors()
        super()._on_theme_change(theme)

    def _on_settings_change(self, key, value):
        if key in ("fonts", "explorer"):
            self._setup_icons()
        super()._on_settings_change(key, value)

    # ── Scroll override (drag cleanup) ─────────────────────────

    def _on_scroll_value_changed(self, adjustment):
        # Cancel any active drag — scroll invalidates drag coordinates
        if self._drag_source_item:
            self._cleanup_drag_state()
        super()._on_scroll_value_changed(adjustment)

    # ── Rendering ──────────────────────────────────────────────

    def _on_snapshot(self, snapshot, width, height):
        """Draw tree items plus drop indicator."""
        super()._on_snapshot(snapshot, width, height)
        # Drop indicator overlay
        if self._drop_target_item is not None and self._drop_position:
            self._draw_drop_indicator(snapshot, width)

    def _draw_item_row(self, snapshot, layout, item, y, width):
        """Draw file explorer item: indent guides, chevron, icon, name, git badge."""
        point = Graphene.Point()
        text_height = self._cached_text_height
        text_y = y + (self.row_height - text_height) / 2
        text_ink_center_y = text_y + self._cached_text_ink_center
        icon_y = text_ink_center_y - self._cached_icon_ink_center

        x = self.LEFT_PADDING

        # Indent guides
        if item.depth > 0:
            x = self._draw_indent_guides(snapshot, item, x, y)

        # Set icon font for chevron and icon
        layout.set_font_description(self.icon_font_desc)

        # Chevron for directories
        if item.is_dir:
            chevron = self.chevron_expanded if item.expanded else self.chevron_collapsed
            color = tuple_to_gdk_rgba(
                self.ignored_color if item.git_status == "I" else self.chevron_color
            )
            layout.set_text(chevron, -1)
            snapshot.save()
            point.init(x, icon_y)
            snapshot.translate(point)
            snapshot.append_layout(layout, color)
            snapshot.restore()
        x += self.INDENT_WIDTH

        # File/folder icon
        icon_char, icon_color = self._get_icon_for_item(item)
        color = tuple_to_gdk_rgba(
            self.ignored_color if item.git_status == "I" else hex_to_rgba(icon_color)
        )
        layout.set_text(icon_char.strip(), -1)
        snapshot.save()
        point.init(x, icon_y)
        snapshot.translate(point)
        snapshot.append_layout(layout, color)
        snapshot.restore()
        x += self._icon_column_width

        # Text color based on git status
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

        # Name
        layout.set_font_description(self.text_font_desc)
        layout.set_text(item.name, -1)
        snapshot.save()
        point.init(x, text_y)
        snapshot.translate(point)
        snapshot.append_layout(layout, tuple_to_gdk_rgba(text_color))
        snapshot.restore()

        # Git status hint badge
        if item.git_status and not item.is_dir and item.git_status != "I":
            self._draw_git_badge(snapshot, layout, item, text_y, width)

    def _draw_git_badge(self, snapshot, layout, item, text_y, width):
        """Draw git status badge at the right edge of the row."""
        hint_text = f"[{item.git_status}]"
        layout.set_text(hint_text, -1)
        _, logical_rect = layout.get_pixel_extents()
        hint_width = logical_rect.width
        hint_x = width - hint_width - 8

        if item.git_status == "M":
            hint_color = self.modified_color
        else:
            hint_color = hex_to_rgba(get_git_status_colors().get(item.git_status, "#808080"))

        # Background pill
        bg_color = (hint_color[0] * 0.25, hint_color[1] * 0.25, hint_color[2] * 0.25, 1.0)
        pill_rect = Graphene.Rect()
        pill_rect.init(hint_x - 4, text_y - 1, hint_width + 8, logical_rect.height + 2)
        rounded = Gsk.RoundedRect()
        rounded.init_from_rect(pill_rect, 3)
        snapshot.push_rounded_clip(rounded)
        snapshot.append_color(tuple_to_gdk_rgba(bg_color), pill_rect)
        snapshot.pop()

        # Hint text
        point = Graphene.Point()
        snapshot.save()
        point.init(hint_x, text_y)
        snapshot.translate(point)
        snapshot.append_layout(layout, tuple_to_gdk_rgba(hint_color))
        snapshot.restore()

    def _get_icon_for_item(self, item):
        """Get icon character and color for an item."""
        if item.is_dir:
            icon = self._icon_map.get("folder_open" if item.expanded else "folder_closed", "\U0001f4c1")
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

        return self._icon_map.get("default", "\U0001f4c4"), ICON_COLORS["default"]

    def _draw_drop_indicator(self, snapshot, width):
        """Draw visual indicator showing where the item will be dropped."""
        if not self._drop_target_item or not self._drop_position:
            return
        try:
            index = self.items.index(self._drop_target_item)
        except ValueError:
            return

        accent = hex_to_rgba(get_theme().accent_color)

        if self._drop_position == "into":
            y = index * self.row_height
            rect = Graphene.Rect()

            fill_color = (accent[0], accent[1], accent[2], 0.2)
            rect.init(0, y, width, self.row_height)
            snapshot.append_color(tuple_to_gdk_rgba(fill_color), rect)

            border_rect = Graphene.Rect()
            border_rect.init(0.5, y + 0.5, width - 1, self.row_height - 1)
            rounded = Gsk.RoundedRect()
            rounded.init_from_rect(border_rect, 0)
            accent_rgba = tuple_to_gdk_rgba(accent)
            snapshot.append_border(
                rounded, [1, 1, 1, 1],
                [accent_rgba, accent_rgba, accent_rgba, accent_rgba],
            )
        else:
            if self._drop_position == "before":
                line_y = index * self.row_height
            else:
                line_y = (index + 1) * self.row_height
            indent = self.LEFT_PADDING + self._drop_target_item.depth * self.INDENT_WIDTH
            accent_rgba = tuple_to_gdk_rgba(accent)

            builder = Gsk.PathBuilder.new()
            builder.move_to(indent, line_y)
            builder.line_to(width, line_y)
            path = builder.to_path()
            stroke = Gsk.Stroke.new(2.0)
            snapshot.append_stroke(path, stroke, accent_rgba)

            builder = Gsk.PathBuilder.new()
            builder.add_circle(Graphene.Point().init(indent, line_y), 3)
            path = builder.to_path()
            snapshot.append_fill(path, Gsk.FillRule.WINDING, accent_rgba)

    # ── Event overrides ────────────────────────────────────────

    def _on_right_click(self, gesture, n_press, x, y):
        """Handle right-click for context menu."""
        item = self._get_item_at_y(y)
        if item:
            if item not in self.selected_items:
                self._select_single_item(item)
            else:
                self.selected_item = item
            self._request_redraw()
            if hasattr(self.tree_view, "_show_context_menu"):
                self.tree_view._show_context_menu(item, x, y)

    def _on_key(self, controller, keyval, keycode, state):
        """Handle keyboard navigation with explorer-specific shortcuts."""
        # Block keys during inline editing
        if self._inline_entry is not None:
            return False

        if not self.items:
            return False

        # Cmd+C — copy selected item
        if keyval == Gdk.KEY_c and (state & _PRIMARY_MOD):
            if self.selected_item:
                self.tree_view._action_copy_item(self.selected_item)
            return True

        # Cmd+V — paste copied item
        if keyval == Gdk.KEY_v and (state & _PRIMARY_MOD):
            if self.selected_item:
                self.tree_view._action_paste_item(self.selected_item)
            return True

        # Cmd+Delete / Cmd+Backspace — delete
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace) and (state & _PRIMARY_MOD):
            if self.selected_item:
                self.tree_view._action_delete(self.selected_item)
            return True

        # h/Left on file → open
        if keyval in (Gdk.KEY_Left, Gdk.KEY_h):
            if self.selected_item and not self.selected_item.is_dir:
                if self.selected_item.path.exists() and self.tree_view.on_file_selected:
                    self.tree_view.on_file_selected(str(self.selected_item.path))
                return True

        # l/Right on file → open
        if keyval in (Gdk.KEY_Right, Gdk.KEY_l):
            if self.selected_item and not self.selected_item.is_dir:
                if self.selected_item.path.exists() and self.tree_view.on_file_selected:
                    self.tree_view.on_file_selected(str(self.selected_item.path))
                return True

        # Fall through to ZenTree for generic navigation
        return super()._on_key(controller, keyval, keycode, state)

    def _on_item_activated(self, item):
        """Handle file activation (click/Enter on a file)."""
        if not item.path.exists():
            self.tree_view.refresh()
            return
        if self.tree_view.on_file_selected:
            self.tree_view.on_file_selected(str(item.path))

    def _should_suppress_hover(self) -> bool:
        """Suppress hover during inline editing."""
        return self._inline_entry is not None

    # ── Data overrides ─────────────────────────────────────────

    def _load_item_children(self, item):
        """Load filesystem children for a directory."""
        self._load_children(item)  # from TreePanelDataMixin

    def _is_modified_dir(self, item: TreeItem) -> bool:
        """Check if a directory contains modified files."""
        if not item.is_dir:
            return False
        return str(item.path) in self._modified_dirs
