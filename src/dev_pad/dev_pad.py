"""
Dev Pad - Activity tracking panel for Zen IDE.

Shows a chronological list of user activities (file edits, AI chats, git operations)
with clickable links to quickly resume work.
"""

import json
import os
import subprocess
import threading
import webbrowser
from datetime import datetime
from typing import Callable, Optional

from gi.repository import Gdk, GLib, Gtk, Pango

from constants import DEFAULT_FONT_SIZE

# Import the dev_pad_storage from same package
from dev_pad.dev_pad_storage import NOTES_DIR, DevPadActivity, get_dev_pad_storage
from fonts import get_font_settings
from icons import Icons, apply_icon_font, get_icon_font_name
from shared.main_thread import main_thread_call
from shared.settings import get_setting
from shared.ui import ZenButton
from shared.ui.zen_entry import ZenEntry
from themes import get_theme, subscribe_theme_change


def _abbreviate_path(path: str, max_len: int = 50) -> str:
    """Abbreviate a file path to fit in a given length."""
    if not path:
        return ""
    if len(path) <= max_len:
        return path
    # Replace home dir with ~
    home = os.path.expanduser("~")
    if path.startswith(home):
        path = "~" + path[len(home) :]
    if len(path) <= max_len:
        return path
    # Truncate from the middle
    half = (max_len - 3) // 2
    return path[:half] + "..." + path[-half:]


class DevPad(Gtk.Box):
    """
    Activity tracking panel that shows recent user activities.
    Uses a scrolled window with native GTK widgets.
    """

    def __init__(
        self,
        open_file_callback: Optional[Callable[[str], None]] = None,
        open_ai_chat_callback: Optional[Callable[[str], None]] = None,
        open_repo_callback: Optional[Callable[[str], None]] = None,
        focus_tab_callback: Optional[Callable[[int], None]] = None,
        get_workspace_folders_callback: Optional[Callable[[], list[str]]] = None,
        new_ai_chat_callback: Optional[Callable[[], None]] = None,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.open_file_callback = open_file_callback
        self.open_ai_chat_callback = open_ai_chat_callback
        self.open_repo_callback = open_repo_callback
        self.focus_tab_callback = focus_tab_callback
        self.get_workspace_folders_callback = get_workspace_folders_callback
        self.new_ai_chat_callback = new_ai_chat_callback

        self._storage = get_dev_pad_storage()
        self._storage.add_listener(self._on_storage_change)

        # Track activities for click handling
        self._activity_links: dict[str, DevPadActivity] = {}
        self._link_tag_counter = 0

        # Search and filter state
        self._search_query = ""
        self._type_filter: set[str] | None = None

        self._setup_ui()
        self._apply_styles()

        # Subscribe to theme changes
        subscribe_theme_change(self._on_theme_change)

    def _get_font_settings(self):
        """Get font settings from config."""
        settings = get_font_settings("dev_pad")
        family = settings["family"]
        size = settings.get("size", DEFAULT_FONT_SIZE)
        weight = settings.get("weight", "normal")
        return family, size, weight

    @staticmethod
    def _apply_nerd_font(label: Gtk.Label, size_pt: int | None = None) -> None:
        """Apply icon font family to a label via Pango attributes."""
        apply_icon_font(label, size_pt)

    def apply_font_settings(self):
        """Re-apply font settings (called after zoom changes)."""
        self._apply_styles()

    def _setup_ui(self):
        """Create the Dev Pad UI."""
        family, size, weight = self._get_font_settings()

        # Row 1: search box with filters inside on the right
        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        search_row.set_margin_start(10)
        search_row.set_margin_end(10)
        search_row.set_margin_top(10)
        search_row.set_margin_bottom(5)

        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        search_box.set_hexpand(True)
        search_box.add_css_class("dev-pad-search-box")

        search_icon = Gtk.Label(label=Icons.SEARCH)
        search_icon.add_css_class("dev-pad-icon")
        search_icon.add_css_class("dev-pad-search-icon")
        self._apply_nerd_font(search_icon, size)
        search_box.append(search_icon)

        self.search_entry = ZenEntry(placeholder="Search recent activities and quick links")
        self.search_entry.set_hexpand(True)
        self.search_entry.add_css_class("dev-pad-search")
        self.search_entry.connect("changed", self._on_search_change)
        search_box.append(self.search_entry)

        # Filter buttons inside search box (right side)
        self._filter_buttons = {}
        filter_options = [
            ("All", None, None),
            ("PRs", {"github_pr"}, Icons.GIT_MERGE),
            ("Notes", {"note"}, Icons.PIN),
            ("Sketches", {"sketch"}, Icons.PENCIL),
        ]

        for text, filter_types, icon in filter_options:
            btn = ZenButton(icon=icon, label=text) if icon else ZenButton(label=text)
            btn.add_css_class("dev-pad-filter-btn")
            if filter_types == self._type_filter:
                btn.add_css_class("dev-pad-filter-active")
            btn.connect("clicked", lambda b, ft=filter_types: self._on_filter_click(ft))
            search_box.append(btn)
            key = str(filter_types) if filter_types else "all"
            self._filter_buttons[key] = btn

        search_row.append(search_box)
        self.append(search_row)

        # Row 2: action buttons below the search row
        action_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        action_bar.set_margin_start(10)
        action_bar.set_margin_end(10)
        action_bar.set_margin_bottom(5)

        # Add Note button
        self.add_note_btn = ZenButton(icon=Icons.PLUS, label="Note")
        self.add_note_btn.add_css_class("dev-pad-btn")
        self.add_note_btn.connect("clicked", self._on_add_note)
        action_bar.append(self.add_note_btn)

        # Add Sketch button
        self.add_sketch_btn = ZenButton(icon=Icons.PLUS, label="Sketch")
        self.add_sketch_btn.add_css_class("dev-pad-btn")
        self.add_sketch_btn.connect("clicked", self._on_add_sketch)
        action_bar.append(self.add_sketch_btn)

        # Refresh PRs button
        self.refresh_prs_btn = ZenButton(icon=Icons.GIT_MERGE, label="Refresh PRs")
        self.refresh_prs_btn.add_css_class("dev-pad-btn-dim")
        self.refresh_prs_btn.connect("clicked", self._on_refresh_prs)
        action_bar.append(self.refresh_prs_btn)

        # Clear All button
        self.clear_btn = ZenButton(label="Clear All")
        self.clear_btn.add_css_class("dev-pad-btn-dim")
        self.clear_btn.connect("clicked", self._on_clear_all)
        action_bar.append(self.clear_btn)

        self.append(action_bar)

        # Separator
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self.append(sep)

        # Scrollable content area
        self.scrolled_window = Gtk.ScrolledWindow()
        self.scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scrolled_window.set_vexpand(True)
        self.append(self.scrolled_window)

        # Content box for activities
        self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.content_box.set_margin_start(10)
        self.content_box.set_margin_end(10)
        self.content_box.set_margin_top(5)
        self.content_box.set_margin_bottom(10)
        self.scrolled_window.set_child(self.content_box)

    def _apply_styles(self):
        """Apply Dev Pad styles."""
        theme = get_theme()
        family, size, weight = self._get_font_settings()

        # Convert weight to CSS value
        css_weight = "bold" if weight == "bold" else ("300" if weight == "light" else "normal")

        nerd_font = get_icon_font_name()

        css_provider = Gtk.CssProvider()
        css = f"""
            .dev-pad-btn {{
                background-color: transparent;
                color: {theme.accent_color};
                border: none;
                padding: 4px 8px;
            }}
            .dev-pad-btn label {{
                font-family: "{family}";
                font-size: {size - 1}pt;
            }}
            .dev-pad-btn:hover {{
                color: {theme.selection_bg};
            }}
            .dev-pad-btn-dim {{
                background-color: transparent;
                color: {theme.fg_dim};
                border: none;
                padding: 4px 8px;
            }}
            .dev-pad-btn-dim label {{
                font-family: "{family}";
                font-size: {size - 1}pt;
            }}
            .dev-pad-btn-dim:hover {{
                color: {theme.accent_color};
            }}
            .dev-pad-close-btn {{
                background-color: transparent;
                color: {theme.fg_dim};
                border: none;
                padding: 4px;
            }}
            .dev-pad-close-btn label {{
                font-family: "{nerd_font}", "{family}";
                font-size: {size}pt;
            }}
            .dev-pad-close-btn:hover {{
                color: {theme.accent_color};
            }}
            .dev-pad-search-box {{
                background-color: {theme.main_bg};
                border: 1px solid {theme.border_color};
                border-radius: 4px;
                padding: 4px 8px;
            }}
            .dev-pad-search-box:focus-within {{
                border-color: {theme.accent_color};
            }}
            .dev-pad-search-icon {{
                font-family: "{nerd_font}", "{family}";
                color: {theme.fg_dim};
                font-size: {size}pt;
            }}
            .dev-pad-search {{
                font-family: "{family}";
                font-size: {size}pt;
                background: none;
                color: {theme.fg_color};
                border: none;
                box-shadow: none;
                outline: none;
                padding: 2px 4px;
            }}
            .dev-pad-filter-label {{
                font-family: "{family}";
                color: {theme.fg_dim};
                font-size: {size - 1}pt;
            }}
            .dev-pad-filter-btn {{
                background-color: transparent;
                color: {theme.fg_dim};
                border: none;
                padding: 4px 8px;
            }}
            .dev-pad-filter-btn label {{
                font-family: "{nerd_font}", "{family}";
                font-size: {size - 1}pt;
            }}
            .dev-pad-filter-btn:hover {{
                color: {theme.accent_color};
            }}
            .dev-pad-filter-active {{
                color: {theme.accent_color};
            }}
            .dev-pad-date {{
                font-family: "{family}";
                font-weight: bold;
                font-size: {size}pt;
                color: {theme.accent_color};
                margin-top: 10px;
                margin-bottom: 5px;
            }}
            .dev-pad-activity-row {{
                padding: 4px 0;
            }}
            .dev-pad-activity-row:hover {{
                background-color: {theme.hover_bg};
            }}
            .dev-pad-delete-btn {{
                color: {theme.fg_dim};
                min-width: 20px;
                min-height: 20px;
            }}
            .dev-pad-delete-btn:hover {{
                color: {theme.accent_color};
            }}
            .dev-pad-time {{
                font-family: "{family}";
                color: {theme.fg_dim};
                font-size: {size - 1}pt;
            }}
            .dev-pad-icon {{
                font-family: "{nerd_font}", "{family}";
                color: {theme.fg_color};
            }}
            .dev-pad-link {{
                font-family: "{family}";
                font-size: {size}pt;
                font-weight: {css_weight};
                color: {theme.accent_color};
            }}
            .dev-pad-link:hover {{
                text-decoration: underline;
            }}
            .dev-pad-text {{
                font-family: "{family}";
                font-size: {size}pt;
                font-weight: {css_weight};
                color: {theme.fg_color};
            }}
            .dev-pad-desc {{
                font-family: "{family}";
                color: {theme.fg_dim};
                font-size: {size - 1}pt;
                margin-left: 25px;
            }}
            .dev-pad-desc-quote {{
                font-family: "{family}";
                color: {theme.fg_dim};
                font-size: {size - 1}pt;
                margin-left: 25px;
                padding-left: 8px;
                padding-top: 4px;
                padding-bottom: 4px;
                border-left: 2px solid {theme.accent_color};
            }}
            .dev-pad-empty {{
                font-family: "{family}";
                color: {theme.fg_dim};
                margin: 20px;
            }}
            .dev-pad-sketch-preview {{
                font-family: "{family}";
                font-size: {size - 2}pt;
                color: {theme.fg_dim};
                background-color: {theme.main_bg};
                border: 1px solid {theme.border_color};
                border-radius: 4px;
                padding: 6px 8px;
                margin-left: 25px;
                margin-top: 2px;
                margin-bottom: 2px;
            }}
        """
        css_provider.load_from_data(css.encode())

        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _refresh(self):
        """Refresh the activity list."""
        # Clear existing content
        while True:
            child = self.content_box.get_first_child()
            if child:
                self.content_box.remove(child)
            else:
                break

        self._activity_links.clear()
        self._link_tag_counter = 0

        # Get activities grouped by date
        max_activities = get_setting("dev_pad.max_activities", 500)
        grouped = self._storage.get_activities_grouped_by_date(
            limit=max_activities, filter_query=self._search_query, type_filter=self._type_filter
        )

        if not grouped:
            # Show empty state
            empty_label = Gtk.Label(label="\n\nNo activities yet.\n\nAs you work, your activities will appear here.")
            empty_label.set_halign(Gtk.Align.CENTER)
            empty_label.add_css_class("dev-pad-empty")
            self.content_box.append(empty_label)
            return

        # Display activities by date
        for date_key, activities in grouped.items():
            # Date header
            date_label = Gtk.Label(label=date_key)
            date_label.set_halign(Gtk.Align.START)
            date_label.add_css_class("dev-pad-date")
            self.content_box.append(date_label)

            # Activities for this date
            for activity in activities:
                row = self._create_activity_row(activity)
                self.content_box.append(row)

    def refresh(self):
        """Public method to refresh the activity list."""
        self._refresh()

    def _create_activity_row(self, activity: DevPadActivity) -> Gtk.Box:
        """Create a row widget for an activity."""
        # Main row container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        main_box.add_css_class("dev-pad-activity-row")

        # Top row: delete, time, icon, title
        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        # Delete icon as a label with click gesture (not Gtk.Button to avoid
        # button CSS overriding the nerd font — same pattern as TabButton)
        del_icon = Gtk.Label(label=Icons.CLOSE)
        del_icon.add_css_class("dev-pad-icon")
        del_icon.add_css_class("dev-pad-delete-btn")
        del_icon.set_cursor_from_name("pointer")
        _, icon_size, _ = self._get_font_settings()
        self._apply_nerd_font(del_icon, icon_size)
        del_click = Gtk.GestureClick.new()
        del_click.connect("released", lambda g, n, x, y, a=activity: self._on_delete_activity(a))
        del_icon.add_controller(del_click)
        top_row.append(del_icon)

        # Time
        try:
            dt = datetime.fromisoformat(activity.timestamp)
            time_str = dt.strftime("%H:%M")
        except Exception:
            time_str = "     "

        time_label = Gtk.Label(label=time_str)
        time_label.add_css_class("dev-pad-time")
        top_row.append(time_label)

        # Icon
        icon = self._get_activity_icon(activity.activity_type)
        icon_label = Gtk.Label(label=icon)
        icon_label.add_css_class("dev-pad-icon")
        _, icon_size, _ = self._get_font_settings()
        self._apply_nerd_font(icon_label, icon_size)
        top_row.append(icon_label)

        # Title (clickable if link_target is set)
        if activity.link_target:
            # Use a label with click gesture for proper wrapping
            title_label = Gtk.Label(label=activity.title)
            title_label.add_css_class("dev-pad-link")
            title_label.set_hexpand(True)
            title_label.set_halign(Gtk.Align.START)
            title_label.set_wrap(True)
            title_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            title_label.set_xalign(0)

            # Add click gesture
            click = Gtk.GestureClick.new()
            click.connect("released", lambda g, n, x, y, a=activity: self._on_link_click(a))
            title_label.add_controller(click)

            # Store activity reference
            self._link_tag_counter += 1
            tag = f"link_{self._link_tag_counter}"
            self._activity_links[tag] = activity

            top_row.append(title_label)
        else:
            title_label = Gtk.Label(label=activity.title)
            title_label.add_css_class("dev-pad-text")
            title_label.set_hexpand(True)
            title_label.set_halign(Gtk.Align.START)
            title_label.set_wrap(True)
            title_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            title_label.set_xalign(0)
            top_row.append(title_label)

        main_box.append(top_row)

        # Sketch preview (for sketch activities with content in metadata)
        if activity.activity_type == "sketch" and activity.metadata.get("content"):
            preview_text = self._get_sketch_preview(activity.metadata["content"])
            if preview_text:
                preview_label = Gtk.Label(label=preview_text)
                preview_label.set_halign(Gtk.Align.START)
                preview_label.add_css_class("dev-pad-sketch-preview")
                preview_label.set_xalign(0)
                # Make the preview clickable too
                if activity.link_target:
                    click = Gtk.GestureClick.new()
                    click.connect("released", lambda g, n, x, y, a=activity: self._on_link_click(a))
                    preview_label.add_controller(click)
                main_box.append(preview_label)
        # Description (if different from title)
        elif activity.description and activity.description != activity.title:
            desc_label = Gtk.Label(label=activity.description)
            desc_label.set_halign(Gtk.Align.START)
            if activity.activity_type in ("ai_chat", "ai_question"):
                desc_label.add_css_class("dev-pad-desc-quote")
            else:
                desc_label.add_css_class("dev-pad-desc")
            desc_label.set_wrap(True)
            desc_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            desc_label.set_xalign(0)
            main_box.append(desc_label)

        return main_box

    def _get_activity_icon(self, activity_type: str) -> str:
        """Get an icon for the activity type."""
        icons = {
            "file_edit": Icons.EDIT,
            "file_open": Icons.FILE,
            "file_save": Icons.SAVE,
            "file_new": Icons.CLIPBOARD,
            "ai_chat": Icons.ROBOT,
            "ai_question": Icons.QUESTION,
            "git_checkout": Icons.GIT_BRANCH,
            "git_commit": Icons.CHECK,
            "git_push": Icons.ARROW_UP,
            "git_pull": Icons.ARROW_DOWN,
            "search": Icons.SEARCH,
            "terminal": Icons.TERMINAL,
            "error": Icons.ERROR,
            "debug": Icons.BUG,
            "test": Icons.FLASK,
            "build": Icons.HAMMER,
            "pr_review": Icons.EYE,
            "github_pr": Icons.GIT_MERGE,
            "note": Icons.PIN,
            "sketch": Icons.PENCIL,
        }
        return icons.get(activity_type, Icons.MODIFIED_DOT)

    def _get_sketch_preview(self, content: str, max_lines: int = 8, max_width: int = 60) -> str:
        """Get a compact preview of sketch ASCII art content."""
        lines = content.split("\n")
        # Filter out empty lines and trim
        non_empty = [line for line in lines if line.strip()]
        if not non_empty:
            return ""
        preview_lines = non_empty[:max_lines]
        result = []
        for line in preview_lines:
            if len(line) > max_width:
                result.append(line[:max_width] + "…")
            else:
                result.append(line)
        if len(non_empty) > max_lines:
            result.append("  ...")
        return "\n".join(result)

    def _on_link_click(self, activity: DevPadActivity):
        """Handle click on an activity link."""

        # Sketch activities: open the .zen_sketch file
        if activity.activity_type == "sketch" and activity.link_type == "file" and self.open_file_callback:
            self.open_file_callback(activity.link_target)
            return

        if activity.link_type == "file" and self.open_file_callback:
            self.open_file_callback(activity.link_target)
        elif activity.link_type == "ai_chat" and self.open_ai_chat_callback:
            self.open_ai_chat_callback(activity.link_target)
        elif activity.link_type == "repo" and self.open_repo_callback:
            self.open_repo_callback(activity.link_target)
        elif activity.link_type == "tab" and self.focus_tab_callback:
            try:
                tab_id = int(activity.link_target)
                self.focus_tab_callback(tab_id)
            except (ValueError, TypeError):
                pass
        elif activity.link_type == "url":
            webbrowser.open(activity.link_target)
        elif activity.link_type == "note":
            # Open note for editing
            self._edit_note(activity)

    def _on_delete_activity(self, activity: DevPadActivity):
        """Delete a single activity."""
        self._storage.delete_activity(activity.id)

    def _edit_note(self, activity: DevPadActivity):
        """Open note as a markdown file in the editor."""
        # Create notes directory if needed
        NOTES_DIR.mkdir(parents=True, exist_ok=True)

        # Create .md file for legacy notes that don't have one yet
        safe_name = "".join(c if c.isalnum() or c in " -_" else "" for c in activity.title)
        safe_name = safe_name.replace(" ", "_").lower()[:60]
        if not safe_name:
            safe_name = "note"

        note_path = NOTES_DIR / f"{safe_name}.md"
        counter = 1
        while note_path.exists():
            note_path = NOTES_DIR / f"{safe_name}_{counter}.md"
            counter += 1

        icon = self._get_activity_icon(activity.activity_type)
        note_path.write_text(f"# {icon} {activity.title}\n\n", encoding="utf-8")

        # Update activity to point to the file
        self._storage.update_activity(activity.id, link_type="file", link_target=str(note_path))

        # Open in editor
        if self.open_file_callback:
            self.open_file_callback(str(note_path))

    def _on_clear_all(self, button):
        """Clear all activities after confirmation."""
        from popups.confirm_dialog import show_confirm

        if self._type_filter is None and not self._search_query:
            msg = "Are you sure you want to clear all activities?"
        else:
            msg = "Are you sure you want to clear the currently visible activities?"

        parent = self.get_root()
        show_confirm(
            parent,
            title="Clear Dev Pad",
            message=msg,
            danger=True,
            on_confirm=lambda: self._storage.clear_all(type_filter=self._type_filter, filter_query=self._search_query),
        )

    def _on_refresh_prs(self, button):
        """Fetch open PRs from workspace repos using gh CLI."""
        if not self.get_workspace_folders_callback:
            return

        workspace_folders = self.get_workspace_folders_callback()
        if not workspace_folders:
            return

        # Update button to show loading
        self.refresh_prs_btn.set_label(f"{Icons.COG} Loading...")

        def fetch_prs_from_folder(folder):
            """Fetch PRs from a single folder."""
            if not os.path.isdir(folder):
                return []
            git_dir = os.path.join(folder, ".git")
            if not os.path.exists(git_dir):
                return []

            try:
                result = subprocess.run(
                    ["gh", "pr", "list", "--state=open", "--json=number,title,author,url,createdAt"],
                    cwd=folder,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0 and result.stdout.strip():
                    pr_list = json.loads(result.stdout)
                    repo_name = os.path.basename(folder)
                    results = []
                    for pr in pr_list:
                        author = pr.get("author", {}).get("login", "unknown")
                        title = pr.get("title", "")
                        url = pr.get("url", "")
                        created_at = pr.get("createdAt", "")
                        if author and title and url:
                            results.append((author, title, url, repo_name, created_at))
                    return results
            except Exception:
                pass
            return []

        def fetch_prs():
            from concurrent.futures import ThreadPoolExecutor, as_completed

            prs_found = []
            with ThreadPoolExecutor(max_workers=len(workspace_folders)) as executor:
                futures = {executor.submit(fetch_prs_from_folder, folder): folder for folder in workspace_folders}
                for future in as_completed(futures):
                    prs_found.extend(future.result())

            # Update UI on main thread
            main_thread_call(self._finish_refresh_prs, prs_found)

        threading.Thread(target=fetch_prs, daemon=True).start()

    def _finish_refresh_prs(self, prs_found: list):
        """Called when PR fetch completes."""
        self.refresh_prs_btn.set_label(f"{Icons.GIT_MERGE} Refresh PRs")

        if not prs_found:
            return

        for author, title, url, repo_name, created_at in prs_found:
            log_github_pr_activity(author, title, url, repo_name, created_at)

    def _on_storage_change(self):
        """Called when storage changes."""
        GLib.idle_add(lambda: self._refresh() or False)

    def _on_search_change(self, entry):
        """Called when search query changes."""
        self._search_query = entry.get_text()
        self._refresh()

    def _on_filter_click(self, filter_types: set[str] | None):
        """Handle click on a filter button."""
        self._type_filter = filter_types
        self._update_filter_button_styles()
        self._refresh()

    def _update_filter_button_styles(self):
        """Update filter button styles based on current selection."""
        for key, btn in self._filter_buttons.items():
            if key == "all":
                is_selected = self._type_filter is None
            else:
                is_selected = str(self._type_filter) == key

            if is_selected:
                btn.add_css_class("dev-pad-filter-active")
            else:
                btn.remove_css_class("dev-pad-filter-active")

    def _on_add_note(self, button):
        """Show dialog to add a new note."""
        from popups.input_dialog import show_input

        parent = self.get_root()
        show_input(
            parent,
            title="Add Note",
            message="Enter a title:",
            placeholder="What's on your mind?",
            on_submit=lambda title: self._add_note_with_title("note", title),
        )

    def _add_note_with_title(self, note_type: str, title: str):
        """Add a note with the given type and title, creating an .md file."""
        if not title.strip():
            return

        # Create notes directory if needed
        NOTES_DIR.mkdir(parents=True, exist_ok=True)

        # Create a sanitized filename from the title
        safe_name = "".join(c if c.isalnum() or c in " -_" else "" for c in title.strip())
        safe_name = safe_name.replace(" ", "_").lower()[:60]
        if not safe_name:
            safe_name = "note"

        # Ensure unique filename
        note_path = NOTES_DIR / f"{safe_name}.md"
        counter = 1
        while note_path.exists():
            note_path = NOTES_DIR / f"{safe_name}_{counter}.md"
            counter += 1

        # Create the .md file with the title as header
        icon = self._get_activity_icon(note_type)
        note_path.write_text(f"# {icon} {title.strip()}\n\n", encoding="utf-8")

        self._storage.add_activity(
            activity_type=note_type,
            title=title.strip(),
            description="",
            link_type="file",
            link_target=str(note_path),
        )

    def _on_add_sketch(self, button):
        """Show dialog to add a new sketch."""
        from popups.input_dialog import show_input

        parent = self.get_root()
        show_input(
            parent,
            title="Add Sketch",
            message="Enter a name:",
            placeholder="My diagram",
            on_submit=self._add_sketch_with_name,
        )

    def _add_sketch_with_name(self, name: str):
        """Create a .zen_sketch file and open it in the sketch pad."""
        if not name.strip():
            return

        NOTES_DIR.mkdir(parents=True, exist_ok=True)

        safe_name = "".join(c if c.isalnum() or c in " -_" else "" for c in name.strip())
        safe_name = safe_name.replace(" ", "_").lower()[:60]
        if not safe_name:
            safe_name = "sketch"

        sketch_path = NOTES_DIR / f"{safe_name}.zen_sketch"
        counter = 1
        while sketch_path.exists():
            sketch_path = NOTES_DIR / f"{safe_name}_{counter}.zen_sketch"
            counter += 1

        empty_content = '{"version":3,"format":"sketch_pad","shapes":[]}'
        sketch_path.write_text(empty_content, encoding="utf-8")

        log_sketch_activity(content=empty_content, file_path=str(sketch_path))

        if self.open_file_callback:
            self.open_file_callback(str(sketch_path))

    def _on_theme_change(self, theme):
        """Handle theme change."""
        GLib.idle_add(lambda: self._apply_styles() or False)
        GLib.idle_add(lambda: self._refresh() or False)

    def show_panel(self):
        """Show the Dev Pad panel."""
        self.set_visible(True)
        self._refresh()

    def hide_panel(self):
        """Hide the Dev Pad panel."""
        self.set_visible(False)

    def destroy(self):
        """Clean up resources."""
        self._storage.remove_listener(self._on_storage_change)


# Helper functions for logging activities from other parts of the app


def log_file_activity(file_path: str, action: str = "open"):
    """Log a file-related activity."""
    storage = get_dev_pad_storage()
    filename = os.path.basename(file_path) if file_path else "Unknown"
    activity_type = f"file_{action}"
    title = f"{filename}"
    description = f"{action.capitalize()} {_abbreviate_path(file_path)}"

    storage.update_or_add_activity(
        activity_type=activity_type,
        title=title,
        description=description,
        link_type="file",
        link_target=file_path,
    )


def log_new_file_activity(tab_id: int) -> str:
    """Log a new/limbo file activity. Returns the activity ID."""
    storage = get_dev_pad_storage()
    activity = storage.add_activity(
        activity_type="file_new",
        title="Untitled (unsaved)",
        description="New file - not yet saved to disk",
        link_type="tab",
        link_target=str(tab_id),
    )
    return activity.id


def remove_new_file_activity(activity_id: str):
    """Remove a new/limbo file activity."""
    storage = get_dev_pad_storage()
    storage.delete_activity(activity_id)


def log_ai_activity(question: str, chat_id: Optional[str] = None):
    """Log an AI chat activity."""
    storage = get_dev_pad_storage()
    short_question = question[:60] + "..." if len(question) > 60 else question

    storage.add_activity(
        activity_type="ai_chat",
        title=f"AI: {short_question}",
        description=question,
        link_type="ai_chat" if chat_id else None,
        link_target=chat_id,
    )


def log_git_activity(action: str, branch: str = "", repo_path: str = ""):
    """Log a git-related activity."""
    storage = get_dev_pad_storage()
    title = f"{action}"
    if branch:
        title += f" ({branch})"

    storage.add_activity(
        activity_type=f"git_{action.lower().replace(' ', '_')}",
        title=title,
        description=f"{action} on branch {branch}" if branch else action,
        link_type="repo" if repo_path else None,
        link_target=repo_path,
    )


def log_search_activity(query: str, results_count: int = 0):
    """Log a search activity."""
    storage = get_dev_pad_storage()
    storage.add_activity(
        activity_type="search",
        title=f'Search: "{query}"',
        description=f"Found {results_count} results" if results_count else f'Searched for "{query}"',
    )


def log_custom_activity(
    activity_type: str,
    title: str,
    description: str = "",
    link_type: Optional[str] = None,
    link_target: Optional[str] = None,
):
    """Log a custom activity."""
    storage = get_dev_pad_storage()
    storage.add_activity(
        activity_type=activity_type,
        title=title,
        description=description or title,
        link_type=link_type,
        link_target=link_target,
    )


def log_github_pr_activity(
    author: str,
    title: str,
    pr_url: str,
    repo_name: str = "",
    created_at: str = "",
):
    """Log a GitHub PR activity."""
    storage = get_dev_pad_storage()

    date_str = ""
    if created_at:
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            date_str = dt.strftime("%b %d, %Y")
        except (ValueError, AttributeError):
            pass

    display_title = f"{author}: {title}"
    date_part = f" ({date_str})" if date_str else ""
    description = f"PR in {repo_name}{date_part}" if repo_name else f"PR by {author}{date_part}"

    storage.update_or_add_activity(
        activity_type="github_pr",
        title=display_title,
        description=description,
        link_type="url",
        link_target=pr_url,
    )


def log_sketch_activity(content: str = "", file_path: str = ""):
    """Log a sketch pad activity. If file_path is given, link to the .zen_sketch file."""
    storage = get_dev_pad_storage()
    from sketch_pad.sketch_model import Board

    # Generate preview from content
    title = "Sketch Pad"
    description = "ASCII diagram"
    if content:
        try:
            board = Board.from_json(content)
            shape_count = len(board.shapes)
            description = f"ASCII diagram ({shape_count} shape{'s' if shape_count != 1 else ''})"
        except Exception:
            pass

    if file_path:
        title = os.path.basename(file_path)
        storage.update_or_add_activity(
            activity_type="sketch",
            title=title,
            description=description,
            link_type="file",
            link_target=file_path,
            metadata={"content": content} if content else {},
        )
    else:
        storage.update_or_add_activity(
            activity_type="sketch",
            title=title,
            description=description,
            link_type="sketch",
            link_target="sketch_pad",
            metadata={"content": content} if content else {},
        )
