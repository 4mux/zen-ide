"""Specialized file openers (image, sketch, binary) for EditorView."""

import os

from gi.repository import Gtk

from constants import AUDIO_EXTENSIONS, IMAGE_EXTENSIONS

from .editor_tab import EditorTab


class EditorViewFileOpenersMixin:
    """Mixin providing image, sketch, and binary file opening for EditorView."""

    def open_image(self, file_path: str, switch_to: bool = True) -> bool:
        """Open an image file in a preview tab."""
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in IMAGE_EXTENSIONS:
            return False

        for tab_id, tab in self.tabs.items():
            if tab.file_path == file_path:
                if switch_to:
                    page_num = self._get_page_num_for_tab_id(tab_id)
                    if page_num >= 0:
                        self.notebook.set_current_page(page_num)
                if self.on_file_opened:
                    self.on_file_opened(file_path)
                return True

        tab_id = self._next_tab_id
        self._next_tab_id += 1

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled._zen_tab_id = tab_id

        picture = Gtk.Picture()
        picture.set_filename(file_path)
        picture.set_can_shrink(True)
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        scrolled.set_child(picture)

        from shared.ui.tab_button import TabButton

        img_tab_btn = TabButton(tab_id, os.path.basename(file_path), on_close=lambda tid: self._do_close_tab_by_id(tid))
        page_num = self.notebook.append_page(scrolled, None)
        self._tab_bar.append(img_tab_btn)
        click = Gtk.GestureClick.new()
        click.connect("pressed", lambda g, n, x, y, tid=tab_id: self._select_tab_by_id(tid))
        img_tab_btn.add_controller(click)

        img_tab = EditorTab(file_path=file_path)
        img_tab._is_image = True
        img_tab._tab_button = img_tab_btn
        img_tab._tab_id = tab_id
        self.tabs[tab_id] = img_tab

        if switch_to:
            self.notebook.set_current_page(page_num)
        if self.on_file_opened:
            self.on_file_opened(file_path)
        from dev_pad import log_file_activity

        log_file_activity(file_path, "open")
        return True

    def _open_sketch_file(self, file_path: str, switch_to: bool = True) -> bool:
        """Open a .zen_sketch file in a SketchPad tab."""
        self._close_welcome_tab()
        norm = os.path.normpath(file_path)

        for tab_id, tab in self.tabs.items():
            if tab.file_path and os.path.normpath(tab.file_path) == norm:
                if switch_to:
                    page_num = self._get_page_num_for_tab_id(tab_id)
                    if page_num >= 0:
                        self.notebook.set_current_page(page_num)
                if self.on_file_opened:
                    self.on_file_opened(file_path)
                return True

        from ..sketch_tab import SketchTab

        sketch_tab = SketchTab(file_path)
        if not os.path.isfile(file_path):
            return False
        if not sketch_tab.load_file(file_path):
            return False

        tab_id = self._next_tab_id
        self._next_tab_id += 1
        sketch_tab.widget._zen_tab_id = tab_id

        from shared.ui.tab_button import FileTabButton

        tab_btn = FileTabButton(tab_id, sketch_tab.get_title(), on_close=lambda tid: self._close_tab_by_id(tid))
        page_num = self.notebook.append_page(sketch_tab.widget, None)
        self._tab_bar.append(tab_btn)
        click = Gtk.GestureClick.new()
        click.connect("pressed", lambda g, n, x, y, tid=tab_id: self._select_tab_by_id(tid))
        tab_btn.add_controller(click)
        sketch_tab._tab_button = tab_btn
        sketch_tab._tab_id = tab_id
        self.tabs[tab_id] = sketch_tab

        if switch_to:
            self.notebook.set_current_page(page_num)
        if self.on_file_opened:
            self.on_file_opened(file_path)

        from dev_pad import log_sketch_activity

        content = sketch_tab.widget.get_content() if hasattr(sketch_tab.widget, "get_content") else ""
        log_sketch_activity(content=content, file_path=file_path)
        return True

    def open_audio(self, file_path: str, switch_to: bool = True) -> bool:
        """Open an audio file in a playback tab."""
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in AUDIO_EXTENSIONS:
            return False

        for tab_id, tab in self.tabs.items():
            if tab.file_path == file_path:
                if switch_to:
                    page_num = self._get_page_num_for_tab_id(tab_id)
                    if page_num >= 0:
                        self.notebook.set_current_page(page_num)
                if self.on_file_opened:
                    self.on_file_opened(file_path)
                return True

        self._close_welcome_tab()
        tab_id = self._next_tab_id
        self._next_tab_id += 1

        from ..preview.audio_player import AudioPlayer

        player = AudioPlayer(file_path)
        player._zen_tab_id = tab_id

        from shared.ui.tab_button import TabButton

        tab_btn = TabButton(tab_id, os.path.basename(file_path), on_close=lambda tid: self._do_close_tab_by_id(tid))
        page_num = self.notebook.append_page(player, None)
        self._tab_bar.append(tab_btn)
        click = Gtk.GestureClick.new()
        click.connect("pressed", lambda g, n, x, y, tid=tab_id: self._select_tab_by_id(tid))
        tab_btn.add_controller(click)

        audio_tab = EditorTab(file_path=file_path)
        audio_tab._is_audio = True
        audio_tab._tab_button = tab_btn
        audio_tab._tab_id = tab_id
        audio_tab._audio_player = player
        self.tabs[tab_id] = audio_tab

        if switch_to:
            self.notebook.set_current_page(page_num)
        if self.on_file_opened:
            self.on_file_opened(file_path)
        from dev_pad import log_file_activity

        log_file_activity(file_path, "open")
        return True

    def open_binary(self, file_path: str, switch_to: bool = True) -> bool:
        """Open a binary file in a hex dump viewer tab."""
        for tab_id, tab in self.tabs.items():
            if tab.file_path == file_path:
                if switch_to:
                    page_num = self._get_page_num_for_tab_id(tab_id)
                    if page_num >= 0:
                        self.notebook.set_current_page(page_num)
                return True

        self._close_welcome_tab()
        tab_id = self._next_tab_id
        self._next_tab_id += 1

        from ..preview.binary_viewer import BinaryViewer

        viewer = BinaryViewer(file_path)
        viewer._zen_tab_id = tab_id

        from shared.ui.tab_button import TabButton

        bin_tab_btn = TabButton(tab_id, os.path.basename(file_path), on_close=lambda tid: self._do_close_tab_by_id(tid))
        page_num = self.notebook.append_page(viewer, None)
        self._tab_bar.append(bin_tab_btn)
        click = Gtk.GestureClick.new()
        click.connect("pressed", lambda g, n, x, y, tid=tab_id: self._select_tab_by_id(tid))
        bin_tab_btn.add_controller(click)

        bin_tab = EditorTab(file_path=file_path)
        bin_tab._is_binary = True
        bin_tab._tab_button = bin_tab_btn
        bin_tab._tab_id = tab_id
        self.tabs[tab_id] = bin_tab

        if switch_to:
            self.notebook.set_current_page(page_num)
        if self.on_file_opened:
            self.on_file_opened(file_path)
        from dev_pad import log_file_activity

        log_file_activity(file_path, "open")
        return True
