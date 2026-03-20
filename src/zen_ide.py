"""
Zen IDE (GTK4 version)
A minimalist IDE for code development.

GTK4 implementation with GtkSourceView for the code editor.
"""

import os
import sys
import time

_STARTUP_TIME = time.monotonic()

# Register this module as 'zen_ide' so `import zen_ide` in submodules
# reuses it instead of re-executing the file (~12ms saved).
if __name__ == "__main__":
    sys.modules["zen_ide"] = sys.modules["__main__"]

# Add parent directory to path for shared framework-agnostic modules
_parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

_STARTUP_HOUSEKEEPING_DONE = False

# Preload macOS AppKit in background thread for instant foreground activation
# at first paint. The import takes ~200ms but runs concurrently with GTK init,
# so it's ready well before the window maps.
# In frozen bundles, AppKit is already loaded by the runtime hook splash window.
_macos_appkit_loaded = None

import threading

if sys.platform == "darwin":
    if os.environ.get("_ZEN_APPKIT_PRELOADED"):
        # AppKit already imported by runtime hook splash — mark as ready
        _macos_appkit_loaded = threading.Event()
        _macos_appkit_loaded.set()
    else:
        _macos_appkit_loaded = threading.Event()

        def _preload_appkit():
            try:
                import AppKit  # noqa: F401 — ~200ms, cached for later use
            except Exception:
                pass
            _macos_appkit_loaded.set()

        threading.Thread(target=_preload_appkit, daemon=True).start()

# Preload workspace I/O in background thread so it's ready by the time the
# window maps (~61ms). Reads workspace settings, parses workspace file, and
# collects gitignore patterns — pure I/O that completes in <10ms.
_workspace_preload = None
_workspace_preload_event = threading.Event()


def _preload_workspace_io():
    """Preload workspace config, gitignore patterns, and treeview module in background."""
    global _workspace_preload
    try:
        from shared.settings import get_workspace

        workspace = get_workspace()
        saved_ws_file = workspace.get("workspace_file", "")
        folders = []
        ws_name = None

        if saved_ws_file and os.path.isfile(saved_ws_file):
            import json as json_module
            import re

            with open(saved_ws_file, "r", encoding="utf-8") as f:
                content = f.read()
            content = re.sub(r"//[^\n]*", "", content)
            content = re.sub(r",(\s*[}\]])", r"\1", content)
            ws_data = json_module.loads(content)
            ws_dir = os.path.dirname(saved_ws_file)
            for folder in ws_data.get("folders", []):
                folder_path = folder.get("path", "")
                if folder_path:
                    if not os.path.isabs(folder_path):
                        folder_path = os.path.normpath(os.path.join(ws_dir, folder_path))
                    if os.path.isdir(folder_path):
                        folders.append(folder_path)
            ws_name = os.path.basename(saved_ws_file)
        else:
            folders = [f for f in workspace.get("folders", []) if os.path.isdir(f)]
            if not folders:
                folders = [os.getcwd()]

        # Collect gitignore patterns (pure I/O)
        if folders:
            from shared.git_ignore_utils import collect_global_patterns

            collect_global_patterns(folders)

        _workspace_preload = {
            "workspace": workspace,
            "folders": folders,
            "ws_file": saved_ws_file,
            "ws_name": ws_name,
        }
    except Exception:
        _workspace_preload = None
    _workspace_preload_event.set()


threading.Thread(target=_preload_workspace_io, daemon=True).start()


def _run_startup_housekeeping():
    """Run startup housekeeping after first frame to keep first paint fast."""
    global _STARTUP_HOUSEKEEPING_DONE
    if _STARTUP_HOUSEKEEPING_DONE:
        return False

    # Deferred: crash log recovery and crash handler (not needed before first paint)
    from shared.crash_log import collect_native_crash, install_crash_handler

    collect_native_crash()
    install_crash_handler()

    # Deferred: exit tracker (imports faulthandler, signal, datetime)
    from shared.exit_tracker import install_exit_tracker

    install_exit_tracker()

    # Register normal exit logging via atexit
    import atexit

    from shared.crash_log import log_exit

    atexit.register(log_exit, "Normal exit")

    _STARTUP_HOUSEKEEPING_DONE = True
    return False


# Set PANGOCAIRO_BACKEND before GTK/Pango initializes, if configured.
# Must read settings.json directly — the settings module isn't loaded yet.
def _read_pango_backend():
    """Read font_rendering.pango_backend from settings.json (pre-GTK)."""
    settings_file = os.path.join(os.path.expanduser("~"), ".zen_ide", "settings.json")
    if not os.path.exists(settings_file):
        return "auto"
    try:
        import json as _json

        with open(settings_file, "r") as f:
            data = _json.load(f)
        return data.get("font_rendering", {}).get("pango_backend", "auto")
    except Exception:
        return "auto"


# Register resource fonts with CoreText/fontconfig BEFORE GTK/Pango initializes,
# so the first Pango font map enumeration includes them (avoids expensive refresh later).
# Fonts are loaded from binary .ttf files on disk (no Python module import overhead).
def _register_fonts_early():
    """Register bundled font .ttf files with CoreText before GTK starts (macOS only).

    Only CoreText registration survives Gtk.init() — fontconfig state is
    discarded when GTK re-initialises it.  Linux skips early registration;
    fonts are registered post-GTK by register_resource_fonts() instead.

    When using fontconfig/freetype backend (PANGOCAIRO_BACKEND=fc), skip early
    registration — fontconfig fonts must be registered post-GTK.

    Uses ctypes.util.find_library for portable library resolution (works on
    both Apple Silicon shared dyld cache and Intel Macs).
    """
    global _fonts_preregistered
    if sys.platform != "darwin":
        return

    # Skip CoreText registration if using fontconfig backend — fonts must be
    # registered with fontconfig post-GTK instead.
    pango_backend = _read_pango_backend()
    if pango_backend == "freetype":
        return

    import ctypes
    import ctypes.util

    fonts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "resources")
    font_files = (
        [os.path.join(fonts_dir, f) for f in os.listdir(fonts_dir) if f.endswith(".ttf")] if os.path.isdir(fonts_dir) else []
    )

    if not font_files:
        return

    try:
        ct_lib = ctypes.util.find_library("CoreText")
        cf_lib = ctypes.util.find_library("CoreFoundation")
        if not ct_lib or not cf_lib:
            return

        ct = ctypes.cdll.LoadLibrary(ct_lib)
        cf = ctypes.cdll.LoadLibrary(cf_lib)
        cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFURLCreateWithFileSystemPath.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_bool]
        cf.CFURLCreateWithFileSystemPath.restype = ctypes.c_void_p
        ct.CTFontManagerRegisterFontsForURL.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
        ct.CTFontManagerRegisterFontsForURL.restype = ctypes.c_bool
        kCFStringEncodingUTF8 = 0x08000100
        registered_any = False
        for font_file in font_files:
            path_str = cf.CFStringCreateWithCString(None, font_file.encode("utf-8"), kCFStringEncodingUTF8)
            url = cf.CFURLCreateWithFileSystemPath(None, path_str, 0, False)
            error = ctypes.c_void_p(0)
            ok = ct.CTFontManagerRegisterFontsForURL(url, 1, ctypes.byref(error))
            if ok:
                registered_any = True
        _fonts_preregistered = registered_any
    except Exception:
        pass


# Run font registration in a background thread — ctypes FFI calls release the
# GIL, so the ~17ms of CoreText work runs concurrently with gi_requirements +
# GTK C library loading (~274ms).  Joined before Gtk.init().
_fonts_preregistered = False
_font_thread = threading.Thread(target=_register_fonts_early, daemon=True)
_font_thread.start()


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

from gi.repository import Gdk, Gio, GLib, Gtk

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
# Join font thread first — fonts must be registered before Pango initializes
# its font map during Gtk.init().  The thread started ~274ms ago and its
# ~17ms of ctypes work completed long before this point.
_font_thread.join()
Gtk.init()

# Start preloading heavy modules in background threads immediately after
# Gtk.init().  They overlap with settings/theme/dark-theme/mixin imports
# below (~40ms of main-thread work).  The GIL releases during .pyc I/O and
# GTK CSS initialisation, giving genuine parallelism (~20ms saved).


def _preload_editor_module():
    import editor.editor_view  # noqa: F401
    import editor.split_panel_manager  # noqa: F401
    import fonts  # noqa: F401


def _preload_treeview_module():
    import treeview  # noqa: F401


_preload_editor_thread = threading.Thread(target=_preload_editor_module, daemon=True)
_preload_treeview_thread = threading.Thread(target=_preload_treeview_module, daemon=True)
_preload_editor_thread.start()
_preload_treeview_thread.start()

from shared.settings import get_setting, load_settings

load_settings()
from themes import set_theme

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

from constants import DEFAULT_FONT_SIZE, DEFAULT_WINDOW_HEIGHT, DEFAULT_WINDOW_WIDTH
from main.action_manager import ActionManager
from main.window_actions import WindowActionsMixin
from main.window_events import WindowEventsMixin
from main.window_fonts import WindowFontsMixin
from main.window_layout import WindowLayoutMixin
from main.window_panels import WindowPanelsMixin
from main.window_state import WindowStateMixin
from shared.settings import get_layout

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
            from shared.system_monitor import SystemMonitorPanel

            self._system_monitor = SystemMonitorPanel(on_close=lambda: self.split_panels.hide("system_monitor"))
            self._system_monitor.set_visible(False)
        return self._system_monitor

    @property
    def dev_pad(self):
        if self._dev_pad is None:
            from dev_pad import DevPad

            self._dev_pad = DevPad(
                open_file_callback=self._on_tree_file_selected,
                get_workspace_folders_callback=lambda: (
                    self.tree_view.get_workspace_folders() if hasattr(self, "tree_view") else []
                ),
            )
            self._dev_pad.set_size_request(200, -1)
            self._dev_pad.set_visible(False)
        return self._dev_pad

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
                "open_workspace": [f"{mod_shift}o"],
                "save": [f"{mod}s"],
                "close_tab": [f"{mod}w"],
                "quit": [f"{mod}q"],
                # Edit
                "undo": [f"{mod}z"],
                "redo": [f"{mod_shift}z"],
                "find": [f"{mod}f"],
                "find_replace": [f"{mod}h"],
                "go_to_line": [f"{mod}g"],
                "toggle_comment": [f"{mod}slash"],
                "indent": [f"{mod}bracketright"],
                "unindent": [f"{mod}bracketleft"],
                # View/Navigation
                "focus_explorer": [f"{mod_shift}e"],
                "clear_terminal": [f"{mod}k"],
                "global_search": [f"{mod_shift}f"],
                "quick_open": [f"{mod}p"],
                "show_diff": [f"{mod}d"],
                "show_dev_pad": [f"{mod}period"],
                "open_sketch_pad": [f"{mod_shift}d"],
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
                "theme_picker": [f"{mod_shift}t"],
                "toggle_dark_light": [f"{mod_shift}l"],
                "shortcuts": [f"{mod_shift}slash", f"{mod_shift}question"],
                "toggle_inspect": [f"{mod_shift}i"],
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


class ZenIDEApp(Gtk.Application):
    """GTK4 Application for Zen IDE."""

    def __init__(self):
        super().__init__(
            application_id="com.zenide.app",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE
            | Gio.ApplicationFlags.HANDLES_OPEN
            | Gio.ApplicationFlags.NON_UNIQUE,
        )
        self._pending_workspace = None
        self._pending_file = None
        self._pending_new_file = None
        self._pending_dir = None
        self._icon_paintable = None

        # On Linux, install the icon and set default icon name BEFORE any
        # window is created.  The window manager reads the icon at window
        # creation time — doing it later in a deferred callback is too late.
        if sys.platform == "linux":
            self._setup_app_icon_early()

    def _setup_app_icon_early(self):
        """Install the app icon into the icon theme BEFORE any window is created.

        On Linux, the window manager reads the icon at window-creation time
        via _NET_WM_ICON (X11) or the xdg-icon-theme (Wayland).  If the
        icon isn't installed and ``set_default_icon_name`` hasn't been called
        yet, the WM falls back to a generic icon and won't update it later.

        This method:
        1. Copies zen_icon.png into ~/.local/share/icons/hicolor/ at multiple
           standard sizes (48, 64, 128, 256) so icon lookups at any DPI work.
        2. Also installs into /usr/share/pixmaps/ as a universal fallback
           (some older DEs/WMs check pixmaps before the icon theme).
        3. Calls Gtk.Window.set_default_icon_name("zen-ide") so every
           GtkWindow created afterwards gets the correct _NET_WM_ICON.
        4. Installs the .desktop file for the current user.
        """
        src_dir = os.path.dirname(os.path.abspath(__file__))
        repo_root = os.path.dirname(src_dir)
        icon_path = os.path.join(repo_root, "zen_icon.png")

        if not os.path.exists(icon_path):
            return

        try:
            import shutil

            # Install icon at multiple sizes in the user's hicolor theme.
            # Many DEs (Cinnamon, KDE, XFCE) require the icon in the hicolor
            # theme hierarchy — /usr/share/pixmaps alone isn't always enough.
            for size in (48, 64, 128, 256):
                icon_dir = os.path.expanduser(f"~/.local/share/icons/hicolor/{size}x{size}/apps")
                os.makedirs(icon_dir, exist_ok=True)
                dest = os.path.join(icon_dir, "zen-ide.png")
                if not os.path.exists(dest) or os.path.getmtime(icon_path) > os.path.getmtime(dest):
                    shutil.copy2(icon_path, dest)

            # Also install a scalable/symbolic copy at the base apps/ level
            # (some compositors look here for SVG/PNG fallback)
            base_dir = os.path.expanduser("~/.local/share/icons/hicolor/scalable/apps")
            os.makedirs(base_dir, exist_ok=True)
            base_dest = os.path.join(base_dir, "zen-ide.png")
            if not os.path.exists(base_dest) or os.path.getmtime(icon_path) > os.path.getmtime(base_dest):
                shutil.copy2(icon_path, base_dest)

            # Install into ~/.local/share/pixmaps as a universal fallback
            pixmaps_dir = os.path.expanduser("~/.local/share/pixmaps")
            os.makedirs(pixmaps_dir, exist_ok=True)
            pixmaps_dest = os.path.join(pixmaps_dir, "zen-ide.png")
            if not os.path.exists(pixmaps_dest) or os.path.getmtime(icon_path) > os.path.getmtime(pixmaps_dest):
                shutil.copy2(icon_path, pixmaps_dest)

            # Install the .desktop file for the current user
            desktop_src = os.path.join(repo_root, "zen-ide.desktop")
            if os.path.exists(desktop_src):
                desktop_dir = os.path.expanduser("~/.local/share/applications")
                os.makedirs(desktop_dir, exist_ok=True)
                desktop_dest = os.path.join(desktop_dir, "zen-ide.desktop")
                if not os.path.exists(desktop_dest) or os.path.getmtime(desktop_src) > os.path.getmtime(desktop_dest):
                    shutil.copy2(desktop_src, desktop_dest)

            # Update the icon theme cache so the DE picks up the new icon
            # immediately (without requiring a logout).  Errors are silenced —
            # the cache will be rebuilt on next login anyway.
            try:
                import subprocess

                hicolor_dir = os.path.expanduser("~/.local/share/icons/hicolor")
                subprocess.Popen(
                    ["gtk-update-icon-cache", "-f", "-t", hicolor_dir],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                pass  # gtk-update-icon-cache not installed

        except Exception:
            pass  # Non-fatal — worst case the generic icon is shown

        # Tell GTK4 that every window should use this icon.  This must be
        # called BEFORE any Gtk.Window is instantiated — it sets the
        # _NET_WM_ICON property on X11 and the app_id icon on Wayland.
        Gtk.Window.set_default_icon_name("zen-ide")

    def _setup_app_icon(self):
        """Set the application icon from zen_icon.png (deferred call for texture + macOS)."""
        # Look for icon relative to this file's location
        src_dir = os.path.dirname(os.path.abspath(__file__))
        repo_root = os.path.dirname(src_dir)

        # Use zen_icon.png
        icon_path = os.path.join(repo_root, "zen_icon.png")

        # Load the icon as texture for direct use (About dialog, etc.)
        if os.path.exists(icon_path):
            try:
                self._icon_paintable = Gdk.Texture.new_from_filename(icon_path)
            except Exception:
                pass

        # Defer macOS dock icon (AppKit import is ~120ms — do it after first paint)
        if sys.platform == "darwin":
            GLib.idle_add(self._set_macos_dock_icon, icon_path)

    def _set_macos_dock_icon(self, icon_path):
        """Set the dock icon on macOS using AppKit and bring app to foreground."""
        try:
            from AppKit import NSApplication, NSImage

            ns_app = NSApplication.sharedApplication()
            # Bring the app to foreground on startup
            ns_app.activateIgnoringOtherApps_(True)

            if os.path.exists(icon_path):
                image = NSImage.alloc().initWithContentsOfFile_(icon_path)
                if image:
                    ns_app.setApplicationIconImage_(image)
        except ImportError:
            pass  # pyobjc not installed
        except Exception:
            pass
        return False  # Don't repeat (GLib.idle_add)

    def get_icon_paintable(self):
        """Get the app icon as a paintable for windows."""
        return self._icon_paintable

    def do_command_line(self, command_line):
        """Handle command line arguments."""
        args = command_line.get_arguments()
        if len(args) > 1:
            path = os.path.abspath(args[1])
            if path.endswith((".zen-workspace", ".code-workspace")) and os.path.isfile(path):
                self._pending_workspace = path
            elif os.path.isdir(path):
                self._pending_dir = path
            elif os.path.isfile(path):
                self._pending_file = path
            else:
                # File doesn't exist — open as a new unsaved file with that name
                self._pending_new_file = path
        self.activate()
        return 0

    def do_open(self, files, n_files, hint):
        """Handle files opened via macOS 'Open With' or drag-and-drop."""
        for gfile in files:
            path = gfile.get_path()
            if path and os.path.isfile(path):
                self._pending_file = os.path.abspath(path)
                break
        self.activate()

    def do_activate(self):
        """Called when the application is activated."""
        win = self.props.active_window
        if not win:
            # Heavy modules (editor, treeview, fonts) already preloaded by
            # background threads at module level — no imports needed here.

            # Start timing from our code (excludes GTK framework overhead in app.run())
            global _STARTUP_TIME
            _STARTUP_TIME = time.monotonic()
            win = ZenIDEWindow(self)

        # Set CLI arguments BEFORE present() — present() triggers the "map"
        # signal which runs _init_workspace synchronously, so these must be
        # available by then.
        if self._pending_file:
            win._cli_file = self._pending_file
            win.tree_view.set_visible(False)
            win.bottom_paned.set_visible(False)

        if self._pending_new_file:
            win._cli_new_file = self._pending_new_file
            win.tree_view.set_visible(False)
            win.bottom_paned.set_visible(False)

        if self._pending_workspace:
            win._cli_workspace = self._pending_workspace
            self._pending_workspace = None

        if self._pending_dir:
            win._cli_dir = self._pending_dir
            self._pending_dir = None

        win.present()

        # Defer main thread poll and housekeeping to after first paint
        from shared.main_thread import start_main_thread_poll

        start_main_thread_poll()
        GLib.idle_add(_run_startup_housekeeping)

        # Open single file after present (editor needs to be mapped first)
        if self._pending_file:
            path = self._pending_file
            self._pending_file = None
            GLib.idle_add(lambda: win.editor_view.open_file(path) and False)

        # Create new file tab for non-existent file path from CLI
        if self._pending_new_file:
            path = self._pending_new_file
            self._pending_new_file = None
            GLib.idle_add(lambda: win.editor_view.open_or_create_file(path) and False)


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
