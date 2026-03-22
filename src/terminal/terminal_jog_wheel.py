"""Jog-wheel overlay scrollbar shared by all terminal views.

The thumb rests at center.  Dragging up/down from center sends continuous
scroll events at a rate proportional to displacement.  Releasing (or leaving
the scrollbar) snaps it back to center.  No position tracking is needed.

Subclasses implement ``_jog_scroll_lines(n)`` to define what "scroll *n*
lines" means for their terminal mode (real adjustment vs SGR mouse events).
"""

from __future__ import annotations

from gi.repository import GLib, Gtk

from constants import TERMINAL_SCROLLBAR_HIDE_DELAY_MS

# ── constants ────────────────────────────────────────────────────────────
JOG_RANGE = 200  # total adjustment range
JOG_CENTER = JOG_RANGE / 2  # rest position
JOG_PAGE = 20  # thumb size (visual only)
JOG_TICK_MS = 50  # interval for continuous scroll while dragging


class JogWheelScrollbarMixin:
    """Mixin that adds a jog-wheel overlay scrollbar to any terminal view.

    Requirements on the host class:
    * ``self.terminal`` — a ``Vte.Terminal``
    * ``self._scrolled_window`` — the ``Gtk.ScrolledWindow`` wrapping the terminal
    * The host must call ``_jog_init_fields()`` **before** ``super().__init__()``
      to set fields used during ``_create_ui`` / ``_configure_terminal``.
    * The host must call ``_jog_create_overlay()`` inside its ``_create_ui``
      to build the overlay + scrollbar widgets.
    """

    # ── fields (call from __init__ before super) ─────────────────────────

    def _jog_init_fields(self) -> None:
        """Initialise jog-wheel state.  Must be called early in ``__init__``."""
        self._vscroll_hide_id: int = 0
        self._vscroll_hovering: bool = False
        self._jog_tick_id: int = 0
        self._vscroll_inhibit: bool = False

    # ── widget creation ──────────────────────────────────────────────────

    def _jog_create_overlay(self, scrolled: Gtk.ScrolledWindow) -> Gtk.Overlay:
        """Wrap *scrolled* in an ``Gtk.Overlay`` with a jog-wheel scrollbar.

        Returns the overlay widget (caller should ``self.append(overlay)``).
        """
        overlay = Gtk.Overlay()
        overlay.set_vexpand(True)
        overlay.set_hexpand(True)

        self._vscroll_adj = Gtk.Adjustment(
            value=JOG_CENTER,
            lower=0,
            upper=JOG_RANGE,
            step_increment=1,
            page_increment=JOG_PAGE,
            page_size=JOG_PAGE,
        )

        self._vscrollbar = Gtk.Scrollbar(
            orientation=Gtk.Orientation.VERTICAL,
            adjustment=self._vscroll_adj,
        )
        self._vscrollbar.add_css_class("terminal-scrollbar")
        self._vscrollbar.set_halign(Gtk.Align.END)
        self._vscrollbar.set_valign(Gtk.Align.FILL)
        self._vscrollbar.set_visible(False)
        self._vscroll_adj.connect("value-changed", self._on_vscroll_changed)

        hover = Gtk.EventControllerMotion.new()
        hover.connect("enter", lambda *_: self._on_vscrollbar_hover(True))
        hover.connect("leave", lambda *_: self._on_vscrollbar_hover(False))
        self._vscrollbar.add_controller(hover)

        overlay.set_child(scrolled)
        overlay.add_overlay(self._vscrollbar)
        return overlay

    # ── scroll controller (installed during _configure_terminal) ─────────

    def _jog_setup_scroll_controller(self) -> None:
        """Install a CAPTURE-phase wheel observer that reveals the scrollbar."""
        flags = Gtk.EventControllerScrollFlags.VERTICAL
        controller = Gtk.EventControllerScroll.new(flags)
        if hasattr(controller, "set_propagation_phase") and hasattr(Gtk, "PropagationPhase"):
            controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        controller.connect("scroll", self._on_wheel_observe)
        self.terminal.add_controller(controller)

    # ── abstract ─────────────────────────────────────────────────────────

    def _jog_scroll_lines(self, lines: int) -> None:
        """Scroll *lines* (positive = down, negative = up).

        Must be implemented by each terminal subclass.
        """
        raise NotImplementedError

    # ── jog-wheel engine ─────────────────────────────────────────────────

    def _on_wheel_observe(self, _controller, _dx, dy) -> bool:
        """Show scrollbar briefly on wheel/touchpad scroll."""
        if float(dy) != 0.0:
            self._show_virtual_scrollbar_temporarily()
        return False  # don't consume — let VTE / ScrolledWindow handle it

    def _on_vscroll_changed(self, adj) -> None:
        """Displacement from center starts/stops continuous scrolling."""
        if self._vscroll_inhibit:
            return
        displacement = float(adj.get_value()) - JOG_CENTER
        if abs(displacement) < 2.0:
            self._stop_jog()
            return
        if not self._jog_tick_id:
            self._jog_tick_id = GLib.timeout_add(JOG_TICK_MS, self._jog_tick)

    def _jog_tick(self) -> bool:
        """Send scroll events proportional to thumb displacement from center."""
        displacement = float(self._vscroll_adj.get_value()) - JOG_CENTER
        if abs(displacement) < 2.0:
            self._jog_tick_id = 0
            return False

        speed = int(displacement / 10)
        if speed == 0:
            speed = 1 if displacement > 0 else -1

        self._jog_scroll_lines(speed)
        return True

    def _stop_jog(self) -> None:
        if self._jog_tick_id:
            GLib.source_remove(self._jog_tick_id)
            self._jog_tick_id = 0

    def _jog_snap_to_center(self) -> None:
        self._stop_jog()
        self._vscroll_inhibit = True
        self._vscroll_adj.set_value(JOG_CENTER)
        self._vscroll_inhibit = False

    # ── visibility helpers ───────────────────────────────────────────────

    def _show_virtual_scrollbar_temporarily(self) -> None:
        self._cancel_virtual_scrollbar_hide()
        self._vscrollbar.set_visible(True)
        if not self._vscroll_hovering:
            self._vscroll_hide_id = GLib.timeout_add(
                TERMINAL_SCROLLBAR_HIDE_DELAY_MS,
                self._hide_virtual_scrollbar,
            )

    def _on_vscrollbar_hover(self, entering: bool) -> None:
        self._vscroll_hovering = entering
        if entering:
            self._cancel_virtual_scrollbar_hide()
            self._vscrollbar.set_visible(True)
        else:
            self._jog_snap_to_center()
            self._vscroll_hide_id = GLib.timeout_add(
                TERMINAL_SCROLLBAR_HIDE_DELAY_MS,
                self._hide_virtual_scrollbar,
            )

    def _cancel_virtual_scrollbar_hide(self) -> None:
        if self._vscroll_hide_id:
            GLib.source_remove(self._vscroll_hide_id)
            self._vscroll_hide_id = 0

    def _hide_virtual_scrollbar(self) -> bool:
        self._vscroll_hide_id = 0
        self._jog_snap_to_center()
        self._vscrollbar.set_visible(False)
        return False

    def _hide_virtual_scrollbar_immediately(self) -> None:
        self._cancel_virtual_scrollbar_hide()
        self._jog_snap_to_center()
        self._vscrollbar.set_visible(False)

    def _vscroll_reset(self) -> None:
        """Snap to center and hide — e.g. when the CLI restarts."""
        self._jog_snap_to_center()
        self._hide_virtual_scrollbar_immediately()
