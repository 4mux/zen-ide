"""Runtime hook for PyGObject/GTK4 — sets up paths for bundled GI typelibs and shared data."""

import os
import sys


def _setup_gi_paths():
    if getattr(sys, "frozen", False):
        bundle_dir = sys._MEIPASS
    else:
        return

    # GI typelib search path
    typelib_dir = os.path.join(bundle_dir, "gi_typelibs")
    if os.path.isdir(typelib_dir):
        os.environ["GI_TYPELIB_PATH"] = typelib_dir

    # GDK pixbuf loaders
    pixbuf_dir = os.path.join(bundle_dir, "lib", "gdk-pixbuf-2.0")
    if os.path.isdir(pixbuf_dir):
        os.environ["GDK_PIXBUF_MODULE_DIR"] = pixbuf_dir

    # XDG data dirs for schemas, icons, themes
    share_dir = os.path.join(bundle_dir, "share")
    if os.path.isdir(share_dir):
        os.environ["XDG_DATA_DIRS"] = share_dir + ":" + os.environ.get("XDG_DATA_DIRS", "/usr/share")
        os.environ["GSETTINGS_SCHEMA_DIR"] = os.path.join(share_dir, "glib-2.0", "schemas")

    # Fontconfig: inject bundled fonts directory into fontconfig's search path.
    # FcConfigAppFontAddFile registers into the "application" font set, but
    # Pango's PangoFcFontMap only enumerates the "system" font set.  The only
    # reliable way is to add a <dir> element via a custom fonts.conf wrapper
    # set BEFORE any library initializes fontconfig.
    _setup_fontconfig(bundle_dir)

    # Ensure PYTHONPATH includes src for relative imports
    src_dir = os.path.join(bundle_dir, "src")
    if os.path.isdir(src_dir) and src_dir not in sys.path:
        sys.path.insert(0, src_dir)


def _setup_fontconfig(bundle_dir):
    """Generate a fonts.conf wrapper that includes bundled fonts.

    Pango's PangoFcFontMap only enumerates fontconfig's *system* font set
    (populated from <dir> entries in fonts.conf), not the *application* set
    (populated by FcConfigAppFontAddFile).  The only reliable way to make
    bundled fonts visible to Pango is to add them via a <dir> element in
    fontconfig's configuration, set via FONTCONFIG_FILE before any library
    initializes fontconfig.
    """
    fonts_dir = os.path.join(bundle_dir, "fonts", "resources")
    if not os.path.isdir(fonts_dir):
        return

    import atexit
    import tempfile

    # Find the system fonts.conf to include
    system_conf = None
    for candidate in ["/opt/homebrew/etc/fonts/fonts.conf", "/usr/local/etc/fonts/fonts.conf", "/etc/fonts/fonts.conf"]:
        if os.path.isfile(candidate):
            system_conf = candidate
            break

    # Write a wrapper fonts.conf that includes the system config + our font dir
    conf = '<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">\n<fontconfig>\n'
    if system_conf:
        conf += f"  <include>{system_conf}</include>\n"
    conf += f"  <dir>{fonts_dir}</dir>\n"
    conf += "</fontconfig>\n"

    fd, conf_path = tempfile.mkstemp(prefix="zen-fonts-", suffix=".conf")
    os.write(fd, conf.encode("utf-8"))
    os.close(fd)
    os.environ["FONTCONFIG_FILE"] = conf_path

    atexit.register(lambda: os.unlink(conf_path) if os.path.exists(conf_path) else None)


_setup_gi_paths()


def _patch_pygobject_glib_bug():
    """Work around PyGObject 3.56.0 bug with GLib 2.88+.

    PyGObject 3.56.0 unconditionally registers ``unix_signal_add_full`` as a
    deprecated attr (via ``GLibUnix.signal_add``) even when that symbol was
    never added to the overrides module's ``__all__`` (because
    ``GLib.unix_signal_add`` no longer exists in GLib 2.88).  This makes
    ``load_overrides()`` crash with::

        AssertionError: unix_signal_add_full was set deprecated
                        but wasn't added to __all__

    Fix: replace ``load_overrides`` with a copy that changes **one line** —
    the deprecated-attrs loop catches ``AttributeError`` and skips instead of
    raising ``AssertionError``.  Everything else is identical to the upstream
    implementation.  This is safe because skipping an orphaned deprecated attr
    only means one fewer deprecation warning — no functionality is lost.

    See: https://gitlab.gnome.org/GNOME/pygobject/-/issues/706
    """
    if not getattr(sys, "frozen", False):
        return
    try:
        import importlib

        import gi.overrides as _ov

        # Rewrite load_overrides with the only change being: the deprecated-
        # attrs loop catches AttributeError and skips instead of raising
        # AssertionError.  Everything else is identical to the original.
        from gi import PyGIDeprecationWarning

        def _safe_load_overrides(introspection_module):
            namespace = introspection_module.__name__.rsplit(".", 1)[-1]
            module_key = "gi.repository." + namespace

            has_old = module_key in sys.modules
            old_module = sys.modules.get(module_key)

            proxy = _ov.OverridesProxyModule(introspection_module)
            sys.modules[module_key] = proxy

            from gi.importer import modules

            assert hasattr(proxy, "_introspection_module")
            modules[namespace] = proxy

            try:
                override_package_name = "gi.overrides." + namespace
                spec = importlib.util.find_spec(override_package_name)
                override_loader = spec.loader if spec is not None else None

                if override_loader is None:
                    return introspection_module

                override_mod = importlib.import_module(override_package_name)
            finally:
                del modules[namespace]
                del sys.modules[module_key]
                if has_old:
                    sys.modules[module_key] = old_module

            proxy._overrides_module = proxy

            override_all = []
            if hasattr(override_mod, "__all__"):
                override_all = override_mod.__all__

            for var in override_all:
                try:
                    item = getattr(override_mod, var)
                except (AttributeError, TypeError):
                    continue
                setattr(proxy, var, item)

            # THIS IS THE ONLY CHANGE: skip missing attrs instead of raising
            for attr, replacement in _ov._deprecated_attrs.pop(namespace, []):
                try:
                    value = getattr(proxy, attr)
                except AttributeError:
                    continue  # <-- was: raise AssertionError(...)
                delattr(proxy, attr)
                proxy._deprecations[attr] = (
                    value,
                    PyGIDeprecationWarning(f"{namespace}.{attr} is deprecated; use {replacement} instead"),
                )

            return proxy

        _ov.load_overrides = _safe_load_overrides
    except Exception:
        pass


_patch_pygobject_glib_bug()


def _show_cocoa_splash():
    """Show a native Cocoa window immediately to stop dock icon bouncing.

    When launched via the native Swift launcher, a splash window is already
    showing — skip creating another one. The launcher sets _ZEN_LAUNCHER_SPLASH=1.
    In direct execution (e.g. development), show a Python-level splash.
    """
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return

    # Native launcher already showed a splash — nothing to do
    if os.environ.get("_ZEN_LAUNCHER_SPLASH"):
        return

    try:
        from AppKit import NSApplication, NSColor, NSWindow
        from Foundation import NSMakeRect

        ns_app = NSApplication.sharedApplication()
        ns_app.setActivationPolicy_(0)  # NSApplicationActivationPolicyRegular

        # Create a minimal dark window matching the GTK window's appearance
        frame = NSMakeRect(0, 0, 900, 600)
        # styleMask: titled(1) | closable(2) | miniaturizable(4) | resizable(8) = 15
        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            15,
            2,
            False,  # NSBackingStoreBuffered = 2
        )
        window.setTitle_("Zen IDE")
        window.setBackgroundColor_(NSColor.colorWithRed_green_blue_alpha_(0.11, 0.11, 0.14, 1.0))
        window.center()
        window.makeKeyAndOrderFront_(None)

        # Activate app to bring window to front
        try:
            ns_app.activate()
        except (AttributeError, TypeError):
            ns_app.activateIgnoringOtherApps_(True)

        # Store reference for cleanup by zen_ide_window.py
        import builtins

        builtins._zen_splash_window = window
        # Signal that AppKit is already loaded (skip background preload in zen_ide_window.py)
        os.environ["_ZEN_APPKIT_PRELOADED"] = "1"
    except ImportError:
        pass
    except Exception:
        pass


_show_cocoa_splash()
