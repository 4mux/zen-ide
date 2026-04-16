"""Startup optimizer mixin — deferred initialization phases for fast first paint."""

import os
import time

from gi.repository import GLib, Gtk


class StartupOptimizerMixin:
    """Mixin: deferred editor/panel/file initialization for fast startup."""

    def _deferred_init_editor(self):
        """Fast init: create EditorView only and print interactive milestone.

        This runs synchronously in _on_window_mapped to reach the interactive
        checkpoint as quickly as possible. Everything else (status bar, bottom
        panels, workspace restore) is deferred to later phases.
        Focus tracking is set up in _on_window_mapped sync batch.
        """
        from gi.repository import Gtk as _Gtk

        from editor.editor_view import EditorView

        # Create editor_split_paned wrapper (deferred from _create_layout to
        # reduce pre-paint widget count — saves ~2ms on present→map).
        self.editor_split_paned = _Gtk.Paned(orientation=_Gtk.Orientation.HORIZONTAL)
        self.editor_split_paned.set_shrink_start_child(False)
        self.editor_split_paned.set_shrink_end_child(False)
        self.editor_split_paned.set_resize_start_child(True)
        self.editor_split_paned.set_resize_end_child(True)
        self.right_paned.set_start_child(self.editor_split_paned)

        self.editor_view = EditorView()
        self.editor_view.add_css_class("editor")
        self.editor_view.on_file_opened = self._on_editor_file_opened
        self.editor_view.on_tab_switched = self._on_editor_tab_switched_reveal
        self.editor_view.on_tabs_empty = self._on_tabs_empty
        self.editor_view.on_tab_closed = self._on_tab_closed
        self.editor_split_paned.set_start_child(self.editor_view)
        self._init_split_panels()
        self.split_panels._editor = self.editor_view

        # Position re-application happens once after TreeView setup in
        # _on_window_mapped — no need to do it here after editor swap.

        elapsed = time.monotonic() - self._startup_time
        print(f"\033[32m⚡ [ZEN] Interactive: {elapsed:.3f}s\033[0m")

    def _create_bottom_panels(self):
        """Create AI chat and terminal panels (deferred from _create_layout for faster first paint)."""
        from constants import DEFAULT_BOTTOM_PANEL_MIN_HEIGHT
        from shared.focus_manager import get_focus_manager
        from shared.settings import get_setting
        from terminal.terminal_stack import TerminalStack

        self._ai_enabled = get_setting("ai.is_enabled", True)

        # Replace placeholder Box with real Paned for side panels (AI Chat on top, Terminal on bottom)
        real_bottom = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        real_bottom.set_shrink_start_child(False)
        real_bottom.set_shrink_end_child(False)
        # Preserve visibility state from placeholder (hidden in single-file mode)
        if not self.bottom_paned.get_visible():
            real_bottom.set_visible(False)
        self.right_paned.set_end_child(real_bottom)
        self.bottom_paned = real_bottom

        if self._ai_enabled:
            from ai.ai_terminal_stack import AITerminalStack
            from shared.settings import get_setting as _gs

            saved_ai_tabs = _gs("workspace.ai_tabs", None)
            self.ai_chat = AITerminalStack(
                saved_tabs=saved_ai_tabs,
                get_workspace_folders_callback=self.tree_view.get_workspace_folders,
                get_editor_context_callback=self._get_editor_context,
            )
            self.ai_chat.set_size_request(DEFAULT_BOTTOM_PANEL_MIN_HEIGHT, DEFAULT_BOTTOM_PANEL_MIN_HEIGHT)
            self.ai_chat.add_css_class("terminal")
            self.bottom_paned.set_start_child(self.ai_chat)
        else:
            # AI disabled — use empty Box so terminal takes full width
            self.ai_chat = Gtk.Box()
            self.ai_chat.set_visible(False)
            self.bottom_paned.set_start_child(self.ai_chat)
            # Only set position to 0 if auto_expand_terminals is enabled
            from shared.settings import get_setting

            if get_setting("behavior.auto_expand_terminals", True):
                self.bottom_paned.set_position(0)

        self.terminal_view = TerminalStack(get_workspace_folders_callback=self.tree_view.get_workspace_folders)
        self.terminal_view.set_size_request(DEFAULT_BOTTOM_PANEL_MIN_HEIGHT, DEFAULT_BOTTOM_PANEL_MIN_HEIGHT)
        self.terminal_view.add_css_class("terminal")
        self.terminal_view.on_open_file = self._on_terminal_open_file

        # Wire tree view → terminal for "Run Test" action
        self.tree_view.write_to_terminal = lambda cmd: (
            self.terminal_view.terminal.feed_child((cmd + "\n").encode())
            if hasattr(self.terminal_view, "terminal") and self.terminal_view.terminal
            else None
        )

        # Wire tree view → debugger for "Debug Test" action
        self.tree_view.on_debug_test = self._on_debug_test

        self.bottom_paned.set_end_child(self.terminal_view)

        # Setup terminal focus tracking (was skipped in _setup_focus_tracking since placeholder had no .terminal)
        if hasattr(self.terminal_view, "terminal"):
            focus_mgr = get_focus_manager()
            focus_ctrl = Gtk.EventControllerFocus()

            def on_terminal_focus(c):
                self._focused_panel = "terminal"
                focus_mgr.set_focus("terminal")

            focus_ctrl.connect("enter", on_terminal_focus)
            self.terminal_view.terminal.add_controller(focus_ctrl)

        self._bottom_panels_created = True

        # Re-apply saved positions — child replacements above may have reset them
        self._reapply_saved_positions()

    def _init_workspace_and_files(self):
        """Init workspace loading — runs synchronously in _on_window_mapped.

        StatusBar creation, file restore, and cursor callbacks are deferred
        to _deferred_init_panels to keep the critical path under 100ms.
        """
        from shared.settings import get_workspace

        # In single-file mode, hide tree/bottom entirely
        if self._cli_file or self._cli_new_file:
            self.tree_view.set_visible(False)
            self.bottom_paned.set_visible(False)

        import zen_ide_window

        workspace = get_workspace()
        preload = zen_ide_window._workspace_preload if zen_ide_window._workspace_preload_event.is_set() else None

        if self._cli_file:
            self.set_title(f"Zen IDE — {os.path.basename(self._cli_file)}")
        elif self._cli_new_file:
            self.set_title(f"Zen IDE — {os.path.basename(self._cli_new_file)}")
        elif self._cli_workspace:
            self._load_workspace_file(self._cli_workspace)
        elif self._cli_dir:
            from shared.git_ignore_utils import collect_global_patterns
            from shared.settings import set_setting

            collect_global_patterns([self._cli_dir])
            self.tree_view.load_workspace([self._cli_dir])
            self.set_title(f"Zen IDE — {os.path.basename(self._cli_dir)}")
            set_setting("workspace.workspace_file", "")
            set_setting("workspace.folders", [self._cli_dir])
        elif preload and preload["folders"]:
            # Use preloaded workspace data (gitignore patterns already cached)
            folders = preload["folders"]
            ws_file = preload["ws_file"]
            ws_name = preload["ws_name"]

            if ws_file:
                from shared.settings import set_setting

                self.tree_view.load_workspace(folders, workspace_name=ws_name)
                self.set_title(f"Zen IDE — {ws_name}")
                set_setting("workspace.workspace_file", ws_file)
                set_setting("workspace.folders", [])
            elif len(folders) > 1:
                self.tree_view.load_workspace(folders)
                self.set_title(f"Zen IDE — {len(folders)} folders")
            else:
                self.tree_view.load_workspace(folders)
                self.set_title(f"Zen IDE — {os.path.basename(folders[0])}")
        else:
            # Preload not available — synchronous fallback
            saved_ws_file = workspace.get("workspace_file", "")
            if saved_ws_file and os.path.isfile(saved_ws_file):
                self._load_workspace_file(saved_ws_file)
            else:
                from shared.git_ignore_utils import collect_global_patterns

                folders = workspace.get("folders", [])
                valid_folders = [f for f in folders if os.path.isdir(f)]

                if len(valid_folders) >= 1:
                    collect_global_patterns(valid_folders)
                    self.tree_view.load_workspace(valid_folders)
                    if len(valid_folders) > 1:
                        self.set_title(f"Zen IDE — {len(valid_folders)} folders")
                    else:
                        self.set_title(f"Zen IDE — {os.path.basename(valid_folders[0])}")
                else:
                    cwd = os.getcwd()
                    collect_global_patterns([cwd])
                    self.tree_view.load_workspace([cwd])
                    self.set_title(f"Zen IDE — {os.path.basename(cwd)}")

    def _init_status_bar_and_files(self):
        """Create StatusBar and wire cursor callbacks.

        File restoration is deferred to _deferred_init_heavy so the window
        can render its first visible frame before loading files.
        """
        from main.status_bar import StatusBar
        from shared.settings import get_workspace

        old_placeholder = self.status_bar_widget
        self.status_bar_widget = StatusBar()
        if old_placeholder is not None:
            self.status_bar_widget.set_margin_bottom(old_placeholder.get_margin_bottom())
            self._main_box.remove(old_placeholder)
        self._main_box.append(self.status_bar_widget)

        workspace = get_workspace()

        # Collect file list but don't open yet — deferred to _deferred_init_heavy
        if self._cli_file or self._cli_new_file or self._cli_workspace or self._cli_dir:
            self._deferred_open_files_list = []
            self._deferred_last_file = ""
        else:
            self._deferred_open_files_list = workspace.get("open_files", [])
            self._deferred_last_file = workspace.get("last_file", "")

        # Wire up cursor tracking for status bar
        self.editor_view.notebook.connect("switch-page", self._on_editor_tab_switched)
        self.editor_view.on_cursor_position_changed = self._on_cursor_position_changed
        self.editor_view.on_diagnostics_changed = self._on_diagnostics_changed
        self.editor_view.on_gutter_diagnostic_clicked = self._on_diagnostics_clicked
        self.status_bar_widget.on_diagnostics_clicked = self._on_diagnostics_clicked
        self.status_bar_widget.set_workspace_folders(
            self.tree_view.get_workspace_folders(),
            workspace_name=self.tree_view._workspace_name,
            workspace_file=workspace.get("workspace_file", ""),
        )

    def _deferred_init_panels(self):
        """Deferred phase 1: actions, shortcuts, theme, StatusBar — lightweight setup.

        Heavy work (bottom panels, terminal spawn, DevPad) is deferred to
        _deferred_init_heavy via GLib.idle_add so the window can render its
        first visible frame between the two phases.
        """
        # Bind actions and shortcuts (deferred from _on_window_mapped —
        # user cannot physically press keys within the first ~130ms)
        if not self._runtime_bindings_ready:
            self._create_actions()
            self._bind_shortcuts()
            self._setup_key_handler()
            self._runtime_bindings_ready = True

        # Setup focus tracking for editor and tree (deferred — invisible)
        from shared.focus_manager import get_focus_manager

        focus_mgr = get_focus_manager()
        if hasattr(self.editor_view, "notebook"):
            focus_ctrl = Gtk.EventControllerFocus()
            focus_ctrl.connect(
                "enter",
                lambda c: (
                    setattr(self, "_focused_panel", "editor"),
                    focus_mgr.set_focus("editor"),
                ),
            )
            self.editor_view.notebook.add_controller(focus_ctrl)

        if hasattr(self.tree_view, "tree") and hasattr(self.tree_view.tree, "drawing_area"):
            focus_ctrl_tv = Gtk.EventControllerFocus()
            focus_ctrl_tv.connect(
                "enter",
                lambda c: (
                    setattr(self, "_focused_panel", "tree"),
                    focus_mgr.set_focus("treeview"),
                ),
            )
            self.tree_view.tree.drawing_area.add_controller(focus_ctrl_tv)

        # Apply full theme CSS (startup used minimal critical-path CSS only)
        self._apply_theme()

        # Load real font size from settings (deferred from __init__ to avoid
        # importing the fonts module before first paint — saves ~8-15ms).
        from constants import DEFAULT_FONT_SIZE
        from fonts import get_font_settings
        from shared.settings import get_setting

        self._font_size = get_font_settings("editor").get("size", DEFAULT_FONT_SIZE)

        # Create StatusBar and wire callbacks (file restore deferred to Phase 2)
        self._init_status_bar_and_files()

        header = self._ensure_header_bar()

        # Add menu button to HeaderBar (deferred from _on_window_mapped)
        from main.menu_builder import MenuBuilder

        menu_btn = Gtk.Button.new_from_icon_name("open-menu-symbolic")
        menu_btn.add_css_class("flat")
        menu_popover = Gtk.PopoverMenu.new_from_model(MenuBuilder().build())
        menu_popover.set_parent(menu_btn)
        menu_popover.set_has_arrow(False)
        menu_btn.connect("clicked", lambda b: menu_popover.popup())
        header.pack_end(menu_btn)

        # Enable drag-and-drop + app icon (deferred from _on_window_mapped)
        self._setup_file_drop_target(self._main_box)
        self.get_application()._setup_app_icon()

        # Show welcome screen immediately (lightweight) if no files and no dev pad
        if not self._deferred_last_file:
            dev_pad_was_open = get_setting("workspace.dev_pad_open", False)
            if not dev_pad_was_open and not get_setting("behavior.auto_show_dev_pad_when_empty", True):
                self._show_welcome_screen()

        # Re-enable GTK animations (disabled at startup for faster first paint)
        _gtk_settings = Gtk.Settings.get_default()
        if _gtk_settings:
            _gtk_settings.set_property("gtk-enable-animations", True)

        # Schedule heavy work after a short delay so the compositor can
        # present the first frame (idle_add can fire before the frame
        # reaches the display server).  50 ms ≈ 3 frames at 60 Hz.
        GLib.timeout_add(50, self._deferred_init_phase2_panels)

        return False  # Don't repeat

    # ------------------------------------------------------------------
    # Phase 2: chained idle steps (panels → file restore → terminals)
    # ------------------------------------------------------------------

    def _deferred_init_phase2_panels(self):
        """Phase 2a: create bottom panels and wire callbacks."""
        if not self._cli_file and not self._cli_new_file:
            self._create_bottom_panels()

        self.editor_view.on_maximize = lambda name: self._maximize_panel(name)
        if self._bottom_panels_created:
            if self._ai_enabled:
                self.ai_chat.on_maximize = lambda name: self._maximize_panel(name)
            self.terminal_view.on_maximize = lambda name: self._maximize_panel(name)

        import zen_ide_window

        preload = zen_ide_window._workspace_preload if zen_ide_window._workspace_preload_event.is_set() else None
        if preload and preload.get("ws_file") and self._bottom_panels_created:
            self._show_all_panels()

        # Next step: restore files (the heaviest part)
        GLib.idle_add(self._deferred_init_phase2_files)
        return False

    def _deferred_init_phase2_files(self):
        """Phase 2b: restore last active file and schedule remaining files."""
        from constants import AUDIO_EXTENSIONS, IMAGE_EXTENSIONS
        from shared.settings import get_setting

        last_file = getattr(self, "_deferred_last_file", "")
        open_files = getattr(self, "_deferred_open_files_list", [])

        if last_file and os.path.isfile(last_file):
            ext = os.path.splitext(last_file)[1].lower()
            if ext in IMAGE_EXTENSIONS:
                self.editor_view.open_image(last_file)
            elif ext in AUDIO_EXTENSIONS:
                self.editor_view.open_audio(last_file)
            else:
                self.editor_view.open_file(last_file)

        remaining_files = [fp for fp in open_files if fp != last_file and os.path.isfile(fp)]
        if remaining_files:
            self._open_deferred_files(remaining_files, last_file)

        # Show DevPad if no file was opened
        if self.editor_view.notebook.get_n_pages() == 0:
            dev_pad_was_open = get_setting("workspace.dev_pad_open", False)
            if dev_pad_was_open or get_setting("behavior.auto_show_dev_pad_when_empty", True):
                self.editor_view.toggle_dev_pad(self.dev_pad)

        # Next step: spawn terminals
        GLib.idle_add(self._deferred_init_phase2_terminals)
        return False

    def _deferred_init_phase2_terminals(self):
        """Phase 2c: spawn terminal shells and finalize layout."""
        if self._bottom_panels_created:
            workspace_dirs = self.tree_view.get_workspace_folders()
            if workspace_dirs and os.path.isdir(workspace_dirs[0]):
                self.terminal_view.change_directory(workspace_dirs[0])
            self.terminal_view.spawn_shell()
            if self._ai_enabled:
                if workspace_dirs and os.path.isdir(workspace_dirs[0]):
                    self.ai_chat.change_directory(workspace_dirs[0])
                self.ai_chat.spawn_shell()

        def _settle_and_unlock():
            self._unlock_paned_positions()
            self._reapply_saved_positions()
            GLib.idle_add(lambda: self._reapply_saved_positions() or False)
            return False

        GLib.idle_add(_settle_and_unlock)

        # Defer non-visible background work past the metric
        GLib.timeout_add(0, self._deferred_background_init)

        return False

    def _deferred_background_init(self):
        """Background init: git status, file watcher, diagnostics — non-visible."""
        self.tree_view.refresh_git_status()
        self._start_file_watcher()
        self.present()

        if not os.environ.get("ZEN_STARTUP_BENCH"):
            GLib.timeout_add(2000, self._run_workspace_diagnostics)

        return False  # Don't repeat

    def _run_workspace_diagnostics(self):
        """Run diagnostics on all workspace files (deferred, async)."""
        from shared.diagnostics_manager import get_diagnostics_manager

        folders = self.tree_view.get_workspace_folders()
        if not folders:
            return False

        mgr = get_diagnostics_manager()

        def on_file_result(file_path, diagnostics):
            # Update gutter if the file is currently open in a tab
            tab = self.editor_view.get_tab_by_path(file_path)
            if tab:
                tab._apply_diagnostic_underlines(diagnostics)
            # Update status bar with workspace-wide totals
            total_errors, total_warnings = mgr.get_total_counts()
            self.status_bar_widget.set_diagnostics(total_errors, total_warnings)

        # Register global callback so repo scans (triggered by save)
        # also update open tabs and status bar
        mgr.set_global_callback(on_file_result)

        mgr.run_workspace_diagnostics(folders, callback=on_file_result)
        return False  # Don't repeat

    def _open_deferred_files(self, files, last_file):
        """Open remaining files one per idle tick to avoid blocking the UI."""
        from constants import AUDIO_EXTENSIONS, IMAGE_EXTENSIONS

        pending = list(files)

        def _open_one(fp, switch_to=True):
            ext = os.path.splitext(fp)[1].lower()
            if ext in IMAGE_EXTENSIONS:
                self.editor_view.open_image(fp, switch_to=switch_to)
            elif ext in AUDIO_EXTENSIONS:
                self.editor_view.open_audio(fp, switch_to=switch_to)
            else:
                self.editor_view.open_file(fp, switch_to=switch_to)

        def _open_next():
            if pending:
                fp = pending.pop(0)
                _open_one(fp, switch_to=False)
                GLib.idle_add(_open_next)
            elif last_file:
                # Re-focus the active file after all tabs are opened
                _open_one(last_file)
            return False

        GLib.idle_add(_open_next)
        return False

    def _show_welcome_screen(self):
        """Show the welcome screen as a tab."""
        from main.welcome_screen import WelcomeScreen

        # Expand editor if it was collapsed (terminals were full-screen)
        if getattr(self, "_editor_collapsed", False):
            self._expand_editor()

        welcome = WelcomeScreen()
        welcome.set_hexpand(True)
        welcome.set_vexpand(True)

        from shared.ui.tab_button import TabButton

        welcome_tab_btn = TabButton(-1, "Welcome", on_close=lambda tid: self.editor_view.close_current_tab())
        page_num = self.editor_view.notebook.append_page(welcome, None)
        self.editor_view._tab_bar.append(welcome_tab_btn)
        self._welcome_tab_btn = welcome_tab_btn
        self.editor_view.notebook.set_current_page(page_num)
