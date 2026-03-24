"""
AI Terminal View for Zen IDE.

Runs the selected AI CLI (claude or copilot) directly inside a VTE terminal,
giving a native interactive experience without any custom rendering layer.

The active CLI is persisted via the ``ai.provider`` setting
(``"claude_cli"`` | ``"copilot_cli"``).  Clicking the header button opens a
popup to switch between available CLIs; the terminal restarts immediately.
"""

import os
import re
import time

from gi.repository import GLib, Gtk, Vte

from ai.cli.cli_manager import cli_manager
from shared.settings import get_setting, set_setting
from terminal.terminal_jog_wheel import JogWheelScrollbarMixin
from terminal.terminal_view import TerminalView


def _strip_escape_fragments(text: str) -> str:
    """Remove leftover escape sequence fragments from captured VTE input.

    The commit signal can include terminal capability responses (e.g.
    ``[?1;2c``, ``[200~``) whose ESC byte (0x1b) is filtered out but
    whose remaining chars (``[``, digits, ``?``, ``;``, letters) leak
    into the input buffer.
    """
    # CSI-style fragments: "[" optionally followed by "?" then digits/semicolons then a letter
    text = re.sub(r"\[[\?]?[\d;]*[A-Za-z~]", "", text)
    return text.strip()


class AITerminalView(JogWheelScrollbarMixin, TerminalView):
    """VTE-based AI terminal that runs claude or copilot CLI interactively.

    Inherits all VTE machinery (theme, scroll, shortcuts, font) from
    TerminalView.  Only the header and the shell-spawn logic are overridden.
    """

    COMPONENT_ID = "ai_chat"

    def __init__(self, config_dir: str | None = None, get_workspace_folders_callback=None, get_editor_context_callback=None):
        self._current_provider: str | None = None
        self._current_model: str | None = None
        self._input_buf: list[str] = []
        self._title_inferred = False
        self._waiting_for_response = False
        self._commit_ready = False  # ignore commit signals until CLI is ready
        self._in_escape_seq = False  # inside a VTE escape sequence
        self._in_osc_seq = False  # inside an OSC (Operating System Command) sequence
        self._idle_poll_id: int = 0  # GLib timer for PTY idle detection
        self._last_contents_serial: int = 0  # bumped on contents-changed
        self._session_id: str | None = None  # Claude CLI session ID for resume
        self._resume_attempted = False  # True while a --resume spawn is settling
        self._resume_spawn_time: float = 0.0
        self._jog_init_fields()
        self.on_title_inferred = None  # callback(title: str)
        self.on_processing_changed = None  # callback(processing: bool)
        self._get_workspace_folders = get_workspace_folders_callback
        self._get_editor_context = get_editor_context_callback
        super().__init__(config_dir=config_dir)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _create_ui(self) -> None:
        from ai.ai_terminal_header import AITerminalHeader

        hdr = AITerminalHeader(label=self._resolve_label())
        hdr.header_btn.connect("clicked", self._on_header_click)
        hdr.clear_btn.connect("clicked", lambda _b: self.clear())
        hdr.maximize_btn.connect("clicked", self._on_maximize_clicked)

        self.header_btn = hdr.header_btn
        self.maximize_btn = hdr.maximize_btn
        self._header = hdr.box
        self._ai_header = hdr
        self.append(hdr.box)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_kinetic_scrolling(True)
        scrolled.add_css_class("terminal-scrolled")
        self._scrolled_window = scrolled

        self.terminal = Vte.Terminal()
        self._configure_terminal()
        scrolled.set_child(self.terminal)

        overlay = self._jog_create_overlay(scrolled)
        self.append(overlay)

        self._commit_handler_id = self.terminal.connect("commit", self._on_vte_commit)
        self.terminal.connect("contents-changed", self._on_contents_changed)

        self._is_maximized = False
        self.on_maximize = None
        self.on_provider_changed = None

    # ------------------------------------------------------------------
    # Maximize (override TerminalView which hardcodes "terminal")
    # ------------------------------------------------------------------

    def _on_maximize_clicked(self, button):
        """Delegate maximize to parent — state and CSS managed by window_panels."""
        if hasattr(self, "on_maximize") and self.on_maximize:
            self.on_maximize("ai_chat")

    # ------------------------------------------------------------------
    # CLI resolution
    # ------------------------------------------------------------------

    def _resolve_cli_binary(self) -> tuple[str | None, str | None]:
        """Return (binary_path, provider_key) for the configured CLI.

        Uses the per-tab provider first, then the global setting, then
        falls back through registered providers in order.
        """
        preferred = self._current_provider or get_setting("ai.provider", "")
        return cli_manager.resolve(preferred)

    def _resolve_label(self) -> str:
        """Return the CLI display name for the current setting."""
        return cli_manager.resolve_label(get_setting("ai.provider", ""))

    # ------------------------------------------------------------------
    # Onboarding (no CLI detected)
    # ------------------------------------------------------------------

    def _show_onboarding(self) -> bool:
        """Print setup instructions into the VTE when no AI CLI is found."""
        self._show_install_hint(None)
        return GLib.SOURCE_REMOVE

    def _show_install_hint(self, provider: str | None) -> None:
        """Print install instructions for a specific CLI (or both) into the VTE."""
        BOLD = "\033[1m"
        RESET = "\033[0m"
        NL = "\r\n"

        lines = [""]
        if provider:
            p = cli_manager.get(provider)
            name = p.display_name if p else provider
            lines.append(f"  {BOLD}{name} CLI is not installed.{RESET}{NL}")
            lines.extend(cli_manager.install_lines(provider))
        else:
            lines.append(f"  {BOLD}No AI CLI detected.{RESET}")
            lines.append(f"  Install one of the supported CLIs to get started:{NL}")
            lines.extend(cli_manager.install_lines())

        lines.extend(["", "  Then select the CLI from the header menu.", ""])
        self.terminal.feed(NL.join(lines).encode("utf-8"))

    # ------------------------------------------------------------------
    # Shell spawn (override TerminalShellMixin)
    # ------------------------------------------------------------------

    def spawn_shell(self, *, resume: bool = False) -> None:
        """Launch the selected AI CLI binary directly inside VTE.

        If *resume* is True and the provider is Claude CLI, pass
        ``--resume <session_id>`` when a saved session ID is available,
        otherwise fall back to ``--continue`` for the first tab only.
        """
        binary, provider = self._resolve_cli_binary()

        if not binary:
            super().spawn_shell()
            GLib.timeout_add(300, self._show_onboarding)
            return

        self._current_provider = provider
        self._update_header_label()

        from shared.utils import ensure_full_path

        env = ensure_full_path(os.environ.copy())
        env["TERM"] = "xterm-256color"
        env["COLORTERM"] = "truecolor"

        # IDE context: inject editor state as environment variables so
        # AI CLIs can reference the active file, open tabs, and workspace.
        editor_ctx = self._get_editor_context() if self._get_editor_context else {}
        if editor_ctx.get("active_file"):
            env["ZEN_ACTIVE_FILE"] = editor_ctx["active_file"]
        if editor_ctx.get("open_files"):
            env["ZEN_OPEN_FILES"] = ":".join(editor_ctx["open_files"])
        if editor_ctx.get("workspace_folders"):
            env["ZEN_WORKSPACE_FOLDERS"] = ":".join(editor_ctx["workspace_folders"])
        if editor_ctx.get("workspace_file"):
            env["ZEN_WORKSPACE_FILE"] = editor_ctx["workspace_file"]
        if editor_ctx.get("git_branch"):
            env["ZEN_GIT_BRANCH"] = editor_ctx["git_branch"]

        from shared.ide_state_writer import get_state_file_path

        env["ZEN_IDE_STATE_FILE"] = get_state_file_path()

        # Resolve resume / continue flags
        self._resume_attempted = False
        resume_session = None
        continue_last = False
        if resume and provider:
            self.validate_session_id()
            if self._session_id:
                resume_session = self._session_id
                self._resume_attempted = True
                self._resume_spawn_time = time.monotonic()
            else:
                continue_last = True

        # Model override: use per-tab model, then global setting, then CLI default.
        model = self._current_model
        if not model:
            model_setting = get_setting("ai.model", "")
            if isinstance(model_setting, dict):
                model = model_setting.get(provider, "")
            else:
                model = model_setting or ""

        # Extra workspace dirs (multi-workspace support)
        extra_dirs: list[str] = []
        if self._get_workspace_folders:
            cwd_abs = os.path.abspath(self.cwd or os.getcwd())
            for folder in self._get_workspace_folders():
                if os.path.abspath(folder) != cwd_abs:
                    extra_dirs.append(folder)

        # Build argv via the provider
        p = cli_manager.get(provider)
        argv = p.build_argv(
            binary,
            resume_session=resume_session,
            continue_last=continue_last,
            yolo=get_setting("ai.yolo_mode", True),
            model=model or "",
            extra_dirs=extra_dirs,
        )

        # IDE context: append provider-specific system prompt / instructions
        p.append_ide_context(argv, editor_ctx)

        # Reset commit readiness — CLI startup sends terminal capability
        # queries whose responses arrive via the commit signal and would
        # otherwise be captured as user input (the "Op Vte 7600 …" garbage).
        self._commit_ready = False
        self._in_escape_seq = False
        self._in_osc_seq = False
        self._input_buf.clear()

        env_list = [f"{k}={v}" for k, v in env.items()]

        self.terminal.spawn_async(
            Vte.PtyFlags.DEFAULT,
            self.cwd,
            argv,
            env_list,
            GLib.SpawnFlags.DEFAULT,
            None,
            None,
            -1,
            None,
            self._on_spawn_callback,
        )

        # Allow enough time for CLI startup queries to settle before
        # the commit handler starts tracking user input.
        GLib.timeout_add(1500, self._enable_commit_tracking)

        # Session ID detection for new (non-resumed) tabs is coordinated
        # by AITerminalStack.spawn_shell() to avoid multiple tabs claiming
        # the same session.  Only detect here when spawned standalone
        # (e.g. via _restart_cli or a manually added tab).
        if not self._session_id and not getattr(self, "_stack_detects", False) and provider:
            self._pre_spawn_sessions = self._list_sessions()
            GLib.timeout_add(3000, self._detect_session_id)

        # After enough time for a successful resume, clear the flag so
        # normal user-initiated exits aren't mistaken for resume failures.
        if self._resume_attempted:
            GLib.timeout_add(10_000, self._clear_resume_flag)

        # Pre-fetch models in background so they're cached by the time
        # the user clicks the header popup.
        if provider:
            cli_manager.prefetch_models(provider)

    def _clear_resume_flag(self) -> bool:
        """One-shot timeout: resume succeeded if the process is still alive."""
        self._resume_attempted = False
        return False

    def _on_child_exited(self, terminal, status) -> None:
        """Handle CLI exit — detect resume failure and retry fresh."""
        if self._shutting_down:
            return
        if self._resume_attempted:
            # Process exited quickly after --resume → session was stale
            self._resume_attempted = False
            self._session_id = None
            self.terminal.reset(True, True)
            GLib.timeout_add(300, lambda: self.spawn_shell(resume=False) or False)
            return
        # Normal exit — respawn fresh
        GLib.timeout_add(100, lambda: self.spawn_shell() or False)

    # ------------------------------------------------------------------
    # Header interaction
    # ------------------------------------------------------------------

    def _on_header_click(self, _button) -> None:
        """Show a popup to select the AI CLI provider."""
        availability = cli_manager.availability()
        labels = cli_manager.labels()
        current = self._current_provider or get_setting("ai.provider", "")

        items: list[dict] = []
        for pid in cli_manager.provider_ids:
            name = labels[pid]
            installed = availability[pid]
            check = "✓ " if pid == current else "  "
            suffix = "" if installed else "  ⚠ not installed"
            items.append({"label": f"{check}{name}{suffix}", "action": pid, "enabled": True})

        parent = self.get_root()
        if parent:
            from popups.nvim_context_menu import show_context_menu

            show_context_menu(parent, items, self._on_cli_selected, title="Select AI")

    def _on_cli_selected(self, provider: str) -> None:
        """Switch this tab's provider and restart the terminal.

        If the selected CLI is not installed, print install instructions instead.
        """
        if not cli_manager.find_binary(provider):
            self._show_install_hint(provider)
            return

        if provider == self._current_provider:
            return
        self._current_provider = provider
        self._current_model = None  # new provider → reset model to default
        self._session_id = None  # new provider → new session
        self._restart_cli()

    def _on_model_selected(self, model: str) -> None:
        """Switch this tab's model and restart the terminal."""
        current = self._current_model
        if not current:
            model_setting = get_setting("ai.model", "")
            if isinstance(model_setting, dict):
                current = model_setting.get(self._current_provider, "")
            else:
                current = model_setting or ""
        if model == current:
            return
        self._current_model = model
        set_setting("ai.model", model, persist=True)
        self._session_id = None  # new model → new session
        self._restart_cli()

    def _restart_cli(self) -> None:
        """Kill the running CLI and respawn with the newly selected one."""
        self.stop_shell()
        self.terminal.reset(True, True)
        self._title_inferred = False
        self._waiting_for_response = False
        self._commit_ready = False
        self._in_escape_seq = False
        self._in_osc_seq = False
        self._stop_idle_poll()
        self._hide_virtual_scrollbar_immediately()
        self._input_buf.clear()
        if callable(self.on_processing_changed):
            self.on_processing_changed(False)
        if not self._commit_handler_id:
            self._commit_handler_id = self.terminal.connect("commit", self._on_vte_commit)
        GLib.timeout_add(200, lambda: self.spawn_shell() or False)

    def _update_header_label(self) -> None:
        labels = cli_manager.labels()
        label = labels.get(self._current_provider or "", "AI")
        self._ai_header.set_label(label)
        if callable(getattr(self, "on_provider_changed", None)):
            self.on_provider_changed(label)

    # ------------------------------------------------------------------
    # Tab title inference from first user message
    # ------------------------------------------------------------------

    def _enable_commit_tracking(self) -> bool:
        """Called after startup delay — begin processing commit signals."""
        self._commit_ready = True
        self._input_buf.clear()
        return False  # one-shot GLib timeout

    # ------------------------------------------------------------------
    # Session management (delegated to CLI providers)
    # ------------------------------------------------------------------

    def validate_session_id(self) -> None:
        """Check that _session_id exists on disk; clear if stale."""
        if not self._session_id or not self._current_provider:
            return
        p = cli_manager.get(self._current_provider)
        if not p or not p.session_exists(self._session_id, cwd=self.cwd):
            self._session_id = None

    def _list_sessions(self) -> set[str]:
        """Return the set of session IDs currently on disk for the active provider."""
        p = cli_manager.get(self._current_provider) if self._current_provider else None
        return p.list_sessions(cwd=self.cwd) if p else set()

    def _sessions_dir(self):
        """Return the sessions directory path for the active provider."""
        p = cli_manager.get(self._current_provider) if self._current_provider else None
        return p.sessions_dir(cwd=self.cwd) if p else None

    def _detect_session_id(self) -> bool:
        """Detect the session ID created by the just-spawned CLI."""
        pre = getattr(self, "_pre_spawn_sessions", None) or set()
        current = self._list_sessions()
        new_sessions = current - pre

        p = cli_manager.get(self._current_provider) if self._current_provider else None
        sessions_dir = p.sessions_dir(cwd=self.cwd) if p else None

        if len(new_sessions) == 1:
            self._session_id = new_sessions.pop()
        elif len(new_sessions) > 1 and sessions_dir:
            # Multiple new sessions (unlikely) — pick the most recent
            best, best_mtime = None, 0.0
            for sid in new_sessions:
                try:
                    # Try both file patterns (file vs directory)
                    candidate = sessions_dir / sid
                    if not candidate.exists():
                        candidate = sessions_dir / f"{sid}.jsonl"
                    mt = candidate.stat().st_mtime
                    if mt > best_mtime:
                        best, best_mtime = sid, mt
                except OSError:
                    pass
            if best:
                self._session_id = best
        elif not new_sessions and not self._session_id and sessions_dir:
            # --continue was used and no new file appeared — the CLI reused
            # the most recent session.  Find it by modification time.
            try:
                entries = list(sessions_dir.iterdir())
                if entries:
                    latest = max(entries, key=lambda f: f.stat().st_mtime)
                    self._session_id = latest.stem if latest.suffix else latest.name
            except (ValueError, OSError):
                pass
        self._pre_spawn_sessions = None  # cleanup
        return False  # one-shot GLib timeout

    def _on_vte_commit(self, _terminal, text, _length) -> None:
        """Accumulate user input; on first Enter infer a tab title.

        Also drives the spinner: Enter → processing=True, next typing → processing=False.
        """
        if not self._commit_ready:
            return
        for ch in text:
            # Skip escape sequences (e.g. focus-in/out \x1b[I / \x1b[O,
            # cursor reports, bracketed-paste markers) so their trailing
            # printable bytes aren't mistaken for real user input.
            if ch == "\x1b":
                self._in_escape_seq = True
                self._in_osc_seq = False
                continue
            if self._in_escape_seq:
                if not self._in_osc_seq:
                    if ch == "]":
                        # OSC sequence (\x1b]...BEL) — skip until BEL
                        self._in_osc_seq = True
                    elif ch.isalpha() or ch == "~":
                        # CSI/short sequences end at an alpha char or ~
                        self._in_escape_seq = False
                else:
                    # Inside OSC payload — ends at BEL (\x07)
                    if ch == "\x07":
                        self._in_escape_seq = False
                        self._in_osc_seq = False
                continue

            if ch in ("\r", "\n"):
                self._vscroll_reset()
                user_text = "".join(self._input_buf).strip()
                # Strip leftover escape sequence fragments (e.g. terminal
                # capability responses like "[?1;2c" or "[200~").
                user_text = _strip_escape_fragments(user_text)
                self._input_buf.clear()
                if user_text:
                    # Start spinner — CLI is now processing
                    if not self._waiting_for_response:
                        self._waiting_for_response = True
                        self._start_idle_poll()
                        if callable(self.on_processing_changed):
                            self.on_processing_changed(True)

                    # Infer tab title from the very first user message
                    if not self._title_inferred:
                        self._title_inferred = True
                        from ai.tab_title_inferrer import infer_title

                        title = infer_title([{"role": "user", "content": user_text}])
                        if title and callable(self.on_title_inferred):
                            self.on_title_inferred(title)
            elif ch == "\x7f":  # backspace
                if self._input_buf:
                    self._input_buf.pop()
                if self._waiting_for_response:
                    self._waiting_for_response = False
                    self._stop_idle_poll()
                    if callable(self.on_processing_changed):
                        self.on_processing_changed(False)
            elif ch >= " ":  # printable characters only
                self._input_buf.append(ch)
                # User is typing again — CLI returned to prompt, stop spinner
                if self._waiting_for_response:
                    self._waiting_for_response = False
                    self._stop_idle_poll()
                    if callable(self.on_processing_changed):
                        self.on_processing_changed(False)

    # ------------------------------------------------------------------
    # PTY idle detection — stop spinner when CLI waits for input
    # ------------------------------------------------------------------

    def _start_idle_poll(self) -> None:
        """Begin polling the PTY to detect when the CLI becomes idle."""
        self._stop_idle_poll()
        self._last_contents_serial = 0
        self._idle_prev_serial = -1
        self._idle_poll_id = GLib.timeout_add(500, self._check_idle)

    def _stop_idle_poll(self) -> None:
        if self._idle_poll_id:
            GLib.source_remove(self._idle_poll_id)
            self._idle_poll_id = 0

    def _check_idle(self) -> bool:
        """Periodically check whether the CLI process is waiting for input."""
        if not self._waiting_for_response:
            self._idle_poll_id = 0
            return False

        # If terminal content changed since last tick, CLI is still producing
        # output — keep waiting.
        if self._last_contents_serial != self._idle_prev_serial:
            self._idle_prev_serial = self._last_contents_serial
            return True  # keep polling

        # Content has been stable for one poll interval.  Ask the OS whether
        # the CLI process is the PTY foreground group (i.e. it is the one
        # reading from the terminal, not a tool subprocess).
        try:
            pty = self.terminal.get_pty()
            if pty is None:
                return True
            fd = pty.get_fd()
            fg_pgid = os.tcgetpgrp(fd)
            if fg_pgid == self.shell_pid:
                self._waiting_for_response = False
                self._idle_poll_id = 0
                if callable(self.on_processing_changed):
                    self.on_processing_changed(False)
                return False
        except OSError:
            pass
        return True  # keep polling

    def _setup_scroll_controller(self) -> None:
        """AI terminal: only observe wheel to show/hide the jog-wheel overlay."""
        self._jog_setup_scroll_controller()

    def _jog_scroll_lines(self, lines: int) -> None:
        """Send simulated SGR mouse-wheel events to the CLI."""
        cols = self.terminal.get_column_count()
        rows = self.terminal.get_row_count()
        mid_col = max(1, cols // 2)
        mid_row = max(1, rows // 2)
        button = 65 if lines > 0 else 64  # 65=down, 64=up
        seq = f"\033[<{button};{mid_col};{mid_row}M".encode()
        for _ in range(min(abs(lines), 15)):
            self.terminal.feed_child(seq)

    def _on_contents_changed(self, _terminal) -> None:
        """Track CLI output for idle detection."""
        self._last_contents_serial += 1

    # ------------------------------------------------------------------
    # Interface expected by window modules
    # ------------------------------------------------------------------

    def focus_input(self) -> None:
        """Focus the VTE widget (called by window_actions on Cmd+Shift+A)."""
        self.terminal.grab_focus()

    def is_processing(self) -> bool:
        """AI terminal delegates processing entirely to the CLI subprocess."""
        return False

    def stop_ai(self) -> None:
        """Send Ctrl+C to interrupt the running CLI command."""
        self.terminal.feed_child(b"\x03")

    def update_font(self) -> None:
        """Refresh font (called by window_fonts on font-settings change)."""
        self.apply_font_settings()
        self._ai_header.apply_header_font()
