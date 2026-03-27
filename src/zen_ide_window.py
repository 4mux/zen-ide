"""
Zen IDE (GTK4 version)
A minimalist IDE for code development.

GTK4 implementation with GtkSourceView for the code editor.
"""

import os
import sys
import time

_STARTUP_TIME = time.monotonic()

# Register this module as 'zen_ide_window' so `import zen_ide` in submodules
# reuses it instead of re-executing the file (~12ms saved).
if __name__ == "__main__":
    sys.modules["zen_ide_window"] = sys.modules["__main__"]

# Add parent directory to path for shared framework-agnostic modules
_parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

# Import preloading infrastructure — starts background threads for AppKit,
# workspace I/O, and font registration at import time.
import threading  # noqa: E402

import app_preload as _ap  # noqa: E402

# Re-export mutable globals so external code (e.g. `import zen_ide_window;
# zen_ide_window._workspace_preload`) sees live values updated by background threads.
# Using module-level __getattr__ ensures reads always delegate to app_preload.
_font_thread = _ap._font_thread
_macos_appkit_loaded = _ap._macos_appkit_loaded
_workspace_preload_event = _ap._workspace_preload_event
_run_startup_housekeeping = _ap._run_startup_housekeeping
_read_pango_backend = _ap._read_pango_backend
_preload_editor_module = _ap._preload_editor_module
_preload_treeview_module = _ap._preload_treeview_module


def __getattr__(name):
    """Delegate lookups for mutable globals to app_preload at access time."""
    if name == "_workspace_preload":
        return _ap._workspace_preload
    if name == "_fonts_preregistered":
        return _ap._fonts_preregistered
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Apply PANGOCAIRO_BACKEND setting before GTK/Pango initializes.
_pango_backend = _read_pango_backend()
if _pango_backend == "freetype":
    os.environ["PANGOCAIRO_BACKEND"] = "fc"
elif _pango_backend == "coretext" and sys.platform == "darwin":
    os.environ.pop("PANGOCAIRO_BACKEND", None)  # Ensure CoreText (default on macOS)

# Check for GTK dependencies
try:
    # On macOS, skip backend detection by setting GDK_BACKEND explicitly (saves ~25ms)
    if sys.platform == "darwin" and "GDK_BACKEND" not in os.environ:
        os.environ["GDK_BACKEND"] = "macos"

    from gi_requirements import ensure_gi_requirements

    ensure_gi_requirements()

except ValueError as e:
    print(f"Missing GTK dependency: {e}")
    print("\nInstall dependencies with:")
    print("  brew install gtk4 gtksourceview5 gobject-introspection pygobject3")
    print("  pip install PyGObject")
    sys.exit(1)

from gi.repository import Gdk, GLib, Gtk  # noqa: E402

# Set prgname BEFORE Gtk.init() so that the X11 WM_CLASS and Wayland app_id
# match the StartupWMClass in zen-ide.desktop.  Without this, the desktop
# environment cannot associate the window with the .desktop file and falls
# back to a generic icon in the dock/taskbar.
GLib.set_prgname("zen-ide")
GLib.set_application_name("Zen IDE")


def _filter_gtk_warnings(domain, level, message, user_data):
    """Suppress known GTK4 bug: 'Broken accounting of active state' (GNOME #3356, #6442)."""
    if "Broken accounting of active state" in (message or ""):
        return
    GLib.log_default_handler(domain, level, message, user_data)


def _filter_gdk_warnings(domain, level, message, user_data):
    """Suppress known macOS GDK bug: display link source pause race condition."""
    if "gdk_display_link_source_pause" in (message or ""):
        return
    GLib.log_default_handler(domain, level, message, user_data)


def _filter_gio_criticals(domain, level, message, user_data):
    """Filter GIO critical warnings for known g_list_store_remove errors."""
    if "g_list_store_remove" in (message or ""):
        return
    GLib.log_default_handler(domain, level, message, user_data)


def _filter_gio_warnings(domain, level, message, user_data):
    """Suppress known macOS poll(2) EAGAIN warnings from GLib event loop."""
    if "poll(2) failed due to: Resource temporarily unavailable" in (message or ""):
        return  # Benign EAGAIN from non-blocking FD — ignore
    GLib.log_default_handler(domain, level, message, user_data)


GLib.log_set_handler("Gtk", GLib.LogLevelFlags.LEVEL_WARNING, _filter_gtk_warnings, None)
GLib.log_set_handler("Gdk", GLib.LogLevelFlags.LEVEL_CRITICAL, _filter_gdk_warnings, None)
GLib.log_set_handler("GLib-GIO", GLib.LogLevelFlags.LEVEL_CRITICAL, _filter_gio_criticals, None)
GLib.log_set_handler("GLib", GLib.LogLevelFlags.LEVEL_WARNING, _filter_gio_warnings, None)

# On macOS, ensure the process is a foreground GUI app before GTK starts
# event polling. Without this, AppKit asserts in _DPSNextEvent on macOS 26+
# (NSAssertMainEventQueueIsCurrentEventQueue → SIGTRAP crash) because the
# detached subprocess launches with procRole=Background.
if sys.platform == "darwin" and _macos_appkit_loaded is not None:
    _macos_appkit_loaded.wait()  # AppKit preloaded concurrently — typically ready by now
    try:
        from AppKit import NSApplication

        NSApplication.sharedApplication().setActivationPolicy_(0)  # NSApplicationActivationPolicyRegular
    except ImportError:
        pass

# Initialize GTK and set dark theme preference at module level so the cost
# is excluded from the first-paint timer (which starts in main()).
# Join font thread first — fontconfig app-fonts must be registered before
# Pango initializes its font map during Gtk.init().  The thread started
# ~274ms ago and its ~11ms of fontconfig work completed long before this point.
_font_thread.join()
Gtk.init()

# Start preloading heavy modules in background threads immediately after
# Gtk.init().  They overlap with settings/theme/dark-theme/mixin imports
# below (~40ms of main-thread work).  The GIL releases during .pyc I/O and
# GTK CSS initialisation, giving genuine parallelism (~20ms saved).

# Pre-import shared.ui on the main thread so both preload threads don't race
# for its module lock (Python's import machinery is not re-entrant and two
# threads importing the same transitive dependency causes a _DeadlockError).
import shared.ui  # noqa: F401, E402

_preload_editor_thread = threading.Thread(target=_preload_editor_module, daemon=True)
_preload_treeview_thread = threading.Thread(target=_preload_treeview_module, daemon=True)
_preload_editor_thread.start()
_preload_treeview_thread.start()

from shared.settings import get_setting, load_settings  # noqa: E402

load_settings()
from themes import set_theme  # noqa: E402

# persist=False — we're restoring the saved theme, no need to write it back to disk (~15ms saved)
_saved_theme = get_setting("theme", "zen_dark")
set_theme(_saved_theme, persist=False)

_settings = Gtk.Settings.get_default()
if _settings:
    # Defer gtk-application-prefer-dark-theme to _on_window_mapped (~9ms saved).
    # Our custom CSS already handles all visible widget colours at first paint.
    # The property only affects Adwaita's built-in widgets (buttons, entries),
    # which are overridden by our CSS provider anyway.  Setting it post-paint
    # in _apply_startup_theme avoids a style cascade on the critical path.
    #
    # Disable animations during startup for faster first paint (~5-10ms).
    # Re-enabled in _deferred_init_panels after first paint completes.
    _settings.set_property("gtk-enable-animations", False)
    # Global cursor blink setting — applies to all GTK text inputs
    _settings.set_property("gtk-cursor-blink", get_setting("cursor_blink", True))
    # Disable error bell (system beep on failed cursor movement, e.g. Down at end of buffer)
    _settings.set_property("gtk-error-bell", False)
    # Font rendering — configurable via settings.json "font_rendering" section.
    _fr = get_setting("font_rendering", {})
    # gtk-xft-* properties apply on Linux always, and on macOS when pango_backend is "freetype".
    _use_xft = sys.platform != "darwin" or _pango_backend == "freetype"
    if _use_xft:
        _settings.set_property("gtk-xft-antialias", 1 if _fr.get("antialias", True) else 0)
        _settings.set_property("gtk-xft-hinting", 1 if _fr.get("hinting", True) else 0)
        _settings.set_property("gtk-xft-hintstyle", _fr.get("hintstyle", "hintslight"))
        _settings.set_property("gtk-xft-rgba", _fr.get("subpixel_order", "rgb"))
        # Honor our xft settings strictly instead of GTK auto-deciding (GTK 4.16+).
        try:
            _settings.set_property("gtk-font-rendering", "manual")
        except TypeError:
            pass  # GTK < 4.16 doesn't have this property
    # Snap glyph metrics to pixel grid — works on all platforms.
    _settings.set_property("gtk-hint-font-metrics", _fr.get("hint_font_metrics", True))

from constants import DEFAULT_FONT_SIZE, DEFAULT_WINDOW_HEIGHT, DEFAULT_WINDOW_WIDTH  # noqa: E402
from main.action_manager import ActionManager  # noqa: E402
from main.window_actions_mixin import WindowActionsMixin  # noqa: E402
from main.window_events_mixin import WindowEventsMixin  # noqa: E402
from main.window_fonts_mixin import WindowFontsMixin  # noqa: E402
from main.window_layout_mixin import WindowLayoutMixin  # noqa: E402
from main.window_panels_mixin import WindowPanelsMixin  # noqa: E402
from main.window_state_mixin import WindowStateMixin  # noqa: E402
from shared.settings import get_layout  # noqa: E402

# Join preload threads — they ran concurrently with settings/theme/mixin work above.
_preload_editor_thread.join()
_preload_treeview_thread.join()


class ZenIDEWindow(
    WindowLayoutMixin,
    WindowStateMixin,
    WindowEventsMixin,
    WindowActionsMixin,
    WindowPanelsMixin,
    WindowFontsMixin,
    Gtk.ApplicationWindow,
):
    """Main IDE window with 4 components: treeview, editor, AI chat, terminal."""

    def __init__(self, app):
        super().__init__(application=app, title="Zen IDE")

        # Settings and theme already loaded at module level
        layout = get_layout()
        self.set_default_size(
            layout.get("window_width", DEFAULT_WINDOW_WIDTH), layout.get("window_height", DEFAULT_WINDOW_HEIGHT)
        )

        # Font size loaded from settings in _deferred_init_panels (Phase 2)
        # to avoid importing the fonts module before first paint (~8-15ms).
        self._font_size = DEFAULT_FONT_SIZE
        self._maximized_panel = None  # Track which panel is maximized
        self._saved_positions = {}  # Saved paned positions for restore

        self._focused_panel = "editor"  # Track which panel has focus
        self._cli_file = None  # File passed via command line (skip workspace restore)
        self._cli_new_file = None  # Non-existent file passed via CLI (create as temporary)
        self._cli_workspace = None  # Workspace file passed via command line
        self._cli_dir = None  # Directory passed via command line
        self._bottom_panels_created = False  # Track if bottom panels have been created
        self._layout_ready = False  # Track if layout is fully initialized (safe to save positions)
        self._startup_time = _STARTUP_TIME or time.monotonic()

        # Theme is set in do_activate before window creation (dark preference applied early)
        # Full CSS applied in _on_window_mapped sync batch after first paint

        # Create main layout (defers HeaderBar, menu, focus tracking, drop target)
        self._create_layout()
        self._runtime_bindings_ready = False

        # Save state on close
        self.connect("close-request", self._on_close_request)

        # Load workspace after window is mapped (positions need size allocation)
        self.connect("map", self._on_window_mapped)

    # -- Lazy panel properties (created on first access for faster startup) --

    @property
    def diff_view(self):
        if self._diff_view is None:
            from editor.preview.diff_view import DiffView

            self._diff_view = DiffView()
            self._diff_view._on_close_callback = lambda: self.split_panels.hide("diff")
            self._diff_view._on_revert_callback = self._on_diff_revert
            self._diff_view._on_navigate_callback = self._on_diff_navigate
            self._diff_view.set_visible(False)
        return self._diff_view

    @property
    def system_monitor(self):
        if self._system_monitor is None:
            from shared.system_monitor_panel import SystemMonitorPanel

            self._system_monitor = SystemMonitorPanel(on_close=lambda: self.split_panels.hide("system_monitor"))
            self._system_monitor.set_visible(False)
        return self._system_monitor

    @property
    def dev_pad(self):
        if self._dev_pad is None:
            from dev_pad import DevPad

            self._dev_pad = DevPad(
                open_file_callback=self._on_tree_file_selected,
                open_ai_chat_callback=self._on_open_ai_chat,
                get_workspace_folders_callback=lambda: (
                    self.tree_view.get_workspace_folders() if hasattr(self, "tree_view") else []
                ),
            )
            self._dev_pad.set_size_request(200, -1)
            self._dev_pad.set_visible(False)
        return self._dev_pad

    @property
    def debug_panel(self):
        if self._debug_panel is None:
            from debugger.debug_panel import DebugPanel

            self._debug_panel = DebugPanel(self)
            self._debug_panel.set_visible(False)
        return self._debug_panel

    def _create_actions(self):
        """Create application actions."""
        app = self.get_application()
        self._action_mgr = ActionManager(app)

        self._action_mgr.create_actions(
            {
                # File
                "new": self._on_new,
                "new_sketch_pad": self._on_new_sketch_pad,
                "open": self._on_open,
                "open_folder": self._on_open_folder,
                "new_workspace": self._on_new_workspace,
                "open_workspace": self._on_open_workspace,
                "edit_workspace": self._on_edit_workspace,
                "save": self._on_save,
                "close_tab": self._on_close_tab,
                # Edit
                "undo": self._on_undo,
                "redo": self._on_redo,
                "find": self._on_find,
                "find_replace": self._on_find_replace,
                "go_to_line": self._on_go_to_line,
                "toggle_comment": self._on_toggle_comment,
                "indent": self._on_indent,
                "unindent": self._on_unindent,
                # View
                "focus_explorer": self._on_focus_explorer,
                "clear_terminal": self._on_clear_terminal,
                "global_search": self._on_global_search,
                "quick_open": self._on_quick_open,
                "show_diff": self._on_show_diff,
                "show_dev_pad": self._on_show_dev_pad,
                "open_sketch_pad": self._on_open_sketch_pad,
                "focus_terminal": self._on_focus_terminal,
                "focus_ai_chat": self._on_focus_ai_chat,
                "stop_ai": self._on_stop_ai,
                "next_tab": self._on_next_tab,
                "prev_tab": self._on_prev_tab,
                "zoom_in": self._on_zoom_in,
                "zoom_out": self._on_zoom_out,
                "maximize_focused": self._on_maximize_focused,
                "maximize_window": self._on_maximize_window,
                "reset_layout": self._on_reset_layout,
                "reload_ide": self._on_reload_ide,
                "fonts": self._on_fonts,
                "theme_picker": self._on_theme_picker,
                "toggle_dark_light": self._on_toggle_dark_light,
                "show_welcome": self._on_show_welcome,
                # Help
                "open_settings_file": self._on_open_settings_file,
                # macOS maps Cmd+, to app.preferences via native menu bar
                "preferences": self._on_open_settings_file,
                "shortcuts": self._on_shortcuts,
                "system_monitor": self._on_system_monitor,
                "view_crash_logs": self._on_view_crash_logs,
                "view_ai_debug_log": self._on_view_ai_debug_log,
                "toggle_inspect": self._on_toggle_inspect,
                "about": self._on_about,
                "quit": self._on_quit,
                # Debug
                "debug_start": self._on_debug_start,
                "debug_stop": self._on_debug_stop,
                "debug_step_over": self._on_debug_step_over,
                "debug_step_into": self._on_debug_step_into,
                "debug_step_out": self._on_debug_step_out,
                "debug_toggle_breakpoint": self._on_debug_toggle_breakpoint,
                "debug_toggle_panel": self._on_debug_toggle_panel,
            }
        )

    def _bind_shortcuts(self):
        """Bind keyboard shortcuts."""
        mod, mod_shift = ActionManager.get_mod_keys()

        self._action_mgr.bind_shortcuts(
            {
                # File
                "new": [f"{mod}n"],
                "open": [f"{mod}o"],
                "open_workspace": [f"{mod_shift}o", f"{mod}O"],
                "save": [f"{mod}s"],
                "close_tab": [f"{mod}w"],
                "quit": [f"{mod}q"],
                # Edit
                "undo": [f"{mod}z"],
                "redo": [f"{mod_shift}z", f"{mod}Z"],
                "find": [f"{mod}f"],
                "find_replace": [f"{mod}h"],
                "go_to_line": [f"{mod}g"],
                "toggle_comment": [f"{mod}slash"],
                "indent": [f"{mod}bracketright"],
                "unindent": [f"{mod}bracketleft"],
                # View/Navigation
                "focus_explorer": [f"{mod_shift}e", f"{mod}E"],
                "clear_terminal": [f"{mod}k"],
                "global_search": [f"{mod_shift}f", f"{mod}F"],
                "quick_open": [f"{mod}p"],
                "show_diff": [f"{mod}d"],
                "show_dev_pad": [f"{mod}period"],
                "open_sketch_pad": [f"{mod_shift}d", f"{mod}D"],
                "focus_terminal": [f"{mod}grave"],
                "focus_ai_chat": [f"{mod_shift}a"],
                "next_tab": [f"{mod}Tab", "<Control>j"],
                "prev_tab": [f"{mod_shift}Tab", "<Control><Shift>j"],
                "zoom_in": [f"{mod}equal"],
                "zoom_out": [f"{mod}minus"],
                "open_settings_file": [f"{mod}comma"],
                "maximize_focused": [f"{mod_shift}backslash", f"{mod_shift}bar"],
                "maximize_window": [f"{mod_shift}0", f"{mod}parenright"],
                "reload_ide": [f"{mod}r"],
                "theme_picker": [f"{mod_shift}t", f"{mod}T"],
                "toggle_dark_light": [f"{mod_shift}l", f"{mod}L"],
                "shortcuts": [f"{mod_shift}slash", f"{mod_shift}question"],
                "toggle_inspect": [f"{mod_shift}i", f"{mod}I"],
                # Debug
                "debug_start": ["F5"],
                "debug_stop": ["<Shift>F5"],
                "debug_step_over": ["F10"],
                "debug_step_into": ["F11"],
                "debug_step_out": ["<Shift>F11"],
                "debug_toggle_breakpoint": ["F9"],
                "debug_toggle_panel": [f"{mod_shift}b", f"{mod}B"],
            }
        )

    def _setup_key_handler(self):
        """Setup global key event handler for shortcuts that GTK accels don't catch."""
        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect("key-pressed", self._on_global_key_pressed)
        self.add_controller(key_controller)

    def _on_global_key_pressed(self, controller, keyval, keycode, state):
        """Handle global key shortcuts (capture phase)."""
        # Debug function keys by hardware keycode — works even when
        # laptop firmware remaps F-row to media keys without Fn held.
        is_shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        no_mods = not (state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.META_MASK))

        if no_mods and not is_shift:
            # keycode 71 = F5, 76 = F10, 95 = F11, 75 = F9
            fkey_actions = {71: "debug_start", 76: "debug_step_over", 95: "debug_step_into", 75: "debug_toggle_breakpoint"}
            action_name = fkey_actions.get(keycode)
            if action_name:
                app = self.get_application()
                if app:
                    app.activate_action(action_name)
                    return True
        elif is_shift and no_mods:
            # Shift+F5 = stop, Shift+F11 = step out
            fkey_shift = {71: "debug_stop", 95: "debug_step_out"}
            action_name = fkey_shift.get(keycode)
            if action_name:
                app = self.get_application()
                if app:
                    app.activate_action(action_name)
                    return True

        # Also handle by keyval (for keyboards where F-keys work normally)
        if keyval == Gdk.KEY_F5 and no_mods and not is_shift:
            self.get_application().activate_action("debug_start")
            return True

        # Escape closes the find bar regardless of focus
        if (
            keyval == Gdk.KEY_Escape
            and getattr(self.editor_view, "_find_bar_created", False)
            and self.editor_view.find_bar.get_search_mode()
        ):
            self.editor_view.find_bar.set_search_mode(False)
            tab = self.editor_view._get_current_tab()
            if tab:
                tab.view.grab_focus()
            return True

        return False


# Import ZenIDEApp from extracted module
from zen_ide_app import ZenIDEApp  # noqa: E402, F401


def main():
    """Main entry point."""
    app = ZenIDEApp()
    try:
        exitcode = app.run(sys.argv)
    except KeyboardInterrupt:
        exitcode = 0
    # Force-exit: daemon threads (file watcher, git status, etc.) or GLib
    # internals can keep the process alive after the main loop ends, which
    # freezes the calling terminal.
    from shared.utils import persist_clipboard

    persist_clipboard()
    os._exit(exitcode or 0)


if __name__ == "__main__":
    sys.exit(main())
