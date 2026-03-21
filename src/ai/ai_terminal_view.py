"""
AI Terminal View for Zen IDE.

Runs the selected AI CLI (claude or copilot) directly inside a VTE terminal,
giving a native interactive experience without any custom rendering layer.

The active CLI is persisted via the ``ai.provider`` setting
(``"claude_cli"`` | ``"copilot_cli"``).  Clicking the header button opens a
popup to switch between available CLIs; the terminal restarts immediately.
"""

import os
import pathlib
import re
import shutil
import time
from typing import Optional

from gi.repository import GLib, Gtk, Vte

from shared.settings import get_setting
from terminal.terminal_view import TerminalView

_CLI_LABELS: dict[str, str] = {
    "claude_cli": "Claude",
    "copilot_cli": "Copilot",
}

_CLAUDE_MODELS = ["opus", "sonnet", "haiku"]
_COPILOT_MODELS = ["claude-sonnet-4.6", "gpt-4.1", "o4-mini", "gemini-2.5-pro"]


def _find_claude_binary() -> Optional[str]:
    """Locate the ``claude`` CLI binary."""
    for candidate in (
        os.path.expanduser("~/.local/bin/claude"),
        "/usr/local/bin/claude",
    ):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return shutil.which("claude")


def _find_copilot_binary() -> Optional[str]:
    """Locate the ``copilot`` CLI binary."""
    nvm_dir = os.environ.get("NVM_DIR", os.path.expanduser("~/.nvm"))
    if os.path.isdir(nvm_dir):
        versions_dir = os.path.join(nvm_dir, "versions", "node")
        if os.path.isdir(versions_dir):
            try:
                for v in sorted(os.listdir(versions_dir), reverse=True):
                    candidate = os.path.join(versions_dir, v, "bin", "copilot")
                    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                        return candidate
            except OSError:
                pass

    for candidate in (
        os.path.expanduser("~/.local/bin/copilot"),
        "/usr/local/bin/copilot",
    ):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    return shutil.which("copilot")


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


# Managed marker to identify Zen IDE's section in copilot-instructions.md
_ZEN_MARKER_START = "<!-- zen-ide-context-start -->"
_ZEN_MARKER_END = "<!-- zen-ide-context-end -->"

_COPILOT_INSTRUCTIONS_PATH = os.path.join(os.path.expanduser("~"), ".copilot", "copilot-instructions.md")


def _write_copilot_instructions(context_block: str) -> None:
    """Write/update the Zen IDE context section in Copilot's global instructions.

    Preserves any existing user content outside the managed markers.
    """
    managed = f"{_ZEN_MARKER_START}\n{context_block}\n{_ZEN_MARKER_END}\n"

    try:
        existing = ""
        if os.path.isfile(_COPILOT_INSTRUCTIONS_PATH):
            with open(_COPILOT_INSTRUCTIONS_PATH, encoding="utf-8") as f:
                existing = f.read()

        # Replace existing managed block, or append
        if _ZEN_MARKER_START in existing:
            import re as _re

            pattern = _re.escape(_ZEN_MARKER_START) + r".*?" + _re.escape(_ZEN_MARKER_END) + r"\n?"
            updated = _re.sub(pattern, managed, existing, flags=_re.DOTALL)
        else:
            separator = "\n" if existing and not existing.endswith("\n") else ""
            updated = existing + separator + managed

        os.makedirs(os.path.dirname(_COPILOT_INSTRUCTIONS_PATH), exist_ok=True)
        with open(_COPILOT_INSTRUCTIONS_PATH, "w", encoding="utf-8") as f:
            f.write(updated)
    except Exception:
        pass


class AITerminalView(TerminalView):
    """VTE-based AI terminal that runs claude or copilot CLI interactively.

    Inherits all VTE machinery (theme, scroll, shortcuts, font) from
    TerminalView.  Only the header and the shell-spawn logic are overridden.
    """

    COMPONENT_ID = "ai_chat"

    def __init__(self, config_dir: str | None = None, get_workspace_folders_callback=None, get_editor_context_callback=None):
        self._current_provider: str | None = None
        self._input_buf: list[str] = []
        self._title_inferred = False
        self._waiting_for_response = False
        self._commit_ready = False  # ignore commit signals until CLI is ready
        self._session_id: str | None = None  # Claude CLI session ID for resume
        self._resume_attempted = False  # True while a --resume spawn is settling
        self._resume_spawn_time: float = 0.0
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
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_kinetic_scrolling(True)
        scrolled.add_css_class("terminal-scrolled")
        self._scrolled_window = scrolled
        self.append(scrolled)

        self.terminal = Vte.Terminal()
        self._configure_terminal()
        scrolled.set_child(self.terminal)
        self._commit_handler_id = self.terminal.connect("commit", self._on_vte_commit)

        self._is_maximized = False
        self.on_maximize = None
        self.on_provider_changed = None

    # ------------------------------------------------------------------
    # CLI resolution
    # ------------------------------------------------------------------

    def _resolve_cli_binary(self) -> tuple[str | None, str | None]:
        """Return (binary_path, provider_key) for the configured CLI.

        Uses the per-tab provider first, then the global setting, then
        falls back: claude → copilot → None.
        """

        preferred = self._current_provider or get_setting("ai.provider", "")

        if preferred == "copilot_cli":
            binary = _find_copilot_binary()
            if binary:
                return binary, "copilot_cli"

        if preferred == "claude_cli":
            binary = _find_claude_binary()
            if binary:
                return binary, "claude_cli"

        # Default / fallback order: claude first, then copilot.
        binary = _find_claude_binary()
        if binary:
            return binary, "claude_cli"

        binary = _find_copilot_binary()
        if binary:
            return binary, "copilot_cli"

        return None, None

    def _resolve_label(self) -> str:
        """Return the CLI display name for the current setting."""
        provider = get_setting("ai.provider", "")
        if provider in _CLI_LABELS:
            return _CLI_LABELS[provider]
        # Peek at availability to pick a sensible default label.

        if _find_claude_binary():
            return "Claude"
        if _find_copilot_binary():
            return "Copilot"
        return "AI"

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

        env_list = [f"{k}={v}" for k, v in env.items()]

        argv = [binary]
        self._resume_attempted = False
        if resume and provider in ("claude_cli", "copilot_cli"):
            self.validate_session_id()
            if self._session_id:
                if provider == "claude_cli":
                    argv.extend(["--resume", self._session_id])
                else:
                    argv.append(f"--resume={self._session_id}")
                self._resume_attempted = True
                self._resume_spawn_time = time.monotonic()
            else:
                argv.append("--continue")

        # Yolo mode: accept all AI changes without confirmation prompts
        if get_setting("ai.yolo_mode", True):
            if provider == "claude_cli":
                argv.append("--dangerously-skip-permissions")
            elif provider == "copilot_cli":
                argv.append("--yolo")

        # Multi-workspace: add extra workspace folders so the CLI can access
        # all repos in the workspace, not just the cwd.
        if self._get_workspace_folders:
            cwd_abs = os.path.abspath(self.cwd or os.getcwd())
            for folder in self._get_workspace_folders():
                if os.path.abspath(folder) != cwd_abs:
                    argv.extend(["--add-dir", folder])

        # IDE context: append a system-prompt snippet so the AI knows about
        # the user's current editor state and the dynamic state file.
        self._append_ide_context_prompt(argv, provider, editor_ctx)

        # Reset commit readiness — CLI startup sends terminal capability
        # queries whose responses arrive via the commit signal and would
        # otherwise be captured as user input (the "Op Vte 7600 …" garbage).
        self._commit_ready = False
        self._input_buf.clear()

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
        if not self._session_id and not getattr(self, "_stack_detects", False):
            if provider == "claude_cli":
                self._pre_spawn_sessions = self._list_claude_sessions()
                GLib.timeout_add(3000, self._detect_session_id)
            elif provider == "copilot_cli":
                self._pre_spawn_sessions = self._list_copilot_sessions()
                GLib.timeout_add(3000, self._detect_session_id)

        # After enough time for a successful resume, clear the flag so
        # normal user-initiated exits aren't mistaken for resume failures.
        if self._resume_attempted:
            GLib.timeout_add(10_000, self._clear_resume_flag)

    def _clear_resume_flag(self) -> bool:
        """One-shot timeout: resume succeeded if the process is still alive."""
        self._resume_attempted = False
        return False

    # ------------------------------------------------------------------
    # IDE context prompt injection
    # ------------------------------------------------------------------

    @staticmethod
    def _append_ide_context_prompt(argv: list[str], provider: str | None, editor_ctx: dict) -> None:
        """Append IDE context instructions to the CLI argv.

        * **Claude CLI** — uses ``--append-system-prompt`` to inject context
          directly into the model's system prompt.
        * **Copilot CLI** — writes ``~/.copilot/copilot-instructions.md``
          (global custom instructions loaded silently) and adds
          ``--add-dir ~/.zen_ide`` so the model can read the dynamic
          state file.

        Both CLIs also receive ``ZEN_*`` environment variables (set in
        ``spawn_shell``), and the dynamic state file is kept up-to-date
        on every tab switch / file open / close.
        """
        if not editor_ctx:
            return

        from shared.ide_state_writer import get_state_file_path

        lines: list[str] = []
        lines.append("## Zen IDE Context")
        lines.append("You are running inside Zen IDE. The user has the following editor state:")

        if editor_ctx.get("active_file"):
            lines.append(f"- Active file (currently viewing): {editor_ctx['active_file']}")
        if editor_ctx.get("open_files"):
            lines.append(f"- Open files: {', '.join(editor_ctx['open_files'])}")
        if editor_ctx.get("workspace_folders"):
            lines.append(f"- Workspace folders: {', '.join(editor_ctx['workspace_folders'])}")
        if editor_ctx.get("workspace_file"):
            lines.append(f"- Workspace file: {editor_ctx['workspace_file']}")
        if editor_ctx.get("git_branch"):
            lines.append(f"- Git branch: {editor_ctx['git_branch']}")

        state_path = get_state_file_path()
        lines.append(
            f"\nThis state was captured at launch. For the latest editor state during this conversation, read: {state_path}"
        )

        prompt = "\n".join(lines)

        if provider == "claude_cli":
            argv.extend(["--append-system-prompt", prompt])
        elif provider == "copilot_cli":
            # Copilot CLI has no --system-prompt flag.  Instead, write
            # the context into ~/.copilot/copilot-instructions.md (global
            # custom instructions) which Copilot loads silently on start.
            _write_copilot_instructions(prompt)
            state_dir = os.path.dirname(state_path)
            argv.extend(["--add-dir", state_dir])

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

        claude_bin = _find_claude_binary()
        copilot_bin = _find_copilot_binary()
        current = self._current_provider or get_setting("ai.provider", "")

        items: list[dict] = []
        if claude_bin:
            items.append(
                {
                    "label": f"{'✓ ' if current == 'claude_cli' else '  '}Claude",
                    "action": "claude_cli",
                    "enabled": True,
                }
            )
        if copilot_bin:
            items.append(
                {
                    "label": f"{'✓ ' if current == 'copilot_cli' else '  '}Copilot",
                    "action": "copilot_cli",
                    "enabled": True,
                }
            )

        if not items:
            return

        parent = self.get_root()
        if parent:
            from popups.nvim_context_menu import show_context_menu

            show_context_menu(parent, items, self._on_cli_selected, title="Select AI")

    def _on_cli_selected(self, provider: str) -> None:
        """Switch this tab's provider and restart the terminal."""
        if provider == self._current_provider:
            return
        self._current_provider = provider
        self._session_id = None  # new provider → new session
        self._restart_cli()

    def _restart_cli(self) -> None:
        """Kill the running CLI and respawn with the newly selected one."""
        self.stop_shell()
        self.terminal.reset(True, True)
        self._title_inferred = False
        self._waiting_for_response = False
        self._commit_ready = False
        self._input_buf.clear()
        if callable(self.on_processing_changed):
            self.on_processing_changed(False)
        if not self._commit_handler_id:
            self._commit_handler_id = self.terminal.connect("commit", self._on_vte_commit)
        GLib.timeout_add(200, lambda: self.spawn_shell() or False)

    def _update_header_label(self) -> None:
        label = _CLI_LABELS.get(self._current_provider or "", "AI")
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
    # Claude session ID detection
    # ------------------------------------------------------------------

    def _claude_sessions_dir(self, cwd: str | None = None) -> pathlib.Path | None:
        """Return the Claude sessions directory for the given or current working directory."""
        cwd = cwd or self.cwd or os.getcwd()
        # Claude stores sessions under ~/.claude/projects/<path-hash>/
        # where path-hash is the absolute path with "/" replaced by "-".
        slug = cwd.replace("/", "-")
        sessions_dir = pathlib.Path.home() / ".claude" / "projects" / slug
        return sessions_dir if sessions_dir.is_dir() else None

    def _find_session_file(self, session_id: str) -> pathlib.Path | None:
        """Find a session JSONL file across all Claude project directories."""
        projects_dir = pathlib.Path.home() / ".claude" / "projects"
        if not projects_dir.is_dir():
            return None
        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            candidate = project_dir / f"{session_id}.jsonl"
            if candidate.exists():
                return candidate
        return None

    def validate_session_id(self) -> None:
        """Check that _session_id exists on disk; clear if stale.

        First checks the current project dir (fast path), then falls back to
        searching all project directories.  This handles the case where a tab's
        session was created under a different cwd than the current one (e.g.
        after IDE restart when change_directory overrides all cwds).
        """
        if not self._session_id:
            return
        if self._current_provider == "copilot_cli":
            d = self._copilot_sessions_dir()
            if d and (d / self._session_id).is_dir():
                return
            self._session_id = None
            return
        d = self._claude_sessions_dir()
        if d and (d / f"{self._session_id}.jsonl").exists():
            return
        # Fallback: search across all Claude project directories
        if self._find_session_file(self._session_id):
            return
        self._session_id = None

    def _list_claude_sessions(self) -> set[str]:
        """Return the set of session IDs (JSONL filenames) currently on disk."""
        d = self._claude_sessions_dir()
        if not d:
            return set()
        return {f.stem for f in d.glob("*.jsonl")}

    # ------------------------------------------------------------------
    # Copilot session ID detection
    # ------------------------------------------------------------------

    @staticmethod
    def _copilot_sessions_dir() -> pathlib.Path | None:
        """Return the Copilot session-state directory."""
        d = pathlib.Path.home() / ".copilot" / "session-state"
        return d if d.is_dir() else None

    def _list_copilot_sessions(self) -> set[str]:
        """Return the set of Copilot session IDs (directories) on disk."""
        d = self._copilot_sessions_dir()
        if not d:
            return set()
        return {p.name for p in d.iterdir() if p.is_dir()}

    def _detect_session_id(self) -> bool:
        """Detect the session ID created by the just-spawned CLI."""
        pre = getattr(self, "_pre_spawn_sessions", set())
        is_copilot = self._current_provider == "copilot_cli"
        current = self._list_copilot_sessions() if is_copilot else self._list_claude_sessions()
        new_sessions = current - pre
        if len(new_sessions) == 1:
            self._session_id = new_sessions.pop()
        elif len(new_sessions) > 1:
            # Multiple new sessions (unlikely) — pick the most recent
            if is_copilot:
                d = self._copilot_sessions_dir()
                if d:
                    best, best_mtime = None, 0.0
                    for sid in new_sessions:
                        try:
                            mt = (d / sid).stat().st_mtime
                            if mt > best_mtime:
                                best, best_mtime = sid, mt
                        except OSError:
                            pass
                    if best:
                        self._session_id = best
            else:
                d = self._claude_sessions_dir()
                if d:
                    best, best_mtime = None, 0.0
                    for sid in new_sessions:
                        p = d / f"{sid}.jsonl"
                        try:
                            mt = p.stat().st_mtime
                            if mt > best_mtime:
                                best, best_mtime = sid, mt
                        except OSError:
                            pass
                    if best:
                        self._session_id = best
        elif not new_sessions and not self._session_id:
            # --continue was used and no new file appeared — the CLI reused
            # the most recent session.  Find it by modification time.
            if is_copilot:
                d = self._copilot_sessions_dir()
                if d:
                    try:
                        latest = max((p for p in d.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
                        self._session_id = latest.name
                    except (ValueError, OSError):
                        pass
            else:
                d = self._claude_sessions_dir()
                if d:
                    try:
                        latest = max(d.glob("*.jsonl"), key=lambda f: f.stat().st_mtime)
                        self._session_id = latest.stem
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
            if ch in ("\r", "\n"):
                user_text = "".join(self._input_buf).strip()
                # Strip leftover escape sequence fragments (e.g. terminal
                # capability responses like "[?1;2c" or "[200~").
                user_text = _strip_escape_fragments(user_text)
                self._input_buf.clear()
                if user_text:
                    # Start spinner — CLI is now processing
                    if not self._waiting_for_response:
                        self._waiting_for_response = True
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
                    if callable(self.on_processing_changed):
                        self.on_processing_changed(False)
            elif ch >= " ":  # printable characters only
                self._input_buf.append(ch)
                # User is typing again — CLI returned to prompt, stop spinner
                if self._waiting_for_response:
                    self._waiting_for_response = False
                    if callable(self.on_processing_changed):
                        self.on_processing_changed(False)

    # ------------------------------------------------------------------
    # Interface expected by window modules
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Scroll speed override — AI terminal content is denser, scroll faster
    # ------------------------------------------------------------------

    def _get_wheel_step_pixels(self) -> float:
        speed = float(get_setting("scroll_speed", 0.4))
        return max(1.0, 180.0 * speed)

    def _get_touchpad_step_pixels(self) -> float:
        speed = float(get_setting("scroll_speed", 0.4))
        return max(1.0, 36.0 * speed)

    # ------------------------------------------------------------------
    # Interface expected by window modules
    # ------------------------------------------------------------------

    def focus_input(self) -> None:
        """Focus the VTE widget (called by window_actions on Cmd+A)."""
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
