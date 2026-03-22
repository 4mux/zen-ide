"""
Theme manager for Zen IDE.
Handles theme switching, settings persistence, and subscriptions.
"""

import threading
from typing import Callable, List, Optional

from shared.settings import (
    get_setting as _get_setting,
)
from shared.settings import (
    get_settings as _get_settings,
)
from shared.settings import (
    set_setting as _set_setting,
)
from themes.theme_definitions import THEMES
from themes.theme_model import Theme

_file_watcher_thread: Optional[threading.Thread] = None
_file_watcher_stop = threading.Event()


def _load_saved_theme() -> str:
    """Load the saved theme name from settings file."""
    return _get_setting("theme", "zen_dark")


def _save_theme(name: str) -> None:
    """Save the theme name to settings file."""
    _set_setting("theme", name)


# Load saved theme on startup
_saved_theme_name = _load_saved_theme()
_current_theme: Theme = THEMES.get(_saved_theme_name) or THEMES["zen_dark"]
_theme_subscribers: List[Callable[[Theme], None]] = []
_settings_subscribers: List[Callable[[str, any], None]] = []


def get_theme() -> Theme:
    """Get the current theme."""
    return _current_theme


def set_theme(name: str, persist: bool = True) -> Theme:
    """Set the current theme by name and notify subscribers."""
    global _current_theme
    if name in THEMES:
        _current_theme = THEMES[name]
        if persist:
            _save_theme(name)
            # Track last-used theme per mode for dark/light toggle
            if _current_theme.is_dark:
                _set_setting("last_dark_theme", name)
            else:
                _set_setting("last_light_theme", name)
        for callback in _theme_subscribers:
            try:
                callback(_current_theme)
            except Exception:
                pass
    return _current_theme


def subscribe_theme_change(callback: Callable[[Theme], None]) -> None:
    """Subscribe to theme changes. Callback receives the new Theme."""
    if callback not in _theme_subscribers:
        _theme_subscribers.append(callback)


def unsubscribe_theme_change(callback: Callable[[Theme], None]) -> None:
    """Unsubscribe from theme changes."""
    if callback in _theme_subscribers:
        _theme_subscribers.remove(callback)


def get_theme_names() -> List[tuple]:
    """Get list of available theme names without importing theme modules."""
    from themes.theme_definitions import get_theme_metadata

    return [(name, display_name) for name, display_name, _ in get_theme_metadata()]


def toggle_dark_light() -> Theme:
    """Toggle between dark and light mode.

    Remembers the last-used theme in each mode so toggling back restores
    the previous preference.
    """
    current = _current_theme
    if current.is_dark:
        # Switching to light — use saved light preference or default
        target = _get_setting("last_light_theme", "zen_light")
        if target not in THEMES or THEMES[target].is_dark:
            target = "zen_light"
    else:
        # Switching to dark — use saved dark preference or default
        target = _get_setting("last_dark_theme", "zen_dark")
        if target not in THEMES or not THEMES[target].is_dark:
            target = "zen_dark"

    # Remember current theme as the last-used in its mode
    if current.is_dark:
        _set_setting("last_dark_theme", current.name)
    else:
        _set_setting("last_light_theme", current.name)

    return set_theme(target, persist=True)


# ============= Settings Management =============


def get_setting(key: str, default=None):
    """Get a setting value."""
    return _get_setting(key, default)


def set_setting(key: str, value, persist: bool = True) -> None:
    """Set a setting value and notify subscribers."""
    if persist:
        _set_setting(key, value)
    else:
        data = _get_settings()
        if "." in key:
            parts = key.split(".")
            current = data
            for part in parts[:-1]:
                if part not in current or not isinstance(current[part], dict):
                    current[part] = {}
                current = current[part]
            current[parts[-1]] = value
        else:
            data[key] = value
    for callback in _settings_subscribers:
        try:
            callback(key, value)
        except Exception:
            pass


def subscribe_settings_change(callback: Callable[[str, any], None]) -> None:
    """Subscribe to settings changes. Callback receives (key, value)."""
    if callback not in _settings_subscribers:
        _settings_subscribers.append(callback)


def get_ai_settings() -> dict:
    """Get AI settings."""
    return get_setting("ai", {})


def get_view_spacing() -> int:
    """Get the spacing between main views in pixels (0-30)."""
    spacing = get_setting("view_spacing", 10)
    return max(0, min(30, int(spacing)))
