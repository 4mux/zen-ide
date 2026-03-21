"""TabButton — base class for all tab buttons (file, terminal, AI)."""

from gi.repository import Gtk

from constants import TAB_BUTTON_HEIGHT
from themes import get_theme, subscribe_theme_change


class TabButton(Gtk.Box):
    """Base class for all tab buttons.

    Provides a consistent tab button with:
    - Label + close button
    - Accent underline when selected
    - Hover effect
    - Theme integration
    """

    def __init__(self, tab_id, title, on_select=None, on_close=None, show_close=True):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        self.tab_id = tab_id
        self._title = title
        self._on_select_cb = on_select
        self._on_close_cb = on_close
        self._show_close = show_close
        self.selected = False
        self.theme = get_theme()

        self._build_ui()
        self._setup_events()
        self._apply_theme()
        subscribe_theme_change(lambda t: self.apply_theme(t))

    def _build_ui(self):
        """Build the tab button UI."""
        self.set_size_request(-1, TAB_BUTTON_HEIGHT)
        self.set_margin_start(4)
        self.set_margin_end(4)
        self.set_margin_top(2)
        self.set_margin_bottom(2)

        self._container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self._content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._content.set_margin_top(4)
        self._content.set_margin_bottom(4)
        self._content.set_margin_start(6)
        self._content.set_margin_end(6)

        self.label = Gtk.Label(label=self._title)
        self.label.set_halign(Gtk.Align.START)
        self._content.append(self.label)

        self._create_close_area()

        self._container.append(self._content)

        self._underline = Gtk.Box()
        self._underline.set_size_request(-1, 2)
        self._underline.set_visible(False)
        self._container.append(self._underline)

        self.append(self._container)
        self.set_cursor_from_name("pointer")

    def _create_close_area(self):
        """Create close button. Override in subclasses for custom behavior."""
        self.close_btn = Gtk.Label(label="\u00d7")
        self.close_btn.set_halign(Gtk.Align.END)
        close_click = Gtk.GestureClick.new()
        close_click.connect("pressed", self._on_close_click)
        self.close_btn.add_controller(close_click)
        self._content.append(self.close_btn)
        if not self._show_close:
            self.close_btn.set_visible(False)

    def _setup_events(self):
        """Setup event handlers. Override to add custom events."""
        if self._on_select_cb:
            click = Gtk.GestureClick.new()
            click.connect("pressed", self._on_click)
            self.add_controller(click)

        motion = Gtk.EventControllerMotion.new()
        motion.connect("enter", self._on_enter)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

    def _on_click(self, gesture, n_press, x, y):
        if self._on_select_cb:
            self._on_select_cb(self.tab_id)

    def _on_close_click(self, gesture, n_press, x, y):
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        if self._on_close_cb:
            self._on_close_cb(self.tab_id)

    def _on_enter(self, controller, x, y):
        if not self.selected:
            self._apply_hover_style()

    def _on_leave(self, controller):
        self._apply_theme()

    def set_selected(self, selected):
        self.selected = selected
        self._underline.set_visible(selected)
        self._apply_theme()

    def set_show_close(self, show):
        self._show_close = show
        self.close_btn.set_visible(show)

    def get_title(self) -> str:
        return self._title

    def set_title(self, title):
        self._title = title
        self.label.set_label(title)

    def _get_font_css(self):
        """Return custom font CSS. Override in subclasses."""
        return ""

    def _get_themed_widgets(self):
        """Return widgets that need theme CSS applied."""
        return [self, self.label, self.close_btn]

    def _apply_theme(self):
        theme = self.theme
        fg = theme.tab_active_fg if self.selected else theme.tab_fg
        bg = theme.tab_active_bg if self.selected else theme.tab_bg
        font_css = self._get_font_css()

        css = f"box {{ background-color: {bg}; }} label {{ color: {fg}; {font_css} }}"
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode())
        for w in self._get_themed_widgets():
            w.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        if self.selected:
            ul_css = f"box {{ background-color: {theme.accent_color}; }}"
            ul_provider = Gtk.CssProvider()
            ul_provider.load_from_data(ul_css.encode())
            self._underline.get_style_context().add_provider(ul_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _apply_hover_style(self):
        theme = self.theme
        font_css = self._get_font_css()
        css = f"box {{ background-color: {theme.hover_bg}; }} label {{ color: {theme.tab_active_fg}; {font_css} }}"
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode())
        for w in [self, self.label]:
            w.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def apply_theme(self, theme):
        self.theme = theme
        self._apply_theme()


class FileTabButton(TabButton):
    """Tab button for editor file tabs with modified indicator."""

    def __init__(self, tab_id, title, on_close=None, show_close=True):
        self._modified = False
        self._font_family = self._load_font_family()
        super().__init__(tab_id, title, on_select=None, on_close=on_close, show_close=show_close)

    def _create_close_area(self):
        """Create close/modified indicator stack."""
        self._indicator_stack = Gtk.Stack()
        self._indicator_stack.set_hhomogeneous(True)
        self._indicator_stack.set_vhomogeneous(True)
        self._indicator_stack.set_transition_type(Gtk.StackTransitionType.NONE)

        self.close_btn = Gtk.Label(label="\u00d7")
        self.close_btn.set_halign(Gtk.Align.END)
        close_click = Gtk.GestureClick.new()
        close_click.connect("pressed", self._on_close_click)
        self.close_btn.add_controller(close_click)
        self._indicator_stack.add_named(self.close_btn, "close")

        self._modified_indicator = Gtk.Label(label="\u25cf")
        self._indicator_stack.add_named(self._modified_indicator, "modified")

        self._indicator_stack.set_visible_child_name("close")
        self._content.append(self._indicator_stack)

        if not self._show_close:
            self._indicator_stack.set_visible(False)

    def set_modified(self, modified):
        """Show/hide the modified indicator."""
        self._modified = modified
        self._indicator_stack.set_visible_child_name("modified" if modified else "close")

    def set_show_close(self, show):
        self._show_close = show
        self._indicator_stack.set_visible(show)

    def _load_font_family(self):
        """Load editor font family from settings."""
        from fonts import get_font_settings

        font_settings = get_font_settings("editor")
        return font_settings["family"]

    def _get_font_css(self):
        return f"font-family: '{self._font_family}';"

    def apply_font_settings(self):
        """Re-read editor font settings and re-apply styling."""
        self._font_family = self._load_font_family()
        self._apply_theme()

    def _get_themed_widgets(self):
        return [self, self.label, self.close_btn, self._modified_indicator]
