"""Shared utility functions used across the IDE.

Consolidates duplicate helpers (color conversion, font sanitisation,
directory helpers, word navigation) so every module uses a single implementation.
"""

import sys
import unicodedata

# ── Terminal display width ─────────────────────────────────────


# Per-codepoint width cache: avoids repeated unicodedata lookups for the same
# characters.  Tables and code blocks re-render the same box-drawing and
# formatting characters thousands of times; this cache turns O(n) unicode
# lookups into O(1) dict hits after the first encounter.
_char_width_cache: dict[int, int] = {}


def _char_display_width(cp: int, c: str) -> int:
    """Return the display width of a single codepoint, with caching."""
    cached = _char_width_cache.get(cp)
    if cached is not None:
        return cached
    # Zero-width categories and variation selectors
    if unicodedata.category(c) in ("Mn", "Me", "Cf") or 0xFE00 <= cp <= 0xFE0F or 0x1F3FB <= cp <= 0x1F3FF:
        _char_width_cache[cp] = 0
        return 0
    eaw = unicodedata.east_asian_width(c)
    w = 2 if eaw in ("W", "F") else 1
    _char_width_cache[cp] = w
    return w


def display_width(s: str) -> int:
    """Calculate terminal display width of a string, accounting for wide/emoji chars.

    Returns the number of monospace cells the string occupies.
    Wide (W) and fullwidth (F) East Asian characters count as 2;
    zero-width marks, format chars, and variation selectors are skipped.

    Fast-path: printable ASCII (0x20–0x7E) always has width 1, avoiding
    expensive ``unicodedata`` lookups for the vast majority of text.

    Uses a per-codepoint cache to avoid repeated unicodedata lookups for
    box-drawing characters, table borders, and other repeated glyphs
    commonly found in AI chat output.
    """
    w = 0
    cache = _char_width_cache
    for c in s:
        cp = ord(c)
        # Fast-path: printable ASCII is always width 1
        if 0x20 <= cp <= 0x7E:
            w += 1
            continue
        cached = cache.get(cp)
        if cached is not None:
            w += cached
            continue
        w += _char_display_width(cp, c)
    return w


# ── Word navigation helpers (treat _ as word char) ─────────────


def _is_word_char(ch):
    return ch.isalnum() or ch == "_"


def move_word_backward(text_iter):
    """Move a Gtk.TextIter backward by one word, treating _ as word char.
    Returns the new iter position."""
    target = text_iter.copy()
    # Skip whitespace
    while not target.is_start():
        prev = target.copy()
        prev.backward_char()
        ch = prev.get_char()
        if ch in (" ", "\t", "\n"):
            target.backward_char()
        else:
            break
    # Skip same-class characters
    if not target.is_start():
        probe = target.copy()
        probe.backward_char()
        first_is_word = _is_word_char(probe.get_char())
        while not target.is_start():
            prev = target.copy()
            prev.backward_char()
            ch = prev.get_char()
            if ch in (" ", "\t", "\n"):
                break
            if _is_word_char(ch) != first_is_word:
                break
            target.backward_char()
    return target


def move_word_forward(text_iter):
    """Move a Gtk.TextIter forward by one word, treating _ as word char.
    Returns the new iter position."""
    target = text_iter.copy()
    # Skip whitespace
    while not target.is_end():
        ch = target.get_char()
        if ch in (" ", "\t", "\n"):
            target.forward_char()
        else:
            break
    # Skip same-class characters
    if not target.is_end():
        first_is_word = _is_word_char(target.get_char())
        while not target.is_end():
            ch = target.get_char()
            if ch in (" ", "\t", "\n"):
                break
            if _is_word_char(ch) != first_is_word:
                break
            target.forward_char()
    return target


def handle_word_nav_keypress(buffer, keyval, state):
    """Handle Option+Left/Right/Backspace word navigation for a Gtk.TextBuffer.

    Returns True if the key was handled, False otherwise.
    Only active on macOS. Treats _ as a word character.
    """
    if sys.platform != "darwin":
        return False

    try:
        from gi.repository import Gdk
    except ImportError:
        return False

    is_alt = bool(state & Gdk.ModifierType.ALT_MASK)
    is_shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
    is_cmd = bool(state & Gdk.ModifierType.META_MASK)

    if not is_alt or is_cmd:
        return False

    cursor = buffer.get_insert()
    it = buffer.get_iter_at_mark(cursor)

    if keyval == Gdk.KEY_Left:
        target = move_word_backward(it)
        if is_shift:
            buffer.move_mark(cursor, target)
        else:
            buffer.place_cursor(target)
        return True

    if keyval == Gdk.KEY_Right:
        target = move_word_forward(it)
        if is_shift:
            buffer.move_mark(cursor, target)
        else:
            buffer.place_cursor(target)
        return True

    if keyval == Gdk.KEY_BackSpace:
        line_start = it.copy()
        line_start.set_line_offset(0)
        if it.equal(line_start):
            if it.get_line() == 0:
                return True
            prev = it.copy()
            prev.backward_char()
            buffer.begin_user_action()
            buffer.delete(prev, it)
            buffer.end_user_action()
            return True
        target = move_word_backward(it)
        # Clamp to line start
        if target.compare(line_start) < 0:
            target = line_start
        buffer.begin_user_action()
        buffer.delete(target, it)
        buffer.end_user_action()
        return True

    return False


# ── Plain-string word boundary helpers (for VTE terminal) ──────


def find_word_boundary_left(text, pos):
    """Find position after moving backward one word in plain text.
    Treats _ as a word character."""
    if pos <= 0:
        return 0
    i = pos
    # Skip whitespace
    while i > 0 and text[i - 1] in (" ", "\t"):
        i -= 1
    # Skip same-class characters
    if i > 0:
        first_is_word = _is_word_char(text[i - 1])
        while i > 0:
            ch = text[i - 1]
            if ch in (" ", "\t"):
                break
            if _is_word_char(ch) != first_is_word:
                break
            i -= 1
    return i


def find_word_boundary_right(text, pos):
    """Find position after moving forward one word in plain text.
    Treats _ as a word character."""
    length = len(text)
    if pos >= length:
        return length
    i = pos
    # Skip whitespace
    while i < length and text[i] in (" ", "\t"):
        i += 1
    # Skip same-class characters
    if i < length:
        first_is_word = _is_word_char(text[i])
        while i < length:
            ch = text[i]
            if ch in (" ", "\t"):
                break
            if _is_word_char(ch) != first_is_word:
                break
            i += 1
    return i


# ── Colour helpers ──────────────────────────────────────────────


def hex_to_rgb(hex_color: str) -> tuple:
    """Convert hex color to RGB tuple with ints in 0-255 range.

    Returns (38, 38, 38) for malformed input.
    """
    if not hex_color:
        return (38, 38, 38)

    h = hex_color.lstrip("#")
    if len(h) != 6:
        return (38, 38, 38)

    try:
        return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (38, 38, 38)


def hex_to_rgb_float(hex_color: str) -> tuple:
    """Convert hex color to (r, g, b) floats in 0-1 range.

    Returns (0.15, 0.15, 0.15) for malformed input.
    """
    if not hex_color:
        return (0.15, 0.15, 0.15)

    h = hex_color.lstrip("#")
    if len(h) == 6:
        try:
            return (
                int(h[0:2], 16) / 255.0,
                int(h[2:4], 16) / 255.0,
                int(h[4:6], 16) / 255.0,
            )
        except ValueError:
            return (0.15, 0.15, 0.15)
    return (0.15, 0.15, 0.15)


def hex_to_rgba(hex_color: str, alpha: float = 1.0) -> tuple:
    """Convert hex color to RGBA tuple with floats in 0-1 range.

    Returns (0.15, 0.15, 0.15, alpha) for malformed input.
    """
    if not hex_color:
        return (0.15, 0.15, 0.15, alpha)

    h = hex_color.lstrip("#")
    if len(h) != 6:
        return (0.15, 0.15, 0.15, alpha)

    try:
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
        return (r, g, b, alpha)
    except ValueError:
        return (0.15, 0.15, 0.15, alpha)


def hex_to_gdk_rgba(hex_color: str, alpha: float = 1.0):
    """Convert hex color string to a ``Gdk.RGBA`` with optional *alpha*.

    Falls back to mid-gray on malformed input.
    """
    from gi.repository import Gdk

    r, g, b, a = hex_to_rgba(hex_color, alpha)
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = r, g, b, a
    return c


def tuple_to_gdk_rgba(color_tuple, alpha: float | None = None):
    """Convert an ``(r, g, b[, a])`` float tuple to a ``Gdk.RGBA``.

    If *alpha* is given it overrides any alpha in the tuple.
    """
    from gi.repository import Gdk

    c = Gdk.RGBA()
    c.red, c.green, c.blue = color_tuple[0], color_tuple[1], color_tuple[2]
    if alpha is not None:
        c.alpha = alpha
    elif len(color_tuple) >= 4:
        c.alpha = color_tuple[3]
    else:
        c.alpha = 1.0
    return c


def hex_to_rgba_css(hex_color: str, alpha: float = 1.0) -> str:
    """Convert hex color to CSS ``rgba(r, g, b, a)`` string.

    Returns a fallback gray color for malformed input.
    """
    if not hex_color:
        return f"rgba(38, 38, 38, {alpha})"  # fallback gray

    h = hex_color.lstrip("#")
    if len(h) != 6:
        return f"rgba(38, 38, 38, {alpha})"  # fallback gray

    try:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
        return f"rgba({r}, {g}, {b}, {alpha})"
    except ValueError:
        return f"rgba(38, 38, 38, {alpha})"  # fallback gray


def blend_hex_colors(start_hex: str, end_hex: str, amount: float) -> str:
    """Blend *start_hex* toward *end_hex* by *amount* in the 0-1 range.

    Returns fallback color for malformed input.
    """
    if not start_hex or not end_hex:
        return "#262626"  # fallback gray

    amount = max(0.0, min(1.0, amount))
    start = hex_to_rgb(start_hex)
    end = hex_to_rgb(end_hex)
    blended = tuple(round(s + (e - s) * amount) for s, e in zip(start, end, strict=False))
    return "#{:02x}{:02x}{:02x}".format(*blended)


def relative_luminance(hex_color: str) -> float:
    """Return the WCAG relative luminance for *hex_color*."""

    def _linearize(channel: int) -> float:
        value = channel / 255.0
        if value <= 0.04045:
            return value / 12.92
        return ((value + 0.055) / 1.055) ** 2.4

    r, g, b = hex_to_rgb(hex_color)
    return (0.2126 * _linearize(r)) + (0.7152 * _linearize(g)) + (0.0722 * _linearize(b))


def contrast_ratio(color_a: str, color_b: str) -> float:
    """Return the WCAG contrast ratio between two colors."""
    luminance_a = relative_luminance(color_a)
    luminance_b = relative_luminance(color_b)
    lighter = max(luminance_a, luminance_b)
    darker = min(luminance_a, luminance_b)
    return (lighter + 0.05) / (darker + 0.05)


def contrast_color(bg_hex: str) -> str:
    """Return black or white text color for best contrast on *bg_hex*.

    Uses a threshold of 0.6 (rather than 0.5) to favor white text
    on medium-dark colors for better readability.
    """
    r, g, b = hex_to_rgb(bg_hex)
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#000000" if luminance > 0.6 else "#ffffff"


def ensure_text_contrast(bg_hex: str, fg_hex: str, min_ratio: float = 4.5) -> str:
    """Adjust *bg_hex* just enough to reach *min_ratio* against *fg_hex*."""
    if contrast_ratio(bg_hex, fg_hex) >= min_ratio:
        return blend_hex_colors(bg_hex, bg_hex, 0.0)

    target_hex = "#000000" if relative_luminance(fg_hex) > 0.5 else "#ffffff"
    adjusted = bg_hex
    for step in range(1, 11):
        adjusted = blend_hex_colors(bg_hex, target_hex, step / 10)
        if contrast_ratio(adjusted, fg_hex) >= min_ratio:
            return adjusted
    return adjusted


# ── Font helpers ────────────────────────────────────────────────


def sanitize_font_for_vte(font_family: str) -> str:
    """Sanitize font family for VTE terminal.

    VTE requires true monospace fonts. Proportional fonts (like "Propo"
    variants) render with incorrect character widths (double-spaced).
    This converts problematic font variants to their monospace equivalents.
    """
    if not font_family:
        return ""

    # Convert "Propo" (proportional) variants to "Mono" variants
    if " Propo" in font_family:
        return font_family.replace(" Propo", " Mono")

    # For Nerd Fonts without "Mono" suffix, add it for fixed-width icon glyphs
    # Exception: SauceCodePro Nerd Font is already monospace for code/text
    if "Nerd Font" in font_family and "Nerd Font Mono" not in font_family and "Nerd Font Propo" not in font_family:
        if "SauceCodePro" not in font_family:
            return font_family.replace("Nerd Font", "Nerd Font Mono")

    return font_family


# ── Filesystem helpers ──────────────────────────────────────────


def ensure_parent_dir(file_path) -> None:
    """Ensure the parent directory of *file_path* exists."""
    from pathlib import Path

    Path(file_path).parent.mkdir(parents=True, exist_ok=True)


# ── Clipboard helpers ──────────────────────────────────────────


def copy_to_system_clipboard(text: str) -> None:
    """Write text directly to the OS clipboard (pbcopy / xclip).

    GTK4 uses lazy content providers that die with the process.
    Call this alongside every GTK clipboard.set() so the OS holds
    a concrete copy that survives app exit.
    """
    import subprocess
    import sys

    if not text:
        return
    try:
        if sys.platform == "darwin":
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            p.communicate(text.encode("utf-8"), timeout=2)
        else:
            p = subprocess.Popen(
                ["xclip", "-selection", "clipboard"],
                stdin=subprocess.PIPE,
            )
            p.communicate(text.encode("utf-8"), timeout=2)
    except Exception:
        pass


def persist_clipboard() -> None:
    """No-op kept for backward compatibility."""
    pass


# ── Animation helpers ──────────────────────────────────────────

# Track active paned animations so we can cancel when a new one starts
_paned_animations: dict[int, int] = {}  # widget id -> GLib source id


def animate_paned(paned, target: int, duration_ms: int = None, on_done=None):
    """Animate a Gtk.Paned to *target* position with ease-out cubic.

    Cancels any in-flight animation on the same paned widget.
    Calls *on_done()* after the animation finishes (if provided).
    """
    from gi.repository import GLib

    from constants import PANED_ANIM_DURATION_MS, PANED_ANIM_FRAME_INTERVAL_MS

    if duration_ms is None:
        duration_ms = PANED_ANIM_DURATION_MS

    widget_id = id(paned)

    # Cancel any running animation on this paned
    if widget_id in _paned_animations:
        GLib.source_remove(_paned_animations[widget_id])
        del _paned_animations[widget_id]

    start = paned.get_position()
    distance = target - start

    if abs(distance) < 2:
        paned.set_position(target)
        if on_done:
            on_done()
        return

    start_time = GLib.get_monotonic_time() / 1000.0  # ms

    def step():
        elapsed = GLib.get_monotonic_time() / 1000.0 - start_time
        progress = min(1.0, elapsed / duration_ms)
        eased = 1 - pow(1 - progress, 3)  # cubic ease-out
        paned.set_position(int(start + distance * eased))

        if progress >= 1.0:
            paned.set_position(target)
            _paned_animations.pop(widget_id, None)
            if on_done:
                on_done()
            return False
        return True

    _paned_animations[widget_id] = GLib.timeout_add(PANED_ANIM_FRAME_INTERVAL_MS, step)


# ── Environment helpers ────────────────────────────────────────


def ensure_full_path(env: dict) -> dict:
    """Ensure PATH in *env* includes common binary directories.

    macOS app bundles launched from Finder inherit a minimal PATH that
    lacks directories like ``/opt/homebrew/bin`` or NVM bin paths.  CLI
    tools such as ``copilot`` and ``claude`` are Node.js scripts with a
    ``#!/usr/bin/env node`` shebang, so ``node`` must be on PATH even
    when the CLI itself is invoked via an absolute path.
    """
    import os

    extra_dirs: list[str] = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        os.path.expanduser("~/.npm-global/bin"),
        os.path.expanduser("~/.local/bin"),
    ]

    # Add NVM bin directories (newest version first)
    nvm_dir = os.path.expanduser("~/.nvm/versions/node")
    if os.path.isdir(nvm_dir):
        try:
            versions = sorted(os.listdir(nvm_dir), reverse=True)
            extra_dirs.extend(os.path.join(nvm_dir, v, "bin") for v in versions if v.startswith("v"))
        except OSError:
            pass

    current = env.get("PATH", "").split(":")
    current_set = set(current)
    additions = [d for d in extra_dirs if d not in current_set]
    if additions:
        env["PATH"] = ":".join(current + additions)

    return env


def get_pango_font_map():
    """Get the default Pango font map.

    In Pango 1.52+, ``Pango.FontMap.get_default()`` no longer exists on the
    base class.  This helper obtains the font map through a lightweight
    ``Gtk.Label`` Pango context, which works on all GTK 4 / Pango versions
    without needing ``PangoCairo`` (which is banned per rendering standards).

    The result is cached after the first call.
    """
    cached = getattr(get_pango_font_map, "_cached", None)
    if cached is not None:
        return cached

    from gi.repository import Gtk

    font_map = Gtk.Label().get_pango_context().get_font_map()
    get_pango_font_map._cached = font_map
    return font_map


def get_resource_path(filename: str) -> str:
    """Resolve path to a bundled resource, works in both dev and PyInstaller."""
    import os
    import sys

    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, filename)
    # Dev mode: resources are at repo root
    shared_dir = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.dirname(shared_dir)
    repo_root = os.path.dirname(src_dir)
    return os.path.join(repo_root, filename)
