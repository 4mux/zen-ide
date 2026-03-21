"""Widget inspector — browser DevTools-like inspect mode for Zen IDE.

Attaches motion + click controllers to the main window. When inspect mode
is active, hovering highlights the widget under the cursor and clicking
opens a popup with full widget introspection info (type, CSS classes,
allocation, hierarchy, and theme-color hints).
"""

from gi.repository import Gdk, Gtk

from themes import get_theme


class WidgetInspector:
    """Manages the inspect mode lifecycle."""

    def __init__(self, window: Gtk.ApplicationWindow):
        self._window = window
        self._active = False
        self._highlighted_widget: Gtk.Widget | None = None
        self._inspect_popup = None
        self._motion = None
        self._click = None

        # CSS provider for the highlight outline
        self._css_provider = Gtk.CssProvider()

    @property
    def active(self) -> bool:
        return self._active

    def toggle(self):
        if self._active:
            self.deactivate()
        else:
            self.activate()

    def activate(self):
        if self._active:
            return
        self._active = True

        self._update_highlight_css()

        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            self._css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 100,
        )

        # Create fresh controllers each time (GTK4 doesn't allow re-adding removed controllers)
        self._motion = Gtk.EventControllerMotion()
        self._motion.connect("motion", self._on_motion)
        self._motion.connect("leave", self._on_leave)
        self._motion.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

        self._click = Gtk.GestureClick()
        self._click.connect("pressed", self._on_click)
        self._click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

        self._window.add_controller(self._motion)
        self._window.add_controller(self._click)

        # Show status indicator
        if hasattr(self._window, "status_bar_widget"):
            self._window.status_bar_widget.set_inspect_mode(True)

    def deactivate(self):
        if not self._active:
            return
        self._active = False

        self._clear_highlight()

        if self._inspect_popup and self._inspect_popup.get_visible():
            self._inspect_popup.close()
            self._inspect_popup = None

        if self._motion:
            try:
                self._window.remove_controller(self._motion)
            except Exception:
                pass
            self._motion = None
        if self._click:
            try:
                self._window.remove_controller(self._click)
            except Exception:
                pass
            self._click = None

        Gtk.StyleContext.remove_provider_for_display(
            Gdk.Display.get_default(),
            self._css_provider,
        )

        if hasattr(self._window, "status_bar_widget"):
            self._window.status_bar_widget.set_inspect_mode(False)

    # -- Event handlers -------------------------------------------------------

    def _on_motion(self, _controller, x: float, y: float):
        widget = self._window.pick(x, y, Gtk.PickFlags.DEFAULT)
        if widget is None or widget is self._window:
            self._clear_highlight()
            return
        if widget is self._highlighted_widget:
            return
        self._clear_highlight()
        self._highlighted_widget = widget
        widget.add_css_class("zen-inspect-highlight")

    def _on_leave(self, _controller):
        self._clear_highlight()

    def _on_click(self, gesture, _n_press, x: float, y: float):
        widget = self._window.pick(x, y, Gtk.PickFlags.DEFAULT)
        if widget is None or widget is self._window:
            return

        # Stop propagation so the click doesn't activate the widget
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)

        info = self._collect_widget_info(widget)

        # Close existing popup
        if self._inspect_popup and self._inspect_popup.get_visible():
            self._inspect_popup.close()

        from debug.inspect_popup import InspectPopup

        self._inspect_popup = InspectPopup(self._window, info)
        self._inspect_popup.present()

    # -- Highlight ------------------------------------------------------------

    def _clear_highlight(self):
        if self._highlighted_widget is not None:
            try:
                self._highlighted_widget.remove_css_class("zen-inspect-highlight")
            except Exception:
                pass
            self._highlighted_widget = None

    def _update_highlight_css(self):
        theme = get_theme()
        css = f"""
            .zen-inspect-highlight {{
                outline: 2px solid {theme.accent_color};
                outline-offset: -1px;
            }}
        """
        self._css_provider.load_from_string(css)

    # -- Widget introspection -------------------------------------------------

    def _collect_widget_info(self, widget: Gtk.Widget) -> dict:
        """Collect detailed information about a widget for the inspector popup."""
        info: dict = {}

        # Type info
        widget_type = type(widget)
        info["type_name"] = widget_type.__name__
        info["module"] = widget_type.__module__ or ""
        info["full_type"] = f"{info['module']}.{info['type_name']}" if info["module"] else info["type_name"]

        # GTK CSS element name (e.g. "button", "label", "box")
        info["css_name"] = widget.get_css_name() if hasattr(widget, "get_css_name") else ""

        # Widget name (set via set_name())
        info["widget_name"] = widget.get_name() or ""

        # CSS classes
        info["css_classes"] = list(widget.get_css_classes()) if hasattr(widget, "get_css_classes") else []

        # Allocation (position & size)
        alloc = widget.get_allocation()
        info["allocation"] = {
            "x": alloc.x,
            "y": alloc.y,
            "width": alloc.width,
            "height": alloc.height,
        }

        # Actual rendered size
        info["size"] = {
            "width": widget.get_width(),
            "height": widget.get_height(),
        }

        # Visibility / sensitivity
        info["visible"] = widget.get_visible()
        info["sensitive"] = widget.get_sensitive()
        info["can_focus"] = widget.get_can_focus()
        info["has_focus"] = widget.has_focus()
        info["focusable"] = widget.get_focusable()

        # Layout properties
        info["halign"] = widget.get_halign().value_nick
        info["valign"] = widget.get_valign().value_nick
        info["hexpand"] = widget.get_hexpand()
        info["vexpand"] = widget.get_vexpand()

        # Margin
        info["margin"] = {
            "top": widget.get_margin_top(),
            "bottom": widget.get_margin_bottom(),
            "start": widget.get_margin_start(),
            "end": widget.get_margin_end(),
        }

        # Opacity
        info["opacity"] = widget.get_opacity()

        # Widget hierarchy (walk up to root)
        hierarchy = []
        current = widget
        while current is not None:
            cls_name = type(current).__name__
            css_cls = list(current.get_css_classes()) if hasattr(current, "get_css_classes") else []
            css_cls_str = " ".join(f".{c}" for c in css_cls) if css_cls else ""
            entry = cls_name
            if css_cls_str:
                entry += f" ({css_cls_str})"
            hierarchy.append(entry)
            current = current.get_parent()
        info["hierarchy"] = hierarchy

        # Theme color hints — attempt to match CSS classes to known theme properties
        info["theme_hints"] = self._guess_theme_colors(widget)

        # Label text (if Gtk.Label)
        if isinstance(widget, Gtk.Label):
            info["label_text"] = widget.get_label() or ""

        # Tooltip
        info["tooltip"] = widget.get_tooltip_text() or ""

        return info

    def _guess_theme_colors(self, widget: Gtk.Widget) -> list[tuple[str, str]]:
        """Try to map CSS classes to theme property names."""
        theme = get_theme()
        hints = []

        css_classes = set(widget.get_css_classes()) if hasattr(widget, "get_css_classes") else set()

        class_to_theme = {
            "sidebar": ("panel_bg", theme.panel_bg),
            "editor": ("editor_bg", getattr(theme, "editor_bg", theme.main_bg)),
            "nvim-popup-window": ("main_bg", theme.main_bg),
            "nvim-popup-frame": ("panel_bg", theme.panel_bg),
            "nvim-popup-title": ("accent_color", theme.accent_color),
            "nvim-popup-hint": ("fg_dim", theme.fg_dim),
            "nvim-popup-message": ("fg_color", theme.fg_color),
            "nvim-status-bar": ("status_bar_bg", getattr(theme, "status_bar_bg", theme.panel_bg)),
        }

        for css_class, (prop_name, color_value) in class_to_theme.items():
            if css_class in css_classes:
                hints.append((prop_name, color_value))

        # Always show the general theme colors as reference
        if not hints:
            hints.append(("main_bg", theme.main_bg))
            hints.append(("fg_color", theme.fg_color))
            hints.append(("accent_color", theme.accent_color))

        return hints
