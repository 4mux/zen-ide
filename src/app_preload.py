"""App preloading — background threads for fonts, workspace I/O, AppKit, and startup housekeeping."""

import os
import sys
import threading

# Preload macOS AppKit in background thread for instant foreground activation
# at first paint. The import takes ~200ms but runs concurrently with GTK init,
# so it's ready well before the window maps.
# In frozen bundles, AppKit is already loaded by the runtime hook splash window.
_macos_appkit_loaded = None

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


_STARTUP_HOUSEKEEPING_DONE = False


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


# Register resource fonts with fontconfig BEFORE GTK/Pango initializes,
# so the first Pango font map enumeration includes them (avoids expensive
# refresh/swap on the critical path — saves ~24ms).
# Fonts are loaded from binary .ttf files on disk (no Python module import overhead).
def _register_fonts_early():
    """Register bundled .ttf files before GTK starts.

    Uses fontconfig on all platforms (app-font state survives Gtk.init()).
    CoreText process-scoped registration is invisible to Pango's font map.
    Runs in a background thread (~11ms of ctypes FFI, concurrent with
    gi_requirements + GTK C library loading).
    """
    global _fonts_preregistered

    import ctypes
    import ctypes.util

    fonts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "resources")
    font_files = (
        [os.path.join(fonts_dir, f) for f in os.listdir(fonts_dir) if f.endswith(".ttf")] if os.path.isdir(fonts_dir) else []
    )

    if not font_files:
        return

    try:
        # Use fontconfig on all platforms — CoreText process-scoped registration
        # is invisible to Pango's font map, but fontconfig works reliably.
        fc_lib = ctypes.util.find_library("fontconfig")
        if not fc_lib:
            return

        fc = ctypes.cdll.LoadLibrary(fc_lib)
        fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        fc.FcConfigAppFontAddFile.restype = ctypes.c_int
        registered_any = False
        for font_file in font_files:
            ok = fc.FcConfigAppFontAddFile(None, font_file.encode("utf-8"))
            if ok:
                registered_any = True
        _fonts_preregistered = registered_any
    except Exception:
        pass


# Run font registration in a background thread — ctypes FFI calls release the
# GIL, so the ~11ms of fontconfig work runs concurrently with gi_requirements +
# GTK C library loading (~274ms).  Joined before Gtk.init().
_fonts_preregistered = False
_font_thread = threading.Thread(target=_register_fonts_early, daemon=True)
_font_thread.start()


def _preload_editor_module():
    import editor.editor_view  # noqa: F401
    import editor.split_panel_manager  # noqa: F401
    import fonts  # noqa: F401


def _preload_treeview_module():
    import treeview  # noqa: F401
