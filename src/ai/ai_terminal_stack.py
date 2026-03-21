"""AI Terminal Stack — manages multiple AI terminal sessions with a tab bar."""

import os

from gi.repository import GLib, Gtk

from ai.spinner import Spinner
from constants import TERMINAL_TAB_BAR_MARGIN_BOTTOM
from shared.focus_border_mixin import FocusBorderMixin
from shared.focus_manager import get_component_focus_manager
from shared.gtk_event_utils import is_click_inside_widget
from shared.settings import get_setting


def _session_mtime(sessions_dir, sid: str) -> float:
    """Return the mtime of a session JSONL file, or 0 on error."""
    try:
        return os.path.getmtime(os.path.join(str(sessions_dir), f"{sid}.jsonl"))
    except OSError:
        return 0.0


def _session_mtime_dir(sessions_dir, sid: str) -> float:
    """Return the mtime of a session directory, or 0 on error."""
    try:
        return os.path.getmtime(os.path.join(str(sessions_dir), sid))
    except OSError:
        return 0.0


class AITerminalStack(FocusBorderMixin, Gtk.Box):
    """Container that holds one or more AITerminalView instances in a tabbed layout.

    A single header row sits at the top:
        [<CLI name> ▾] ─────────── [🗑️] [+] [⛶]

    When more than one chat tab exists a scrollable tab bar appears below the
    header.  The active chat is shown inside a Gtk.Stack.

    Proxies the AITerminalView public API so callers can treat it as a
    drop-in replacement:  spawn_shell, cleanup, focus_input, is_processing,
    stop_ai, update_font, on_maximize.
    """

    COMPONENT_ID = "ai_chat"

    def __init__(self, saved_tabs: list[dict] | None = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._views: list = []
        self._tab_buttons: list = []
        self._active_idx: int = 0
        self._spinners: dict[int, dict] = {}  # view_idx -> {spinner, timeout_id}
        self.on_maximize = None
        self._saved_tabs = saved_tabs  # deferred until spawn_shell
        self._vertical_mode = get_setting("behavior.ai_chat_on_vertical_stack", False)

        self._init_focus_border()
        # In vertical mode, remove focus classes from the parent container
        # so the border goes around individual chat views instead
        if self._vertical_mode:
            self.remove_css_class(self.UNFOCUS_CSS_CLASS)

        focus_mgr = get_component_focus_manager()
        focus_mgr.register(
            self.COMPONENT_ID,
            on_focus_in=self._on_focus_in,
            on_focus_out=self._on_focus_out,
        )

        click_ctrl = Gtk.GestureClick.new()
        click_ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click_ctrl.connect("pressed", self._on_panel_click)
        self.add_controller(click_ctrl)

        self._build_header()

        if self._vertical_mode:
            # Hide header in vertical mode (each pane has its own)
            self._header.box.set_visible(False)
            # Vertical mode: all chats visible in a scrolled vertical box
            self._content_scroll = Gtk.ScrolledWindow()
            self._content_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            self._content_scroll.set_vexpand(True)
            self._content_scroll.set_hexpand(True)
            self._content_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            self._content_scroll.set_child(self._content_container)
            self.append(self._content_scroll)
            self._content_stack = None
        else:
            self._build_tab_bar()
            self._content_stack = Gtk.Stack()
            self._content_stack.set_transition_type(Gtk.StackTransitionType.NONE)
            self._content_stack.set_vexpand(True)
            self._content_stack.set_hexpand(True)
            self.append(self._content_stack)

        # Create views: restore from saved state or create a single default tab
        if saved_tabs and len(saved_tabs) > 0:
            for tab_info in saved_tabs:
                view = self._add_view()
                title = tab_info.get("title", "")
                if title:
                    idx = len(self._views) - 1
                    if not self._vertical_mode and 0 <= idx < len(self._tab_buttons):
                        self._tab_buttons[idx].set_title(title)
                    view._title_inferred = True
                # Restore per-tab provider so each tab keeps its CLI
                provider = tab_info.get("provider")
                if provider:
                    view._current_provider = provider
                # Restore per-tab session ID so --resume uses the right session
                session_id = tab_info.get("session_id")
                if session_id:
                    view._session_id = session_id
            # Restore active tab
            active = saved_tabs[0].get("active_idx", 0) if saved_tabs else 0
            # active_idx is stored on the first entry by convention
            for t in saved_tabs:
                if "active_idx" in t:
                    active = t["active_idx"]
                    break
            if 0 <= active < len(self._views):
                self._switch_to_tab(active)
        else:
            self._add_view()

    # ── Header ────────────────────────────────────────────────────────

    def _build_header(self) -> None:
        from ai.ai_terminal_header import AITerminalHeader

        hdr = AITerminalHeader(label=self._resolve_label())
        hdr.header_btn.connect("clicked", self._on_header_click)
        hdr.add_btn.connect("clicked", lambda _b: self._on_add_request())
        hdr.clear_btn.connect("clicked", lambda _b: self._clear_active())
        hdr.maximize_btn.connect("clicked", self._on_maximize_clicked)
        self._header = hdr
        self.append(hdr.box)

    # ── Tab bar ───────────────────────────────────────────────────────

    def _build_tab_bar(self) -> None:
        # Outer container: [◀] [scrollable tabs] [▶]
        self._tab_bar_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._tab_bar_row.set_margin_start(8)
        self._tab_bar_row.set_margin_end(8)
        self._tab_bar_row.set_margin_bottom(TERMINAL_TAB_BAR_MARGIN_BOTTOM)
        self._tab_bar_row.set_visible(False)

        self._scroll_left_btn = Gtk.Button.new_from_icon_name("pan-start-symbolic")
        self._scroll_left_btn.add_css_class("flat")
        self._scroll_left_btn.add_css_class("tab-scroll-btn")
        self._scroll_left_btn.connect("clicked", lambda _b: self._scroll_tab_bar(-1))
        self._tab_bar_row.append(self._scroll_left_btn)

        self._tab_bar_scroll = Gtk.ScrolledWindow()
        self._tab_bar_scroll.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        self._tab_bar_scroll.set_propagate_natural_width(False)
        self._tab_bar_scroll.set_hexpand(True)

        self._tab_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._tab_bar_scroll.set_child(self._tab_bar)
        self._tab_bar_row.append(self._tab_bar_scroll)

        self._scroll_right_btn = Gtk.Button.new_from_icon_name("pan-end-symbolic")
        self._scroll_right_btn.add_css_class("flat")
        self._scroll_right_btn.add_css_class("tab-scroll-btn")
        self._scroll_right_btn.connect("clicked", lambda _b: self._scroll_tab_bar(1))
        self._tab_bar_row.append(self._scroll_right_btn)

        self.append(self._tab_bar_row)

    def _add_tab_button(self, index: int, title: str) -> None:
        from terminal.terminal_tab_button import TerminalTabButton

        btn = TerminalTabButton(
            index=index,
            title=title,
            on_select=self._switch_to_tab,
            on_close=self._close_tab,
            show_close=len(self._views) > 1,
        )
        self._tab_buttons.append(btn)
        self._tab_bar.append(btn)

    def _switch_to_tab(self, index: int) -> None:
        if index < 0 or index >= len(self._views):
            return
        self._active_idx = index
        view = self._views[index]
        if self._vertical_mode:
            self._update_vertical_focus_border()
            view.terminal.grab_focus()
        else:
            self._content_stack.set_visible_child_name(f"ai_{id(view)}")
            self._update_tab_selection()
            self._scroll_tab_into_view(index)
            self._header.set_label(self._label_for_view(view))
            view.terminal.grab_focus()

    def _close_tab(self, index: int) -> None:
        if len(self._views) <= 1:
            return
        self._stop_tab_spinner(index)
        view = self._views[index]
        view.cleanup()
        if self._vertical_mode:
            self._content_container.remove(view)
            self._views.remove(view)
            # Reset maximize state if the closed view was maximized
            if getattr(self, "_maximized_view", None) is view:
                self._maximized_view = None
                for v in self._views:
                    v.set_visible(True)
            self._active_idx = min(self._active_idx, len(self._views) - 1)
        else:
            self._content_stack.remove(view)
            tab_btn = self._tab_buttons.pop(index)
            self._tab_bar.remove(tab_btn)
            self._views.remove(view)
            for i, btn in enumerate(self._tab_buttons):
                btn.index = i
            self._active_idx = min(self._active_idx, len(self._views) - 1)
            active = self._views[self._active_idx]
            self._content_stack.set_visible_child_name(f"ai_{id(active)}")
            self._update_tab_selection()
            self._update_tab_close_buttons()
            self._update_tab_bar_visibility()

    def _close_tab_by_view(self, view) -> None:
        """Close a specific view (used in vertical mode)."""
        try:
            idx = self._views.index(view)
        except ValueError:
            return
        self._close_tab(idx)

    def _update_tab_selection(self) -> None:
        for i, btn in enumerate(self._tab_buttons):
            btn.set_selected(i == self._active_idx)

    def _update_tab_close_buttons(self) -> None:
        show = len(self._tab_buttons) > 1
        for btn in self._tab_buttons:
            btn.set_show_close(show)

    def _update_tab_bar_visibility(self) -> None:
        self._tab_bar_row.set_visible(len(self._views) > 1)

    def _scroll_tab_bar(self, direction: int) -> None:
        """Scroll the tab bar left (-1) or right (+1) by one tab width."""
        hadj = self._tab_bar_scroll.get_hadjustment()
        if not hadj:
            return
        # Use the width of a tab button as the scroll step
        step = 120
        if self._tab_buttons:
            step = max(self._tab_buttons[0].get_width(), 60)
        new_val = hadj.get_value() + direction * step
        new_val = max(0, min(new_val, hadj.get_upper() - hadj.get_page_size()))
        hadj.set_value(new_val)

    def _scroll_tab_into_view(self, index: int) -> None:
        """Ensure the tab button at *index* is visible in the scroll area."""
        if index < 0 or index >= len(self._tab_buttons):
            return
        btn = self._tab_buttons[index]
        hadj = self._tab_bar_scroll.get_hadjustment()
        if not hadj:
            return

        # Compute offset of btn within the tab bar box
        offset = 0
        for i in range(index):
            offset += self._tab_buttons[i].get_width() + 4  # spacing=4
        btn_w = btn.get_width()

        cur = hadj.get_value()
        page = hadj.get_page_size()
        if offset < cur:
            hadj.set_value(offset)
        elif offset + btn_w > cur + page:
            hadj.set_value(offset + btn_w - page)

    # ── View management ───────────────────────────────────────────────

    def _add_view(self):
        from ai.ai_terminal_view import AITerminalView

        view = AITerminalView()
        view.set_vexpand(True)

        view.on_maximize = lambda name: self._on_view_maximize(name)
        view.on_provider_changed = lambda label, v=view: self._on_view_provider_changed(v, label)
        view.on_title_inferred = lambda title, idx=len(self._views): self._on_title_inferred(idx, title)
        view.on_processing_changed = lambda p, idx=len(self._views): self._on_processing_changed(idx, p)

        self._views.append(view)
        tab_idx = len(self._views) - 1

        if self._vertical_mode:
            # Vertical mode: show each view's own header, add to vertical container
            view.add_css_class(self.UNFOCUS_CSS_CLASS)
            # Wire up header buttons for pane-level add/close/maximize
            view._ai_header.add_btn.connect("clicked", lambda _b: self._on_add_request())
            view._ai_header.clear_btn.connect("clicked", lambda _b, v=view: self._close_tab_by_view(v))
            view._ai_header.maximize_btn.connect("clicked", lambda _b, v=view: self._on_pane_maximize(v))
            self._content_container.prepend(view)
        else:
            view._header.set_visible(False)
            stack_name = f"ai_{id(view)}"
            self._content_stack.add_named(view, stack_name)
            self._add_tab_button(tab_idx, f"Chat {len(self._views)}")
            self._update_tab_close_buttons()
            self._update_tab_bar_visibility()
            self._content_stack.set_visible_child_name(stack_name)
            self._update_tab_selection()

        self._active_idx = tab_idx
        return view

    def _on_add_request(self) -> None:
        # Capture the active view's provider before _add_view moves the index.
        prev_provider = self._views[self._active_idx]._current_provider if self._views else None
        view = self._add_view()
        # Inherit provider and workspace cwd from the previous active view so
        # the new tab matches the current header selection.
        if prev_provider:
            view._current_provider = prev_provider
        if self._views and len(self._views) > 1:
            view.cwd = self._views[0].cwd
        view.spawn_shell()

    # ── CLI provider header logic ──────────────────────────────────────

    def _resolve_label(self) -> str:
        from ai.ai_terminal_view import _CLI_LABELS
        from shared.settings import get_setting

        provider = get_setting("ai.provider", "")
        if provider in _CLI_LABELS:
            return _CLI_LABELS[provider]
        from ai.ai_terminal_view import _find_claude_binary, _find_copilot_binary

        if _find_claude_binary():
            return "Claude"
        if _find_copilot_binary():
            return "Copilot"
        return "AI"

    def _label_for_view(self, view) -> str:
        from ai.ai_terminal_view import _CLI_LABELS

        return _CLI_LABELS.get(view._current_provider or "", "AI")

    def _on_header_click(self, _button) -> None:
        from ai.ai_terminal_view import _find_claude_binary, _find_copilot_binary
        from shared.settings import get_setting

        claude_bin = _find_claude_binary()
        copilot_bin = _find_copilot_binary()
        active = self._active
        current = (active._current_provider if active else None) or get_setting("ai.provider", "")

        items: list[dict] = []
        if claude_bin:
            items.append(
                {"label": f"{'✓ ' if current == 'claude_cli' else '  '}Claude", "action": "claude_cli", "enabled": True}
            )
        if copilot_bin:
            items.append(
                {"label": f"{'✓ ' if current == 'copilot_cli' else '  '}Copilot", "action": "copilot_cli", "enabled": True}
            )

        if not items:
            return

        root = self.get_root()
        if root:
            from popups.nvim_context_menu import show_context_menu

            show_context_menu(root, items, self._on_cli_selected, title="Select AI")

    def _on_cli_selected(self, provider: str) -> None:
        from ai.ai_terminal_view import _CLI_LABELS

        active = self._active
        if active:
            active._on_cli_selected(provider)
        label = _CLI_LABELS.get(provider, "AI")
        self._header.set_label(label)

    def _on_title_inferred(self, view_idx: int, title: str) -> None:
        if 0 <= view_idx < len(self._tab_buttons):
            self._tab_buttons[view_idx].set_title(title)

    def _on_processing_changed(self, view_idx: int, processing: bool) -> None:
        if view_idx < 0 or view_idx >= len(self._tab_buttons):
            return
        if processing:
            self._start_tab_spinner(view_idx)
        else:
            self._stop_tab_spinner(view_idx)

    def _start_tab_spinner(self, view_idx: int) -> None:
        self._stop_tab_spinner(view_idx)
        spinner = Spinner()
        btn = self._tab_buttons[view_idx]
        btn.close_btn.set_visible(True)

        def tick():
            if view_idx not in self._spinners:
                return False
            btn.close_btn.set_label(spinner.spin())
            return True

        timeout_id = GLib.timeout_add(80, tick)
        self._spinners[view_idx] = {"spinner": spinner, "timeout_id": timeout_id}
        btn.close_btn.set_label(spinner.spin())

    def _stop_tab_spinner(self, view_idx: int) -> None:
        state = self._spinners.pop(view_idx, None)
        if state:
            GLib.source_remove(state["timeout_id"])
        if 0 <= view_idx < len(self._tab_buttons):
            btn = self._tab_buttons[view_idx]
            btn.close_btn.set_label("\u00d7")
            btn.close_btn.set_visible(btn._show_close)

    def _on_view_maximize(self, name: str) -> None:
        if self.on_maximize:
            self.on_maximize(name)

    def _on_view_provider_changed(self, view, label: str) -> None:
        if view is self._active:
            self._header.set_label(label)

    def _on_maximize_clicked(self, _button) -> None:
        if self.on_maximize:
            self.on_maximize("ai_chat")

    def _clear_active(self) -> None:
        active = self._active
        if active:
            active.clear()

    @property
    def _active(self):
        if self._views and 0 <= self._active_idx < len(self._views):
            return self._views[self._active_idx]
        return None

    # ── Click / focus ──────────────────────────────────────────────────

    def _on_panel_click(self, gesture, n_press, x, y):
        gesture.set_state(Gtk.EventSequenceState.DENIED)
        get_component_focus_manager().set_focus(self.COMPONENT_ID)

        # In vertical mode, detect which chat pane was clicked
        if self._vertical_mode:
            widget = gesture.get_widget()
            for i, view in enumerate(self._views):
                if is_click_inside_widget(widget, x, y, view):
                    if i != self._active_idx:
                        self._active_idx = i
                        self._update_vertical_focus_border()
                    break

    def _on_focus_in(self):
        if self._vertical_mode:
            self._update_vertical_focus_border()
        else:
            self._handle_panel_focus_in()
        active = self._active
        if active:
            active.terminal.grab_focus()

    def _on_focus_out(self):
        if self._vertical_mode:
            self._clear_vertical_focus_border()
        else:
            self._handle_panel_focus_out()

    def _on_pane_maximize(self, view) -> None:
        """Handle maximize button click from a pane header in vertical mode."""
        maximized = getattr(self, "_maximized_view", None)
        if maximized is view:
            # Restore: show all views
            self._maximized_view = None
            for v in self._views:
                v.set_visible(True)
        else:
            # Maximize: hide all except this one
            self._maximized_view = view
            for v in self._views:
                v.set_visible(v is view)

    def _update_vertical_focus_border(self):
        """In vertical mode, apply focus border to the active view only."""
        for view in self._views:
            view.remove_css_class(self.FOCUS_CSS_CLASS)
            view.add_css_class(self.UNFOCUS_CSS_CLASS)
        if 0 <= self._active_idx < len(self._views):
            active = self._views[self._active_idx]
            active.remove_css_class(self.UNFOCUS_CSS_CLASS)
            active.add_css_class(self.FOCUS_CSS_CLASS)

    def _clear_vertical_focus_border(self):
        """In vertical mode, remove focus border from all views."""
        for view in self._views:
            view.remove_css_class(self.FOCUS_CSS_CLASS)
            view.add_css_class(self.UNFOCUS_CSS_CLASS)

    # ── Public API (AITerminalView-compatible) ─────────────────────────

    def change_directory(self, path: str) -> None:
        """Set the working directory for all AI terminal views."""
        for view in self._views:
            view.cwd = path

    def _is_claude_view(self, view) -> bool:
        """Check if a view is (or will be) running Claude CLI."""
        if view._current_provider:
            return view._current_provider == "claude_cli"
        # No per-tab provider set — will resolve from global setting
        from shared.settings import get_setting

        return get_setting("ai.provider", "") != "copilot_cli"

    def spawn_shell(self) -> None:
        resume = bool(self._saved_tabs)

        # Identify views that need session ID detection (no saved ID)
        claude_detect: list = []
        copilot_detect: list = []

        for view in self._views:
            if not getattr(view, "_session_id", None) or not resume:
                if self._is_claude_view(view):
                    if not resume or not getattr(view, "_session_id", None):
                        view._stack_detects = True
                        claude_detect.append(view)
                elif self._is_copilot_view(view):
                    if not resume or not getattr(view, "_session_id", None):
                        view._stack_detects = True
                        copilot_detect.append(view)

        # Snapshot existing sessions BEFORE any spawning
        pre_claude = claude_detect[0]._list_claude_sessions() if claude_detect else set()
        pre_copilot = copilot_detect[0]._list_copilot_sessions() if copilot_detect else set()

        # Now spawn all views
        if resume:
            for view in self._views:
                # Resume if we have a session ID, or if the tab had a
                # conversation (title inferred) — spawn_shell will use
                # --continue as fallback when session_id is missing.
                has_session = bool(getattr(view, "_session_id", None))
                had_conversation = getattr(view, "_title_inferred", False)
                view.spawn_shell(resume=has_session or had_conversation)
        else:
            for view in self._views:
                view.spawn_shell(resume=False)

        # Coordinated session detection: assign new sessions to tabs
        # by creation time after all have started.
        if claude_detect:
            self._pending_detect_claude = (claude_detect, pre_claude)
            GLib.timeout_add(4000, self._detect_sessions_claude)
        if copilot_detect:
            self._pending_detect_copilot = (copilot_detect, pre_copilot)
            GLib.timeout_add(4000, self._detect_sessions_copilot)

        self._saved_tabs = None  # consumed

    def _is_copilot_view(self, view) -> bool:
        """Check if a view is (or will be) running Copilot CLI."""
        if view._current_provider:
            return view._current_provider == "copilot_cli"
        from shared.settings import get_setting

        return get_setting("ai.provider", "") == "copilot_cli"

    def _detect_sessions_claude(self) -> bool:
        """Assign new Claude session IDs to tabs, sorted by file mtime."""
        pending = getattr(self, "_pending_detect_claude", None)
        if not pending:
            return False
        views, pre_sessions = pending
        self._pending_detect_claude = None
        self._detect_sessions_generic(views, pre_sessions, is_copilot=False)
        return False

    def _detect_sessions_copilot(self) -> bool:
        """Assign new Copilot session IDs to tabs, sorted by dir mtime."""
        pending = getattr(self, "_pending_detect_copilot", None)
        if not pending:
            return False
        views, pre_sessions = pending
        self._pending_detect_copilot = None
        self._detect_sessions_generic(views, pre_sessions, is_copilot=True)
        return False

    def _detect_sessions_generic(self, views: list, pre_sessions: set, *, is_copilot: bool) -> None:
        """Assign new session IDs to tabs, one per tab, sorted by mtime."""
        if not views:
            return

        # Get current sessions and find new ones
        if is_copilot:
            current = views[0]._list_copilot_sessions()
        else:
            current = views[0]._list_claude_sessions()
        new_ids = current - pre_sessions
        # Exclude IDs already claimed by other (resumed) tabs
        claimed = {v._session_id for v in self._views if v._session_id and v not in views}
        new_ids -= claimed

        if not new_ids:
            # Fallback: each view detects on its own (single tab --continue case)
            for v in views:
                v._stack_detects = False
                v._pre_spawn_sessions = pre_sessions
                v._detect_session_id()
            return

        # Sort new sessions by mtime (oldest first = first tab spawned)
        if is_copilot:
            d = views[0]._copilot_sessions_dir()
            if not d:
                return
            sorted_ids = sorted(new_ids, key=lambda sid: _session_mtime_dir(d, sid))
        else:
            d = views[0]._claude_sessions_dir()
            if not d:
                return
            sorted_ids = sorted(new_ids, key=lambda sid: _session_mtime(d, sid))

        # Assign one session per tab in spawn order
        for i, view in enumerate(views):
            if i < len(sorted_ids):
                view._session_id = sorted_ids[i]
            view._stack_detects = False

    def cleanup(self) -> None:
        for idx in list(self._spinners):
            self._stop_tab_spinner(idx)
        for view in self._views:
            view.cleanup()

    def focus_input(self) -> None:
        active = self._active
        if active:
            active.focus_input()

    def is_processing(self) -> bool:
        return False

    def stop_ai(self) -> None:
        active = self._active
        if active:
            active.stop_ai()

    def update_font(self) -> None:
        for view in self._views:
            view.update_font()
        if not self._vertical_mode:
            self._header.apply_header_font()

    def save_state(self) -> list[dict]:
        """Return a serialisable list describing every open tab.

        The first entry carries the ``active_idx`` key so the caller only
        needs to persist a single list.  Each entry includes the Claude
        session ID (if any) so tabs can resume their individual sessions.
        """
        seen_ids: set[str] = set()
        tabs: list[dict] = []
        items = enumerate(self._tab_buttons) if not self._vertical_mode else enumerate(self._views)
        for i, item in items:
            if self._vertical_mode:
                entry: dict = {"title": f"Chat {i + 1}"}
            else:
                entry = {"title": item.get_title()}
            if i == 0:
                entry["active_idx"] = self._active_idx
            if True:
                view = self._views[i] if not self._vertical_mode else item
                # Persist per-tab provider
                if view._current_provider:
                    entry["provider"] = view._current_provider
                # Persist per-tab session ID for individual session resume
                # Validate session exists before saving
                if hasattr(view, "validate_session_id"):
                    view.validate_session_id()
                sid = getattr(view, "_session_id", None)
                # Last-resort detection: if this view had a conversation
                # (title was inferred) but session ID is missing, try to find it
                # by picking the most recent unclaimed session.
                if not sid and getattr(view, "_title_inferred", False):
                    sid = self._detect_session_for_save(view, seen_ids)
                # Skip duplicate session IDs — each tab must have its own
                if sid and sid not in seen_ids:
                    entry["session_id"] = sid
                    seen_ids.add(sid)
            tabs.append(entry)
        return tabs

    def _detect_session_for_save(self, view, claimed_ids: set[str]) -> str | None:
        """Try to find the session ID for a view that lost it.

        Picks the most recently modified session not claimed by another tab.
        """
        all_claimed = claimed_ids | {v._session_id for v in self._views if v._session_id and v is not view}

        if view._current_provider == "copilot_cli":
            d = view._copilot_sessions_dir()
            if not d:
                return None
            try:
                candidates = sorted(
                    (p for p in d.iterdir() if p.is_dir()),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
            except OSError:
                return None
            for p in candidates:
                sid = p.name
                if sid in all_claimed:
                    continue
                # Check it has an events file (valid session)
                if (p / "events.jsonl").exists():
                    return sid
            return None

        # Claude
        d = view._claude_sessions_dir()
        if not d:
            return None
        try:
            candidates = sorted(d.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
        except OSError:
            return None
        for f in candidates:
            sid = f.stem
            if sid in all_claimed:
                continue
            # Quick check: is this a conversation session (has user message)?
            try:
                with open(f) as fh:
                    for i, line in enumerate(fh):
                        if i >= 5:
                            break
                        if '"human"' in line or '"user"' in line:
                            return sid
            except OSError:
                continue
        return None
