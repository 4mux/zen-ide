"""
Diff View for Zen IDE.
Shows side-by-side diff of file changes with commit history navigation.
Inline revert buttons appear at the start of each diff region.
"""

import difflib
import os
import threading

from gi.repository import Gdk, GLib, Graphene, Gtk, GtkSource, Pango

from constants import DIFF_MINIMAP_WIDTH
from fonts import get_font_settings
from icons import ICON_FONT_FAMILY, Icons
from popups.confirm_dialog import show_confirm
from shared.focus_border_mixin import FocusBorderMixin
from shared.focus_manager import get_component_focus_manager
from shared.git_manager import get_git_manager
from shared.main_thread import main_thread_call
from shared.settings import get_setting
from shared.ui import ZenButton
from shared.ui.zen_entry import ZenSearchEntry
from themes import get_theme, subscribe_theme_change

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


def _disable_text_view_drag(view):
    """Prevent DnD of selected text (crashes on macOS) while keeping selection.

    Adds a capture-phase drag gesture that claims the sequence only when
    the click starts inside an existing selection (the DnD trigger case).
    """

    def _on_capture_drag_begin(gesture, start_x, start_y):
        buf = view.get_buffer()
        sel = buf.get_selection_bounds()
        if sel:
            bx, by = view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(start_x), int(start_y))
            ok, click_iter = view.get_iter_at_location(bx, by)
            if ok and sel[0].compare(click_iter) <= 0 and click_iter.compare(sel[1]) <= 0:
                gesture.set_state(Gtk.EventSequenceState.CLAIMED)
                return
        gesture.set_state(Gtk.EventSequenceState.DENIED)

    g = Gtk.GestureDrag()
    g.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
    g.connect("drag-begin", _on_capture_drag_begin)
    view.add_controller(g)


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
                f'<span font_family="{ICON_FONT_FAMILY}" foreground="{get_theme().warning_color}" weight="bold">{Icons.UNDO_ARROW}</span>',
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


class DiffView(FocusBorderMixin, Gtk.Box):
    """Side-by-side diff view showing changes with commit history navigation."""

    COMPONENT_ID = "diff_view"

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        # Make focusable so keyboard events work
        self.set_focusable(True)
        self.set_can_focus(True)

        # Initialize focus border for visual indication
        self._init_focus_border()

        # Register with focus manager so other panels unfocus properly
        focus_mgr = get_component_focus_manager()
        focus_mgr.register(
            self.COMPONENT_ID,
            on_focus_in=lambda: self._set_focused(True),
            on_focus_out=lambda: self._set_focused(False),
        )

        focus_ctrl = Gtk.EventControllerFocus()
        focus_ctrl.connect("enter", lambda _: get_component_focus_manager().set_focus(self.COMPONENT_ID))
        focus_ctrl.connect("leave", lambda _: get_component_focus_manager().clear_focus(self.COMPONENT_ID))
        self.add_controller(focus_ctrl)

        self._syncing_scroll = False
        self._on_close_callback = None
        self._on_revert_callback = None
        self._on_click_callback = None  # Called when user clicks on diff view
        self._on_navigate_callback = None  # Called on double-click: (line_number) -> close diff & go to line

        # State
        self._current_file_path = None
        self._current_content = None
        self._commit_content = None
        self._commits = []
        self._current_commit_index = 0
        self._diff_regions = []
        self._old_lines = []
        self._new_lines = []

        # Gutter renderers for revert buttons
        self._left_revert_renderer = None
        self._right_revert_renderer = None

        # UI elements (created lazily)
        self._header = None
        self._commit_label = None
        self._prev_btn = None
        self._next_btn = None
        self._left_pane_label = None
        self._right_pane_label = None
        self.paned = None
        self.left_view = None
        self.right_view = None
        self.left_buffer = None
        self.right_buffer = None
        self._left_scroll = None
        self._right_scroll = None
        self._minimap = None
        self._viewport_update_pending = False
        self._left_font_provider = None
        self._right_font_provider = None

        # Search state
        self._find_bar = None
        self._find_entry = None
        self._find_count_label = None
        self._left_search_context = None
        self._right_search_context = None
        self._search_settings = None
        self._active_search_side = "right"  # which side has the active cursor

        self._create_ui()
        subscribe_theme_change(self._on_theme_change)

    def _create_ui(self):
        # ESC and arrow key handler (CAPTURE phase to intercept before child widgets)
        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

        # Click anywhere on diff view grabs focus for keyboard events
        click_focus = Gtk.GestureClick()
        click_focus.connect("pressed", self._on_diff_clicked)
        self.add_controller(click_focus)

        # Apply dark background
        self._apply_css()

        # Header bar
        self._header = self._create_header()
        self.append(self._header)

        # Find bar (hidden by default)
        self._create_find_bar()

        # Editor area with pane labels
        editor_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        editor_box.set_vexpand(True)
        editor_box.set_hexpand(True)

        # Pane labels row
        labels_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        labels_box.set_margin_start(8)
        labels_box.set_margin_end(8)
        labels_box.set_margin_top(4)
        labels_box.set_margin_bottom(4)

        self._left_pane_label = Gtk.Label(label="← commit")
        self._left_pane_label.set_halign(Gtk.Align.START)
        self._left_pane_label.set_hexpand(True)
        self._left_pane_label.add_css_class("diff-left-label")
        labels_box.append(self._left_pane_label)

        self._right_pane_label = Gtk.Label(label="→ current")
        self._right_pane_label.set_halign(Gtk.Align.END)
        self._right_pane_label.set_hexpand(True)
        self._right_pane_label.add_css_class("diff-right-label")
        labels_box.append(self._right_pane_label)

        editor_box.append(labels_box)

        # Paned for side-by-side views
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.paned.set_vexpand(True)
        self.paned.set_hexpand(True)
        self.paned.set_wide_handle(True)
        self.paned.set_shrink_start_child(False)
        self.paned.set_shrink_end_child(False)

        # Left side (commit version)
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._left_scroll = Gtk.ScrolledWindow()
        self._left_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.EXTERNAL)
        self._left_scroll.set_vexpand(True)

        self.left_buffer = GtkSource.Buffer()
        from editor.editor_view import ZenSourceView

        self.left_view = ZenSourceView(buffer=self.left_buffer)
        self._configure_view(self.left_view)
        self.left_view.set_editable(False)
        self._left_scroll.set_child(self.left_view)
        left_box.append(self._left_scroll)

        # Add revert gutter to left view (for deletions)
        self._left_revert_renderer = RevertGutterRenderer(self)
        left_gutter = self.left_view.get_gutter(Gtk.TextWindowType.LEFT)
        left_gutter.insert(self._left_revert_renderer, 0)

        # Add click gesture to left gutter for revert
        left_click = Gtk.GestureClick()
        left_click.set_button(1)  # Left mouse button
        left_click.connect("released", self._on_left_gutter_click)
        left_gutter.add_controller(left_click)

        self.paned.set_start_child(left_box)

        # Right side (current version)
        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._right_scroll = Gtk.ScrolledWindow()
        self._right_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.EXTERNAL)
        self._right_scroll.set_vexpand(True)

        self.right_buffer = GtkSource.Buffer()
        self.right_view = ZenSourceView(buffer=self.right_buffer)
        self._configure_view(self.right_view)
        self.right_view.set_editable(False)
        self._right_scroll.set_child(self.right_view)

        # Add revert gutter to right view (for additions/changes)
        self._right_revert_renderer = RevertGutterRenderer(self)
        right_gutter = self.right_view.get_gutter(Gtk.TextWindowType.LEFT)
        right_gutter.insert(self._right_revert_renderer, 0)

        # Add click gesture to right gutter for revert
        right_click = Gtk.GestureClick()
        right_click.set_button(1)  # Left mouse button
        right_click.connect("released", self._on_right_gutter_click)
        right_gutter.add_controller(right_click)

        # Double-click on right view to navigate to that line in the editor
        right_dblclick = Gtk.GestureClick()
        right_dblclick.set_button(1)
        right_dblclick.connect("pressed", self._on_view_double_click)
        self.right_view.add_controller(right_dblclick)

        right_box.append(self._right_scroll)
        self.paned.set_end_child(right_box)

        # Wrap paned + minimap in a horizontal box
        content_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        content_box.set_vexpand(True)
        content_box.set_hexpand(True)
        content_box.append(self.paned)

        self._minimap = DiffMinimap(self)
        content_box.append(self._minimap)

        editor_box.append(content_box)
        self.append(editor_box)

        # Sync scrolling (bidirectional)
        right_vadj = self._right_scroll.get_vadjustment()
        right_vadj.connect("value-changed", self._on_right_scroll)
        left_vadj = self._left_scroll.get_vadjustment()
        left_vadj.connect("value-changed", self._on_left_scroll)

        # Create text tags for diff highlighting
        self._setup_diff_tags()

    def _apply_css(self):
        """Apply CSS styling."""
        theme = get_theme()
        font_settings = get_font_settings("editor")
        font_family = font_settings["family"]
        css_provider = Gtk.CssProvider()
        css = f"""
            .diff-header {{
                background-color: {theme.hover_bg};
                padding: 8px;
            }}
            .diff-header > label {{
                color: {theme.fg_color};
                font-family: '{font_family}';
            }}
            .diff-title {{
                font-weight: bold;
                color: white;
            }}
            .diff-commit-info {{
                color: {theme.fg_color};
            }}
            .diff-nav-btn {{
                padding: 4px 8px;
                min-width: 24px;
                border-radius: 4px;
                font-family: '{font_family}';
            }}
            .diff-nav-btn:hover {{
                background-color: alpha(white, 0.1);
            }}
            .diff-nav-btn:disabled {{
                opacity: 0.3;
            }}
            .diff-hint {{
                color: {theme.fg_dim};
                font-size: 11pt;
            }}
            .diff-left-label {{
                color: {_diff_gutter_colors()[1]};
                font-family: '{font_family}';
            }}
            .diff-right-label {{
                color: {_diff_gutter_colors()[0]};
                font-family: '{font_family}';
            }}
        """
        css_provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _create_header(self) -> Gtk.Box:
        """Create the header bar with navigation and info."""
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("diff-header")
        header.set_margin_start(8)
        header.set_margin_end(8)
        header.set_margin_top(4)
        header.set_margin_bottom(4)

        # Close button
        close_btn = ZenButton(icon=Icons.CLOSE, tooltip="Close (Esc)")
        close_btn.set_focusable(False)
        close_btn.connect("clicked", lambda b: self._close())
        header.append(close_btn)

        # Title
        self._title_label = Gtk.Label(label="Diff")
        self._title_label.add_css_class("diff-title")
        header.append(self._title_label)

        # Spacer
        spacer1 = Gtk.Box()
        spacer1.set_hexpand(True)
        header.append(spacer1)

        # Navigation: prev button (older commit)
        self._prev_btn = ZenButton(label="◀", tooltip="Older commit (←)")
        self._prev_btn.add_css_class("diff-nav-btn")
        self._prev_btn.set_focusable(False)
        self._prev_btn.connect("clicked", lambda b: self._navigate_commit(1))
        header.append(self._prev_btn)

        # Commit info label
        self._commit_label = Gtk.Label(label="")
        self._commit_label.add_css_class("diff-commit-info")
        self._commit_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._commit_label.set_max_width_chars(50)
        header.append(self._commit_label)

        # Navigation: next button (newer commit)
        self._next_btn = ZenButton(label=Icons.PLAY, tooltip="Newer commit (→)")
        self._next_btn.add_css_class("diff-nav-btn")
        self._next_btn.set_focusable(False)
        self._next_btn.connect("clicked", lambda b: self._navigate_commit(-1))
        header.append(self._next_btn)

        # Spacer
        spacer2 = Gtk.Box()
        spacer2.set_hexpand(True)
        header.append(spacer2)

        # Keyboard hint
        hint = Gtk.Label(label="← → navigate commits | ⌘F search | Esc close")
        hint.add_css_class("diff-hint")
        header.append(hint)

        return header

    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Handle key press events."""
        meta = Gdk.ModifierType.META_MASK
        ctrl = Gdk.ModifierType.CONTROL_MASK

        # Cmd+F / Ctrl+F opens find bar
        if keyval == Gdk.KEY_f and (state & (meta | ctrl)):
            self.show_find_bar()
            return True

        if keyval == Gdk.KEY_Escape:
            # If find bar is open, close it first
            if self._find_bar and self._find_bar.get_search_mode():
                self._find_bar.set_search_mode(False)
                self.grab_focus()
                return True
            self._close()
            return True
        elif keyval == Gdk.KEY_Left:
            self._navigate_commit(1)  # older
            return True
        elif keyval == Gdk.KEY_Right:
            self._navigate_commit(-1)  # newer
            return True
        return False

    # -- Find bar --

    def _create_find_bar(self):
        """Create the find bar for searching in diff view."""
        self._find_bar = Gtk.SearchBar()
        self._find_bar.set_show_close_button(True)

        find_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        self._find_entry = ZenSearchEntry(placeholder="Find in diff...")
        self._find_entry.set_hexpand(True)
        self._find_entry.connect("search-changed", self._on_diff_find_changed)
        self._find_entry.connect("activate", self._on_diff_find_next)

        find_key_ctrl = Gtk.EventControllerKey()
        find_key_ctrl.connect("key-pressed", self._on_find_entry_key)
        self._find_entry.add_controller(find_key_ctrl)
        find_row.append(self._find_entry)

        self._find_count_label = Gtk.Label(label="")
        self._find_count_label.add_css_class("dim-label")
        find_row.append(self._find_count_label)

        prev_btn = ZenButton(icon=Icons.ARROW_UP, tooltip="Previous (Shift+Enter)")
        prev_btn.connect("clicked", lambda b: self._on_diff_find_prev())
        find_row.append(prev_btn)

        next_btn = ZenButton(icon=Icons.ARROW_DOWN, tooltip="Next (Enter)")
        next_btn.connect("clicked", lambda b: self._on_diff_find_next())
        find_row.append(next_btn)

        self._find_bar.set_child(find_row)
        self._find_bar.connect_entry(self._find_entry)
        self.append(self._find_bar)

        # Move find bar after header (index 1)
        self.reorder_child_after(self._find_bar, self._header)

        self._apply_find_bar_font()

    def _apply_find_bar_font(self):
        """Apply editor font to find entry."""
        font_settings = get_font_settings("editor")
        font_family = font_settings["family"]
        font_size = font_settings.get("size", 13)

        provider = Gtk.CssProvider()
        css = f"""
            searchentry {{
                font-family: '{font_family}';
                font-size: {font_size}pt;
            }}
        """
        provider.load_from_data(css.encode())
        self._find_entry.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)

    def show_find_bar(self):
        """Show the find bar and focus the entry."""
        self._find_bar.set_search_mode(True)
        self._find_entry.grab_focus()
        pos = len(self._find_entry.get_text())
        if pos > 0:
            self._find_entry.select_region(0, pos)

    def _on_find_entry_key(self, controller, keyval, keycode, state):
        """Handle key press in find entry."""
        if keyval == Gdk.KEY_Escape:
            self._find_bar.set_search_mode(False)
            self.grab_focus()
            return True

        # Shift+Enter = find previous
        shift = Gdk.ModifierType.SHIFT_MASK
        if keyval == Gdk.KEY_Return and (state & shift):
            self._on_diff_find_prev()
            return True

        # Cmd+Backspace clears entry
        meta = Gdk.ModifierType.META_MASK
        if keyval == Gdk.KEY_BackSpace and (state & meta):
            self._find_entry.set_text("")
            return True

        return False

    def _ensure_diff_search_contexts(self, text: str):
        """Create or update search contexts for both diff buffers."""
        if self._search_settings is None:
            self._search_settings = GtkSource.SearchSettings()
            self._search_settings.set_case_sensitive(False)
            self._search_settings.set_wrap_around(True)

        self._search_settings.set_search_text(text if text else None)

        if self._left_search_context is None or self._left_search_context.get_buffer() != self.left_buffer:
            self._left_search_context = GtkSource.SearchContext(buffer=self.left_buffer, settings=self._search_settings)
        if self._right_search_context is None or self._right_search_context.get_buffer() != self.right_buffer:
            self._right_search_context = GtkSource.SearchContext(buffer=self.right_buffer, settings=self._search_settings)

    def _on_diff_find_changed(self, entry):
        """Handle find text change."""
        text = entry.get_text()
        self._ensure_diff_search_contexts(text)
        if text:
            self._diff_find_text(text, forward=True)
        else:
            self._find_count_label.set_label("")

    def _on_diff_find_next(self, *args):
        """Find next occurrence."""
        text = self._find_entry.get_text()
        if text:
            self._diff_find_text(text, forward=True)

    def _on_diff_find_prev(self, *args):
        """Find previous occurrence."""
        text = self._find_entry.get_text()
        if text:
            self._diff_find_text(text, forward=False)

    def _diff_find_text(self, text: str, forward: bool = True):
        """Find text in the active diff side (right by default)."""
        self._ensure_diff_search_contexts(text)

        # Search in the right (current) buffer
        ctx = self._right_search_context
        buf = self.right_buffer
        view = self.right_view

        cursor = buf.get_insert()
        cursor_iter = buf.get_iter_at_mark(cursor)

        if forward:
            if buf.get_has_selection():
                _, cursor_iter = buf.get_selection_bounds()
            found, start, end, wrapped = ctx.forward(cursor_iter)
        else:
            if buf.get_has_selection():
                cursor_iter, _ = buf.get_selection_bounds()
            found, start, end, wrapped = ctx.backward(cursor_iter)

        if found:
            buf.select_range(start, end)
            view.scroll_to_iter(start, 0.2, False, 0.0, 0.5)

        GLib.timeout_add(50, lambda: self._update_diff_find_count() or False)

    def _update_diff_find_count(self):
        """Update the match count label with combined counts from both sides."""
        if not self._right_search_context:
            self._find_count_label.set_label("")
            return

        left_count = max(0, self._left_search_context.get_occurrences_count()) if self._left_search_context else 0
        right_count = max(0, self._right_search_context.get_occurrences_count())

        if left_count < 0 or right_count < 0:
            self._find_count_label.set_label("...")
            return

        total = left_count + right_count
        if total == 0:
            self._find_count_label.set_label("No results")
            return

        # Show position in right side
        ctx = self._right_search_context
        buf = self.right_buffer
        pos_str = ""
        if buf.get_has_selection():
            sel_start, sel_end = buf.get_selection_bounds()
            pos = ctx.get_occurrence_position(sel_start, sel_end)
            if pos > 0:
                pos_str = f"{pos} of "

        if left_count > 0 and right_count > 0:
            self._find_count_label.set_label(f"{pos_str}{right_count}  (left: {left_count})")
        elif right_count > 0:
            self._find_count_label.set_label(f"{pos_str}{right_count} results")
        else:
            self._find_count_label.set_label(f"left: {left_count}")

    def _on_diff_clicked(self, gesture, n_press, x, y):
        """Handle click anywhere on diff view - grab focus for keyboard events."""
        self.grab_focus()

    def _on_view_clicked(self, gesture, n_press, x, y):
        """Handle click on diff view - notify parent to focus editor."""
        if self._on_click_callback:
            self._on_click_callback()

    def _on_view_double_click(self, gesture, n_press, x, y):
        """Handle double-click on right view - close diff and navigate to that line."""
        if n_press != 2 or not self._on_navigate_callback:
            return
        # Get the line number at the click position
        buf_x, buf_y = self.right_view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
        found, over_iter = self.right_view.get_iter_at_location(buf_x, buf_y)
        if not found:
            return
        line_number = over_iter.get_line() + 1  # 1-based
        self._on_navigate_callback(line_number)

    def update_font_settings(self):
        """Update font on both diff views to match current editor font settings."""
        for view in (self.left_view, self.right_view):
            if view is None:
                continue
            self._apply_font_to_view(view)

    def _apply_font_to_view(self, view):
        """Apply current editor font settings to a source view."""
        font_settings = get_font_settings("editor")
        font_family = font_settings["family"]
        font_size = font_settings.get("size", 13)

        # Remove old provider if present
        is_left = view is self.left_view
        attr = "_left_font_provider" if is_left else "_right_font_provider"
        old_provider = getattr(self, attr, None)
        if old_provider:
            view.get_style_context().remove_provider(old_provider)

        css_provider = Gtk.CssProvider()
        css = f"""
            textview, textview text {{
                font-family: '{font_family}';
                font-size: {font_size}pt;
            }}
        """
        css_provider.load_from_data(css.encode())
        view.get_style_context().add_provider(css_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        setattr(self, attr, css_provider)

    def _configure_view(self, view):
        """Configure a source view for diff display."""
        view.set_show_line_numbers(True)
        view.set_show_line_marks(True)
        view.set_monospace(True)
        view.set_highlight_current_line(False)

        # Disable built-in text drag gesture to prevent macOS crash
        _disable_text_view_drag(view)

        # Add key handler to each view
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        view.add_controller(key_controller)

        # Add click handler to focus editor when diff view is clicked
        click_controller = Gtk.GestureClick()
        click_controller.connect("pressed", self._on_view_clicked)
        view.add_controller(click_controller)

        # Apply the same style scheme as the main editor
        from editor.editor_view import _generate_style_scheme

        theme = get_theme()
        scheme_id = _generate_style_scheme(theme)
        scheme_manager = GtkSource.StyleSchemeManager.get_default()
        scheme = scheme_manager.get_scheme(scheme_id)
        if scheme:
            view.get_buffer().set_style_scheme(scheme)

        # Apply indent guide color
        from constants import INDENT_GUIDE_ALPHA

        if hasattr(view, "set_guide_color_hex"):
            view.set_guide_color_hex(theme.indent_guide, alpha=INDENT_GUIDE_ALPHA)

        # Apply same line spacing as editor
        line_spacing = get_setting("editor.line_spacing", 4)
        above = line_spacing // 2
        below = line_spacing - above
        view.set_pixels_above_lines(above)
        view.set_pixels_below_lines(below)

        # SpaceDrawer: match editor whitespace rendering
        space_drawer = view.get_space_drawer()
        show_ws = get_setting("editor.show_whitespace", False)
        if show_ws:
            space_drawer.set_types_for_locations(
                GtkSource.SpaceLocationFlags.LEADING,
                GtkSource.SpaceTypeFlags.SPACE | GtkSource.SpaceTypeFlags.TAB,
            )
            space_drawer.set_types_for_locations(
                GtkSource.SpaceLocationFlags.TRAILING,
                GtkSource.SpaceTypeFlags.NONE,
            )
            space_drawer.set_types_for_locations(
                GtkSource.SpaceLocationFlags.INSIDE_TEXT,
                GtkSource.SpaceTypeFlags.NONE,
            )
            space_drawer.set_enable_matrix(True)
        else:
            space_drawer.set_enable_matrix(False)

        # Apply same font as editor
        self._apply_font_to_view(view)

    def _setup_diff_tags(self):
        """Register GtkSource mark categories for diff line backgrounds.

        Uses GtkSource.MarkAttributes with set_background() — the idiomatic way
        to paint full-line backgrounds in GtkSourceView, unaffected by the style
        scheme's text background.
        """
        theme = get_theme()
        bg = theme.editor_bg

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

    def _on_right_scroll(self, adj):
        """Sync left scroll to match right scroll."""
        if self._syncing_scroll:
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
        if self._syncing_scroll:
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

    def _update_minimap(self):
        """Update minimap with current diff regions."""
        if not self._minimap:
            return
        total_lines = max(self.right_buffer.get_line_count(), 1)
        self._minimap.update(total_lines, self._diff_regions)
        # Schedule viewport update after layout settles
        GLib.idle_add(self._update_minimap_viewport)
        return False

    def _scroll_to_line(self, line):
        """Scroll the right view to center on a specific line (instant, no animation)."""
        line = max(0, min(line, self.right_buffer.get_line_count() - 1))
        adj = self._right_scroll.get_vadjustment()
        upper = adj.get_upper()
        page = adj.get_page_size()
        if upper <= page:
            return
        frac = line / max(self.right_buffer.get_line_count() - 1, 1)
        target = frac * (upper - page)
        adj.set_value(max(0.0, min(target, upper - page)))

    def _update_paned_position(self):
        """Set the paned position to 50% of available width."""
        width = self.paned.get_allocated_width()
        if width > 0:
            self.paned.set_position(width // 2)
        return False

    def show_diff(self, file_path: str, current_content: str = None):
        """Show diff for a file with commit history."""
        if not file_path or not os.path.exists(file_path):
            return

        self._current_file_path = file_path

        # Get current content
        if current_content is None:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    current_content = f.read()
            except Exception:
                current_content = ""
        self._current_content = current_content

        # Show loading state (don't clear buffers yet to avoid empty pane flash)
        self._title_label.set_text(f"Diff: {os.path.basename(file_path)}")
        self._commit_label.set_text("Loading...")
        self._prev_btn.set_sensitive(False)
        self._next_btn.set_sensitive(False)

        # Load git data in background
        def load_git_data():
            commits = self._get_file_commits(file_path)
            if not commits:
                main_thread_call(self._on_load_complete, None, None, "no_commits")
                return

            commit_content = self._get_commit_content(file_path, commits[0]["sha"])
            if commit_content is None:
                main_thread_call(self._on_load_complete, None, None, "no_content")
                return

            main_thread_call(self._on_load_complete, commits, commit_content, None)

        thread = threading.Thread(target=load_git_data, daemon=True)
        thread.start()

    def _on_load_complete(self, commits, commit_content, error):
        """Called when git data loading is complete."""
        if error:
            if error == "no_commits":
                self._commit_label.set_text("No commit history")
                self._show_main_branch_diff()
            else:
                self._commit_label.set_text("Error loading commits")
            return

        self._commits = commits
        self._current_commit_index = 0
        self._commit_content = commit_content

        self._update_ui()
        self._apply_diff(commit_content, self._current_content)

        # Set language for syntax highlighting
        self._set_language(self._current_file_path)

        # Schedule paned position update
        GLib.idle_add(self._update_paned_position)

    def _show_main_branch_diff(self):
        """Fall back to showing diff vs main branch."""
        main_content, error = self._get_main_branch_content(self._current_file_path)

        if error:
            self._left_pane_label.set_text(f"← main ({error})")
        else:
            self._left_pane_label.set_text("← main")
        self._right_pane_label.set_text("→ current")

        self._commit_content = main_content
        self._apply_diff(main_content, self._current_content)
        self._set_language(self._current_file_path)
        GLib.idle_add(self._update_paned_position)

    def _update_ui(self):
        """Update UI elements based on current state."""
        if not self._commits:
            return

        commit = self._commits[self._current_commit_index]
        sha_short = commit["sha"][:7]
        date = commit.get("date", "")
        message = commit.get("message", "")[:40]

        self._commit_label.set_text(f"{sha_short} - {date} - {message}")

        # Update pane labels
        self._left_pane_label.set_text(f"← {sha_short}")

        # Get current branch name
        git_root = self._find_git_root(self._current_file_path)
        if git_root:
            branch = self._get_current_branch(git_root)
            self._right_pane_label.set_text(f"→ {branch}")
        else:
            self._right_pane_label.set_text("→ current")

        # Update navigation buttons
        can_go_older = self._current_commit_index < len(self._commits) - 1
        can_go_newer = self._current_commit_index > 0
        self._prev_btn.set_sensitive(can_go_older)
        self._next_btn.set_sensitive(can_go_newer)

    def _navigate_commit(self, direction: int):
        """Navigate to prev/next commit. direction: 1=older, -1=newer."""
        if not self._commits:
            return

        new_index = self._current_commit_index + direction
        if new_index < 0 or new_index >= len(self._commits):
            return

        self._current_commit_index = new_index
        commit_content = self._get_commit_content(self._current_file_path, self._commits[self._current_commit_index]["sha"])
        if commit_content is None:
            return

        self._commit_content = commit_content
        self._update_ui()
        self._apply_diff(commit_content, self._current_content)

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

        # Refresh the diff view
        self._apply_diff(self._commit_content, self._current_content)

    # --- Git operations (delegated to GitManager) ---

    def _get_file_commits(self, file_path: str, limit: int = 100) -> list:
        """Get list of commits that touched this file."""
        git = get_git_manager()
        commits = git.get_file_commits(file_path, limit=limit)
        # Remap keys: GitManager returns {sha, message, author, date}
        return [{"sha": c["sha"], "date": c["date"], "message": c["message"]} for c in commits]

    def _get_commit_content(self, file_path: str, commit_sha: str) -> str | None:
        """Get file content at a specific commit."""
        git = get_git_manager()
        repo_root = git.get_repo_root(file_path)
        if not repo_root:
            return None
        rel_path = os.path.relpath(file_path, repo_root)
        return git.get_file_at_ref(repo_root, rel_path, commit_sha)

    def _get_main_branch_content(self, file_path: str) -> tuple[str, str | None]:
        """Get file content from main branch."""
        git = get_git_manager()
        repo_root = git.get_repo_root(file_path)
        if not repo_root:
            return "", "Not a git repository"
        rel_path = os.path.relpath(file_path, repo_root)
        content = git.get_file_at_main_branch(repo_root, rel_path)
        if content is not None:
            return content, None
        return "", "File not on main/master"

    def _find_git_root(self, file_path: str) -> str | None:
        """Find git repository root."""
        return get_git_manager().get_repo_root(file_path)

    def _get_current_branch(self, git_root: str) -> str:
        """Get current branch name."""
        return get_git_manager().get_current_branch(git_root)

    def _set_language(self, file_path: str):
        """Set syntax highlighting language."""
        from editor.langs.language_detect import detect_language

        language = detect_language(file_path)
        if language:
            self.left_buffer.set_language(language)
            self.right_buffer.set_language(language)

    def _close(self):
        """Close the diff view."""
        win = self.get_root()
        if isinstance(win, Gtk.Window) and not isinstance(win, Gtk.ApplicationWindow):
            win.close()
        else:
            self.set_visible(False)
            if self._on_close_callback:
                self._on_close_callback()
