"""
Vim mode manager for Zen IDE.

Wraps GtkSource.VimIMContext to provide full vim modal editing.
Handles mode tracking, cursor shape, status bar updates, and
routes commands through VimCommandRouter.
"""

from typing import Callable

import gi

gi.require_version("GtkSource", "5")
gi.require_version("Gtk", "4.0")

from gi.repository import Gtk, GtkSource

from shared.settings import get_setting

from .vim_command_router import VimCommandRouter

# Mode strings derived from VimIMContext command-bar-text
_MODE_MAP = {
    "-- INSERT --": "INSERT",
    "-- REPLACE --": "REPLACE",
    "-- VISUAL --": "VISUAL",
    "-- VISUAL LINE --": "V-LINE",
    "-- VISUAL BLOCK --": "V-BLOCK",
}


class _RelativeLineRenderer(GtkSource.GutterRendererText):
    """Gutter renderer showing relative line numbers (current line is absolute)."""

    def do_query_data(self, lines, line):
        buf = lines.get_buffer()
        cursor_iter = buf.get_iter_at_mark(buf.get_insert())
        cursor_line = cursor_iter.get_line()

        if line == cursor_line:
            self.set_text(str(line + 1), -1)
        else:
            self.set_text(str(abs(line - cursor_line)), -1)


class VimModeManager:
    """Manages vim mode for a single editor tab."""

    def __init__(
        self,
        view: GtkSource.View,
        on_mode_changed: Callable[[str], None] | None = None,
        on_command_changed: Callable[[str, str], None] | None = None,
    ):
        self._view = view
        self._on_mode_changed = on_mode_changed
        self._on_command_changed = on_command_changed
        self._enabled = False
        self._mode = "NORMAL"
        self._vim_ctx: GtkSource.VimIMContext | None = None
        self._router: VimCommandRouter | None = None
        self._router_handler_ids: list[int] = []
        self._rel_renderer: _RelativeLineRenderer | None = None
        self._cursor_notify_id: int = 0

        if get_setting("behavior.is_nvim_emulation_enabled", False):
            self.enable()

    def enable(self) -> None:
        """Activate vim mode on this tab's view."""
        if self._enabled:
            return

        try:
            ctx = GtkSource.VimIMContext()
            ctx.set_client_widget(self._view)

            ctx.connect("notify::command-bar-text", self._on_bar_text_changed)
            ctx.connect("notify::command-text", self._on_command_text_changed)

            self._vim_ctx = ctx
            self._enabled = True
            self._mode = "NORMAL"
            self._view.set_overwrite(True)
            self._install_relative_lines()

            if self._on_mode_changed:
                self._on_mode_changed(self._mode)

        except Exception:
            from shared.crash_log import log_message

            log_message("VimIMContext unavailable — vim mode disabled")
            self._enabled = False

    def disable(self) -> None:
        """Deactivate vim mode on this tab's view."""
        if not self._enabled:
            return

        if self._vim_ctx:
            self._vim_ctx.set_client_widget(None)
            self._vim_ctx = None

        self._enabled = False
        self._mode = ""
        self._view.set_overwrite(False)
        self._uninstall_relative_lines()

        if self._on_mode_changed:
            self._on_mode_changed("")

    def is_enabled(self) -> bool:
        return self._enabled

    def is_insert_mode(self) -> bool:
        return self._mode in ("INSERT", "REPLACE")

    @property
    def mode(self) -> str:
        return self._mode

    def set_router(self, router: VimCommandRouter) -> None:
        """Attach command router and wire VimIMContext signals."""
        if self._vim_ctx and self._router:
            for hid in self._router_handler_ids:
                self._vim_ctx.disconnect(hid)
        self._router_handler_ids = []
        self._router = router
        if self._vim_ctx and router:
            self._router_handler_ids = [
                self._vim_ctx.connect("write", router.handle_write),
                self._vim_ctx.connect("edit", router.handle_edit),
                self._vim_ctx.connect("execute-command", router.handle_execute_command),
            ]

    def filter_keypress(self, event) -> bool:
        """Route a key event through VimIMContext. Returns True if consumed."""
        if not self._enabled or not self._vim_ctx:
            return False
        return self._vim_ctx.filter_keypress(event)

    def _on_bar_text_changed(self, ctx, _pspec) -> None:
        """Track mode from command-bar-text property."""
        bar_text = ctx.get_command_bar_text() or ""
        new_mode = self._parse_mode(bar_text)

        if new_mode != self._mode:
            self._mode = new_mode
            self._update_cursor_shape()
            if self._on_mode_changed:
                self._on_mode_changed(new_mode)

        if self._on_command_changed:
            cmd_text = ctx.get_command_text() or ""
            display = bar_text if bar_text.startswith((":")) else cmd_text
            self._on_command_changed(new_mode, display)

    def _on_command_text_changed(self, ctx, _pspec) -> None:
        """Track partial command text (e.g., d2, 3y)."""
        if self._on_command_changed:
            bar_text = ctx.get_command_bar_text() or ""
            cmd_text = ctx.get_command_text() or ""
            display = bar_text if bar_text.startswith(":") else cmd_text
            self._on_command_changed(self._mode, display)

    def _update_cursor_shape(self) -> None:
        """Switch cursor between block (Normal/Visual) and line (Insert)."""
        if self._mode in ("INSERT",):
            self._view.set_overwrite(False)
            self._uninstall_relative_lines()
        elif self._mode in ("REPLACE",):
            self._view.set_overwrite(True)
        else:
            self._view.set_overwrite(True)
            self._install_relative_lines()

    # --- Relative line numbers ---

    def _install_relative_lines(self) -> None:
        """Replace built-in line numbers with relative renderer."""
        if self._rel_renderer:
            return
        self._view.set_show_line_numbers(False)
        renderer = _RelativeLineRenderer()
        renderer.set_alignment_mode(GtkSource.GutterRendererAlignmentMode.FIRST)
        gutter = self._view.get_gutter(Gtk.TextWindowType.LEFT)
        gutter.insert(renderer, 0)
        self._rel_renderer = renderer

        buf = self._view.get_buffer()
        self._cursor_notify_id = buf.connect("notify::cursor-position", self._on_cursor_moved)

    def _uninstall_relative_lines(self) -> None:
        """Restore built-in absolute line numbers."""
        if not self._rel_renderer:
            return
        if self._cursor_notify_id:
            buf = self._view.get_buffer()
            buf.disconnect(self._cursor_notify_id)
            self._cursor_notify_id = 0
        gutter = self._view.get_gutter(Gtk.TextWindowType.LEFT)
        gutter.remove(self._rel_renderer)
        self._rel_renderer = None
        self._view.set_show_line_numbers(True)

    def _on_cursor_moved(self, _buf, _pspec) -> None:
        """Refresh gutter when cursor moves so relative numbers update."""
        if self._rel_renderer:
            self._rel_renderer.queue_draw()

    @staticmethod
    def _parse_mode(bar_text: str) -> str:
        """Derive vim mode from command-bar-text string."""
        if not bar_text:
            return "NORMAL"
        mapped = _MODE_MAP.get(bar_text)
        if mapped:
            return mapped
        if bar_text.startswith(":"):
            return "COMMAND"
        if bar_text.startswith(("/", "?")):
            return "SEARCH"
        return "NORMAL"
