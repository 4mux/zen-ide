"""Tests for font registration — ensures bundled fonts are visible to Pango.

Regression: CoreText process-scoped font registration returns success but
Pango never sees the fonts.  All registration now uses fontconfig which
makes fonts reliably visible to Pango on all platforms.
"""

import inspect
from pathlib import Path
from unittest.mock import patch


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


class TestFontconfigDirIntegration:
    """Test that the FONTCONFIG_FILE + <dir> mechanism makes fonts visible to Pango.

    Regression: The dist app started corrupted because neither CoreText nor
    FcConfigAppFontAddFile made bundled fonts visible to Pango.  The fix
    generates a fonts.conf with a <dir> pointing to the bundled fonts, set
    via FONTCONFIG_FILE in the PyInstaller runtime hook.
    """

    def test_setup_fontconfig_generates_valid_conf(self, tmp_path):
        """_setup_fontconfig must create a fonts.conf with <dir> for bundled fonts."""
        import importlib
        import sys

        # Import the runtime hook module
        hook_path = Path(__file__).parent.parent.parent / "tools" / "pyinstaller_hooks"
        sys.path.insert(0, str(hook_path))
        try:
            import rthook_gi

            importlib.reload(rthook_gi)

            # Create a fake bundle_dir with fonts/resources
            fonts_dir = tmp_path / "fonts" / "resources"
            fonts_dir.mkdir(parents=True)
            (fonts_dir / "SourceCodePro-VariableFont_wght.ttf").write_bytes(b"\x00" * 100)

            rthook_gi._setup_fontconfig(str(tmp_path))

            # Verify FONTCONFIG_FILE was set
            import os

            conf_path = os.environ.get("FONTCONFIG_FILE")
            assert conf_path, "FONTCONFIG_FILE not set by _setup_fontconfig"
            assert os.path.isfile(conf_path), f"fonts.conf not created at {conf_path}"

            # Verify the generated config includes the font directory
            conf_content = Path(conf_path).read_text()
            assert f"<dir>{fonts_dir}</dir>" in conf_content, (
                "fonts.conf must include <dir> for bundled fonts — FcConfigAppFontAddFile alone is invisible to Pango"
            )
            assert '<?xml version="1.0"?>' in conf_content
            assert "<fontconfig>" in conf_content

            # Clean up
            os.unlink(conf_path)
            os.environ.pop("FONTCONFIG_FILE", None)
        finally:
            sys.path.remove(str(hook_path))
            sys.modules.pop("rthook_gi", None)

    def test_source_code_pro_font_file_valid(self):
        """The SourceCodePro variable font must exist and not be corrupted."""
        project_root = Path(__file__).parent.parent.parent
        font_file = project_root / "src" / "fonts" / "resources" / "SourceCodePro-VariableFont_wght.ttf"
        assert font_file.exists()
        # Variable font should be at least 100KB
        assert font_file.stat().st_size > 100_000, "Font file may be corrupted"

    def test_all_bundled_fonts_exist(self):
        """All 3 bundled font files must exist in fonts/resources."""
        resources = Path(__file__).parent.parent.parent / "src" / "fonts" / "resources"
        expected = [
            "SourceCodePro-VariableFont_wght.ttf",
            "ZenIcons.ttf",
            "SymbolsNerdFont-Regular.ttf",
        ]
        for name in expected:
            assert (resources / name).exists(), f"Bundled font missing: {name}"
