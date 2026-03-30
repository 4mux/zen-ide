"""Tests for font registration — ensures bundled fonts are visible to Pango.

Regression: CoreText process-scoped font registration returns success but
Pango never sees the fonts.  All registration now uses fontconfig which
makes fonts reliably visible to Pango on all platforms.
"""

import inspect
from pathlib import Path
from unittest.mock import patch

import gi

gi.require_version("PangoCairo", "1.0")


class TestFontRegistrationBackendSelection:
    """Test that font registration always uses fontconfig (not CoreText).

    Regression: CoreText process-scoped registration returns success but
    Pango never sees the fonts. Fontconfig works on all platforms.
    """

    def test_fontconfig_always_used(self):
        """register_resource_fonts() should always use fontconfig, never CoreText."""
        from fonts import font_manager

        font_manager._resource_fonts_registered = False

        # Mock the early-thread fast path so we exercise the full fallback code path
        with patch.dict("sys.modules", {"zen_ide_window": None}):
            with patch.object(font_manager, "_fonts_already_in_pango", return_value=False):
                with patch.object(font_manager, "_register_fonts_fontconfig_files") as mock_fc:
                    with patch.object(font_manager, "_refresh_pango_font_map"):
                        font_manager.register_resource_fonts()

        mock_fc.assert_called_once()

    def test_no_coretext_registration_function(self):
        """font_manager must not have _register_fonts_macos (CoreText removed)."""
        from fonts import font_manager

        assert not hasattr(font_manager, "_register_fonts_macos"), (
            "_register_fonts_macos still exists — CoreText registration is invisible to Pango"
        )

    def test_register_resource_fonts_no_coretext_in_source(self):
        """register_resource_fonts source must not dispatch to CoreText on macOS."""
        from fonts import font_manager

        source = inspect.getsource(font_manager.register_resource_fonts)
        assert "darwin" not in source, "register_resource_fonts should not branch on platform — fontconfig works everywhere"


class TestEarlyFontRegistrationUsesFontconfig:
    """Test that early font registration uses fontconfig on all platforms.

    Regression: CoreText process-scoped fonts are invisible to Pango.
    The early registration must use fontconfig for fonts to be visible.

    NOTE: We verify via source inspection rather than calling _register_fonts_early()
    because importing app_preload triggers background threads with global side effects.
    """

    def _get_early_registration_source(self):
        """Read the source of _register_fonts_early without importing app_preload."""
        source_file = Path(__file__).parent.parent.parent / "src" / "app_preload.py"
        return source_file.read_text()

    def test_early_registration_no_coretext_in_source(self):
        """_register_fonts_early must not use CTFontManager (CoreText)."""
        source = self._get_early_registration_source()
        # Extract the function body
        start = source.index("def _register_fonts_early()")
        # Find the next top-level def/class or module-level statement
        end = source.index("\n\n\n", start)
        func_source = source[start:end]
        assert "CTFontManager" not in func_source, "_register_fonts_early still uses CoreText — invisible to Pango"
        assert "FcConfigAppFontAddFile" in func_source, "_register_fonts_early must use fontconfig for Pango visibility"

    def test_early_registration_no_platform_branch(self):
        """_register_fonts_early must not branch on sys.platform for macOS CoreText."""
        source = self._get_early_registration_source()
        start = source.index("def _register_fonts_early()")
        end = source.index("\n\n\n", start)
        func_source = source[start:end]
        assert 'sys.platform == "darwin"' not in func_source, "_register_fonts_early should use fontconfig on all platforms"


class TestSourceCodeProPangoVisibility:
    """End-to-end: Source Code Pro must be visible to Pango after registration.

    Regression: The dist app started corrupted because CoreText-registered
    fonts were invisible to Pango.  This test catches the bug directly.
    """

    def test_source_code_pro_visible_after_fontconfig_registration(self):
        """After fontconfig registration, Pango font map must include Source Code Pro."""
        import ctypes
        import ctypes.util

        from gi.repository import PangoCairo

        from fonts.font_manager import DEFAULT_FONT

        project_root = Path(__file__).parent.parent.parent
        font_file = project_root / "src" / "fonts" / "resources" / "SourceCodePro-VariableFont_wght.ttf"
        assert font_file.exists(), f"Font file missing: {font_file}"

        # Register via fontconfig (the production code path)
        fc_lib = ctypes.util.find_library("fontconfig")
        assert fc_lib, "fontconfig not available"
        fc = ctypes.cdll.LoadLibrary(fc_lib)
        fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        fc.FcConfigAppFontAddFile.restype = ctypes.c_int
        ok = fc.FcConfigAppFontAddFile(None, str(font_file).encode("utf-8"))
        assert ok, "fontconfig failed to register SourceCodePro"

        # Create a fresh font map — the cached default may predate registration.
        # In production, fonts are registered BEFORE Gtk.init() creates the
        # initial font map, so a fresh map correctly reflects reality.
        fresh_map = PangoCairo.FontMap.new()
        families = {f.get_name() for f in fresh_map.list_families()}
        assert DEFAULT_FONT in families, (
            f"'{DEFAULT_FONT}' not visible in a fresh Pango font map after fontconfig "
            f"registration. This was the dist app corruption bug — fonts registered "
            f"via CoreText are invisible to Pango."
        )

    def test_source_code_pro_font_file_valid(self):
        """The SourceCodePro variable font must exist and not be corrupted."""
        project_root = Path(__file__).parent.parent.parent
        font_file = project_root / "src" / "fonts" / "resources" / "SourceCodePro-VariableFont_wght.ttf"
        assert font_file.exists()
        # Variable font should be at least 100KB
        assert font_file.stat().st_size > 100_000, "Font file may be corrupted"
