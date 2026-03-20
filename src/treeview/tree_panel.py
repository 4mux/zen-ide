"""
CustomTreePanel — core tree panel with GtkSnapshot drawing, scrolling, and data management.
Composes behavior from renderer, drag, inline-edit, and keyboard mixins.
"""

import os
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

from gi.repository import Gdk, GLib, Gtk, Pango

from fonts import get_font_settings
from icons import Icons, get_icon_font_name
from shared.git_ignore_utils import get_global_patterns, get_matcher, get_workspace_patterns
from shared.settings import get_setting
from shared.utils import hex_to_rgba
from themes import (
    get_theme,
    subscribe_settings_change,
    subscribe_theme_change,
)
from treeview.tree_canvas import TreeCanvas
from treeview.tree_icons import (
    CHEVRON_COLLAPSED,
    CHEVRON_COLOR,
    CHEVRON_EXPANDED,
    get_icon_set,
)
from treeview.tree_item import TreeItem
from treeview.tree_panel_drag import TreePanelDragMixin
from treeview.tree_panel_inline_edit import TreePanelInlineEditMixin
from treeview.tree_panel_keyboard import TreePanelKeyboardMixin
from treeview.tree_panel_renderer import TreePanelRendererMixin

_PRIMARY_MOD = Gdk.ModifierType.META_MASK if sys.platform == "darwin" else Gdk.ModifierType.CONTROL_MASK


class CustomTreePanel(
    TreePanelRendererMixin,
    TreePanelDragMixin,
    TreePanelInlineEditMixin,
    TreePanelKeyboardMixin,
    Gtk.ScrolledWindow,
):
    """Custom drawn tree control with neovim-style indent guides."""

    DEFAULT_ROW_HEIGHT = 22
    INDENT_WIDTH = 16
    LEFT_PADDING = 10

    def __init__(self, tree_view):
        super().__init__()
        self.tree_view = tree_view
        self.items: List[TreeItem] = []  # Flattened visible items
        self.roots: List[TreeItem] = []  # Root tree items
        self.selected_item: Optional[TreeItem] = None
        self.selected_items: Set[TreeItem] = set()
        self.hover_item: Optional[TreeItem] = None
        self._selection_anchor_item: Optional[TreeItem] = None

        # Git status tracking
        self._git_modified_files: Set[str] = set()
        self._git_status_map: Dict[str, str] = {}
        self._modified_dirs: Set[str] = set()

        # Theme colors (will be set in _setup_colors)
        self._setup_colors()

        # Row height (will be calculated in _setup_fonts)
        self.row_height = self.DEFAULT_ROW_HEIGHT
        self._pango_fonts_warm = False

        # Custom widget for GtkSnapshot rendering (replaces Gtk.DrawingArea)
        self.drawing_area = TreeCanvas(panel=self)

        # Font setup (needs drawing_area for widget Pango context resolution)
        self._setup_fonts()

        # Icon set
        self._setup_icons()
        self.drawing_area.set_can_focus(True)
        self.drawing_area.set_focusable(True)

        # Inline editing state
        self._inline_entry: Optional[Gtk.Entry] = None
        self._inline_item: Optional[TreeItem] = None
        self._inline_on_confirm: Optional[Callable[[str], None]] = None
        self._inline_on_cancel: Optional[Callable[[], None]] = None

        # Use Overlay to allow Entry to be placed on top of DrawingArea
        self._overlay = Gtk.Overlay()
        self._overlay.set_child(self.drawing_area)

        # Wrap in a viewport for scrolling
        self.set_child(self._overlay)
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        # Event controllers
        self._setup_event_controllers()

        # Animation state
        self._scroll_animation_id: Optional[int] = None
        self._ensure_visible_gen: int = 0  # generation counter to invalidate stale retries

        # Scroll state for hover suppression
        self._is_scrolling = False
        self._scroll_end_timer: Optional[int] = None

        # Coalesced redraw flag
        self._redraw_pending = False

        # Custom cursor blink for selection highlight
        from shared.cursor_blink import CursorBlinker
        from shared.settings import get_setting

        self._cursor_blinker = CursorBlinker(self._request_redraw)
        self._cursor_blinker.set_enabled(get_setting("cursor_blink", True))

        # Focus tracking for cursor blink
        focus_ctrl = Gtk.EventControllerFocus()
        focus_ctrl.connect("enter", lambda c: self._cursor_blinker.on_focus_in())
        focus_ctrl.connect("leave", lambda c: self._cursor_blinker.on_focus_out())
        self.drawing_area.add_controller(focus_ctrl)

        # Drag-and-drop state
        self._drag_source_item: Optional[TreeItem] = None
        self._drop_target_item: Optional[TreeItem] = None
        self._drop_position: Optional[str] = None  # "into", "before", "after"
        self._drag_start_y: float = 0.0
        self._drag_activated: bool = False  # True once threshold exceeded
        self._drag_start_scroll_y: float = 0.0  # Scroll pos at drag begin

        # Compiled gitignore pattern cache: workspace_root -> (patterns_set, compiled_globs)
        self._pattern_cache: Dict[Optional[str], tuple] = {}

        # Connect to scroll adjustment to redraw when scrollbar is dragged
        self.connect("notify::vadjustment", self._on_vadjustment_changed)
        GLib.idle_add(self._connect_vadjustment)

        # Subscribe to theme changes
        subscribe_theme_change(self._on_theme_change)
        subscribe_settings_change(self._on_settings_change)

    def _connect_vadjustment(self):
        """Connect to the vertical adjustment's value-changed signal."""
        vadj = self.get_vadjustment()
        if vadj:
            vadj.connect("value-changed", self._on_scroll_value_changed)
        return False  # Don't repeat idle callback

    def _on_vadjustment_changed(self, widget, pspec):
        """Handle when the vertical adjustment property changes."""
        vadj = self.get_vadjustment()
        if vadj:
            vadj.connect("value-changed", self._on_scroll_value_changed)

    def _on_scroll_value_changed(self, adjustment):
        """Handle scrollbar/adjustment value changes - redraw the tree."""
        self._is_scrolling = True
        # Cancel any active drag — scroll invalidates drag coordinates
        if self._drag_source_item:
            self._cleanup_drag_state()
        if self.hover_item:
            self.hover_item = None

        # Cancel any existing scroll-end timer
        if self._scroll_end_timer is not None:
            GLib.source_remove(self._scroll_end_timer)

        self._scroll_end_timer = GLib.timeout_add(150, self._on_scroll_end)
        self.drawing_area.queue_draw()

    def _on_scroll_end(self):
        """Called after scrolling stops."""
        self._is_scrolling = False
        self._scroll_end_timer = None
        return False  # Don't repeat

    def _request_redraw(self):
        """Coalesce multiple redraws into a single frame."""
        if not self._redraw_pending:
            self._redraw_pending = True
            GLib.idle_add(self._do_coalesced_redraw)

    def _do_coalesced_redraw(self):
        """Execute the coalesced redraw."""
        self._redraw_pending = False
        self.drawing_area.queue_draw()
        return False

    def _setup_colors(self):
        """Setup colors from theme."""
        theme = get_theme()

        self.bg_color = hex_to_rgba(theme.tree_bg)
        self.fg_color = hex_to_rgba(theme.tree_fg)
        self.selected_bg = hex_to_rgba(theme.tree_selected_bg)
        self.hover_bg = hex_to_rgba(theme.hover_bg)
        self.guide_color = hex_to_rgba(theme.indent_guide)
        self.chevron_color = hex_to_rgba(CHEVRON_COLOR)
        self.modified_color = hex_to_rgba(theme.tree_modified_fg)
        self.ignored_color = hex_to_rgba(theme.tree_ignored_fg or theme.fg_dim)

    @staticmethod
    def _get_display_dpi():
        """Get display DPI for font size estimation."""
        import sys

        try:
            settings = Gtk.Settings.get_default()
            if settings:
                xft_dpi = settings.get_property("gtk-xft-dpi")
                if xft_dpi > 0:
                    return xft_dpi / 1024.0
        except Exception:
            pass
        return 72.0 if sys.platform == "darwin" else 96.0

    def _setup_fonts(self):
        """Setup fonts for rendering."""
        # Get display DPI for font size estimation
        self._pango_dpi = self._get_display_dpi()

        nerd_font = get_icon_font_name()

        # Get font from settings
        font_settings = get_font_settings("explorer")
        family = font_settings["family"]
        size = font_settings.get("size", 13)
        weight = font_settings.get("weight", "normal")

        # Text font
        self.text_font_desc = Pango.FontDescription.from_string(f"{family} {size}")

        from fonts import PANGO_WEIGHT_MAP

        pango_weight = PANGO_WEIGHT_MAP.get(weight, Pango.Weight.NORMAL)
        self.text_font_desc.set_weight(pango_weight)

        # Icon font - prefer user's font if it's a Nerd Font, else auto-detected
        user_is_nerd = family and "nerd font" in family.lower()
        icon_font = family if user_is_nerd else nerd_font

        # For non-Propo Nerd Fonts, icons render small due to monospace constraints.
        if icon_font and "nerd font" in icon_font.lower() and "propo" not in icon_font.lower():
            propo_name = icon_font.replace(" Mono", "").rstrip() + " Propo"
            if propo_name != icon_font:
                font_map = self.drawing_area.get_pango_context().get_font_map()
                available = {f.get_name() for f in font_map.list_families()}
                if propo_name in available:
                    icon_font = propo_name

        if icon_font:
            self.icon_font_desc = Pango.FontDescription.from_string(f"{icon_font} {size + 1}")
        else:
            self.icon_font_desc = Pango.FontDescription.from_string(f"{family} {size}")
        self.chevron_expanded = CHEVRON_EXPANDED
        self.chevron_collapsed = CHEVRON_COLLAPSED

        # Calculate row height from actual font metrics + margins
        self._calculate_row_height()

        # Icon column width (fixed for alignment)
        import sys

        platform_pad = 5 if sys.platform == "linux" else 0
        self._icon_column_width = int(size * 1.6) + platform_pad

    def _calculate_row_height(self):
        """Calculate row height from font size without Pango measurement.

        Uses a mathematical estimate to avoid the ~14ms Pango first-time font
        loading cost. The estimate matches Pango's output exactly at 72 DPI
        (macOS) and is within 1-2px at other resolutions — invisible in a tree.
        Pango warms up naturally on the first draw (after metrics are printed).
        """
        font_settings = get_font_settings("explorer")
        size = font_settings.get("size", 13)
        font_px = max(int(size * self._pango_dpi / 72), size)
        line_spacing = get_setting("treeview.line_spacing", 10)
        margin_top = line_spacing // 2
        margin_bottom = line_spacing - margin_top
        self.row_height = font_px + margin_top + margin_bottom
        # Invalidate cached text/icon heights so renderer re-measures on next draw
        self._cached_text_height = None
        self._cached_icon_height = None

    def _setup_icons(self):
        """Setup icon mappings."""
        file_icons, name_icons, folder_closed, folder_open = get_icon_set()
        self._icon_map = {
            "folder_closed": folder_closed,
            "folder_open": folder_open,
            "default": Icons.FILE + " ",
        }
        self._icon_map.update({f"ext_{k}": v for k, v in file_icons.items()})
        self._icon_map.update({f"name_{k}": v for k, v in name_icons.items()})

    def _setup_event_controllers(self):
        """Setup event controllers for mouse and keyboard."""
        # Click controller
        click_ctrl = Gtk.GestureClick.new()
        click_ctrl.connect("pressed", self._on_click)
        click_ctrl.set_button(1)  # Left button
        self.drawing_area.add_controller(click_ctrl)

        # Right-click controller
        right_click_ctrl = Gtk.GestureClick.new()
        right_click_ctrl.connect("pressed", self._on_right_click)
        right_click_ctrl.set_button(3)  # Right button
        self.drawing_area.add_controller(right_click_ctrl)

        # Motion controller for hover
        motion_ctrl = Gtk.EventControllerMotion.new()
        motion_ctrl.connect("motion", self._on_motion)
        motion_ctrl.connect("leave", self._on_leave)
        self.drawing_area.add_controller(motion_ctrl)

        # Key controller
        key_ctrl = Gtk.EventControllerKey.new()
        key_ctrl.connect("key-pressed", self._on_key)
        self.drawing_area.add_controller(key_ctrl)

        # NOTE: We don't add a custom scroll controller here.
        # The ScrolledWindow parent handles scrolling naturally, including
        # kinetic/momentum scrolling on trackpads.

        # Internal drag gesture for file reordering (avoids native DnD crash on macOS)
        drag_gesture = Gtk.GestureDrag()
        drag_gesture.connect("drag-begin", self._on_gesture_drag_begin)
        drag_gesture.connect("drag-update", self._on_gesture_drag_update)
        drag_gesture.connect("drag-end", self._on_gesture_drag_end)
        self.drawing_area.add_controller(drag_gesture)

        # External drop target for files dragged from outside the IDE
        self._setup_external_drop_target()

    def _on_theme_change(self, theme):
        """Handle theme change."""
        self._setup_colors()
        self._request_redraw()

    def _on_settings_change(self, key, value):
        """Handle settings change."""
        if key == "fonts" or key == "explorer":
            self._setup_fonts()
            self._setup_icons()
            self._update_virtual_size()
            self._request_redraw()
        elif key == "treeview":
            self._calculate_row_height()
            self._update_virtual_size()
            self._request_redraw()

    def _flatten_items(self):
        """Flatten the tree into a list of visible items."""
        self.items = []

        def traverse(item: TreeItem):
            self.items.append(item)
            if item.is_dir and item.expanded:
                for child in item.children:
                    traverse(child)

        for root in self.roots:
            traverse(root)

        self._prune_selection_to_visible_items()
        self._update_virtual_size()

    def _flatten_and_redraw(self):
        """Flatten tree and schedule a coalesced redraw."""
        self._flatten_items()
        self._request_redraw()

    def _update_virtual_size(self):
        """Update the drawing area size for scrolling."""
        height = max(len(self.items) * self.row_height, 100)
        self.drawing_area.set_size_request(-1, height)

    def _is_modified_dir(self, item: TreeItem) -> bool:
        """Check if a directory contains modified files."""
        if not item.is_dir:
            return False
        return str(item.path) in self._modified_dirs

    def _get_item_at_y(self, y):
        """Get the item at a given y coordinate."""
        index = int(y / self.row_height)
        if 0 <= index < len(self.items):
            return self.items[index]
        return None

    def _is_item_selected(self, item: Optional[TreeItem]) -> bool:
        """Return whether an item is part of the current selection."""
        return item is not None and item in self.selected_items

    def get_selected_items(self) -> List[TreeItem]:
        """Return selected items in visible tree order."""
        if not self.selected_items:
            return []
        return [item for item in self.items if item in self.selected_items]

    def _set_selection(
        self,
        items: List[TreeItem],
        primary_item: Optional[TreeItem] = None,
        anchor_item: Optional[TreeItem] = None,
    ):
        """Replace the current selection."""
        visible_items = [item for item in items if item in self.items]
        self.selected_items = set(visible_items)

        if not visible_items:
            self.selected_item = None
            self._selection_anchor_item = None
            return

        if primary_item not in self.selected_items:
            primary_item = visible_items[-1]
        self.selected_item = primary_item

        if anchor_item not in self.selected_items:
            anchor_item = primary_item
        self._selection_anchor_item = anchor_item

    def _clear_selection(self):
        """Clear the current selection."""
        self.selected_items.clear()
        self.selected_item = None
        self._selection_anchor_item = None

    def _select_single_item(self, item: Optional[TreeItem]):
        """Select a single tree item."""
        if item is None:
            self._clear_selection()
            return
        self._set_selection([item], primary_item=item, anchor_item=item)

    def _toggle_item_selection(self, item: TreeItem):
        """Toggle an item inside the current selection."""
        if item in self.selected_items:
            remaining_items = [selected for selected in self.get_selected_items() if selected != item]
            if remaining_items:
                new_primary = self.selected_item if self.selected_item != item else remaining_items[-1]
                new_anchor = self._selection_anchor_item if self._selection_anchor_item != item else new_primary
                self._set_selection(remaining_items, primary_item=new_primary, anchor_item=new_anchor)
            else:
                self._clear_selection()
            return

        items = self.get_selected_items()
        items.append(item)
        self._set_selection(items, primary_item=item, anchor_item=item)

    def _select_range_to(self, item: TreeItem):
        """Select an inclusive range from the anchor item to the target item."""
        anchor = self._selection_anchor_item or self.selected_item
        if anchor not in self.items:
            self._select_single_item(item)
            return

        start = self.items.index(anchor)
        end = self.items.index(item)
        if start <= end:
            range_items = self.items[start : end + 1]
        else:
            range_items = self.items[end : start + 1]
        self._set_selection(range_items, primary_item=item, anchor_item=anchor)

    def _prune_selection_to_visible_items(self):
        """Drop any selected items that are no longer visible."""
        if not self.selected_items:
            self.selected_item = None
            if self._selection_anchor_item not in self.items:
                self._selection_anchor_item = None
            return

        visible = set(self.items)
        self.selected_items = {item for item in self.selected_items if item in visible}

        if not self.selected_items:
            self.selected_item = None
            self._selection_anchor_item = None
            return

        if self.selected_item not in self.selected_items:
            self.selected_item = self.get_selected_items()[-1]

        if self._selection_anchor_item not in self.selected_items:
            self._selection_anchor_item = self.selected_item

    def _on_click(self, gesture, n_press, x, y):
        """Handle click."""
        vadj = self.get_vadjustment()
        saved_scroll = vadj.get_value() if vadj else 0
        self.drawing_area.grab_focus()
        if vadj:
            vadj.set_value(saved_scroll)
        # Cancel any running scroll animation
        if self._scroll_animation_id is not None:
            GLib.source_remove(self._scroll_animation_id)
            self._scroll_animation_id = None
        # Invalidate any pending deferred _ensure_visible calls
        self._ensure_visible_gen += 1
        state = gesture.get_current_event_state()
        is_range_select = bool(state & Gdk.ModifierType.SHIFT_MASK)
        is_toggle_select = bool(state & _PRIMARY_MOD)
        item = self._get_item_at_y(y)
        if item:
            if is_range_select:
                self._select_range_to(item)
            elif is_toggle_select:
                self._toggle_item_selection(item)
            else:
                self._select_single_item(item)
            self._cursor_blinker.reset()
            if is_range_select or is_toggle_select:
                self._request_redraw()
                return
            # For files, ignore double-clicks to avoid opening twice.
            # For directories, allow every press so rapid expand/collapse works.
            if n_press > 1 and not item.is_dir:
                self._request_redraw()
                return
            if item.is_dir:
                self._toggle_expand(item)
            else:
                # Verify file still exists before opening (handles deleted files)
                if not item.path.exists():
                    self.tree_view.refresh()
                    return
                if self.tree_view.on_file_selected:
                    self.tree_view.on_file_selected(str(item.path))
            self._request_redraw()

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

    def _on_motion(self, controller, x, y):
        """Handle mouse motion for hover effect."""
        if self._is_scrolling or self._inline_entry is not None:
            return

        item = self._get_item_at_y(y)
        if item != self.hover_item:
            self.hover_item = item
            self._request_redraw()

    def _on_leave(self, controller):
        """Handle mouse leave."""
        if self.hover_item:
            self.hover_item = None
            self._request_redraw()

    def _toggle_expand(self, item: TreeItem):
        """Toggle folder expansion."""
        if not item.is_dir:
            return

        vadj = self.get_vadjustment()
        saved_scroll = vadj.get_value() if vadj else 0

        item.expanded = not item.expanded

        if item.expanded and not item.children:
            self._load_children(item)

        self._flatten_and_redraw()

        if vadj:
            GLib.idle_add(lambda: vadj.set_value(saved_scroll) or False)

    def _load_children(self, item: TreeItem):
        """Load children for a directory."""
        try:
            entries = sorted(item.path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except PermissionError:
            return

        item.children = []

        parent_inherited = item.git_status if item.is_dir else ""

        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            path_str = str(entry)

            is_ignored = self._should_skip(entry)

            if is_ignored:
                git_status = "I"
            elif path_str in self._git_modified_files:
                git_status = self._git_status_map.get(path_str, "M")
            elif parent_inherited:
                git_status = parent_inherited
            else:
                git_status = ""
            child = TreeItem(
                name=entry.name,
                path=entry,
                is_dir=entry.is_dir(),
                depth=item.depth + 1,
                parent=item,
                is_last=is_last,
                git_status=git_status,
            )
            item.children.append(child)

    def _should_skip(self, path: Path) -> bool:
        """Check if a path should be skipped (uses cached compiled patterns)."""
        name = path.name

        workspace_root = None
        path_str = str(path)
        for root in self.roots:
            root_str = str(root.path)
            if path_str.startswith(root_str + os.sep) or path_str == root_str:
                workspace_root = root_str
                break

        if workspace_root not in self._pattern_cache:
            self._compile_patterns(workspace_root)

        exact_names, compiled_globs = self._pattern_cache[workspace_root]

        if name in exact_names:
            return True
        for regex in compiled_globs:
            if regex.match(name):
                return True

        # Fall back to full GitIgnoreUtils matcher for path-based patterns
        if workspace_root:
            matcher = get_matcher(workspace_root)
            return matcher.is_ignored(path_str, path.is_dir())

        return False

    def _compile_patterns(self, workspace_root):
        """Compile and cache gitignore patterns for a workspace root."""
        import fnmatch as fnmatch_mod
        import re as re_mod

        patterns = get_workspace_patterns(workspace_root) if workspace_root else get_global_patterns()
        exact_names = set()
        compiled_globs = []
        for pattern in patterns:
            if "*" in pattern:
                compiled_globs.append(re_mod.compile(fnmatch_mod.translate(pattern)))
            else:
                exact_names.add(pattern)
        self._pattern_cache[workspace_root] = (exact_names, compiled_globs)

    def load_directory(self, path: Path, expanded: bool = False):
        """Load a directory as a root."""
        root = TreeItem(
            name=path.name,
            path=path,
            is_dir=True,
            depth=0,
            expanded=expanded,
            is_last=True,
        )
        self.roots.append(root)
        if expanded:
            self._load_children(root)
        self._flatten_and_redraw()

    def clear(self):
        """Clear all items."""
        self.roots = []
        self.items = []
        self._clear_selection()
        self.hover_item = None
        self._pattern_cache.clear()
        self._request_redraw()

    def set_git_modified_files(self, modified_files: Set[str], status_map: Optional[Dict[str, str]] = None):
        """Set git modified files and update tree display."""
        new_status_map = status_map or {}

        if self._git_modified_files == modified_files and self._git_status_map == new_status_map:
            return

        self._git_modified_files = modified_files
        self._git_status_map = new_status_map

        # Pre-compute directories containing modified files
        self._modified_dirs = set()
        for file_path in modified_files:
            parent = os.path.dirname(str(file_path))
            while parent and parent not in self._modified_dirs:
                self._modified_dirs.add(parent)
                parent = os.path.dirname(parent)

        self._update_item_git_status()
        self._request_redraw()

    def _update_item_git_status(self):
        """Update git_status field on all tree items."""

        def update_item(item: TreeItem, inherited_status: str = ""):
            if item.git_status == "I":
                for child in item.children:
                    update_item(child, "I")
                return

            path_str = str(item.path)
            if path_str in self._git_modified_files:
                item.git_status = self._git_status_map.get(path_str, "M")
            elif inherited_status:
                item.git_status = inherited_status
            else:
                item.git_status = ""

            child_inherited = item.git_status if item.is_dir else inherited_status
            for child in item.children:
                update_item(child, child_inherited)

        for root in self.roots:
            update_item(root)
