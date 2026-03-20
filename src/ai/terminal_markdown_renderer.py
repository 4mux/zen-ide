"""Streaming markdown-to-ANSI renderer for ChatCanvas display.

Features:
- Syntax-highlighted code blocks via Pygments
- Table rendering with box-drawing characters
- Inline formatting (bold, italic, code, links)
- Streaming: feed() chunks → formatted output for complete lines
"""

import re

from shared.utils import display_width as _display_width

# Pre-compiled regex for stripping ANSI escape sequences.
# Shared across all methods to avoid re-compiling per call.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Pre-compiled regex patterns for markdown line classification.
# These are called on every line during rendering; pre-compiling avoids
# the overhead of re.match() rebuilding the pattern each time.
_RE_HR = re.compile(r"^[-*_]{3,}\s*$")
_RE_TABLE_SEP = re.compile(r"^\|?[\s|:-]+\|?$")
_RE_HEADER = re.compile(r"^(#{1,6})\s+(.*)")
_RE_LIST_ITEM = re.compile(r"^(\s*)([-*+●]|\d+\.)\s+(.*)")
_RE_TABLE_SEP_INNER = re.compile(r"^[\s|:-]+$")


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int] | None:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return None
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _darken(hex_color: str, factor: float = 0.35) -> str:
    """Darken a hex color for code block backgrounds."""
    rgb = _hex_to_rgb(hex_color)
    if not rgb:
        return "#1e1e2e"
    r, g, b = rgb
    return "#{:02x}{:02x}{:02x}".format(int(r * factor), int(g * factor), int(b * factor))


class TerminalMarkdownRenderer:
    """Converts markdown text to ANSI-formatted text, line by line.

    Designed for streaming: feed() accepts chunks of text and returns
    formatted output for complete lines. Tracks state across calls
    (e.g. whether we're inside a code block).

    Code blocks are buffered until the closing fence, then highlighted
    with Pygments for full syntax coloring.
    """

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    def __init__(self, terminal_width_fn=None):
        self._in_code_block = False
        self._code_language = ""
        self._code_buffer: list[str] = []
        self._code_lexer = None  # Cached Pygments lexer for incremental highlighting
        self._code_block_width = 0  # Width for current code block borders
        self._line_buffer = ""
        self._colors: dict[str, str] = {}
        self._table_buffer: list[str] = []
        self._in_table = False
        self._code_bg = ""
        self._pygments_style = "monokai"
        self._pygments_formatter = None  # Cached Pygments formatter instance
        self._terminal_width_fn = terminal_width_fn
        self._seen_content = False

    def update_colors(self, colors: dict[str, str]):
        """Update theme colors. Keys: header, code, inline_code, quote, link, list, accent."""
        self._colors = colors
        bg_base = colors.get("code", "#1e1e2e")
        self._code_bg = _darken(bg_base)

    def _get_terminal_width(self) -> int:
        """Return the current terminal width, falling back to 80 columns."""
        if not self._terminal_width_fn:
            return 80
        try:
            return max(int(self._terminal_width_fn()), 20)
        except Exception:
            return 80

    def _fg(self, key: str) -> str:
        """Get ANSI foreground escape for a theme color key."""
        hex_color = self._colors.get(key, "")
        if not hex_color:
            return ""
        rgb = _hex_to_rgb(hex_color)
        if not rgb:
            return ""
        r, g, b = rgb
        return f"\033[38;2;{r};{g};{b}m"

    def _bg(self, hex_color: str) -> str:
        """Get ANSI background escape for a hex color."""
        rgb = _hex_to_rgb(hex_color)
        if not rgb:
            return ""
        r, g, b = rgb
        return f"\033[48;2;{r};{g};{b}m"

    def reset(self):
        """Reset state for a new response."""
        self._in_code_block = False
        self._code_language = ""
        self._code_buffer = []
        self._code_lexer = None
        self._code_block_width = 0
        self._line_buffer = ""
        self._table_buffer = []
        self._in_table = False
        self._seen_content = False

    def feed(self, text: str) -> str:
        """Feed a chunk of text and return formatted output.

        Complete lines are fully formatted. Any trailing partial line is
        emitted immediately (without trailing newline) so characters appear
        in real time. The next feed() call will overwrite the partial line
        via \\r when the line completes.
        """
        self._line_buffer += text
        result = []

        while "\n" in self._line_buffer:
            line, self._line_buffer = self._line_buffer.split("\n", 1)
            formatted = self._format_line(line)
            if formatted is not None:
                # Skip leading empty lines before first real content
                if not self._seen_content and formatted.strip() == "":
                    continue
                if formatted.strip():
                    self._seen_content = True
                result.append(formatted)

        # Emit partial line immediately for real-time character display.
        # Don't emit partials inside code blocks (they're already handled
        # incrementally) or tables (need full row to format).
        if self._line_buffer and not self._in_code_block and not self._in_table:
            if self._seen_content or self._line_buffer.strip():
                # Emit raw partial (minimal formatting — will be overwritten
                # by the fully formatted line when \n arrives)
                partial = self._format_inline(self._line_buffer)
                if result:
                    # Complete lines end with \n, partial appended after
                    return "\n".join(result) + "\n" + partial
                return partial

        if result:
            return "\n".join(result) + "\n"
        return ""

    def flush(self) -> str:
        """Flush any remaining buffered text."""
        parts = []
        # Process any remaining line buffer FIRST so that a trailing closing
        # fence (```) is handled as the end of the current code block rather
        # than being misinterpreted as opening a new one after we force-close.
        if self._line_buffer:
            formatted = self._format_line(self._line_buffer)
            self._line_buffer = ""
            if formatted is not None:
                parts.append(formatted)
        if self._in_code_block:
            # Close unclosed code block with bottom border
            fg = self._fg("code")
            width = self._code_block_width if self._code_block_width > 0 else 60
            bottom = f"{fg}{self.DIM}└{'─' * (width - 2)}┘{self.RESET}"
            parts.append(bottom)
            self._in_code_block = False
            self._code_lexer = None
            self._code_block_width = 0
        if self._table_buffer:
            parts.append(self._render_table())
        return "\n".join(parts) if parts else ""

    def format_block(self, text: str) -> str:
        """Format a complete block of text (for restoring messages)."""
        self.reset()
        lines = text.split("\n")
        result = []
        for line in lines:
            formatted = self._format_line(line)
            if formatted is not None:
                result.append(formatted)
        # Flush any remaining buffered content
        tail = self.flush()
        if tail:
            result.append(tail)
        return "\n".join(result)

    def _format_line(self, line: str) -> str | None:
        """Format a single line of markdown to ANSI.

        Returns None when the line is buffered (code blocks, tables)
        and will be emitted later.
        """
        stripped = line.rstrip()

        # Code fence
        if stripped.startswith("```"):
            if not self._in_code_block:
                # Flush any pending table
                table_out = ""
                if self._table_buffer:
                    table_out = self._render_table() + "\n"
                self._in_code_block = True
                self._code_language = stripped[3:].strip()
                self._code_buffer = []
                self._code_lexer = self._get_lexer(self._code_language)
                # Use terminal width for code block borders
                term_w = self._get_terminal_width()
                self._code_block_width = max(60, min(max(40, term_w - 2), term_w))
                # Emit top border immediately
                fg = self._fg("code")
                lang_label = f" {self._code_language}" if self._code_language else ""
                bar_len = max(0, self._code_block_width - 4 - _display_width(lang_label))
                top = f"{fg}{self.DIM}┌──{lang_label}{'─' * bar_len}┐{self.RESET}"
                return (table_out + top) if table_out else top
            else:
                # End of code block — emit bottom border
                fg = self._fg("code")
                bottom = f"{fg}{self.DIM}└{'─' * (self._code_block_width - 2)}┘{self.RESET}"
                self._in_code_block = False
                self._code_language = ""
                self._code_buffer = []
                self._code_lexer = None
                self._code_block_width = 0
                return bottom

        # Inside code block — emit line immediately with highlighting
        if self._in_code_block:
            self._code_buffer.append(line)
            return self._render_code_line(line)

        # Table detection: lines with | (but not just |---|)
        if "|" in stripped and not _RE_HR.match(stripped):
            # Check if this is a table separator row or data row
            if _RE_TABLE_SEP.match(stripped):
                # Separator row
                self._table_buffer.append(stripped)
                self._in_table = True
                return None
            elif self._in_table or stripped.startswith("|"):
                self._table_buffer.append(stripped)
                self._in_table = True
                return None

        # If we were in a table and hit a non-table line, flush the table
        if self._table_buffer:
            table_out = self._render_table()
            formatted = self._format_regular_line(stripped)
            return table_out + "\n" + formatted

        return self._format_regular_line(stripped)

    def _format_regular_line(self, stripped: str) -> str:
        """Format a non-code, non-table line."""
        term_w = self._get_terminal_width()

        # Headers
        m = _RE_HEADER.match(stripped)
        if m:
            level = len(m.group(1))
            text = m.group(2)
            fg = self._fg("header")
            formatted_text = self._wrap_ansi_lines(self._format_inline(text), term_w)
            if level == 1:
                return f"\n{self.BOLD}{fg}{formatted_text}{self.RESET}"
            elif level == 2:
                return f"\n{self.BOLD}{fg}{formatted_text}{self.RESET}"
            return f"{fg}{formatted_text}{self.RESET}"

        # Blockquote
        if stripped.startswith(">"):
            quote_text = stripped[1:].lstrip()
            fg = self._fg("quote")
            prefix = f"{fg}{self.DIM}▎ {self.RESET}"
            content = f"{fg}{self.DIM}{self._format_inline(quote_text)}{self.RESET}"
            return self._wrap_prefixed_ansi(content, term_w, prefix)

        # Horizontal rule
        if _RE_HR.match(stripped):
            fg = self._fg("code")
            return f"{fg}{self.DIM}{'─' * min(44, term_w)}{self.RESET}"

        # List items (unordered and ordered)
        # Also match ● directly since some AI providers output pre-formatted bullets
        m = _RE_LIST_ITEM.match(stripped)
        if m:
            indent = m.group(1)
            marker = m.group(2)
            text = m.group(3)
            # Use filled circle (●) for unordered lists - more visible than bullet (•)
            bullet = "●" if marker in ("-", "*", "+", "●") else marker
            fg = self._fg("list")
            prefix = f"{indent}{fg}{bullet}{self.RESET} "
            continuation_prefix = indent + " " * (_display_width(bullet) + 1)
            return self._wrap_prefixed_ansi(self._format_inline(text), term_w, prefix, continuation_prefix)

        # Regular text — apply inline formatting
        return self._wrap_ansi_lines(self._format_inline(stripped), term_w)

    def _render_code_block(self) -> str:
        """Render a buffered code block with Pygments syntax highlighting.

        Note: This is the legacy batch-rendering path kept for flush() and
        format_block(). The incremental path (_render_code_line) is used
        during live streaming.
        """
        code = "\n".join(self._code_buffer)
        lang = self._code_language
        fg = self._fg("code")
        bg = self._bg(self._code_bg) if self._code_bg else ""
        lang_label = f" {lang}" if lang else ""

        # Highlight code with Pygments
        highlighted_lines = self._highlight_code(code, lang)

        # Get terminal width for responsive sizing
        term_w = self._get_terminal_width()
        # Reserve space for borders (2) and padding (2) = 4 chars
        max_allowed_width = max(40, term_w - 2)  # Leave small margin

        # Compute effective width: max of default and longest content line + 4 (borders + padding)
        max_content = max((_display_width(_ANSI_RE.sub("", l)) for l in highlighted_lines), default=0)
        width = min(max_allowed_width, max(60, max_content + 4))

        # Content width available inside the box (width - 2 borders - 2 padding spaces)
        content_width = width - 4

        # Hard-wrap lines that exceed content width (preserving ANSI codes)
        wrapped_lines = []
        for hl_line in highlighted_lines:
            plain = _ANSI_RE.sub("", hl_line)
            if _display_width(plain) <= content_width:
                wrapped_lines.append(hl_line)
            else:
                # Hard-wrap: split by character to fit within content_width
                wrapped_lines.extend(self._hard_wrap_ansi(hl_line, content_width))

        # Top border
        bar_len = max(0, width - 4 - _display_width(lang_label))
        top = f"{fg}{self.DIM}┌──{lang_label}{'─' * bar_len}┐{self.RESET}"

        # Format each line with border and background
        body_lines = []
        for hl_line in wrapped_lines:
            # Pad line to fill background
            visible_len = _display_width(_ANSI_RE.sub("", hl_line))
            pad = max(0, content_width - visible_len)
            body_lines.append(
                f"{fg}{self.DIM}│{self.RESET} {bg}{hl_line}{' ' * pad}{self.RESET} {fg}{self.DIM}│{self.RESET}"
            )

        # Bottom border
        bottom = f"{fg}{self.DIM}└{'─' * (width - 2)}┘{self.RESET}"

        return "\n".join([top] + body_lines + [bottom])

    def _render_code_line(self, line: str) -> str:
        """Render a single code line incrementally with borders and highlighting."""
        fg = self._fg("code")
        bg = self._bg(self._code_bg) if self._code_bg else ""
        content_width = self._code_block_width - 4

        # Highlight the single line
        highlighted = self._highlight_single_line(line)

        # Hard-wrap if needed
        plain = _ANSI_RE.sub("", highlighted)
        if _display_width(plain) > content_width:
            wrapped = self._hard_wrap_ansi(highlighted, content_width)
        else:
            wrapped = [highlighted]

        body_lines = []
        for hl_line in wrapped:
            visible_len = _display_width(_ANSI_RE.sub("", hl_line))
            pad = max(0, content_width - visible_len)
            body_lines.append(
                f"{fg}{self.DIM}│{self.RESET} {bg}{hl_line}{' ' * pad}{self.RESET} {fg}{self.DIM}│{self.RESET}"
            )
        return "\n".join(body_lines)

    def _highlight_single_line(self, line: str) -> str:
        """Highlight a single code line using the cached lexer and formatter."""
        if self._code_lexer is None:
            fg = self._fg("code")
            return f"{fg}{line}{self.RESET}"
        try:
            from pygments import highlight

            formatter = self._get_formatter()
            if formatter is None:
                fg = self._fg("code")
                return f"{fg}{line}{self.RESET}"
            highlighted = highlight(line, self._code_lexer, formatter)
            return highlighted.rstrip("\n")
        except Exception:
            fg = self._fg("code")
            return f"{fg}{line}{self.RESET}"

    def _get_lexer(self, lang: str):
        """Get a Pygments lexer for the given language, or None."""
        if not lang:
            return None
        try:
            from pygments.lexers import get_lexer_by_name

            return get_lexer_by_name(lang)
        except Exception:
            return None

    def _get_formatter(self):
        """Get a cached Pygments TerminalTrueColorFormatter instance.

        Reuses the same formatter across all highlight calls within a
        code block (and across code blocks with the same style) to avoid
        the overhead of re-instantiating and re-parsing the Pygments
        style definition on every line.
        """
        if self._pygments_formatter is not None:
            return self._pygments_formatter
        try:
            from pygments.formatters import TerminalTrueColorFormatter

            self._pygments_formatter = TerminalTrueColorFormatter(style=self._pygments_style)
            return self._pygments_formatter
        except Exception:
            return None

    def _hard_wrap_ansi(self, s: str, max_w: int) -> list[str]:
        """Hard-wrap an ANSI-formatted string by character to fit within max_w visible width."""
        if max_w < 1:
            return [s]

        lines = []
        current_line = ""
        current_width = 0
        active_codes = ""  # Track active ANSI codes to reapply on new lines

        i = 0
        while i < len(s):
            # Check for ANSI escape sequence
            m = _ANSI_RE.match(s, i)
            if m:
                code = m.group()
                current_line += code
                # Track reset vs style codes
                if code == "\033[0m":
                    active_codes = ""
                else:
                    active_codes += code
                i = m.end()
                continue

            # Regular character
            ch = s[i]
            ch_w = _display_width(ch)

            if current_width + ch_w > max_w and current_line:
                # Flush current line and start new one
                lines.append(current_line + self.RESET)
                current_line = active_codes + ch
                current_width = ch_w
            else:
                current_line += ch
                current_width += ch_w
            i += 1

        if current_line:
            lines.append(current_line)

        return lines if lines else [""]

    def _wrap_ansi_lines(self, s: str, max_w: int) -> str:
        """Return ANSI-aware wrapped lines joined with newlines."""
        return "\n".join(self._hard_wrap_ansi(s, max_w))

    def _wrap_prefixed_ansi(
        self,
        s: str,
        max_w: int,
        first_prefix: str,
        continuation_prefix: str | None = None,
    ) -> str:
        """Wrap ANSI-formatted content within a prefixed block."""
        continuation_prefix = first_prefix if continuation_prefix is None else continuation_prefix
        first_width = _display_width(_ANSI_RE.sub("", first_prefix))
        continuation_width = _display_width(_ANSI_RE.sub("", continuation_prefix))
        first_content_width = max(1, max_w - first_width)
        continuation_content_width = max(1, max_w - continuation_width)

        wrapped = self._hard_wrap_ansi(s, first_content_width)
        if not wrapped:
            return first_prefix.rstrip()

        lines = [f"{first_prefix}{wrapped[0]}"]
        for line in wrapped[1:]:
            continuation_lines = self._hard_wrap_ansi(line, continuation_content_width)
            if continuation_lines:
                lines.append(f"{continuation_prefix}{continuation_lines[0]}")
                for extra in continuation_lines[1:]:
                    lines.append(f"{continuation_prefix}{extra}")
            else:
                lines.append(continuation_prefix.rstrip())
        return "\n".join(lines)

    def _highlight_code(self, code: str, lang: str) -> list[str]:
        """Highlight code using Pygments. Falls back to plain colored text."""
        try:
            from pygments import highlight
            from pygments.lexers import TextLexer, get_lexer_by_name

            try:
                lexer = get_lexer_by_name(lang) if lang else TextLexer()
            except Exception:
                lexer = TextLexer()

            formatter = self._get_formatter()
            if formatter is None:
                fg = self._fg("code")
                return [f"{fg}{line}{self.RESET}" for line in code.split("\n")]

            highlighted = highlight(code, lexer, formatter)
            # Remove trailing newline from Pygments output
            lines = highlighted.rstrip("\n").split("\n")
            return lines
        except Exception:
            # Fallback: plain colored text
            fg = self._fg("code")
            return [f"{fg}{line}{self.RESET}" for line in code.split("\n")]

    def _render_table(self) -> str:
        """Render buffered table rows with box-drawing characters."""
        if not self._table_buffer:
            return ""

        rows = self._table_buffer
        self._table_buffer = []
        self._in_table = False

        # Parse cells from each row
        parsed: list[list[str]] = []
        separator_indices: list[int] = []
        for idx, row in enumerate(rows):
            cells = [c.strip() for c in row.strip("|").split("|")]
            if _RE_TABLE_SEP_INNER.match(row.strip("|").replace("|", "").replace(" ", "")):
                separator_indices.append(idx)
            else:
                parsed.append(cells)

        if not parsed:
            fg = self._fg("code")
            return "\n".join(f"{fg}{r}{self.RESET}" for r in rows)

        # Apply inline formatting to cells and compute visible widths

        def _visible_width(s: str) -> int:
            return _display_width(_ANSI_RE.sub("", s))

        formatted: list[list[str]] = []
        for row in parsed:
            formatted.append([self._format_inline(cell) for cell in row])

        # Determine column widths from visible (ANSI-stripped) content
        max_cols = max(len(r) for r in formatted)
        col_widths = [0] * max_cols
        for row in formatted:
            for ci, cell in enumerate(row):
                if ci < max_cols:
                    col_widths[ci] = max(col_widths[ci], _visible_width(cell))

        # Ensure minimum width
        col_widths = [max(w, 3) for w in col_widths]

        # Constrain table to terminal width to prevent line-wrap corruption
        term_w = self._get_terminal_width()
        # Total width = borders (max_cols+1) + padding (2 per col) + content
        total = sum(col_widths) + max_cols * 2 + max_cols + 1
        if total > term_w and term_w > max_cols * 4 + max_cols + 1:
            available = term_w - max_cols - 1 - max_cols * 2  # subtract borders and padding
            # Shrink columns proportionally
            ratio = available / sum(col_widths)
            col_widths = [max(3, int(w * ratio)) for w in col_widths]

        fg = self._fg("code")
        accent = self._fg("header")

        def make_sep(left: str, mid: str, right: str, fill: str = "─") -> str:
            parts = [fill * (w + 2) for w in col_widths]
            return f"{fg}{self.DIM}{left}{mid.join(parts)}{right}{self.RESET}"

        def _wrap_ansi(s: str, max_w: int) -> list[str]:
            """Wrap ANSI-formatted string into multiple lines of max visible width."""
            if max_w < 1:
                return [s]
            # Strip ANSI and split into words with their positions
            plain = _ANSI_RE.sub("", s)
            words = plain.split()
            if not words:
                return [s]

            def _break_word(word: str, max_w: int) -> list[str]:
                """Break a single word into chunks that fit within max_w."""
                if _visible_width(word) <= max_w:
                    return [word]
                chunks = []
                current = ""
                current_w = 0
                for ch in word:
                    ch_w = _visible_width(ch)
                    if current_w + ch_w > max_w and current:
                        chunks.append(current)
                        current = ch
                        current_w = ch_w
                    else:
                        current += ch
                        current_w += ch_w
                if current:
                    chunks.append(current)
                return chunks

            # Reconstruct with word wrapping (and character breaking for long words)
            lines = []
            current_line = ""
            current_width = 0
            for word in words:
                word_w = _visible_width(word)
                space_w = 1 if current_line else 0
                # If word fits on current line, add it
                if current_width + space_w + word_w <= max_w:
                    current_line += (" " if current_line else "") + word
                    current_width += space_w + word_w
                # Word doesn't fit but line has content - flush line first
                elif current_line:
                    lines.append(current_line)
                    # Try to fit word on new line
                    if word_w <= max_w:
                        current_line = word
                        current_width = word_w
                    else:
                        # Word too long even for empty line - break it
                        chunks = _break_word(word, max_w)
                        for i, chunk in enumerate(chunks[:-1]):
                            lines.append(chunk)
                        current_line = chunks[-1] if chunks else ""
                        current_width = _visible_width(current_line)
                # Word doesn't fit and line is empty - break the word
                else:
                    chunks = _break_word(word, max_w)
                    for chunk in chunks[:-1]:
                        lines.append(chunk)
                    current_line = chunks[-1] if chunks else ""
                    current_width = _visible_width(current_line)
            if current_line:
                lines.append(current_line)
            # For styled text, apply formatting to all lines
            if lines and s != plain:
                # Extract leading ANSI codes
                leading_codes = ""
                for m in re.finditer(r"^\x1b\[[0-9;]*m", s):
                    leading_codes += m.group()
                if leading_codes:
                    lines = [leading_codes + line + self.RESET for line in lines]
            return lines if lines else [""]

        def make_row_lines(cells: list[str], is_header: bool = False) -> list[str]:
            """Create multiple output lines for a row with wrapped cells."""
            # Wrap each cell into lines
            wrapped_cells: list[list[str]] = []
            for ci, w in enumerate(col_widths):
                cell = cells[ci] if ci < len(cells) else ""
                if _visible_width(cell) > w:
                    wrapped_cells.append(_wrap_ansi(cell, w))
                else:
                    wrapped_cells.append([cell])
            # Find max lines needed
            max_lines = max(len(wc) for wc in wrapped_cells) if wrapped_cells else 1
            # Build each output line
            style = f"{accent}{self.BOLD}" if is_header else ""
            output_lines = []
            for line_idx in range(max_lines):
                padded = []
                for ci, w in enumerate(col_widths):
                    cell_lines = wrapped_cells[ci] if ci < len(wrapped_cells) else [""]
                    cell = cell_lines[line_idx] if line_idx < len(cell_lines) else ""
                    pad = w - _visible_width(cell)
                    padded.append(f" {cell}{' ' * pad} ")
                content = f"{fg}{self.DIM}│{self.RESET}".join(f"{style}{p}{self.RESET}" for p in padded)
                output_lines.append(f"{fg}{self.DIM}│{self.RESET}{content}{fg}{self.DIM}│{self.RESET}")
            return output_lines

        result = [make_sep("┌", "┬", "┐")]
        for ri, row in enumerate(formatted):
            is_header = ri == 0 and len(separator_indices) > 0
            result.extend(make_row_lines(row, is_header))
            if ri == 0 and separator_indices:
                result.append(make_sep("├", "┼", "┤"))
        result.append(make_sep("└", "┴", "┘"))

        return "\n".join(result)

    def _format_inline(self, text: str) -> str:
        """Apply inline markdown formatting (bold, italic, code, links)."""
        if not text:
            return text

        result = []
        i = 0
        n = len(text)

        while i < n:
            # Inline code
            if text[i] == "`":
                end = text.find("`", i + 1)
                if end != -1:
                    code_text = text[i + 1 : end]
                    fg = self._fg("inline_code")
                    bg = self._bg(self._code_bg) if self._code_bg else ""
                    result.append(f"{bg}{fg} {code_text} {self.RESET}")
                    i = end + 1
                    continue

            # Bold + italic (***text***)
            if text[i : i + 3] == "***":
                end = text.find("***", i + 3)
                if end != -1:
                    inner = text[i + 3 : end]
                    result.append(f"{self.BOLD}{self.ITALIC}{self._format_inline(inner)}{self.RESET}")
                    i = end + 3
                    continue

            # Bold (**text**)
            if text[i : i + 2] == "**":
                end = text.find("**", i + 2)
                if end != -1:
                    inner = text[i + 2 : end]
                    result.append(f"{self.BOLD}{self._format_inline(inner)}{self.RESET}")
                    i = end + 2
                    continue

            # Italic (*text*) — only when preceded by whitespace/start
            if text[i] == "*" and (i == 0 or text[i - 1] in " \t("):
                end = text.find("*", i + 1)
                if end != -1 and end > i + 1:
                    inner = text[i + 1 : end]
                    result.append(f"{self.ITALIC}{self._format_inline(inner)}{self.RESET}")
                    i = end + 1
                    continue

            # Link [text](url)
            if text[i] == "[":
                bracket_end = text.find("]", i + 1)
                if bracket_end != -1 and bracket_end + 1 < n and text[bracket_end + 1] == "(":
                    paren_end = text.find(")", bracket_end + 2)
                    if paren_end != -1:
                        link_text = text[i + 1 : bracket_end]
                        fg = self._fg("link")
                        result.append(f"{fg}{self.UNDERLINE}{link_text}{self.RESET}")
                        i = paren_end + 1
                        continue

            result.append(text[i])
            i += 1

        return "".join(result)
