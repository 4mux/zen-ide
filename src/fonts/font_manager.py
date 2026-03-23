"""
Font Manager for Zen IDE - Centralized font handling.

This is the single source of truth for all font operations in Zen IDE.
All font loading, saving, defaults, and font-related utilities should go through this module.
"""

import sys
from typing import Callable, List, Optional

from gi.repository import Pango

from constants import DEFAULT_FONT_SIZE, MAX_FONT_SIZE, MIN_FONT_SIZE
from shared.utils import get_pango_font_map

# Canonical weight maps — single source of truth for all components.
# Components must import these instead of defining local copies.
PANGO_WEIGHT_MAP: dict[str, Pango.Weight] = {
    "thin": Pango.Weight.THIN,
    "light": Pango.Weight.LIGHT,
    "normal": Pango.Weight.NORMAL,
    "medium": Pango.Weight.MEDIUM,
    "semibold": Pango.Weight.SEMIBOLD,
    "bold": Pango.Weight.BOLD,
    "heavy": Pango.Weight.HEAVY,
}

CSS_WEIGHT_MAP: dict[str, int] = {
    "thin": 100,
    "light": 300,
    "normal": 400,
    "medium": 500,
    "semibold": 600,
    "bold": 700,
    "heavy": 900,
}

# Single default font — bundled Source Code Pro variable font (all weights in one file).
DEFAULT_FONT = "Source Code Pro"

# Default proportional font for markdown/OpenAPI prose.
DEFAULT_PROSE_FONT = "sans"

# macOS CoreText renders text thinner — "medium" (500) produces bolder, more readable glyphs.
DEFAULT_FONT_WEIGHT = "medium" if sys.platform == "darwin" else "normal"

# Track registered resource fonts
_resource_fonts_registered = False


def _fonts_already_in_pango() -> bool:
    """Check whether bundled fonts are already visible in Pango's font map."""
    try:
        font_map = get_pango_font_map()
        families = {f.get_name() for f in font_map.list_families()}
        return DEFAULT_FONT in families
    except Exception:
        return False


def register_resource_fonts() -> None:
    """Register font files from embedded data with the OS font system.

    Uses fontconfig on all platforms (including macOS).  Fonts stay
    app-scoped — never installed system-wide.

    If the early background thread (zen_ide.py) already registered fonts via
    fontconfig before Gtk.init(), its ``_fonts_preregistered`` flag is checked
    first (zero-cost).  Falls back to Pango font map enumeration if the flag
    is unavailable, and re-registers from .ttf files on disk as a last resort.
    """
    global _resource_fonts_registered
    if _resource_fonts_registered:
        return
    _resource_fonts_registered = True

    # Fast path: early thread already registered fonts via fontconfig.
    try:
        import zen_ide

        if zen_ide._fonts_preregistered:
            return
    except (ImportError, AttributeError):
        pass

    # Fallback: check Pango font map (expensive ~8ms, but only if early thread failed).
    if _fonts_already_in_pango():
        return

    # Fonts not visible — register from TTF files on disk.
    from pathlib import Path

    resources_dir = Path(__file__).parent / "resources"
    font_files = sorted(resources_dir.glob("*.ttf"))

    if not font_files:
        return

    _register_fonts_fontconfig_files(font_files)

    # Force Pango to re-enumerate fonts so newly registered fonts are visible
    _refresh_pango_font_map()


def _register_fonts_macos(font_files: List) -> None:
    """Register fonts using macOS CoreText (process-scoped)."""
    try:
        import ctypes
        import ctypes.util

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
        kCFURLPOSIXPathStyle = 0
        kCTFontManagerScopeProcess = 1

        for font_file in font_files:
            path_str = cf.CFStringCreateWithCString(None, str(font_file).encode("utf-8"), kCFStringEncodingUTF8)
            url = cf.CFURLCreateWithFileSystemPath(None, path_str, kCFURLPOSIXPathStyle, False)
            error = ctypes.c_void_p(0)
            ct.CTFontManagerRegisterFontsForURL(url, kCTFontManagerScopeProcess, ctypes.byref(error))
    except Exception:
        pass


def _refresh_pango_font_map() -> None:
    """Signal Pango that available fonts may have changed.

    After registering fonts with CoreText/fontconfig, the existing Pango
    font map singleton may have cached its family list without the new fonts.
    Calling changed() forces re-enumeration on next access.

    On macOS, the PangoCairoCoreTextFontMap may not pick up post-Gtk.init()
    CoreText registrations via changed() alone.  In that case, create a fresh
    font map (which queries CoreText anew) and swap it in as the default.
    """
    try:
        font_map = get_pango_font_map()
        font_map.changed()
    except Exception:
        pass

    # On macOS CoreText, changed() often isn't enough for post-GTK registrations.
    if not _fonts_already_in_pango():
        _swap_pango_font_map()


def _swap_pango_font_map() -> None:
    """Replace the default PangoCairo font map with a freshly created one.

    A new PangoCairo.FontMap queries CoreText/fontconfig from scratch, picking
    up any fonts registered since the original map was created.  Also updates
    the cache in get_pango_font_map() so all subsequent callers see the new map.
    """
    try:
        from gi.repository import PangoCairo

        new_map = PangoCairo.FontMap.new()
        PangoCairo.FontMap.set_default(new_map)
        # Update the cached reference used by the rest of the codebase.
        get_pango_font_map._cached = new_map
    except Exception:
        pass


def _register_fonts_fontconfig(resources_path) -> None:
    """Register fonts using fontconfig (Linux) - directory mode."""
    try:
        import ctypes
        import ctypes.util

        fc_lib = ctypes.util.find_library("fontconfig")
        if not fc_lib:
            return

        fc = ctypes.cdll.LoadLibrary(fc_lib)
        fc.FcConfigAppFontAddDir.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        fc.FcConfigAppFontAddDir.restype = ctypes.c_int
        fc.FcConfigAppFontAddDir(None, str(resources_path).encode())
    except Exception:
        pass


def _register_fonts_fontconfig_files(font_files: List) -> None:
    """Register individual font files using fontconfig (Linux)."""
    try:
        import ctypes
        import ctypes.util

        fc_lib = ctypes.util.find_library("fontconfig")
        if not fc_lib:
            return

        fc = ctypes.cdll.LoadLibrary(fc_lib)
        fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        fc.FcConfigAppFontAddFile.restype = ctypes.c_int
        for font_file in font_files:
            fc.FcConfigAppFontAddFile(None, str(font_file).encode())
    except Exception:
        pass


# Component types
FONT_COMPONENTS = ["editor", "terminal", "explorer", "ai_chat", "markdown_preview", "dev_pad"]


class FontManager:
    """Centralized font manager for Zen IDE.

    Single source of truth for:
    - Font defaults (platform-specific)
    - Font settings (load/save per component)
    - Font availability checks
    - Font subscriptions (notify on changes)
    """

    _instance: Optional["FontManager"] = None

    def __new__(cls) -> "FontManager":
        """Singleton pattern - only one FontManager instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._font_subscribers: List[Callable[[str, dict], None]] = []

    # ============= Default Fonts =============

    def get_default_editor_font(self) -> str:
        """Get the default editor font (bundled Source Code Pro)."""
        return DEFAULT_FONT

    def get_default_terminal_font(self) -> str:
        """Get the default terminal font (bundled Source Code Pro)."""
        return DEFAULT_FONT

    def get_default_ui_font(self) -> str:
        """Get the default UI font (bundled Source Code Pro)."""
        return DEFAULT_FONT

    def get_default_size_for_component(self, component: str) -> int:
        """Get the default font size for a specific component.

        Args:
            component: One of 'editor', 'terminal', 'explorer', 'ai_chat', 'markdown_preview'

        Returns:
            Default font size in points
        """
        if component == "markdown_preview":
            return 14
        return DEFAULT_FONT_SIZE  # 16 for all components

    # ============= Font Settings =============

    def get_font_settings(self, component: str) -> dict:
        """Get font settings for a specific component.

        This is the primary method for getting font settings. It handles:
        - Reading from settings file
        - Backward compatibility with old format
        - Returning defaults if not set

        Args:
            component: One of 'editor', 'terminal', 'explorer', 'ai_chat', 'markdown_preview'

        Returns:
            Dict with 'family', 'size', 'weight' keys
        """
        from shared.settings import get_setting

        default_size = self.get_default_size_for_component(component)
        default_weight = DEFAULT_FONT_WEIGHT if component != "explorer" else "medium"
        default_family = DEFAULT_PROSE_FONT if component == "markdown_preview" else DEFAULT_FONT
        default = {"family": default_family, "size": default_size, "weight": default_weight}

        # Try new format first: fonts.{component}
        fonts = get_setting("fonts", {})
        if component in fonts:
            result = fonts.get(component, default)
            # Normalise empty family from legacy settings
            if not result.get("family"):
                result["family"] = default_family
            return result

        return default

    def set_font_settings(
        self,
        component: str,
        family: Optional[str] = None,
        size: Optional[int] = None,
        weight: Optional[str] = None,
    ) -> None:
        """Set font settings for a specific component.

        Args:
            component: One of 'editor', 'terminal', 'explorer', 'ai_chat', 'markdown_preview'
            family: Font family name (None to keep current)
            size: Font size in points (None to keep current)
            weight: Font weight ('light', 'normal', 'medium', 'bold') (None to keep current)
        """
        from shared.settings import set_setting

        current = self.get_font_settings(component)

        if family is not None:
            current["family"] = family
        if size is not None:
            current["size"] = self._clamp_font_size(size)
        if weight is not None:
            current["weight"] = weight

        set_setting(f"fonts.{component}", current)

        # Notify subscribers
        self._notify_font_change(component, current)

    def _clamp_font_size(self, size: int) -> int:
        """Clamp font size to valid range."""
        return max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, size))

    # ============= Font Utilities =============

    def font_exists(self, font_name: str) -> bool:
        """Check if a font exists on the system.

        Args:
            font_name: Font family name to check

        Returns:
            True if font is available
        """
        font_map = get_pango_font_map()
        families = font_map.list_families()
        family_names = [f.get_name() for f in families]
        return font_name in family_names

    def create_font_description(
        self,
        family: str,
        size: int = 12,
        weight: str = "normal",
    ) -> Pango.FontDescription:
        """Create a Pango FontDescription.

        Args:
            family: Font family name
            size: Font size in points
            weight: Font weight ('light', 'normal', 'medium', 'bold')

        Returns:
            Pango.FontDescription instance
        """
        font_desc = Pango.FontDescription()
        font_desc.set_family(family)
        font_desc.set_size(size * Pango.SCALE)
        font_desc.set_weight(PANGO_WEIGHT_MAP.get(weight, Pango.Weight.NORMAL))

        return font_desc

    def get_all_system_fonts(self) -> List[str]:
        """Get all fonts available on the system.

        Returns:
            Sorted list of font family names
        """
        try:
            font_map = get_pango_font_map()
            families = font_map.list_families()
            return sorted([f.get_name() for f in families], key=str.lower)
        except Exception:
            return []

    # ============= Subscriptions =============

    def subscribe_font_change(self, callback: Callable[[str, dict], None]) -> None:
        """Subscribe to font setting changes.

        Args:
            callback: Function(component, settings) called when fonts change
        """
        if callback not in self._font_subscribers:
            self._font_subscribers.append(callback)

    def _notify_font_change(self, component: str, settings: dict) -> None:
        """Notify all subscribers of a font change."""
        for callback in self._font_subscribers:
            try:
                callback(component, settings)
            except Exception:
                pass


# ============= Module-level API =============

# NOTE: register_resource_fonts() is called from ZenIDEWindow._deferred_init()
# (after first paint) to avoid ~300ms startup penalty from CoreText registration.

_font_manager: Optional[FontManager] = None


def get_font_manager() -> FontManager:
    """Get the singleton FontManager instance."""
    global _font_manager
    if _font_manager is None:
        _font_manager = FontManager()
    return _font_manager


# Convenience functions that delegate to FontManager
def get_font_settings(component: str) -> dict:
    """Get font settings for a component."""
    return get_font_manager().get_font_settings(component)


def set_font_settings(
    component: str,
    family: Optional[str] = None,
    size: Optional[int] = None,
    weight: Optional[str] = None,
) -> None:
    """Set font settings for a component."""
    get_font_manager().set_font_settings(component, family, size, weight)


def subscribe_font_change(callback: Callable[[str, dict], None]) -> None:
    """Subscribe to font setting changes. Callback receives (component, settings)."""
    get_font_manager().subscribe_font_change(callback)


def get_default_editor_font() -> str:
    """Get the default editor font for the current platform."""
    return get_font_manager().get_default_editor_font()


def get_default_terminal_font() -> str:
    """Get the default terminal font for the current platform."""
    return get_font_manager().get_default_terminal_font()


def get_default_ui_font() -> str:
    """Get the default UI font (bundled Source Code Pro)."""
    return get_font_manager().get_default_ui_font()


def font_exists(font_name: str) -> bool:
    """Check if a font exists on the system."""
    return get_font_manager().font_exists(font_name)


def create_font_description(
    family: str,
    size: int = 12,
    weight: str = "normal",
) -> Pango.FontDescription:
    """Create a Pango FontDescription."""
    return get_font_manager().create_font_description(family, size, weight)
