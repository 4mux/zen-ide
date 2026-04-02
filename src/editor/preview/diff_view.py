"""
Diff View for Zen IDE.
Shows side-by-side diff of file changes with commit history navigation.
Inline revert buttons appear at the start of each diff region.
"""

from gi.repository import Gdk, Gtk, GtkSource, Pango

# Re-export public names so existing `from editor.preview.diff_view import X` still works
from editor.preview.diff_gutter_mixin import DiffGutterMixin, DiffMinimap, RevertGutterRenderer  # noqa: F401
from editor.preview.diff_navigation_mixin import DiffNavigationMixin
from editor.preview.diff_parser_mixin import (  # noqa: F401
    DIFF_ADD_RGBA,
    DIFF_CHANGE_RGBA,
    DIFF_DEL_RGBA,
    DIFF_WHITESPACE_RGBA,
    DiffParserMixin,
    _blend_diff_color,
    _diff_gutter_colors,
)
from fonts import get_font_settings
from icons import IconsManager
from shared.focus_border_mixin import FocusBorderMixin
from shared.focus_manager import get_focus_manager
from shared.ui import ZenButton
from themes import ThemeAwareMixin, get_theme


class DiffView(DiffParserMixin, DiffGutterMixin, DiffNavigationMixin, ThemeAwareMixin, FocusBorderMixin, Gtk.Box):
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
        focus_mgr = get_focus_manager()
        focus_mgr.register(
            self.COMPONENT_ID,
            on_focus_in=lambda: self._set_focused(True),
            on_focus_out=lambda: self._set_focused(False),
        )

        focus_ctrl = Gtk.EventControllerFocus()
        focus_ctrl.connect("enter", lambda _: get_focus_manager().set_focus(self.COMPONENT_ID))
        focus_ctrl.connect("leave", lambda _: get_focus_manager().clear_focus(self.COMPONENT_ID))
        self.add_controller(focus_ctrl)

        self._syncing_scroll = False
        self._scroll_frozen_value = None
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
        self._subscribe_theme()

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
        self._configure_view(self.left_view, self._left_scroll)
        self.left_view.set_editable(False)
        self.left_view.connect("copy-clipboard", self._on_copy_to_system)
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
        self._configure_view(self.right_view, self._right_scroll)
        self.right_view.set_editable(False)
        self.right_view.connect("copy-clipboard", self._on_copy_to_system)
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
        close_btn = ZenButton(icon=IconsManager.CLOSE, tooltip="Close (Esc)")
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
        self._next_btn = ZenButton(label=IconsManager.PLAY, tooltip="Newer commit (→)")
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

    def _on_copy_to_system(self, textview):
        """Write selected text to the OS clipboard so it survives app exit."""
        buf = textview.get_buffer()
        bounds = buf.get_selection_bounds()
        if bounds:
            from shared.utils import copy_to_system_clipboard

            text = buf.get_text(bounds[0], bounds[1], True)
            copy_to_system_clipboard(text)

    def _on_diff_clicked(self, gesture, n_press, x, y):
        """Handle click anywhere on diff view - grab focus for keyboard events.
        Skip if a child source view already has focus (preserves text selection for copy)."""
        focused = self.get_root().get_focus() if self.get_root() else None
        if focused in (self.left_view, self.right_view):
            return
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

    def _update_paned_position(self):
        """Set the paned position to 50% of available width."""
        width = self.paned.get_allocated_width()
        if width > 0:
            self.paned.set_position(width // 2)
        return False

    def _close(self):
        """Close the diff view."""
        win = self.get_root()
        if isinstance(win, Gtk.Window) and not isinstance(win, Gtk.ApplicationWindow):
            win.close()
        else:
            self.set_visible(False)
            if self._on_close_callback:
                self._on_close_callback()
