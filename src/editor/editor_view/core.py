"""Core helper functions and buffer utilities."""


def _iter_at_line(buf, line):
    """Get a valid TextIter at a line number, handling GTK4 tuple returns safely."""
    try:
        line_count = max(1, buf.get_line_count())
        safe_line = min(max(0, int(line)), line_count - 1)
    except Exception:
        safe_line = 0

    result = buf.get_iter_at_line(safe_line)
    if isinstance(result, (tuple, list)):
        if len(result) >= 2:
            if isinstance(result[0], bool) and not result[0]:
                return buf.get_start_iter()
            return result[1]
        return buf.get_start_iter()
    return result


def _iter_at_line_offset(buf, line, offset):
    """Get a valid TextIter at a line+offset, handling GTK4 tuple returns safely."""
    line_iter = _iter_at_line(buf, line)
    line_end = line_iter.copy()
    if not line_end.ends_line():
        line_end.forward_to_line_end()
    max_col = line_end.get_line_offset()
    safe_offset = min(max(0, int(offset)), max_col)
    safe_line = line_iter.get_line()

    result = buf.get_iter_at_line_offset(safe_line, safe_offset)
    if isinstance(result, (tuple, list)):
        if len(result) >= 2:
            if isinstance(result[0], bool) and not result[0]:
                return line_iter
            return result[1]
        return line_iter
    return result


def _iter_at_offset(buf, offset):
    """Get a fresh TextIter at a character offset, handling GTK4 tuple returns."""
    result = buf.get_iter_at_offset(min(max(0, offset), buf.get_char_count()))
    if isinstance(result, (tuple, list)):
        return result[1] if len(result) >= 2 else buf.get_start_iter()
    return result
