"""
ZenTree — reusable GtkSnapshot-based tree widget.

Provides hardware-accelerated rendering with selection highlight, hover highlight,
chevron expand/collapse, indent guides, and keyboard navigation (j/k/h/l).
Subclass and override _draw_item_row() for custom row rendering.
"""

import sys
from typing import Any, Callable, List, Optional, Set

from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk, Pango

from fonts import get_font_settings
from icons import get_icon_font_name
from shared.cursor_blinker import CursorBlinker
from shared.settings import get_setting
from shared.utils import hex_to_rgba, tuple_to_gdk_rgba
from themes import ThemeAwareMixin, get_theme, subscribe_settings_change

# Chevron glyphs (Nerd Font)
CHEVRON_EXPANDED = "\U000f0140"  # nf-md-chevron_down
CHEVRON_COLLAPSED = "\U000f0142"  # nf-md-chevron_right
_CHEVRON_COLOR = "#dcb67a"

# Scroll animation
_SCROLL_ANIM_DURATION_MS = 300
_SCROLL_ANIM_FRAME_MS = 16  # ~60fps

_PRIMARY_MOD = Gdk.ModifierType.META_MASK if sys.platform == "darwin" else Gdk.ModifierType.CONTROL_MASK


class ZenTreeItem:
    """Generic tree item for ZenTree."""

    __slots__ = ("name", "depth", "parent", "expanded", "is_expandable",
                 "children", "is_last", "data")

    def __init__(
        self,
        name: str,
        *,
        is_expandable: bool = False,
        depth: int = 0,
        parent: Optional["ZenTreeItem"] = None,
        expanded: bool = False,
        is_last: bool = False,
        data: Any = None,
    ):
        self.name = name
        self.depth = depth
        self.parent = parent
        self.expanded = expanded
        self.is_expandable = is_expandable
        self.children: List["ZenTreeItem"] = []
        self.is_last = is_last
        self.data = data


class _ZenTreeCanvas(Gtk.DrawingArea):
    """Internal DrawingArea that renders the tree via GtkSnapshot."""

    __gtype_name__ = "ZenTreeCanvas"

    def __init__(self, tree: "ZenTree"):
        super().__init__()
        self._tree = tree

    def do_snapshot(self, snapshot):
        w, h = self.get_width(), self.get_height()
        if w > 0 and h > 0:
            self._tree._on_snapshot(snapshot, w, h)


class ZenTree(ThemeAwareMixin, Gtk.ScrolledWindow):
    """Reusable GtkSnapshot-based tree widget.

    Override these for custom behavior:
    - ``_draw_item_row(snapshot, layout, item, y, width)``
    - ``_is_item_expandable(item)``
    - ``_on_item_activated(item)``
    - ``_load_item_children(item)``
    - ``_should_suppress_hover()``
    """

    DEFAULT_ROW_HEIGHT = 22
    INDENT_WIDTH = 16
    LEFT_PADDING = 10

    def __init__(self, *, font_context: str = "explorer"):
        Gtk.ScrolledWindow.__init__(self)

        self._font_context = font_context
        self.items: List = []  # Flattened visible items
        self.roots: List = []  # Root items
        self.selected_item = None
        self.selected_items: Set = set()
        self.hover_item = None
        self._selection_anchor_item = None

        # Colors
        self._setup_colors()

        # Row height
        self.row_height = self.DEFAULT_ROW_HEIGHT
        self._cached_text_height: Optional[float] = None
        self._cached_icon_height: Optional[float] = None
        self._cached_text_ink_center: Optional[float] = None
        self._cached_icon_ink_center: Optional[float] = None

        # Canvas
        self.drawing_area = _ZenTreeCanvas(self)
        self.drawing_area.set_can_focus(True)
        self.drawing_area.set_focusable(True)

        # Fonts
        self._pango_dpi = self._get_display_dpi()
        self._setup_fonts()

        # Overlay (allows subclasses to add widgets on top, e.g. inline editing)
        self._overlay = Gtk.Overlay()
        self._overlay.set_child(self.drawing_area)
        self.set_child(self._overlay)
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        # Event controllers
        self._setup_event_controllers()

        # Scroll / animation state
        self._scroll_animation_id: Optional[int] = None
        self._ensure_visible_gen: int = 0
        self._is_scrolling = False
        self._scroll_end_timer: Optional[int] = None
        self._redraw_pending = False

        # Cursor blinker for selection highlight
        self._cursor_blinker = CursorBlinker(self._request_redraw)
        self._cursor_blinker.set_enabled(get_setting("cursor_blink", True))

        focus_ctrl = Gtk.EventControllerFocus()
        focus_ctrl.connect("enter", lambda c: self._cursor_blinker.on_focus_in())
        focus_ctrl.connect("leave", lambda c: self._cursor_blinker.on_focus_out())
        self.drawing_area.add_controller(focus_ctrl)

        # Scroll adjustment
        self.connect("notify::vadjustment", self._on_vadjustment_changed)
        GLib.idle_add(self._connect_vadjustment)

        # Theme / settings subscriptions
        self._subscribe_theme()
        subscribe_settings_change(self._on_settings_change)

        # Callbacks
        self.on_item_activated: Optional[Callable] = None

    # ── Setup ──────────────────────────────────────────────────

    def _setup_colors(self):
        """Setup colors from theme."""
        theme = get_theme()
        self.bg_color = hex_to_rgba(theme.tree_bg)
        self.fg_color = hex_to_rgba(theme.tree_fg)
        self.selected_bg = hex_to_rgba(theme.tree_selected_bg)
        self.hover_bg = hex_to_rgba(theme.hover_bg)
        self.guide_color = hex_to_rgba(theme.indent_guide)
        self.chevron_color = hex_to_rgba(_CHEVRON_COLOR)

    @staticmethod
    def _get_display_dpi():
        """Get display DPI for font size estimation."""
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
        """Setup text and icon fonts for rendering."""
        nerd_font = get_icon_font_name()
        font_settings = get_font_settings(self._font_context)
        family = font_settings["family"]
        size = font_settings.get("size", 13)
        weight = font_settings.get("weight", "normal")

        # Text font
        self.text_font_desc = Pango.FontDescription.from_string(f"{family} {size}")
        from fonts import PANGO_WEIGHT_MAP
        pango_weight = PANGO_WEIGHT_MAP.get(weight, Pango.Weight.NORMAL)
        self.text_font_desc.set_weight(pango_weight)

        # Icon font (Nerd Font for chevrons)
        user_is_nerd = family and "nerd font" in family.lower()
        icon_font = family if user_is_nerd else nerd_font

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

        self._calculate_row_height()

        # Icon column width (fixed for alignment)
        platform_pad = 5 if sys.platform == "linux" else 0
        self._icon_column_width = int(size * 1.6) + platform_pad

    def _calculate_row_height(self):
        """Calculate row height from font size without Pango measurement."""
        font_settings = get_font_settings(self._font_context)
        size = font_settings.get("size", 13)
        font_px = max(int(size * self._pango_dpi / 72), size)
        line_spacing = get_setting("treeview.line_spacing", 10)
        margin_top = line_spacing // 2
        margin_bottom = line_spacing - margin_top
        self.row_height = font_px + margin_top + margin_bottom
        self._cached_text_height = None
        self._cached_icon_height = None

    def _setup_event_controllers(self):
        """Setup mouse and keyboard event controllers."""
        # Click
        click_ctrl = Gtk.GestureClick.new()
        click_ctrl.connect("pressed", self._on_click)
        click_ctrl.set_button(1)
        self.drawing_area.add_controller(click_ctrl)

        # Motion (hover)
        motion_ctrl = Gtk.EventControllerMotion.new()
        motion_ctrl.connect("motion", self._on_motion)
        motion_ctrl.connect("leave", self._on_leave)
        self.drawing_area.add_controller(motion_ctrl)

        # Keyboard
        key_ctrl = Gtk.EventControllerKey.new()
        key_ctrl.connect("key-pressed", self._on_key)
        self.drawing_area.add_controller(key_ctrl)

    # ── Theme & Settings ───────────────────────────────────────

    def _on_theme_change(self, theme):
        """Handle theme change."""
        self._setup_colors()
        self._request_redraw()

    def _on_settings_change(self, key, value):
        """Handle settings change."""
        if key in ("fonts", self._font_context):
            self._setup_fonts()
            self._update_virtual_size()
            self._request_redraw()
        elif key == "treeview":
            self._calculate_row_height()
            self._update_virtual_size()
            self._request_redraw()

    # ── Scroll ─────────────────────────────────────────────────

    def _connect_vadjustment(self):
        vadj = self.get_vadjustment()
        if vadj:
            vadj.connect("value-changed", self._on_scroll_value_changed)
        return False

    def _on_vadjustment_changed(self, widget, pspec):
        vadj = self.get_vadjustment()
        if vadj:
            vadj.connect("value-changed", self._on_scroll_value_changed)

    def _on_scroll_value_changed(self, adjustment):
        self._is_scrolling = True
        if self.hover_item:
            self.hover_item = None
        if self._scroll_end_timer is not None:
            GLib.source_remove(self._scroll_end_timer)
        self._scroll_end_timer = GLib.timeout_add(150, self._on_scroll_end)
        self.drawing_area.queue_draw()

    def _on_scroll_end(self):
        self._is_scrolling = False
        self._scroll_end_timer = None
        return False

    # ── Redraw ─────────────────────────────────────────────────

    def _request_redraw(self):
        """Coalesce multiple redraws into a single frame."""
        if not self._redraw_pending:
            self._redraw_pending = True
            GLib.idle_add(self._do_coalesced_redraw)

    def _do_coalesced_redraw(self):
        self._redraw_pending = False
        self.drawing_area.queue_draw()
        return False

    # ── Items ──────────────────────────────────────────────────

    def _is_item_expandable(self, item) -> bool:
        """Check if item is expandable. Override for custom logic."""
        return getattr(item, "is_expandable", False) or getattr(item, "is_dir", False)

    def _flatten_items(self):
        """Flatten the tree into a list of visible items."""
        self.items = []

        def traverse(item):
            self.items.append(item)
            if self._is_item_expandable(item) and item.expanded:
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
        """Update drawing area size for scrolling."""
        height = max(len(self.items) * self.row_height, 100)
        self.drawing_area.set_size_request(-1, height)

    def _get_item_at_y(self, y):
        """Get the item at a given y coordinate."""
        index = int(y / self.row_height)
        if 0 <= index < len(self.items):
            return self.items[index]
        return None

    def _toggle_expand(self, item):
        """Toggle item expansion."""
        if not self._is_item_expandable(item):
            return
        vadj = self.get_vadjustment()
        saved_scroll = vadj.get_value() if vadj else 0
        item.expanded = not item.expanded
        if item.expanded and not item.children:
            self._load_item_children(item)
        self._flatten_and_redraw()
        if vadj:
            GLib.idle_add(lambda: vadj.set_value(saved_scroll) or False)

    def _load_item_children(self, item):
        """Load children for an item. Override for lazy loading."""
        pass

    def set_roots(self, roots: List):
        """Set root items and flatten."""
        self.roots = roots
        self._flatten_and_redraw()

    def clear(self):
        """Clear all items."""
        self.roots = []
        self.items = []
        self._clear_selection()
        self.hover_item = None
        self._request_redraw()

    # ── Rendering ──────────────────────────────────────────────

    def _on_snapshot(self, snapshot, width, height):
        """Draw the tree using GtkSnapshot."""
        # Clear background
        rect = Graphene.Rect()
        rect.init(0, 0, width, height)
        snapshot.append_color(tuple_to_gdk_rgba(self.bg_color), rect)

        if not self.items:
            return

        # Scroll range
        vadj = self.get_vadjustment()
        scroll_y = vadj.get_value() if vadj else 0
        first_visible = int(scroll_y / self.row_height)
        last_visible = int((scroll_y + height) / self.row_height) + 1

        # Reusable Pango layout
        pango_ctx = self.drawing_area.get_pango_context()
        layout = Pango.Layout.new(pango_ctx)

        # Cache font metrics on first draw
        if self._cached_text_height is None:
            layout.set_font_description(self.text_font_desc)
            layout.set_text("Ay", -1)
            text_ink, text_logical = layout.get_pixel_extents()
            self._cached_text_height = text_logical.height
            self._cached_text_ink_center = text_ink.y + text_ink.height / 2

            layout.set_font_description(self.icon_font_desc)
            layout.set_text(CHEVRON_EXPANDED, -1)
            icon_ink, icon_logical = layout.get_pixel_extents()
            self._cached_icon_height = icon_logical.height
            self._cached_icon_ink_center = icon_ink.y + icon_ink.height / 2

        # Draw visible items
        for i in range(max(0, first_visible), min(len(self.items), last_visible)):
            self._draw_item(snapshot, layout, i, self.items[i], width)

    def _draw_item(self, snapshot, layout, index, item, width):
        """Draw a single item (background + content)."""
        y = index * self.row_height
        rect = Graphene.Rect()

        # Selection / hover background
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

        # Content
        self._draw_item_row(snapshot, layout, item, y, width)

    def _draw_item_row(self, snapshot, layout, item, y, width):
        """Draw item content. Override for custom rendering."""
        point = Graphene.Point()
        text_height = self._cached_text_height
        text_y = y + (self.row_height - text_height) / 2
        text_ink_center_y = text_y + self._cached_text_ink_center
        icon_y = text_ink_center_y - self._cached_icon_ink_center

        x = self.LEFT_PADDING

        # Indent guides
        if item.depth > 0:
            x = self._draw_indent_guides(snapshot, item, x, y)

        # Chevron
        layout.set_font_description(self.icon_font_desc)
        if self._is_item_expandable(item):
            chevron = self.chevron_expanded if item.expanded else self.chevron_collapsed
            layout.set_text(chevron, -1)
            snapshot.save()
            point.init(x, icon_y)
            snapshot.translate(point)
            snapshot.append_layout(layout, tuple_to_gdk_rgba(self.chevron_color))
            snapshot.restore()
        x += self.INDENT_WIDTH

        # Name
        layout.set_font_description(self.text_font_desc)
        layout.set_text(item.name, -1)
        snapshot.save()
        point.init(x, text_y)
        snapshot.translate(point)
        snapshot.append_layout(layout, tuple_to_gdk_rgba(self.fg_color))
        snapshot.restore()

    def _draw_indent_guides(self, snapshot, item, start_x, y):
        """Draw indent guide lines using GtkSnapshot."""
        show_line = []
        current = getattr(item, "parent", None)
        depth = item.depth - 1
        while current and depth >= 0:
            show_line.append(not getattr(current, "is_last", False))
            current = getattr(current, "parent", None)
            depth -= 1
        show_line.reverse()

        x = start_x
        row_top = y
        row_bottom = y + self.row_height
        row_mid = y + self.row_height // 2

        builder = Gsk.PathBuilder.new()

        for draw_line in show_line:
            line_x = x + self.INDENT_WIDTH // 2
            if draw_line:
                builder.move_to(line_x + 0.5, row_top)
                builder.line_to(line_x + 0.5, row_bottom)
            x += self.INDENT_WIDTH

        line_x = x + self.INDENT_WIDTH // 2
        if getattr(item, "is_last", False):
            builder.move_to(line_x + 0.5, row_top)
            builder.line_to(line_x + 0.5, row_mid)
            builder.move_to(line_x + 0.5, row_mid)
            builder.line_to(x + self.INDENT_WIDTH, row_mid)
        else:
            builder.move_to(line_x + 0.5, row_top)
            builder.line_to(line_x + 0.5, row_bottom)

        x += self.INDENT_WIDTH
        path = builder.to_path()
        stroke = Gsk.Stroke.new(1.0)
        snapshot.append_stroke(path, stroke, tuple_to_gdk_rgba(self.guide_color))
        return x

    # ── Events ─────────────────────────────────────────────────

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
        self._ensure_visible_gen += 1

        state = gesture.get_current_event_state()
        is_range = bool(state & Gdk.ModifierType.SHIFT_MASK)
        is_toggle = bool(state & _PRIMARY_MOD)

        item = self._get_item_at_y(y)
        if item:
            if is_range:
                self._select_range_to(item)
            elif is_toggle:
                self._toggle_item_selection(item)
            else:
                self._select_single_item(item)
            self._cursor_blinker.reset()

            if is_range or is_toggle:
                self._request_redraw()
                return

            # For non-expandable items, ignore double-clicks
            if n_press > 1 and not self._is_item_expandable(item):
                self._request_redraw()
                return

            if self._is_item_expandable(item):
                self._toggle_expand(item)
            else:
                self._on_item_activated(item)
            self._request_redraw()

    def _on_motion(self, controller, x, y):
        """Handle mouse motion for hover effect."""
        if self._is_scrolling or self._should_suppress_hover():
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

    def _on_item_activated(self, item):
        """Called when a non-expandable item is clicked/entered. Override for custom behavior."""
        if self.on_item_activated:
            self.on_item_activated(item)

    def _should_suppress_hover(self) -> bool:
        """Override to suppress hover in certain states (e.g. inline editing)."""
        return False

    # ── Selection ──────────────────────────────────────────────

    def _is_item_selected(self, item) -> bool:
        """Return whether an item is part of the current selection."""
        return item is not None and item in self.selected_items

    def get_selected_items(self) -> List:
        """Return selected items in visible tree order."""
        if not self.selected_items:
            return []
        return [item for item in self.items if item in self.selected_items]

    def _set_selection(self, items: List, primary_item=None, anchor_item=None):
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

    def _select_single_item(self, item):
        """Select a single tree item."""
        if item is None:
            self._clear_selection()
            return
        self._set_selection([item], primary_item=item, anchor_item=item)

    def _toggle_item_selection(self, item):
        """Toggle an item inside the current selection."""
        if item in self.selected_items:
            remaining = [s for s in self.get_selected_items() if s != item]
            if remaining:
                new_primary = self.selected_item if self.selected_item != item else remaining[-1]
                new_anchor = self._selection_anchor_item if self._selection_anchor_item != item else new_primary
                self._set_selection(remaining, primary_item=new_primary, anchor_item=new_anchor)
            else:
                self._clear_selection()
            return
        items = self.get_selected_items()
        items.append(item)
        self._set_selection(items, primary_item=item, anchor_item=item)

    def _select_range_to(self, item):
        """Select an inclusive range from the anchor item to the target item."""
        anchor = self._selection_anchor_item or self.selected_item
        if anchor not in self.items:
            self._select_single_item(item)
            return
        start = self.items.index(anchor)
        end = self.items.index(item)
        if start <= end:
            range_items = self.items[start:end + 1]
        else:
            range_items = self.items[end:start + 1]
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

    # ── Keyboard ───────────────────────────────────────────────

    def _on_key(self, controller, keyval, keycode, state):
        """Handle keyboard navigation (j/k/h/l, arrows, Enter, Space)."""
        if not self.items:
            return False

        # Up / k
        if keyval in (Gdk.KEY_Up, Gdk.KEY_k):
            self._navigate(-1)
            return True
        # Down / j
        if keyval in (Gdk.KEY_Down, Gdk.KEY_j):
            self._navigate(1)
            return True
        # Enter
        if keyval == Gdk.KEY_Return:
            if self.selected_item:
                if self._is_item_expandable(self.selected_item):
                    self._toggle_expand(self.selected_item)
                else:
                    self._on_item_activated(self.selected_item)
            return True
        # Space
        if keyval == Gdk.KEY_space:
            if self.selected_item and self._is_item_expandable(self.selected_item):
                self._toggle_expand(self.selected_item)
            return True
        # Left / h — collapse or go to parent
        if keyval in (Gdk.KEY_Left, Gdk.KEY_h):
            if self.selected_item:
                if self._is_item_expandable(self.selected_item) and self.selected_item.expanded:
                    self._toggle_expand(self.selected_item)
                elif hasattr(self.selected_item, "parent") and self.selected_item.parent:
                    self._select_single_item(self.selected_item.parent)
                    self._ensure_visible(self.selected_item)
                    self._request_redraw()
            return True
        # Right / l — expand or go to first child
        if keyval in (Gdk.KEY_Right, Gdk.KEY_l):
            if self.selected_item and self._is_item_expandable(self.selected_item):
                if not self.selected_item.expanded:
                    self._toggle_expand(self.selected_item)
                elif self.selected_item.children:
                    self._select_single_item(self.selected_item.children[0])
                    self._ensure_visible(self.selected_item)
                    self._request_redraw()
            return True

        return False

    def _navigate(self, direction):
        """Navigate up/down in the list."""
        if not self.items:
            return
        if self.selected_item is None:
            self._select_single_item(self.items[0])
        else:
            try:
                idx = self.items.index(self.selected_item)
                new_idx = max(0, min(len(self.items) - 1, idx + direction))
                self._select_single_item(self.items[new_idx])
            except ValueError:
                self._select_single_item(self.items[0])
        self._cursor_blinker.reset()
        self._ensure_visible(self.selected_item)
        self._request_redraw()

    def _ensure_visible(self, item, animate=False, _retries=0, _gen=-1):
        """Scroll to make an item visible (only if currently out of view)."""
        if _gen == -1:
            self._ensure_visible_gen += 1
            _gen = self._ensure_visible_gen
        elif _gen != self._ensure_visible_gen:
            return False

        try:
            idx = self.items.index(item)
            vadj = self.get_vadjustment()
            if not vadj:
                return False

            item_y = idx * self.row_height
            view_height = vadj.get_page_size()
            scroll_y = vadj.get_value()

            if view_height <= 0:
                if _retries < 5:
                    GLib.idle_add(self._ensure_visible, item, animate, _retries + 1, _gen)
                return False

            item_top = item_y
            item_bottom = item_y + self.row_height

            if animate:
                item_visible = item_bottom > scroll_y and item_top < scroll_y + view_height
            else:
                tolerance = 1.0
                item_visible = (
                    item_top >= scroll_y - tolerance
                    and item_bottom <= scroll_y + view_height + tolerance
                )

            if item_visible:
                if self._scroll_animation_id is not None:
                    GLib.source_remove(self._scroll_animation_id)
                    self._scroll_animation_id = None
                return False

            target_y = None
            if item_top < scroll_y:
                target_y = max(0, item_y - view_height / 2 + self.row_height / 2)
            elif item_bottom > scroll_y + view_height:
                target_y = min(
                    vadj.get_upper() - view_height,
                    item_y - view_height / 2 + self.row_height / 2,
                )

            if target_y is not None:
                if animate:
                    self._animate_scroll_to(target_y)
                else:
                    vadj.set_value(target_y)
        except ValueError:
            pass
        return False

    def _animate_scroll_to(self, target_y):
        """Animate scroll to a target position using easing."""
        if self._scroll_animation_id is not None:
            GLib.source_remove(self._scroll_animation_id)
            self._scroll_animation_id = None

        vadj = self.get_vadjustment()
        if not vadj:
            return

        start_y = vadj.get_value()
        distance = target_y - start_y

        if abs(distance) < 5:
            vadj.set_value(target_y)
            return

        start_time = GLib.get_monotonic_time() / 1000.0

        def ease_out_cubic(t):
            return 1 - pow(1 - t, 3)

        def step():
            elapsed = GLib.get_monotonic_time() / 1000.0 - start_time
            progress = min(1.0, elapsed / _SCROLL_ANIM_DURATION_MS)
            vadj.set_value(start_y + distance * ease_out_cubic(progress))
            if progress >= 1.0:
                self._scroll_animation_id = None
                return False
            return True

        self._scroll_animation_id = GLib.timeout_add(_SCROLL_ANIM_FRAME_MS, step)
