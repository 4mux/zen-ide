"""
Commit history navigation and find bar for Zen IDE's diff view.
"""

import os
import threading

from gi.repository import Gdk, GLib, Gtk, GtkSource

from fonts import get_font_settings
from icons import IconsManager
from shared.git_manager import get_git_manager
from shared.main_thread import main_thread_call
from shared.ui import ZenButton
from shared.ui.zen_entry import ZenSearchEntry


class DiffNavigationMixin:
    """Mixin providing commit navigation, git operations, and find bar for DiffView."""

    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Handle key press events."""
        meta = Gdk.ModifierType.META_MASK
        ctrl = Gdk.ModifierType.CONTROL_MASK

        # Cmd+F / Ctrl+F opens find bar
        if keyval == Gdk.KEY_f and (state & (meta | ctrl)):
            self.show_find_bar()
            return True

        if keyval == Gdk.KEY_Escape:
            # If find bar is open, close it first
            if self._find_bar and self._find_bar.get_search_mode():
                self._find_bar.set_search_mode(False)
                self.grab_focus()
                return True
            self._close()
            return True
        elif keyval == Gdk.KEY_Left:
            self._navigate_commit(1)  # older
            return True
        elif keyval == Gdk.KEY_Right:
            self._navigate_commit(-1)  # newer
            return True
        return False

    def show_diff(self, file_path: str, current_content: str = None, scroll_to_line: int = 0):
        """Show diff for a file with commit history."""
        if not file_path or not os.path.exists(file_path):
            return

        self._current_file_path = file_path
        self._pending_scroll_line = scroll_to_line

        # Get current content
        if current_content is None:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    current_content = f.read()
            except Exception:
                current_content = ""
        self._current_content = current_content

        # Show loading state (don't clear buffers yet to avoid empty pane flash)
        self._title_label.set_text(f"Diff: {os.path.basename(file_path)}")
        self._commit_label.set_text("Loading...")
        self._prev_btn.set_sensitive(False)
        self._next_btn.set_sensitive(False)

        # Load git data in background
        def load_git_data():
            commits = self._get_file_commits(file_path)
            if not commits:
                main_thread_call(self._on_load_complete, None, None, "no_commits")
                return

            commit_content = self._get_commit_content(file_path, commits[0]["sha"])
            if commit_content is None:
                main_thread_call(self._on_load_complete, None, None, "no_content")
                return

            main_thread_call(self._on_load_complete, commits, commit_content, None)

        thread = threading.Thread(target=load_git_data, daemon=True)
        thread.start()

    def _on_load_complete(self, commits, commit_content, error):
        """Called when git data loading is complete."""
        if error:
            if error == "no_commits":
                self._commit_label.set_text("No commit history")
                self._show_main_branch_diff()
            else:
                self._commit_label.set_text("Error loading commits")
            return

        self._commits = commits
        self._current_commit_index = 0
        self._commit_content = commit_content

        self._update_ui()
        self._apply_diff(commit_content, self._current_content)

        # Set language for syntax highlighting
        self._set_language(self._current_file_path)

        # Schedule paned position update, then scroll to the editor's line
        GLib.idle_add(self._update_paned_position)
        self._scroll_to_pending_line()

    def _show_main_branch_diff(self):
        """Fall back to showing diff vs main branch."""
        main_content, error = self._get_main_branch_content(self._current_file_path)

        if error:
            self._left_pane_label.set_text(f"← main ({error})")
        else:
            self._left_pane_label.set_text("← main")
        self._right_pane_label.set_text("→ current")

        self._commit_content = main_content
        self._apply_diff(main_content, self._current_content)
        self._set_language(self._current_file_path)
        GLib.idle_add(self._update_paned_position)
        self._scroll_to_pending_line()

    def _scroll_to_pending_line(self):
        """Scroll to the line saved from the editor, once layout has settled.

        Hides both panes before the scroll so no intermediate top-of-file
        frame is ever painted, then reveals after the position is set.
        """
        line = getattr(self, "_pending_scroll_line", 0)
        if line <= 0:
            return
        self._pending_scroll_line = 0

        self._left_scroll.set_opacity(0)
        self._right_scroll.set_opacity(0)

        def _apply_and_reveal():
            self._scroll_to_line(line)
            # Reveal on the next frame after the adjustment has taken effect
            GLib.idle_add(self._reveal_scroll_panes)
            return False

        GLib.idle_add(_apply_and_reveal)

    def _reveal_scroll_panes(self):
        self._left_scroll.set_opacity(1)
        self._right_scroll.set_opacity(1)
        return False

    def _update_ui(self):
        """Update UI elements based on current state."""
        if not self._commits:
            return

        commit = self._commits[self._current_commit_index]
        sha_short = commit["sha"][:7]
        date = commit.get("date", "")
        message = commit.get("message", "")[:40]

        self._commit_label.set_text(f"{sha_short} - {date} - {message}")

        # Update pane labels
        self._left_pane_label.set_text(f"← {sha_short}")

        # Get current branch name
        git_root = self._find_git_root(self._current_file_path)
        if git_root:
            branch = self._get_current_branch(git_root)
            self._right_pane_label.set_text(f"→ {branch}")
        else:
            self._right_pane_label.set_text("→ current")

        # Update navigation buttons
        can_go_older = self._current_commit_index < len(self._commits) - 1
        can_go_newer = self._current_commit_index > 0
        self._prev_btn.set_sensitive(can_go_older)
        self._next_btn.set_sensitive(can_go_newer)

    def _navigate_commit(self, direction: int):
        """Navigate to prev/next commit. direction: 1=older, -1=newer."""
        if not self._commits:
            return

        new_index = self._current_commit_index + direction
        if new_index < 0 or new_index >= len(self._commits):
            return

        self._current_commit_index = new_index
        commit_content = self._get_commit_content(self._current_file_path, self._commits[self._current_commit_index]["sha"])
        if commit_content is None:
            return

        self._commit_content = commit_content
        self._update_ui()
        self._apply_diff(commit_content, self._current_content)

    # --- Git operations (delegated to GitManager) ---

    def _get_file_commits(self, file_path: str, limit: int = 100) -> list:
        """Get list of commits that touched this file."""
        git = get_git_manager()
        commits = git.get_file_commits(file_path, limit=limit)
        # Remap keys: GitManager returns {sha, message, author, date}
        return [{"sha": c["sha"], "date": c["date"], "message": c["message"]} for c in commits]

    def _get_commit_content(self, file_path: str, commit_sha: str) -> str | None:
        """Get file content at a specific commit."""
        git = get_git_manager()
        repo_root = git.get_repo_root(file_path)
        if not repo_root:
            return None
        rel_path = os.path.relpath(file_path, repo_root)
        return git.get_file_at_ref(repo_root, rel_path, commit_sha)

    def _get_main_branch_content(self, file_path: str) -> tuple[str, str | None]:
        """Get file content from main branch."""
        git = get_git_manager()
        repo_root = git.get_repo_root(file_path)
        if not repo_root:
            return "", "Not a git repository"
        rel_path = os.path.relpath(file_path, repo_root)
        content = git.get_file_at_main_branch(repo_root, rel_path)
        if content is not None:
            return content, None
        return "", "File not on main/master"

    def _find_git_root(self, file_path: str) -> str | None:
        """Find git repository root."""
        return get_git_manager().get_repo_root(file_path)

    def _get_current_branch(self, git_root: str) -> str:
        """Get current branch name."""
        return get_git_manager().get_current_branch(git_root)

    def _set_language(self, file_path: str):
        """Set syntax highlighting language."""
        from editor.langs.language_detect import detect_language

        language = detect_language(file_path)
        if language:
            self.left_buffer.set_language(language)
            self.right_buffer.set_language(language)

    # -- Find bar --

    def _create_find_bar(self):
        """Create the find bar for searching in diff view."""
        self._find_bar = Gtk.SearchBar()
        self._find_bar.set_show_close_button(True)

        find_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        self._find_entry = ZenSearchEntry(placeholder="Find in diff...")
        self._find_entry.set_hexpand(True)
        self._find_entry.connect("search-changed", self._on_diff_find_changed)
        self._find_entry.connect("activate", self._on_diff_find_next)

        find_key_ctrl = Gtk.EventControllerKey()
        find_key_ctrl.connect("key-pressed", self._on_find_entry_key)
        self._find_entry.add_controller(find_key_ctrl)
        find_row.append(self._find_entry)

        self._find_count_label = Gtk.Label(label="")
        self._find_count_label.add_css_class("dim-label")
        find_row.append(self._find_count_label)

        prev_btn = ZenButton(icon=IconsManager.ARROW_UP, tooltip="Previous (Shift+Enter)")
        prev_btn.connect("clicked", lambda b: self._on_diff_find_prev())
        find_row.append(prev_btn)

        next_btn = ZenButton(icon=IconsManager.ARROW_DOWN, tooltip="Next (Enter)")
        next_btn.connect("clicked", lambda b: self._on_diff_find_next())
        find_row.append(next_btn)

        self._find_bar.set_child(find_row)
        self._find_bar.connect_entry(self._find_entry)
        self.append(self._find_bar)

        # Move find bar after header (index 1)
        self.reorder_child_after(self._find_bar, self._header)

        self._apply_find_bar_font()

    def _apply_find_bar_font(self):
        """Apply editor font to find entry."""
        font_settings = get_font_settings("editor")
        font_family = font_settings["family"]
        font_size = font_settings.get("size", 13)

        provider = Gtk.CssProvider()
        css = f"""
            searchentry {{
                font-family: '{font_family}';
                font-size: {font_size}pt;
            }}
        """
        provider.load_from_data(css.encode())
        self._find_entry.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)

    def show_find_bar(self):
        """Show the find bar and focus the entry."""
        self._find_bar.set_search_mode(True)
        self._find_entry.grab_focus()
        pos = len(self._find_entry.get_text())
        if pos > 0:
            self._find_entry.select_region(0, pos)

    def _on_find_entry_key(self, controller, keyval, keycode, state):
        """Handle key press in find entry."""
        if keyval == Gdk.KEY_Escape:
            self._find_bar.set_search_mode(False)
            self.grab_focus()
            return True

        # Shift+Enter = find previous
        shift = Gdk.ModifierType.SHIFT_MASK
        if keyval == Gdk.KEY_Return and (state & shift):
            self._on_diff_find_prev()
            return True

        # Cmd+Backspace clears entry
        meta = Gdk.ModifierType.META_MASK
        if keyval == Gdk.KEY_BackSpace and (state & meta):
            self._find_entry.set_text("")
            return True

        return False

    def _ensure_diff_search_contexts(self, text: str):
        """Create or update search contexts for both diff buffers."""
        if self._search_settings is None:
            self._search_settings = GtkSource.SearchSettings()
            self._search_settings.set_case_sensitive(False)
            self._search_settings.set_wrap_around(True)

        self._search_settings.set_search_text(text if text else None)

        if self._left_search_context is None or self._left_search_context.get_buffer() != self.left_buffer:
            self._left_search_context = GtkSource.SearchContext(buffer=self.left_buffer, settings=self._search_settings)
        if self._right_search_context is None or self._right_search_context.get_buffer() != self.right_buffer:
            self._right_search_context = GtkSource.SearchContext(buffer=self.right_buffer, settings=self._search_settings)

    def _on_diff_find_changed(self, entry):
        """Handle find text change."""
        text = entry.get_text()
        self._ensure_diff_search_contexts(text)
        if text:
            self._diff_find_text(text, forward=True)
        else:
            self._find_count_label.set_label("")

    def _on_diff_find_next(self, *args):
        """Find next occurrence."""
        text = self._find_entry.get_text()
        if text:
            self._diff_find_text(text, forward=True)

    def _on_diff_find_prev(self, *args):
        """Find previous occurrence."""
        text = self._find_entry.get_text()
        if text:
            self._diff_find_text(text, forward=False)

    def _diff_find_text(self, text: str, forward: bool = True):
        """Find text in the active diff side (right by default)."""
        self._ensure_diff_search_contexts(text)

        # Search in the right (current) buffer
        ctx = self._right_search_context
        buf = self.right_buffer
        view = self.right_view

        cursor = buf.get_insert()
        cursor_iter = buf.get_iter_at_mark(cursor)

        if forward:
            if buf.get_has_selection():
                _, cursor_iter = buf.get_selection_bounds()
            found, start, end, wrapped = ctx.forward(cursor_iter)
        else:
            if buf.get_has_selection():
                cursor_iter, _ = buf.get_selection_bounds()
            found, start, end, wrapped = ctx.backward(cursor_iter)

        if found:
            buf.select_range(start, end)
            view.scroll_to_iter(start, 0.2, False, 0.0, 0.5)

        GLib.timeout_add(50, lambda: self._update_diff_find_count() or False)

    def _update_diff_find_count(self):
        """Update the match count label with combined counts from both sides."""
        if not self._right_search_context:
            self._find_count_label.set_label("")
            return

        left_count = max(0, self._left_search_context.get_occurrences_count()) if self._left_search_context else 0
        right_count = max(0, self._right_search_context.get_occurrences_count())

        if left_count < 0 or right_count < 0:
            self._find_count_label.set_label("...")
            return

        total = left_count + right_count
        if total == 0:
            self._find_count_label.set_label("No results")
            return

        # Show position in right side
        ctx = self._right_search_context
        buf = self.right_buffer
        pos_str = ""
        if buf.get_has_selection():
            sel_start, sel_end = buf.get_selection_bounds()
            pos = ctx.get_occurrence_position(sel_start, sel_end)
            if pos > 0:
                pos_str = f"{pos} of "

        if left_count > 0 and right_count > 0:
            self._find_count_label.set_label(f"{pos_str}{right_count}  (left: {left_count})")
        elif right_count > 0:
            self._find_count_label.set_label(f"{pos_str}{right_count} results")
        else:
            self._find_count_label.set_label(f"left: {left_count}")
