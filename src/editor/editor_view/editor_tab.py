"""EditorTab — represents a single editor tab with file I/O and diagnostics."""

import os
import time
from typing import Callable

from gi.repository import GLib, GtkSource

from themes import get_theme

from ..color_preview_renderer import ColorPreviewRenderer
from ..semantic_highlight import setup_semantic_highlight
from .core import _iter_at_line, _iter_at_line_offset
from .editor_tab_config_mixin import EditorTabConfigMixin
from .editor_tab_hover_mixin import EditorTabHoverMixin
from .editor_tab_input_mixin import EditorTabInputMixin
from .editor_tab_theme_mixin import EditorTabThemeMixin
from .zen_source_view import ZenSourceView


class EditorTab(EditorTabInputMixin, EditorTabHoverMixin, EditorTabThemeMixin, EditorTabConfigMixin):
    """Represents a single editor tab."""

    def __init__(self, file_path: str = None, is_new: bool = False):
        self.file_path = file_path
        self.is_new = is_new
        self.modified = False
        self.original_content = ""
        self._last_internal_save_time = 0.0

        # Create source view (ZenSourceView adds indent guide lines)
        self.buffer = GtkSource.Buffer()
        self.view = ZenSourceView(buffer=self.buffer)

        # Git diff gutter renderer (vertical bars drawn in do_snapshot).
        # File path is set later in load_file() to avoid duplicate git fetches.
        from ..gutter_diff_renderer import GutterDiffRenderer

        self._gutter_diff = GutterDiffRenderer(self.view)
        self.view._gutter_diff_renderer = self._gutter_diff

        # Inline color preview swatches (colored squares next to hex colors)
        self._color_preview = ColorPreviewRenderer(self.view)
        self.view._color_preview_renderer = self._color_preview

        # Breakpoint gutter renderer (red dots, execution pointer)
        from debugger.breakpoint_manager import get_breakpoint_manager
        from debugger.breakpoint_renderer import BreakpointRenderer

        self._breakpoint_renderer = BreakpointRenderer(self.view, get_breakpoint_manager())
        self.view._breakpoint_renderer = self._breakpoint_renderer

        # Diagnostic wavy underline tags
        self._setup_diagnostic_underline_tags()

        # Callback for diagnostics updates (set by EditorView)
        self.on_diagnostics_changed: Callable[[str, int, int], None] | None = None

        # Configure view
        self._configure_view()

        # Apply theme (language is set later in load_file to avoid
        # duplicate work — __init__ has no buffer content yet).
        self._apply_theme()

        # Semantic call-site highlighting (class usage + function calls)
        setup_semantic_highlight(self, get_theme())

        # Tree-sitter parse tree cache (incremental updates for semantic features)
        from ..tree_sitter_buffer_cache import setup_buffer_cache

        setup_buffer_cache(self)

        # Code folding (tree-sitter fold detection + invisible tags)
        from ..fold_manager import FoldManager

        self._fold_manager = FoldManager(self.view, self._ts_cache)
        self.view._fold_manager = self._fold_manager

        # Autocomplete (Ctrl+Space) — lazy init on first use
        self._autocomplete = None

        # Inline AI suggestions (ghost text) — lazy init on first keypress
        self._inline_completion = None

    def _ensure_inline_completion(self):
        """Lazily initialise the inline completion manager."""
        if self._inline_completion is not None:
            return self._inline_completion

        try:
            from ..inline_completion import InlineCompletionManager

            self._inline_completion = InlineCompletionManager(self)
        except Exception:
            pass
        return self._inline_completion

    def _ensure_autocomplete(self):
        """Lazily initialise the autocomplete manager."""
        if self._autocomplete is not None:
            return self._autocomplete
        from ..autocomplete import Autocomplete

        self._autocomplete = Autocomplete(self)
        return self._autocomplete

    def _apply_diagnostic_underlines(self, diagnostics):
        """Apply wavy underline tags for each diagnostic."""
        from shared.diagnostics_manager import SEVERITY_ERROR

        self._clear_diagnostic_underlines()

        line_count = self.buffer.get_line_count()
        for d in diagnostics:
            if d.line < 1 or d.line > line_count:
                continue

            tag = self._diag_error_tag if d.severity == SEVERITY_ERROR else self._diag_warning_tag

            # Start iter at (line, col) — both 1-based → 0-based
            start_line_0 = d.line - 1
            start_line_iter = _iter_at_line(self.buffer, start_line_0)
            line_chars = start_line_iter.get_chars_in_line()
            start_col = min(max(0, d.col - 1), max(0, line_chars - 1))
            start = _iter_at_line_offset(self.buffer, start_line_0, start_col)

            if d.end_line > 0 and d.end_col > 0:
                # Exact range from linter
                end_line_0 = min(d.end_line - 1, line_count - 1)
                end_iter = _iter_at_line(self.buffer, end_line_0)
                end_line_chars = end_iter.get_chars_in_line()
                end_col_0 = min(d.end_col - 1, max(0, end_line_chars - 1))
                end = _iter_at_line_offset(self.buffer, end_line_0, end_col_0)
            else:
                # No end info — underline the word at start position
                end = start.copy()
                if not end.ends_line():
                    end.forward_char()
                    while not end.ends_line():
                        ch = end.get_char()
                        if not (ch.isalnum() or ch == "_"):
                            break
                        end.forward_char()

            if start.compare(end) < 0:
                self.buffer.apply_tag(tag, start, end)

    def load_file(self, file_path: str) -> bool:
        """Load content from a file."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            # Auto-format JSON files for readability
            if file_path.lower().endswith(".json"):
                import json

                try:
                    parsed = json.loads(content)
                    content = json.dumps(parsed, indent=2, ensure_ascii=False) + "\n"
                except (json.JSONDecodeError, ValueError):
                    pass  # Keep original content if JSON is invalid

            # Set language BEFORE content so GtkSourceView applies regex
            # highlighting as the buffer text is set (avoids white flash).
            from editor.langs.language_detect import detect_language

            lang = detect_language(file_path)
            if lang:
                self.buffer.set_language(lang)

            self.buffer.set_text(content)
            self.original_content = content
            self.file_path = file_path
            self.modified = False
            self.is_new = False

            # Configure indent from file content (set_language is a no-op
            # since the same language is already set above).
            self._set_language_from_file(file_path)

            # Update gutter diff renderer with file path
            self._gutter_diff.set_file_path(file_path)

            # Update breakpoint renderer with file path
            self._breakpoint_renderer.set_file_path(file_path)

            # Apply cached diagnostics (from workspace scan) or run fresh
            self._apply_or_run_diagnostics()

            # Move cursor to beginning
            self.buffer.place_cursor(self.buffer.get_start_iter())

            # Force GtkSourceView to synchronously finish regex tokenisation
            # for the entire buffer so the first paint never shows un-styled
            # text.  Without this, the regex engine runs in idle handlers and
            # the view may render before highlighting is complete.
            self.buffer.ensure_highlight(
                self.buffer.get_start_iter(),
                self.buffer.get_end_iter(),
            )

            return True
        except Exception as e:
            import traceback

            print(f"\033[31m[ZEN] load_file failed for {file_path}: {e}\033[0m")
            traceback.print_exc()
            return False

    def reload_file(self) -> bool:
        """Reload content from file, preserving cursor position.

        Used when the file is modified externally.
        Returns True if reload succeeded, False otherwise.
        """
        if not self.file_path or not os.path.isfile(self.file_path):
            return False

        try:
            with open(self.file_path, "r", encoding="utf-8", errors="replace") as f:
                new_content = f.read()

            # Auto-format JSON files for readability
            if self.file_path.lower().endswith(".json"):
                import json

                try:
                    parsed = json.loads(new_content)
                    new_content = json.dumps(parsed, indent=2, ensure_ascii=False) + "\n"
                except (json.JSONDecodeError, ValueError):
                    pass

            # Skip reload if content hasn't actually changed
            start_iter = self.buffer.get_start_iter()
            end_iter = self.buffer.get_end_iter()
            current_content = self.buffer.get_text(start_iter, end_iter, True)
            if new_content == current_content:
                return True

            # Save cursor position (line and column) and scroll position
            cursor_mark = self.buffer.get_insert()
            cursor_iter = self.buffer.get_iter_at_mark(cursor_mark)
            cursor_line = cursor_iter.get_line()
            cursor_col = cursor_iter.get_line_offset()
            vadj = self.view.get_vadjustment()
            saved_scroll = vadj.get_value() if vadj else 0.0

            # Update original_content BEFORE set_text so the buffer-changed
            # handler sees matching content and doesn't mark tab as modified
            self.original_content = new_content
            self.modified = False
            self.buffer.set_text(new_content)

            # Restore cursor position (clamped to valid range)
            line_count = self.buffer.get_line_count()
            target_line = min(cursor_line, line_count - 1)
            new_iter = _iter_at_line(self.buffer, target_line)
            if new_iter:
                # Clamp column to line length
                line_end = new_iter.copy()
                if not line_end.ends_line():
                    line_end.forward_to_line_end()
                max_col = line_end.get_line_offset()
                target_col = min(cursor_col, max_col)
                new_iter.forward_chars(target_col)
                self.buffer.place_cursor(new_iter)

            # Restore scroll position after set_text reset it
            if vadj:
                GLib.idle_add(lambda: vadj.set_value(saved_scroll) or False)

            # Refresh gutter diff for external changes
            self._gutter_diff.refresh_head()

            # Force synchronous highlighting so the reload doesn't flash
            self.buffer.ensure_highlight(
                self.buffer.get_start_iter(),
                self.buffer.get_end_iter(),
            )

            return True
        except Exception as e:
            import traceback

            print(f"\033[31m[ZEN] reload_file failed: {e}\033[0m")
            traceback.print_exc()
            return False

    def save_file(self, file_path: str = None) -> bool:
        """Save content to a file."""
        if getattr(self, "_is_image", False):
            return False
        path = file_path or self.file_path
        if not path:
            return False

        try:
            start = self.buffer.get_start_iter()
            end = self.buffer.get_end_iter()
            content = self.buffer.get_text(start, end, True)

            # Auto-format on save
            formatted = self._format_on_save(path, content)
            if formatted is not None and formatted != content:
                content = formatted
                # Apply formatting using incremental edits to preserve scroll/cursor
                self._apply_incremental_edit(content)

            # Mark as internally saved BEFORE file write so file watcher
            # (which runs in background thread) won't race and reload
            self._last_internal_save_time = time.monotonic()

            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

            self.original_content = content
            self.file_path = path
            self.modified = False
            self.is_new = False

            # Refresh gutter diff (HEAD now matches saved content)
            self._gutter_diff.refresh_head()

            # Run diagnostics (linting) on save — deferred to avoid blocking
            self._run_diagnostics_deferred()

            return True
        except Exception as e:
            import traceback

            print(f"\033[31m[ZEN] save_file failed for {path}: {e}\033[0m")
            traceback.print_exc()
            return False

    def _format_on_save(self, path: str, content: str) -> str | None:
        """Run configured formatter on content before saving."""
        try:
            from editor.format_manager import format_content

            return format_content(path, content)
        except Exception:
            return None

    def _apply_incremental_edit(self, new_content: str):
        """Apply text changes incrementally to preserve scroll and cursor.

        Uses difflib to find minimal changes.
        This avoids the scroll jump caused by buffer.set_text().
        """
        import difflib

        old_lines = self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), True).splitlines(
            keepends=True
        )
        new_lines = new_content.splitlines(keepends=True)

        # Ensure last line has newline for consistent comparison
        if old_lines and not old_lines[-1].endswith("\n"):
            old_lines[-1] += "\n"
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"

        # Get opcodes describing how to transform old -> new
        matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
        opcodes = matcher.get_opcodes()

        # If no changes, nothing to do
        if all(op[0] == "equal" for op in opcodes):
            return

        self.buffer.begin_user_action()
        try:
            # Apply changes in reverse order to preserve line numbers
            for tag, i1, i2, j1, j2 in reversed(opcodes):
                if tag == "equal":
                    continue

                # Calculate character offsets for the range [i1, i2)
                start_iter = self.buffer.get_start_iter()
                for _ in range(i1):
                    if not start_iter.forward_line():
                        break

                end_iter = self.buffer.get_start_iter()
                for _ in range(i2):
                    if not end_iter.forward_line():
                        # i2 might be past end, go to buffer end
                        end_iter = self.buffer.get_end_iter()
                        break

                # Get new text for this region
                new_text = "".join(new_lines[j1:j2])
                # Strip trailing newline if we're at end of buffer
                if end_iter.is_end() and new_text.endswith("\n"):
                    new_text = new_text[:-1]

                # Use a mark to preserve position across the delete
                mark = self.buffer.create_mark(None, start_iter, True)
                self.buffer.delete(start_iter, end_iter)
                ins_iter = self.buffer.get_iter_at_mark(mark)
                self.buffer.delete_mark(mark)
                self.buffer.insert(ins_iter, new_text)

        finally:
            self.buffer.end_user_action()

    def _apply_or_run_diagnostics(self):
        """Apply cached diagnostics if available, otherwise run fresh."""
        if not self.file_path:
            return

        from shared.diagnostics_manager import get_diagnostics_manager

        mgr = get_diagnostics_manager()
        if mgr.has_diagnostics_data(self.file_path):
            # Workspace scan already produced results — apply them directly
            cached = mgr.get_diagnostics(self.file_path)
            self._apply_diagnostic_underlines(cached)
            cb = self.on_diagnostics_changed
            if cb:
                errors = sum(1 for d in cached if d.severity == "error")
                warnings = sum(1 for d in cached if d.severity != "error")
                cb(self.file_path, errors, warnings)
            return
        # No cached results — run fresh diagnostics
        self._run_diagnostics()

    def _run_diagnostics(self):
        """Run linter diagnostics for this file."""
        if not self.file_path:
            return

        from shared.diagnostics_manager import get_diagnostics_manager

        mgr = get_diagnostics_manager()

        def on_results(file_path, diagnostics):
            if file_path == self.file_path:
                self._apply_diagnostic_underlines(diagnostics)
                # Resolve callback at result time (not capture time) so it
                # works even when diagnostics are kicked off before
                # _add_tab_common wires the callback.
                cb = self.on_diagnostics_changed
                if cb:
                    errors = sum(1 for d in diagnostics if d.severity == "error")
                    warnings = sum(1 for d in diagnostics if d.severity != "error")
                    cb(file_path, errors, warnings)

        mgr.run_diagnostics(self.file_path, callback=on_results)

    def _run_diagnostics_deferred(self):
        """Run linter diagnostics after a short delay (debounced)."""
        if not self.file_path:
            return

        from shared.diagnostics_manager import get_diagnostics_manager

        mgr = get_diagnostics_manager()

        def on_results(file_path, diagnostics):
            if file_path == self.file_path:
                self._apply_diagnostic_underlines(diagnostics)
                cb = self.on_diagnostics_changed
                if cb:
                    errors = sum(1 for d in diagnostics if d.severity == "error")
                    warnings = sum(1 for d in diagnostics if d.severity != "error")
                    cb(file_path, errors, warnings)

        mgr.run_diagnostics_deferred(self.file_path, callback=on_results)

    def get_title(self) -> str:
        """Get the tab title (without modified indicator)."""
        if self.file_path:
            name = os.path.basename(self.file_path)
            from constants import WORKSPACE_EXTENSIONS

            for ext in WORKSPACE_EXTENSIONS:
                if name.endswith(ext):
                    name = name[: -len(ext)]
                    break
            return name
        else:
            return "Untitled"
