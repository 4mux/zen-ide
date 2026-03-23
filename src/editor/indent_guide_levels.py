"""Indent guide level computation with per-language strategies.

Pure logic (no GTK dependency) so it can be unit-tested easily.
"""

from math import gcd


def detect_indent_width(text, fallback):
    """Detect the indent width used in a file from its content.

    Scans leading whitespace of each line, collects non-zero space-only
    indents, and returns the GCD.  Falls back to *fallback* when the file
    has fewer than 3 indented lines (not enough signal).
    """
    indents = []
    for line in text.split("\n"):
        if not line.strip() or line[0] != " ":
            continue
        n = 0
        for ch in line:
            if ch == " ":
                n += 1
            else:
                break
        if n > 0:
            indents.append(n)

    if len(indents) < 3:
        return fallback

    step = gcd(*indents)
    return max(step, 2)


def compute_indent_step(non_zero_indents, tab_width):
    """Determine the indent step from a list of non-zero indent widths.

    Uses GCD of all indents, with a conservative heuristic to prefer
    tab_width when very few lines are misaligned (< 20%).
    """
    if not non_zero_indents:
        return tab_width

    step = gcd(*non_zero_indents)
    if step < tab_width:
        misaligned = sum(1 for r in non_zero_indents if r % tab_width != 0)
        if misaligned * 5 <= len(non_zero_indents):
            step = tab_width
    return max(step, 2)


def compute_guide_levels(text_lines, indent_step, tab_width, lang_id=None):
    """Return a list of guide levels (one per line).

    A level of 0 means no guides; level *n* draws *n* vertical lines at
    columns 0, indent_step, 2*indent_step … (n-1)*indent_step.

    JetBrains-style: guides appear only on content lines between
    opener/closer braces, never on the brace lines themselves.
    Blank lines (whitespace-only) are interpolated from neighbours.
    """
    raw_indents = _raw_indents(text_lines, tab_width)
    levels = [r // indent_step if r >= 0 else -1 for r in raw_indents]

    _interpolate_blanks(levels)
    return levels


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _raw_indents(text_lines, tab_width):
    """Compute raw character-indent per line (-1 for blank lines)."""
    result = []
    for text in text_lines:
        if not text.strip():
            result.append(-1)
        else:
            indent = 0
            for ch in text:
                if ch == " ":
                    indent += 1
                elif ch == "\t":
                    indent += tab_width
                else:
                    break
            result.append(indent)
    return result


def _interpolate_blanks(levels):
    """Fill blank-line entries (-1) using min of nearest non-blank neighbours."""
    n = len(levels)
    for i in range(n):
        if levels[i] != -1:
            continue
        above = 0
        for j in range(i - 1, -1, -1):
            if levels[j] >= 0:
                above = levels[j]
                break
        below = 0
        for j in range(i + 1, n):
            if levels[j] >= 0:
                below = levels[j]
                break
        levels[i] = min(above, below)
