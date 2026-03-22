"""
Vim command router for Zen IDE.

Routes VimIMContext signals (write, edit, execute-command) to Zen IDE actions
such as saving files, closing tabs, opening files, and navigating tabs.
"""

from typing import Callable, Optional


class VimCommandRouter:
    """Routes vim ex-commands to Zen IDE actions."""

    def __init__(
        self,
        on_save: Callable[[], bool] | None = None,
        on_save_as: Callable[[str], bool] | None = None,
        on_close: Callable[[], None] | None = None,
        on_force_close: Callable[[], None] | None = None,
        on_open: Callable[[str], None] | None = None,
        on_new_tab: Callable[[], None] | None = None,
        on_next_tab: Callable[[], None] | None = None,
        on_prev_tab: Callable[[], None] | None = None,
        on_clear_search: Callable[[], None] | None = None,
    ):
        self._on_save = on_save
        self._on_save_as = on_save_as
        self._on_close = on_close
        self._on_force_close = on_force_close
        self._on_open = on_open
        self._on_new_tab = on_new_tab
        self._on_next_tab = on_next_tab
        self._on_prev_tab = on_prev_tab
        self._on_clear_search = on_clear_search

    def handle_write(self, _vim_ctx, view, path: Optional[str]) -> bool:
        """Handle :w signal from VimIMContext."""
        if path and self._on_save_as:
            return self._on_save_as(path)
        if self._on_save:
            return self._on_save()
        return False

    def handle_edit(self, _vim_ctx, view, path: Optional[str]) -> None:
        """Handle :e signal from VimIMContext."""
        if path and self._on_open:
            self._on_open(path)

    def handle_execute_command(self, _vim_ctx, command: str) -> bool:
        """Handle execute-command signal for commands VimIMContext doesn't handle natively."""
        cmd = command.strip()

        if cmd in (":q", ":quit"):
            if self._on_close:
                self._on_close()
            return True

        if cmd in (":q!", ":quit!"):
            if self._on_force_close:
                self._on_force_close()
            return True

        if cmd in (":wq", ":x"):
            if self._on_save:
                self._on_save()
            if self._on_close:
                self._on_close()
            return True

        if cmd in (":wq!", ":x!"):
            if self._on_save:
                self._on_save()
            if self._on_force_close:
                self._on_force_close()
            return True

        if cmd == ":tabnew":
            if self._on_new_tab:
                self._on_new_tab()
            return True

        if cmd in (":tabnext", ":tabn"):
            if self._on_next_tab:
                self._on_next_tab()
            return True

        if cmd in (":tabprev", ":tabp", ":tabprevious"):
            if self._on_prev_tab:
                self._on_prev_tab()
            return True

        if cmd in (":noh", ":nohlsearch"):
            if self._on_clear_search:
                self._on_clear_search()
            return True

        if cmd.startswith(":e ") or cmd.startswith(":edit "):
            parts = cmd.split(None, 1)
            if len(parts) == 2 and self._on_open:
                self._on_open(parts[1])
            return True

        if cmd.startswith(":tabnew "):
            parts = cmd.split(None, 1)
            if len(parts) == 2 and self._on_open:
                self._on_open(parts[1])
            return True

        return False
