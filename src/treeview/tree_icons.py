"""
Tree view icons, font detection, and icon set utilities.
"""

import os
from typing import Optional

from gi.repository import Gtk

# Icon definitions
ICON_COLORS = {
    "folder": "#dcb67a",
    ".py": "#ffbc03",
    ".js": "#f1e05a",
    ".ts": "#3178c6",
    ".jsx": "#61dafb",
    ".tsx": "#61dafb",
    ".html": "#e34c26",
    ".css": "#563d7c",
    ".json": "#cbcb41",
    ".yaml": "#cb171e",
    ".yml": "#cb171e",
    ".md": "#ffffff",
    ".sh": "#89e051",
    ".go": "#00ADD8",
    ".rb": "#701516",
    ".rs": "#dea584",
    ".c": "#599eff",
    ".cpp": "#599eff",
    ".h": "#a074c4",
    ".hpp": "#a074c4",
    ".tf": "#844fba",
    ".tfvars": "#844fba",
    "default": "#6d8086",
}


def get_git_status_colors():
    """Return git status colors from the active theme."""
    from themes import get_theme

    theme = get_theme()
    return {
        "M": theme.git_modified,
        "A": theme.git_added,
        "D": theme.git_deleted,
        "R": theme.term_blue,
        "?": theme.term_green,
    }


# Nerd Font icons
NERD_FILE_ICONS = {
    ".py": "\ue606 ",
    ".pyx": "\ue606 ",
    ".pyi": "\ue606 ",
    ".js": "\ue60c ",
    ".mjs": "\ue60c ",
    ".cjs": "\ue60c ",
    ".ts": "\ue628 ",
    ".jsx": "\ue625 ",
    ".tsx": "\ue625 ",
    ".html": "\ue60e ",
    ".htm": "\ue60e ",
    ".css": "\ue614 ",
    ".scss": "\ue603 ",
    ".sass": "\ue603 ",
    ".json": "\ue60b ",
    ".yaml": "\ue607 ",
    ".yml": "\ue607 ",
    ".toml": "\ue607 ",
    ".xml": "\uf121 ",
    ".md": "\ue609 ",
    ".markdown": "\ue609 ",
    ".txt": "\uf15c ",
    ".sh": "\uf489 ",
    ".bash": "\uf489 ",
    ".zsh": "\uf489 ",
    ".go": "\ue627 ",
    ".rb": "\ue739 ",
    ".rs": "\ue7a8 ",
    ".java": "\ue608 ",
    ".kt": "\ue634 ",
    ".c": "\ue61e ",
    ".cpp": "\ue61d ",
    ".h": "\ue61e ",
    ".hpp": "\ue61d ",
    ".swift": "\ue622 ",
    ".lua": "\ue620 ",
    ".sql": "\uf472 ",
    ".gitignore": "\ue702 ",
    ".gitattributes": "\ue702 ",
    ".env": "\uf023 ",
    ".lock": "\uf023 ",
    ".dockerfile": "\uf308 ",
    ".pdf": "\uf1c1 ",
    ".zip": "\uf1c6 ",
    ".tar": "\uf1c6 ",
    ".gz": "\uf1c6 ",
    ".png": "\uf03e ",
    ".jpg": "\uf03e ",
    ".jpeg": "\uf03e ",
    ".gif": "\uf03e ",
    ".svg": "\uf03e ",
    ".clj": "\ue66a ",
    ".cljs": "\ue66a ",
    ".cljc": "\ue66a ",
    ".edn": "\ue66a ",
    ".tf": "\ue69a ",
    ".tfvars": "\ue69a ",
}

NERD_NAME_ICONS = {
    "Dockerfile": "\uf308 ",
    "Makefile": "\uf489 ",
    "LICENSE": "\uf0e3 ",
    "README": "\ue609 ",
    "README.md": "\ue609 ",
    ".gitignore": "\ue702 ",
    ".dockerignore": "\uf308 ",
    "package.json": "\ue71e ",
    "requirements.txt": "\ue606 ",
    "setup.py": "\ue606 ",
    "pyproject.toml": "\ue606 ",
}

NERD_FOLDER_CLOSED = "\uf07b "
NERD_FOLDER_OPEN = "\uf07c "

# Emoji fallbacks
EMOJI_FILE_ICONS = {
    ".py": "🐍",
    ".js": "📜",
    ".ts": "📘",
    ".json": "📋",
    ".md": "📝",
    ".html": "🌐",
    ".css": "🎨",
    ".yaml": "⚙️",
    ".yml": "⚙️",
}

EMOJI_NAME_ICONS = {
    "Dockerfile": "🐳",
    "Makefile": "🔧",
    "LICENSE": "📜",
    "README": "📝",
    "README.md": "📝",
}

EMOJI_FOLDER_CLOSED = "📁"
EMOJI_FOLDER_OPEN = "📂"
EMOJI_FILE_DEFAULT = "📄"

# Chevrons
CHEVRON_EXPANDED = "\U000f0140"  # nf-md-chevron_down (󰅀)
CHEVRON_COLLAPSED = "\U000f0142"  # nf-md-chevron_right (󰅂)
CHEVRON_COLOR = ICON_COLORS["folder"]

# Nerd Font detection cache
_nerd_font_name: Optional[str] = None
_nerd_font_checked = False
_FONT_CACHE_FILE = os.path.expanduser("~/.zen_ide/font_cache.txt")

_NERD_FONT_NAMES = [
    "ZenIcons",  # bundled subset — always available, ~35 KB
    "JetBrainsMono Nerd Font",
    "JetBrainsMono NF",
    "JetBrainsMonoNL Nerd Font Mono",
    "FiraCode Nerd Font",
    "FiraCode NF",
    "Hack Nerd Font",
    "Hack NF",
    "CaskaydiaCove Nerd Font",
    "CaskaydiaCove NF",
    "SauceCodePro Nerd Font",
    "DejaVuSansMono Nerd Font",
    "UbuntuMono Nerd Font",
]


def _detect_nerd_font() -> Optional[str]:
    """Detect if a Nerd Font is available using Pango."""
    global _nerd_font_name, _nerd_font_checked

    if _nerd_font_checked:
        return _nerd_font_name

    _nerd_font_checked = True

    # Use Pango to check for fonts
    try:
        font_map = Gtk.Label().get_pango_context().get_font_map()
        families = font_map.list_families()
        available = {f.get_name() for f in families}

        # Try loading from cache first — validate it's still installed
        try:
            if os.path.exists(_FONT_CACHE_FILE):
                with open(_FONT_CACHE_FILE, "r") as f:
                    cached = f.read().strip()
                    if cached and cached in available:
                        _nerd_font_name = cached
                        return _nerd_font_name
        except Exception:
            pass

        for nf in _NERD_FONT_NAMES:
            if nf in available:
                _nerd_font_name = nf
                # Cache for next startup
                try:
                    os.makedirs(os.path.dirname(_FONT_CACHE_FILE), exist_ok=True)
                    with open(_FONT_CACHE_FILE, "w") as f:
                        f.write(nf)
                except Exception:
                    pass
                return _nerd_font_name
    except Exception:
        pass

    return None


def get_nerd_font_name() -> Optional[str]:
    """Get the icon font name for rendering Nerd Font glyphs.

    .. deprecated::
        Use ``from icons import get_icon_font_name`` instead.
        This wrapper delegates to the centralised icon manager.
    """
    from icons import ICON_FONT_FAMILY

    return ICON_FONT_FAMILY


def get_icon_set():
    """Get the icon set for the tree view.

    Always returns the Nerd Font icon set since the bundled ZenIcons
    font is always available.
    """
    return NERD_FILE_ICONS, NERD_NAME_ICONS, NERD_FOLDER_CLOSED, NERD_FOLDER_OPEN
