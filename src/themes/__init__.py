"""
Theme package for Zen IDE.
Re-exports all public API from submodules.
"""

from themes.theme_definitions import THEMES
from themes.theme_manager import (
    get_ai_settings,
    get_setting,
    get_theme,
    get_theme_names,
    get_view_spacing,
    set_setting,
    set_theme,
    subscribe_settings_change,
    subscribe_theme_change,
    toggle_dark_light,
    unsubscribe_theme_change,
)
from themes.theme_model import Theme

__all__ = [
    "Theme",
    "THEMES",
    "get_theme",
    "set_theme",
    "get_theme_names",
    "subscribe_theme_change",
    "unsubscribe_theme_change",
    "toggle_dark_light",
    "get_setting",
    "set_setting",
    "subscribe_settings_change",
    "get_ai_settings",
    "get_view_spacing",
]
