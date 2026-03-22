"""
Markdown Preview for Zen IDE.
Renders markdown content using cmarkgfm (GitHub Flavored Markdown).
Uses WebKit for rich HTML rendering when available, with GtkTextView fallback.

Rendering backends (in priority order):
  1. WebKitGTK (Linux) - full HTML/CSS via GObject introspection
  2. macOS native WKWebView (via PyObjC) - full HTML/CSS overlaid on GTK4
  3. GtkTextView (fallback) - text-only with formatting tags
"""

import hashlib
import platform
from html.parser import HTMLParser
from pathlib import Path

import cmarkgfm
from gi.repository import GLib, Gtk, Pango

from editor.preview.preview_scroll_mixin import SCROLL_SYNC_JS, PreviewScrollMixin
from gi_requirements import load_webkit
from themes import get_theme, subscribe_theme_change
from themes.theme_manager import get_setting

# --- Backend detection ---

# 1. WebKitGTK (Linux)
WebKit = load_webkit()
_HAS_WEBKIT = WebKit is not None

# 2. macOS native WKWebView (via PyObjC)
_HAS_MACOS_WEBKIT = False
if not _HAS_WEBKIT and platform.system() == "Darwin":
    try:
        from editor.preview.macos_webkit_helpers import (
            _HAS_MACOS_WEBKIT as _mac_available,
        )
        from editor.preview.macos_webkit_helpers import (
            _NSURL,
            _NSApp,
            _NSMakeRect,
            _ScrollHandler,
            _WKWebView,
            _WKWebViewConfig,
        )

        _HAS_MACOS_WEBKIT = _mac_available
    except ImportError:
        pass


def _build_github_css(theme, font_family=None, font_size=None):
    """Build a GitHub-like dark CSS stylesheet using the IDE theme colors."""
    from fonts import get_font_settings

    if not font_family:
        md_settings = get_font_settings("markdown_preview")
        font_family = md_settings["family"]
    if not font_size:
        md_settings = get_font_settings("markdown_preview")
        font_size = md_settings.get("size", 14)

    editor_settings = get_font_settings("editor")
    code_font = editor_settings["family"]
    code_size = editor_settings.get("size", 16)
    code_stack = f'"{code_font}", monospace'
    body_stack = f'"{font_family}", sans-serif'
    return f"""
    :root {{
        color-scheme: dark;
    }}
    html {{
        height: 100%;
        overflow-y: auto;
    }}
    body {{
        font-family: {body_stack};
        font-size: {font_size}px;
        line-height: 1.8;
        color: {theme.fg_color};
        background-color: {theme.main_bg};
        padding: 0 0 0 24px;
        margin: 0;
        word-wrap: break-word;
        min-height: 100%;
    }}
    /* Scrollbar styling to match editor GTK scrollbar (slider 6px centered in 12px track) */
    ::-webkit-scrollbar {{
        width: 20px;
        background: transparent;
    }}
    ::-webkit-scrollbar-track {{
        background: transparent;
    }}
    ::-webkit-scrollbar-thumb {{
        background-color: {theme.fg_color}40;
        border-radius: 0;
        border: 3px solid transparent;
        background-clip: padding-box;
    }}
    ::-webkit-scrollbar-thumb:hover {{
        background-color: {theme.fg_color}66;
        border: 3px solid transparent;
        background-clip: padding-box;
    }}
    h1, h2, h3, h4, h5, h6 {{
        margin-top: 24px;
        margin-bottom: 16px;
        font-weight: 600;
        line-height: 1.25;
        color: {theme.fg_color};
    }}
    h1 {{ font-size: 2em; padding-bottom: 0.3em; border-bottom: 1px solid {theme.border_color}; }}
    h2 {{ font-size: 1.5em; padding-bottom: 0.3em; border-bottom: 1px solid {theme.border_color}; }}
    h3 {{ font-size: 1.25em; }}
    h4 {{ font-size: 1em; }}
    h5 {{ font-size: 0.875em; }}
    h6 {{ font-size: 0.85em; color: {theme.fg_dim}; }}
    p {{ margin-top: 0; margin-bottom: 16px; }}
    a {{ color: {theme.accent_color}; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    strong {{ font-weight: 600; }}
    code {{
        font-family: {code_stack};
        font-size: {code_size}px;
        font-variant-ligatures: none;
        font-feature-settings: "liga" 0, "calt" 0;
        padding: 0.2em 0.4em;
        margin: 0;
        background-color: {theme.panel_bg};
        border-radius: 6px;
    }}
    pre {{
        font-family: {code_stack};
        font-variant-ligatures: none;
        font-feature-settings: "liga" 0, "calt" 0;
        padding: 16px;
        overflow: auto;
        font-size: {code_size}px;
        line-height: 1.45;
        background-color: {theme.panel_bg};
        border: 1px solid {theme.border_color};
        border-radius: 6px;
        margin-bottom: 16px;
    }}
    pre code {{
        padding: 0;
        background-color: transparent;
        border-radius: 0;
        font-size: 100%;
    }}
    blockquote {{
        padding: 0 1em;
        color: {theme.fg_dim};
        border-left: 0.25em solid {theme.accent_color};
        margin: 0 0 16px 0;
    }}
    blockquote > :first-child {{ margin-top: 0; }}
    blockquote > :last-child {{ margin-bottom: 0; }}
    ul, ol {{
        padding-left: 2em;
        margin-top: 0;
        margin-bottom: 16px;
    }}
    li {{ margin-top: 0.25em; }}
    li + li {{ margin-top: 0.25em; }}
    table {{
        border-spacing: 0;
        border-collapse: collapse;
        border: none;
        margin-bottom: 16px;
        width: auto;
    }}
    table th, table td {{
        padding: 6px 13px;
        border: 1px solid {theme.border_color};
    }}
    /* Remove outer frame — keep only inner grid lines */
    table tr:first-child th,
    table tr:first-child td {{ border-top: none; }}
    table tr:last-child th,
    table tr:last-child td {{ border-bottom: none; }}
    table th:first-child,
    table td:first-child {{ border-left: none; }}
    table th:last-child,
    table td:last-child {{ border-right: none; }}
    table th {{
        font-weight: 600;
        background-color: {theme.panel_bg};
    }}
    table tr {{
        background-color: {theme.main_bg};
    }}
    table tr:nth-child(2n) {{
        background-color: {theme.fg_color}08;
    }}
    hr {{
        height: 0.25em;
        padding: 0;
        margin: 24px 0;
        background-color: {theme.border_color};
        border: 0;
    }}
    img {{ max-width: 100%; box-sizing: border-box; }}
    del {{ color: {theme.fg_dim}; }}
    input[type="checkbox"] {{
        margin: 0 0.2em 0.25em -1.4em;
        vertical-align: middle;
    }}
    /* Task list items */
    .task-list-item {{ list-style-type: none; }}
    .task-list-item + .task-list-item {{ margin-top: 3px; }}
    """


class _MacOSWebKitHelper:
    """Manages a native macOS WKWebView overlaid on a GTK4 widget area.

    Creates a WKWebView (via PyObjC) and adds it as a subview of the
    NSWindow's content view. Position is synced with a GTK placeholder
    widget using compute_bounds().
    """

    def __init__(self, on_scroll_fraction=None):
        self._on_scroll_fraction = on_scroll_fraction
        config = _WKWebViewConfig.alloc().init()
        # Allow loading local file:// resources (images) from HTML with file:// base URL
        prefs = config.preferences()
        prefs.setValue_forKey_(True, "allowFileAccessFromFileURLs")

        # Register JS → Python message handler for reverse scroll sync
        if on_scroll_fraction:
            self._scroll_handler = _ScrollHandler.alloc().init()
            self._scroll_handler.callback = on_scroll_fraction
            uc = config.userContentController()
            uc.addScriptMessageHandler_name_(self._scroll_handler, "zenScrollSync")

        self._webview = _WKWebView.alloc().initWithFrame_configuration_(_NSMakeRect(0, 0, 1, 1), config)
        if self._webview is None:
            self._ns_window = None
            self._attached = False
            return
        # Transparent background; CSS in the HTML handles the actual bg color
        self._webview.setValue_forKey_(False, "drawsBackground")
        self._webview.setHidden_(True)
        self._ns_window = None
        self._attached = False

    def attach(self, gtk_widget):
        """Attach WKWebView as subview of the app's NSWindow content view."""
        if self._webview is None:
            return False
        self._ns_window = _NSApp.mainWindow()
        if not self._ns_window and _NSApp.windows():
            self._ns_window = _NSApp.windows()[0]
        if not self._ns_window:
            return False

        content_view = self._ns_window.contentView()
        content_view.addSubview_(self._webview)
        self._webview.setHidden_(False)
        self._attached = True
        return True

    def update_frame(self, x, y, width, height):
        """Update WKWebView position. Coords are GTK-style (top-left origin)."""
        if not self._attached or not self._ns_window:
            return
        cv = self._ns_window.contentView()
        cv_height = cv.frame().size.height
        # NSView uses bottom-left origin unless flipped
        ns_y = y if cv.isFlipped() else cv_height - y - height
        self._webview.setFrame_(_NSMakeRect(x, ns_y, width, height))

    def load_html(self, html, base_uri=None):
        """Load HTML string into the WKWebView.

        When a file:// base_uri is given, writes HTML to a temp file and uses
        loadFileURL:allowingReadAccessToURL: so that relative <img> sources
        resolve correctly.  loadHTMLString:baseURL: does NOT grant file://
        access even with a file:// base URL – this is a known WKWebView
        security restriction.
        """
        if base_uri and base_uri.startswith("file://"):
            import tempfile

            # Clean up previous temp file
            old = getattr(self, "_tmp_html_path", None)
            if old:
                try:
                    Path(old).unlink(missing_ok=True)
                except OSError:
                    pass
            fd, tmp_path = tempfile.mkstemp(suffix=".html", prefix=".zen_preview_")
            import os

            os.write(fd, html.encode("utf-8"))
            os.close(fd)
            self._tmp_html_path = tmp_path
            file_url = _NSURL.fileURLWithPath_(tmp_path)
            # Grant read access to root so WKWebView can read both the temp
            # file and images in the project directory.
            root_url = _NSURL.fileURLWithPath_("/")
            self._webview.loadFileURL_allowingReadAccessToURL_(file_url, root_url)
        else:
            if base_uri:
                ns_url = _NSURL.URLWithString_(base_uri)
            else:
                ns_url = _NSURL.URLWithString_("about:blank")
            self._webview.loadHTMLString_baseURL_(html, ns_url)

    def scroll_by(self, dx, dy):
        """Scroll the WKWebView content by the given pixel offsets."""
        js = f"window.scrollBy({dx},{dy});"
        self._webview.evaluateJavaScript_completionHandler_(js, None)

    def set_hidden(self, hidden):
        """Show or hide the WKWebView."""
        if self._webview:
            self._webview.setHidden_(hidden)

    def destroy(self):
        """Remove the WKWebView from its superview and release."""
        # Clean up temp preview file
        tmp = getattr(self, "_tmp_html_path", None)
        if tmp:
            try:
                Path(tmp).unlink(missing_ok=True)
            except OSError:
                pass
        if self._webview:
            self._webview.removeFromSuperview()
            self._webview = None
        self._attached = False


class _HtmlToTextView(HTMLParser):
    """Parse cmarkgfm HTML output and insert formatted text into a GtkTextBuffer."""

    _BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote", "li", "tr", "table", "hr"}

    def __init__(self, buf):
        super().__init__()
        self._buf = buf
        self._tag_stack = []
        self._in_pre = False
        self._in_code = False
        self._list_stack = []
        self._table_rows = []
        self._current_row = []
        self._in_table = False
        self._in_th = False
        self._cell_text = ""

    def _insert(self, text, *tag_names):
        end = self._buf.get_end_iter()
        if tag_names:
            valid = [t for t in tag_names if self._buf.get_tag_table().lookup(t)]
            if valid:
                self._buf.insert_with_tags_by_name(end, text, *valid)
                return
        self._buf.insert(end, text)

    def _active_tags(self):
        mapping = {
            "strong": "bold",
            "b": "bold",
            "em": "italic",
            "i": "italic",
            "del": "strikethrough",
            "s": "strikethrough",
            "code": "code",
        }
        tags = []
        for t in self._tag_stack:
            if t in mapping and mapping[t] not in tags:
                tags.append(mapping[t])
        if self._in_pre and "code" in tags:
            tags.remove("code")
            tags.append("code_block")
        elif self._in_pre:
            tags.append("code_block")
        return tags

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._tag_stack.append(tag)
        elif tag in ("strong", "b", "em", "i", "del", "s", "code"):
            self._tag_stack.append(tag)
        elif tag == "pre":
            self._in_pre = True
        elif tag == "a":
            self._tag_stack.append("a")
        elif tag == "blockquote":
            self._tag_stack.append("blockquote")
            self._insert("  ▎ ", "quote_bar")
        elif tag == "ul":
            self._list_stack.append(("ul", 0))
        elif tag == "ol":
            start = int(attrs_dict.get("start", "1"))
            self._list_stack.append(("ol", start - 1))
        elif tag == "li":
            indent = "  " * max(0, len(self._list_stack) - 1)
            if self._list_stack:
                kind, count = self._list_stack[-1]
                if kind == "ul":
                    self._insert(f"{indent}  ▪ ", "list_item")
                else:
                    count += 1
                    self._list_stack[-1] = (kind, count)
                    self._insert(f"{indent}  {count}. ", "list_item")
            self._tag_stack.append("li")
        elif tag == "hr":
            self._insert("─" * 40 + "\n", "hr")
        elif tag == "br":
            self._insert("\n")
        elif tag == "table":
            self._in_table = True
            self._table_rows = []
        elif tag == "tr":
            self._current_row = []
        elif tag in ("th", "td"):
            self._in_th = tag == "th"
            self._cell_text = ""
        elif tag == "input":
            checked = "checked" in attrs_dict
            self._insert("☑ " if checked else "☐ ")
        elif tag == "p":
            self._tag_stack.append("p")

    def handle_endtag(self, tag):
        if tag in ("th", "td"):
            self._current_row.append((self._cell_text.strip(), self._in_th))
            self._cell_text = ""
            return
        if tag == "tr":
            if self._current_row:
                self._table_rows.append(self._current_row)
            self._current_row = []
            return
        if tag == "table":
            self._render_table()
            self._in_table = False
            self._table_rows = []
            return
        if tag in ("thead", "tbody"):
            return
        if tag == "pre":
            self._in_pre = False
            self._insert("\n")
            return
        if tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
            self._insert("\n")
            return
        if tag in (
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "strong",
            "b",
            "em",
            "i",
            "del",
            "s",
            "code",
            "a",
            "blockquote",
            "li",
            "p",
        ):
            for idx in range(len(self._tag_stack) - 1, -1, -1):
                if self._tag_stack[idx] == tag:
                    self._tag_stack.pop(idx)
                    break
        if tag in self._BLOCK_TAGS:
            self._insert("\n")
        if tag in ("h1", "h2"):
            self._insert("─" * 50 + "\n", "heading_rule")

    def handle_data(self, data):
        if self._in_table:
            self._cell_text += data
            return
        if self._in_pre:
            self._insert(data, *self._active_tags())
            return
        tags = self._active_tags()
        for t in self._tag_stack:
            if t in ("h1", "h2", "h3", "h4", "h5", "h6") and t not in tags:
                tags.append(t)
        if "a" in self._tag_stack and "link" not in tags:
            tags.append("link")
        if "blockquote" in self._tag_stack and "quote" not in tags:
            tags.append("quote")
        if "li" in self._tag_stack and "list_item" not in tags:
            tags.append("list_item")
        self._insert(data, *tags)

    def handle_entityref(self, name):
        from html import unescape

        self.handle_data(unescape(f"&{name};"))

    def handle_charref(self, name):
        from html import unescape

        self.handle_data(unescape(f"&#{name};"))

    def _render_table(self):
        if not self._table_rows:
            return
        num_cols = max(len(row) for row in self._table_rows)
        col_widths = [0] * num_cols
        for row in self._table_rows:
            for i, (cell, _) in enumerate(row):
                col_widths[i] = max(col_widths[i], len(cell))
        col_widths = [max(w, 1) for w in col_widths]
        has_header = self._table_rows and any(is_th for _, is_th in self._table_rows[0])

        # Top border: ┌──────┬──────┐
        top = "┌" + "┬".join("─" * (w + 2) for w in col_widths) + "┐"
        self._insert(top + "\n", "table_cell")

        for row_idx, row in enumerate(self._table_rows):
            parts = []
            for i in range(num_cols):
                cell_text = row[i][0] if i < len(row) else ""
                parts.append(f" {cell_text.ljust(col_widths[i])} ")
            line = "│" + "│".join(parts) + "│"
            tag = "table_header" if (row_idx == 0 and has_header) else "table_cell"
            self._insert(line + "\n", tag)
            if row_idx == 0 and has_header:
                sep = "├" + "┼".join("─" * (w + 2) for w in col_widths) + "┤"
                self._insert(sep + "\n", "table_cell")

        # Bottom border: └──────┴──────┘
        bottom = "└" + "┴".join("─" * (w + 2) for w in col_widths) + "┘"
        self._insert(bottom + "\n", "table_cell")


class _SyncPlaceholder(Gtk.Widget):
    """Lightweight widget that calls a sync function on every snapshot.

    Replaces Gtk.DrawingArea+set_draw_func for macOS WKWebView overlay
    positioning — no Cairo dependency needed.
    """

    def __init__(self, sync_func):
        super().__init__()
        self._sync_func = sync_func

    def do_snapshot(self, snapshot):
        w = self.get_width()
        h = self.get_height()
        if self._sync_func:
            self._sync_func(self, w, h)


class MarkdownPreview(PreviewScrollMixin, Gtk.Box):
    """Markdown preview using cmarkgfm. Rendering backends:
    1. WebKitGTK (Linux) - full HTML/CSS
    2. macOS native WKWebView (PyObjC) - full HTML/CSS overlaid on GTK4
    3. GtkTextView (fallback) - text-only with formatting tags
    """

    _ZOOM_STEP = 0.1
    _ZOOM_MIN = 0.3
    _ZOOM_MAX = 3.0

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._init_scroll_sync()
        self._zoom_level = 1.0
        self._last_markdown = None
        self._css_provider = None
        self._on_preview_scroll_line_callback = None

        # Canvas backend is the default — native GTK scroll physics
        # (DrawingArea in ScrolledWindow, same architecture as ChatCanvas).
        # Override via preview.backend setting to use "webkit_gtk" or "macos_webkit".
        backend_override = get_setting("preview.backend", "")
        if backend_override == "webkit_gtk" and _HAS_WEBKIT:
            self._backend = "webkit_gtk"
        elif backend_override == "macos_webkit" and _HAS_MACOS_WEBKIT:
            self._backend = "macos_webkit"
        else:
            self._backend = "canvas"
        self._create_ui()
        subscribe_theme_change(self._on_theme_change)
        from fonts import subscribe_font_change

        subscribe_font_change(self._on_font_change)

    def _create_ui(self):
        """Create the markdown preview UI."""
        if self._backend == "canvas":
            self._create_canvas_ui()
        elif self._backend == "webkit_gtk":
            self._create_webkit_gtk_ui()
        elif self._backend == "macos_webkit":
            self._create_macos_webkit_ui()
        else:
            self._create_textview_ui()

    # -- Native Canvas --

    def _create_canvas_ui(self):
        """Create native MarkdownCanvas preview — pixel-perfect scroll sync."""
        from editor.preview.markdown_canvas import MarkdownCanvas

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        self.append(scrolled)

        canvas = MarkdownCanvas()
        scrolled.set_child(canvas)
        canvas.attach_to_scrolled_window(scrolled)

        # Shared scroll sync wiring (kinetic scrolling + value-changed signal)
        self._connect_canvas_scroll_sync(scrolled, canvas)

        # Apply theme
        theme = get_theme()
        self._apply_canvas_theme(theme)

        # Apply font
        from fonts import get_font_settings

        md_settings = get_font_settings("markdown_preview")
        font_family = md_settings["family"]
        font_size = md_settings.get("size", 14)
        self._canvas.set_font(font_family, font_size)

    def _apply_canvas_theme(self, theme):
        """Apply theme to MarkdownCanvas."""
        self._canvas.set_theme(
            fg=theme.fg_color,
            bg=theme.main_bg,
            code_bg=theme.panel_bg,
            accent=theme.accent_color,
            dim=theme.fg_dim,
            border=theme.border_color,
            selection_bg=theme.selection_bg,
        )

    # -- WebKitGTK (Linux) --

    def _create_webkit_gtk_ui(self):
        """Create WebKit-based preview for rich HTML rendering."""
        # Use a UserContentManager to receive JS scroll messages
        ucm = WebKit.UserContentManager()
        ucm.connect("script-message-received::zenScrollSync", self._on_webkit_script_message)
        ucm.register_script_message_handler("zenScrollSync")
        self.webview = WebKit.WebView.new_with_user_content_manager(ucm)
        self.webview.set_vexpand(True)
        self.webview.set_hexpand(True)

        settings = self.webview.get_settings()
        if hasattr(settings, "set_enable_developer_extras"):
            settings.set_enable_developer_extras(False)
        if hasattr(settings, "set_enable_javascript"):
            settings.set_enable_javascript(True)
        if hasattr(settings, "set_allow_file_access_from_file_urls"):
            settings.set_allow_file_access_from_file_urls(True)

        theme = get_theme()
        self._css_provider = Gtk.CssProvider()
        self._css_provider.load_from_data(f"webview {{ background-color: {theme.main_bg}; }}".encode())
        self.webview.get_style_context().add_provider(self._css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.append(self.webview)
        self._connect_webkit_scroll_sync(self.webview)

    # -- macOS native WKWebView (PyObjC) --

    def _create_macos_webkit_ui(self):
        """Create a placeholder widget; a native WKWebView overlays it once mapped."""
        self._placeholder = _SyncPlaceholder(self._on_placeholder_sync)
        self._placeholder.set_vexpand(True)
        self._placeholder.set_hexpand(True)
        self._placeholder.set_can_target(True)
        self._placeholder.set_focusable(True)
        self.append(self._placeholder)

        # Forward trackpad scroll events to the native WKWebView via JS
        scroll_ctrl = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.BOTH_AXES | Gtk.EventControllerScrollFlags.KINETIC
        )
        scroll_ctrl.connect("scroll", self._on_macos_scroll)
        self._placeholder.add_controller(scroll_ctrl)

        self._macos_helper = _MacOSWebKitHelper(on_scroll_fraction=self._on_preview_scrolled)
        self._macos_attached = False
        self._pending_html = None

        self._placeholder.connect("realize", self._on_macos_realize)
        self._placeholder.connect("unrealize", self._on_macos_unrealize)
        self._placeholder.connect("map", lambda _w: self._macos_set_visible(True))
        self._placeholder.connect("unmap", lambda _w: self._macos_set_visible(False))

    def _on_macos_realize(self, _widget):
        """Delay attachment until the NSWindow is ready."""
        self._macos_attach_attempts = 0
        GLib.timeout_add(200, self._try_attach_macos)

    def _try_attach_macos(self):
        _MAX_ATTEMPTS = 10
        if self._macos_attached:
            return False
        self._macos_attach_attempts += 1
        if self._macos_helper.attach(self._placeholder):
            self._macos_attached = True
            if self._pending_html:
                self._macos_helper.load_html(self._pending_html, getattr(self, "_pending_base_uri", None))
                self._pending_html = None
                self._pending_base_uri = None
            self._placeholder.queue_draw()
        elif self._macos_attach_attempts >= _MAX_ATTEMPTS:
            pass
        else:
            delay = min(200 * (2 ** (self._macos_attach_attempts - 1)), 2000)
            GLib.timeout_add(delay, self._try_attach_macos)
        return False

    def _on_placeholder_sync(self, area, width, height):
        """Sync WKWebView frame with the GTK placeholder on every snapshot."""
        if not self._macos_attached:
            return
        root = area.get_root()
        if not root:
            return
        success, bounds = area.compute_bounds(root)
        if success:
            self._macos_helper.update_frame(bounds.get_x(), bounds.get_y(), width, height)

    def _on_macos_scroll(self, _ctrl, dx, dy):
        """Forward GTK scroll events to the native WKWebView."""
        if self._macos_attached:
            speed = get_setting("scroll_speed", 0.4)
            px_per_unit = 50 * speed
            self._macos_helper.scroll_by(dx * px_per_unit, dy * px_per_unit)
        return True

    def _macos_set_visible(self, visible):
        if hasattr(self, "_macos_helper"):
            self._macos_helper.set_hidden(not visible)

    def _on_macos_unrealize(self, _widget):
        self._macos_helper.destroy()
        self._macos_attached = False

    # -- GtkTextView fallback --

    def _create_textview_ui(self):
        """Create GtkTextView-based preview as fallback."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        self.append(scrolled)
        self._textview_scrolled = scrolled

        self.text_view = Gtk.TextView()
        self.text_view.set_editable(False)
        self.text_view.set_focusable(False)
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.text_view.set_margin_start(24)
        self.text_view.set_margin_end(0)
        self.text_view.set_margin_top(0)
        self.text_view.set_margin_bottom(0)
        self.text_view.set_pixels_above_lines(2)
        self.text_view.set_pixels_below_lines(2)

        self.buffer = self.text_view.get_buffer()
        scrolled.set_child(self.text_view)

        # Reverse scroll sync for textview fallback
        self._connect_textview_scroll_sync(scrolled)

        self._setup_tags()
        self._apply_styles()

    def _setup_tags(self):
        """Setup text tags for markdown formatting."""
        theme = get_theme()
        from fonts import get_font_settings

        editor_settings = get_font_settings("editor")
        editor_font = editor_settings["family"]
        md_settings = get_font_settings("markdown_preview")
        md_font = md_settings["family"]
        self.buffer.create_tag("h1", weight=Pango.Weight.BOLD, scale=2.2, pixels_above_lines=16, pixels_below_lines=4)
        self.buffer.create_tag("h2", weight=Pango.Weight.BOLD, scale=1.6, pixels_above_lines=16, pixels_below_lines=4)
        self.buffer.create_tag("h3", weight=Pango.Weight.BOLD, scale=1.3, pixels_above_lines=12, pixels_below_lines=4)
        self.buffer.create_tag("h4", weight=Pango.Weight.BOLD, scale=1.1, pixels_above_lines=8, pixels_below_lines=2)
        self.buffer.create_tag("h5", weight=Pango.Weight.BOLD, scale=1.0, pixels_above_lines=8, pixels_below_lines=2)
        self.buffer.create_tag("h6", weight=Pango.Weight.BOLD, scale=0.9, pixels_above_lines=8, pixels_below_lines=2)
        self.buffer.create_tag("bold", weight=Pango.Weight.BOLD)
        self.buffer.create_tag("italic", style=Pango.Style.ITALIC)
        self.buffer.create_tag("strikethrough", strikethrough=True)
        self.buffer.create_tag("code", family=editor_font, background=theme.panel_bg)
        self.buffer.create_tag("link", foreground=theme.accent_color, underline=Pango.Underline.SINGLE)
        self.buffer.create_tag(
            "quote",
            left_margin=32,
            foreground=theme.fg_dim,
            style=Pango.Style.ITALIC,
            pixels_above_lines=4,
            pixels_below_lines=4,
        )
        self.buffer.create_tag("quote_bar", foreground=theme.accent_color)
        self.buffer.create_tag("list_item", left_margin=24, pixels_above_lines=1, pixels_below_lines=1)
        self.buffer.create_tag(
            "code_block",
            family=editor_font,
            background=theme.panel_bg,
            paragraph_background=theme.panel_bg,
            pixels_above_lines=6,
            pixels_below_lines=6,
            left_margin=16,
            right_margin=16,
            pixels_inside_wrap=2,
        )
        self.buffer.create_tag("hr", foreground=theme.fg_dim)
        self.buffer.create_tag("heading_rule", foreground=theme.fg_dim, pixels_below_lines=8)
        self.buffer.create_tag(
            "table_header",
            family=md_font,
            weight=Pango.Weight.BOLD,
            pixels_above_lines=0,
            pixels_below_lines=0,
        )
        self.buffer.create_tag(
            "table_cell",
            family=md_font,
            pixels_above_lines=0,
            pixels_below_lines=0,
        )

    def _apply_styles(self):
        """Apply custom styles."""
        theme = get_theme()
        self._css_provider = Gtk.CssProvider()
        css = f"""
            textview text {{
                background-color: {theme.main_bg};
                color: {theme.fg_color};
            }}
        """
        self._css_provider.load_from_data(css.encode())
        self.text_view.get_style_context().add_provider(self._css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    # -- Public API --

    def zoom_in(self):
        """Increase zoom level."""
        self._zoom_level = min(self._zoom_level + self._ZOOM_STEP, self._ZOOM_MAX)
        self._apply_zoom()

    def zoom_out(self):
        """Decrease zoom level."""
        self._zoom_level = max(self._zoom_level - self._ZOOM_STEP, self._ZOOM_MIN)
        self._apply_zoom()

    def zoom_reset(self):
        """Reset zoom to 100%."""
        self._zoom_level = 1.0
        self._apply_zoom()

    def _apply_zoom(self):
        """Apply current zoom level to the preview backend."""
        if self._backend == "canvas" and hasattr(self, "_canvas"):
            self._canvas._zoom_level = self._zoom_level
            self._canvas._needs_layout = True
            self._canvas._schedule_redraw()
        elif self._backend == "webkit_gtk" and hasattr(self, "webview"):
            self.webview.set_zoom_level(self._zoom_level)
        elif self._backend == "macos_webkit" and hasattr(self, "_macos_helper"):
            js = f"document.body.style.zoom = '{self._zoom_level}';"
            self._macos_helper._webview.evaluateJavaScript_completionHandler_(js, None)
        elif self._backend == "textview" and hasattr(self, "text_view"):
            # Scale font size for textview fallback
            base_size = 14
            scaled = int(base_size * self._zoom_level * Pango.SCALE)
            font_desc = Pango.FontDescription()
            font_desc.set_size(scaled)
            self.text_view.override_font(font_desc)

    # -- Scroll sync --

    def set_on_preview_scroll_line(self, callback):
        """Register a callback for line-level scroll sync (canvas backend only).

        The callback receives the source line number of the topmost visible block.
        """
        self._on_preview_scroll_line_callback = callback

    def render(self, markdown_text: str, file_path: str = None):
        """Render markdown text to the preview."""
        self._last_markdown = markdown_text
        self._last_file_path = file_path

        # Skip re-render if content is identical
        content_hash = hashlib.md5(markdown_text.encode("utf-8")).hexdigest()
        if getattr(self, "_last_content_hash", None) == content_hash:
            return
        self._last_content_hash = content_hash

        if self._backend == "canvas":
            from editor.preview.markdown_block_renderer import MarkdownBlockRenderer

            if file_path:
                from pathlib import Path

                self._canvas.set_base_path(str(Path(file_path).parent))
            renderer = MarkdownBlockRenderer()
            blocks = renderer.render(markdown_text)
            self._canvas.set_blocks(blocks)
            if self._target_fraction > 0.001:
                GLib.idle_add(self._apply_scroll_fraction)
            return

        try:
            html = cmarkgfm.github_flavored_markdown_to_html(markdown_text)
        except Exception:
            html = "<pre style='color:red;'>Error rendering markdown</pre>"

        # Build base URI from file path so relative images resolve
        base_uri = None
        if file_path:
            base_uri = Path(file_path).parent.as_uri() + "/"

        if self._backend in ("webkit_gtk", "macos_webkit"):
            theme = get_theme()
            css = _build_github_css(theme)
            # Inject <base> tag so relative image/link paths resolve from
            # the markdown file's directory (needed when HTML is loaded
            # from a temp file on macOS).
            base_tag = ""
            if base_uri:
                base_tag = f'<base href="{base_uri}">'
            full_html = f'<!DOCTYPE html>\n<html>\n<head><meta charset="utf-8">{base_tag}<style>{css}</style></head>\n<body>{html}{SCROLL_SYNC_JS}</body>\n</html>'

            if self._backend == "webkit_gtk":
                self.webview.load_html(full_html, base_uri)
            elif self._macos_attached:
                self._macos_helper.load_html(full_html, base_uri)
                if self._target_fraction > 0.001:
                    GLib.timeout_add(300, self._apply_scroll_fraction)
            else:
                self._pending_html = full_html
                self._pending_base_uri = base_uri
        else:
            self.buffer.set_text("")
            parser = _HtmlToTextView(self.buffer)
            parser.feed(html)
            if self._target_fraction > 0.001:
                GLib.idle_add(self._apply_scroll_fraction)

    def _on_theme_change(self, theme):
        """Update preview styles when theme changes."""
        if self._backend == "canvas" and hasattr(self, "_canvas"):
            self._apply_canvas_theme(theme)
            if self._last_markdown is not None:
                self._schedule_debounced_render()
            return
        if self._css_provider:
            if self._backend == "webkit_gtk":
                self._css_provider.load_from_data(f"webview {{ background-color: {theme.main_bg}; }}".encode())
            elif self._backend == "textview" and hasattr(self, "text_view"):
                css = f"""
                    textview text {{
                        background-color: {theme.main_bg};
                        color: {theme.fg_color};
                    }}
                """
                self._css_provider.load_from_data(css.encode())
        if self._last_markdown is not None:
            self._schedule_debounced_render()

    def _on_font_change(self, component, settings):
        """Re-render preview when markdown_preview or editor font changes."""
        if component in ("markdown_preview", "editor"):
            if self._backend == "canvas" and hasattr(self, "_canvas") and component == "markdown_preview":
                font_family = settings["family"]
                font_size = settings.get("size", 14)
                self._canvas.set_font(font_family, font_size)
            if self._last_markdown is not None:
                self._schedule_debounced_render()

    def _schedule_debounced_render(self):
        """Schedule a re-render after a short delay, cancelling any pending one."""
        pending = getattr(self, "_debounce_render_id", None)
        if pending:
            GLib.source_remove(pending)
        self._debounce_render_id = GLib.timeout_add(100, self._do_debounced_render)

    def _do_debounced_render(self):
        self._debounce_render_id = None
        # Clear hash so render() actually re-renders
        self._last_content_hash = None
        file_path = getattr(self, "_last_file_path", None)
        self.render(self._last_markdown, file_path)
        return False

    def update_from_editor(self, content: str, file_path: str = None):
        """Update preview from editor content (for live preview)."""
        self.render(content, file_path)
