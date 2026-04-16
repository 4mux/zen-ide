"""Audio player tab for Zen IDE (GStreamer playbin + GTK4 controls)."""

import os

import gi

gi.require_version("Gst", "1.0")

from gi.repository import GLib, Gst, Gtk  # noqa: E402

from fonts import get_font_settings  # noqa: E402
from icons import get_icon_font_name  # noqa: E402
from themes import get_theme, subscribe_theme_change  # noqa: E402

_ICON_PLAY = "\uf04b"
_ICON_PAUSE = "\uf04c"
_ICON_STOP = "\uf04d"
_ICON_VOLUME = "\uf028"
_ICON_MUTE = "\uf026"

_gst_initialized = False


def _ensure_gst() -> None:
    global _gst_initialized
    if not _gst_initialized:
        Gst.init(None)
        _gst_initialized = True


def _format_time(seconds: float) -> str:
    if seconds < 0 or seconds != seconds:  # NaN guard
        seconds = 0
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class AudioPlayer(Gtk.Box):
    """GStreamer-backed audio playback widget shown in an editor tab."""

    def __init__(self, file_path: str):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        _ensure_gst()

        self.file_path = file_path
        self._duration_ns = 0
        self._update_source_id = 0
        self._updating_pos = False
        self._css_provider = None
        self._saved_volume = 1.0
        self._error_text: str | None = None

        self._playbin = Gst.ElementFactory.make("playbin", "zen-audio-player")
        uri = GLib.filename_to_uri(os.path.abspath(file_path), None)
        self._playbin.set_property("uri", uri)
        self._bus = self._playbin.get_bus()
        self._bus.add_signal_watch()
        self._bus.connect("message", self._on_bus_message)

        self._build_ui()
        self._apply_theme()
        subscribe_theme_change(lambda _name: self._apply_theme())
        self.connect("unrealize", lambda _w: self.stop())

    def _build_ui(self) -> None:
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_margin_top(32)
        self.set_margin_bottom(32)
        self.set_margin_start(32)
        self.set_margin_end(32)

        self._name_label = Gtk.Label(label=os.path.basename(self.file_path))
        self._name_label.set_halign(Gtk.Align.CENTER)
        self._name_label.set_wrap(True)
        self._name_label.set_max_width_chars(60)
        self._name_label.add_css_class("audio-name")
        self.append(self._name_label)

        self._status_label = Gtk.Label(label="")
        self._status_label.set_halign(Gtk.Align.CENTER)
        self._status_label.add_css_class("audio-status")
        self._status_label.set_visible(False)
        self.append(self._status_label)

        seek_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        seek_row.set_halign(Gtk.Align.CENTER)

        self._pos_label = Gtk.Label(label="0:00")
        self._pos_label.add_css_class("audio-time")
        seek_row.append(self._pos_label)

        self._seek = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.001)
        self._seek.set_draw_value(False)
        self._seek.set_hexpand(True)
        self._seek.set_size_request(480, -1)
        self._seek.connect("change-value", self._on_user_seek)
        seek_row.append(self._seek)

        self._dur_label = Gtk.Label(label="0:00")
        self._dur_label.add_css_class("audio-time")
        seek_row.append(self._dur_label)

        self.append(seek_row)

        ctl_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ctl_row.set_halign(Gtk.Align.CENTER)

        self._play_btn = Gtk.Button()
        self._play_icon = Gtk.Label(label=_ICON_PLAY)
        self._play_icon.add_css_class("audio-icon")
        self._play_btn.set_child(self._play_icon)
        self._play_btn.add_css_class("audio-btn-primary")
        self._play_btn.set_tooltip_text("Play / Pause (Space)")
        self._play_btn.connect("clicked", self._on_play_pause)
        ctl_row.append(self._play_btn)

        self._stop_btn = Gtk.Button()
        stop_icon = Gtk.Label(label=_ICON_STOP)
        stop_icon.add_css_class("audio-icon")
        self._stop_btn.set_child(stop_icon)
        self._stop_btn.add_css_class("audio-btn")
        self._stop_btn.set_tooltip_text("Stop")
        self._stop_btn.connect("clicked", self._on_stop)
        ctl_row.append(self._stop_btn)

        spacer = Gtk.Box()
        spacer.set_size_request(16, -1)
        ctl_row.append(spacer)

        self._mute_btn = Gtk.Button()
        self._mute_icon = Gtk.Label(label=_ICON_VOLUME)
        self._mute_icon.add_css_class("audio-icon")
        self._mute_btn.set_child(self._mute_icon)
        self._mute_btn.add_css_class("audio-btn")
        self._mute_btn.set_tooltip_text("Mute / Unmute")
        self._mute_btn.connect("clicked", self._on_mute_toggle)
        ctl_row.append(self._mute_btn)

        self._vol_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.01)
        self._vol_scale.set_value(1.0)
        self._vol_scale.set_draw_value(False)
        self._vol_scale.set_size_request(140, -1)
        self._vol_scale.connect("value-changed", self._on_volume_changed)
        ctl_row.append(self._vol_scale)

        self.append(ctl_row)

        key = Gtk.EventControllerKey.new()
        key.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key)

    def _on_key_pressed(self, _ctrl, keyval, _keycode, _state):
        from gi.repository import Gdk

        if keyval == Gdk.KEY_space:
            self._on_play_pause(None)
            return True
        return False

    def _on_play_pause(self, _btn) -> None:
        _ok, current, _pending = self._playbin.get_state(0)
        if current == Gst.State.PLAYING:
            self._playbin.set_state(Gst.State.PAUSED)
            self._play_icon.set_label(_ICON_PLAY)
            self._stop_update_loop()
        else:
            self._playbin.set_state(Gst.State.PLAYING)
            self._play_icon.set_label(_ICON_PAUSE)
            self._start_update_loop()

    def _on_stop(self, _btn) -> None:
        self._playbin.set_state(Gst.State.READY)
        self._play_icon.set_label(_ICON_PLAY)
        self._updating_pos = True
        self._seek.set_value(0.0)
        self._updating_pos = False
        self._pos_label.set_label("0:00")
        self._stop_update_loop()

    def _on_volume_changed(self, scale) -> None:
        value = scale.get_value()
        self._playbin.set_property("volume", value)
        if value > 0.0:
            self._saved_volume = value
            self._mute_icon.set_label(_ICON_VOLUME)
        else:
            self._mute_icon.set_label(_ICON_MUTE)

    def _on_mute_toggle(self, _btn) -> None:
        current = self._vol_scale.get_value()
        if current > 0.0:
            self._saved_volume = current
            self._vol_scale.set_value(0.0)
        else:
            self._vol_scale.set_value(self._saved_volume or 1.0)

    def _on_user_seek(self, _scale, _scroll_type, value) -> bool:
        if self._duration_ns <= 0:
            return False
        frac = max(0.0, min(1.0, value))
        pos_ns = int(frac * self._duration_ns)
        self._playbin.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            pos_ns,
        )
        self._pos_label.set_label(_format_time(pos_ns / Gst.SECOND))
        return False

    def _start_update_loop(self) -> None:
        if self._update_source_id:
            return
        self._update_source_id = GLib.timeout_add(250, self._tick)

    def _stop_update_loop(self) -> None:
        if self._update_source_id:
            GLib.source_remove(self._update_source_id)
            self._update_source_id = 0

    def _tick(self) -> bool:
        if self._duration_ns <= 0:
            ok, dur = self._playbin.query_duration(Gst.Format.TIME)
            if ok and dur > 0:
                self._duration_ns = dur
                self._dur_label.set_label(_format_time(dur / Gst.SECOND))
        ok, pos = self._playbin.query_position(Gst.Format.TIME)
        if ok and self._duration_ns > 0:
            frac = pos / self._duration_ns
            self._updating_pos = True
            self._seek.set_value(frac)
            self._updating_pos = False
            self._pos_label.set_label(_format_time(pos / Gst.SECOND))
        return True

    def _on_bus_message(self, _bus, message) -> None:
        t = message.type
        if t == Gst.MessageType.EOS:
            self._playbin.set_state(Gst.State.READY)
            self._updating_pos = True
            self._seek.set_value(0.0)
            self._updating_pos = False
            self._pos_label.set_label("0:00")
            self._play_icon.set_label(_ICON_PLAY)
            self._stop_update_loop()
        elif t == Gst.MessageType.ERROR:
            err, _dbg = message.parse_error()
            self._play_icon.set_label(_ICON_PLAY)
            self._stop_update_loop()
            self._error_text = err.message if err else "playback error"
            self._status_label.set_label(f"Playback error: {self._error_text}")
            self._status_label.set_visible(True)
        elif t == Gst.MessageType.DURATION_CHANGED:
            ok, dur = self._playbin.query_duration(Gst.Format.TIME)
            if ok and dur > 0:
                self._duration_ns = dur
                self._dur_label.set_label(_format_time(dur / Gst.SECOND))
        elif t == Gst.MessageType.ASYNC_DONE:
            if self._duration_ns <= 0:
                ok, dur = self._playbin.query_duration(Gst.Format.TIME)
                if ok and dur > 0:
                    self._duration_ns = dur
                    self._dur_label.set_label(_format_time(dur / Gst.SECOND))

    def stop(self) -> None:
        self._stop_update_loop()
        if self._playbin is not None:
            self._playbin.set_state(Gst.State.NULL)
        if self._bus is not None:
            try:
                self._bus.remove_signal_watch()
            except Exception:
                pass
            self._bus = None

    def _apply_theme(self) -> None:
        theme = get_theme()
        font_settings = get_font_settings("editor")
        font_family = font_settings["family"]
        font_size = font_settings.get("size", 13)
        nerd_font = get_icon_font_name()

        css = f"""
            box {{
                background-color: {theme.main_bg};
                color: {theme.fg_color};
            }}
            label.audio-name {{
                font-family: '{font_family}';
                font-size: {font_size + 4}pt;
                font-weight: bold;
                color: {theme.fg_color};
            }}
            label.audio-status {{
                font-family: '{font_family}';
                font-size: {font_size}pt;
                color: {theme.warning_color};
            }}
            label.audio-time {{
                font-family: '{font_family}';
                font-size: {font_size}pt;
                color: {theme.fg_dim};
                min-width: 48px;
            }}
            label.audio-icon {{
                font-family: "{nerd_font}", '{font_family}';
                font-size: {font_size + 4}pt;
                padding: 0 4px;
            }}
            button.audio-btn,
            button.audio-btn-primary {{
                padding: 6px 12px;
                border-radius: 6px;
                background: {theme.panel_bg};
                border: 1px solid {theme.border_color};
                color: {theme.fg_color};
            }}
            button.audio-btn-primary {{
                background: {theme.accent_color};
                border-color: {theme.accent_color};
            }}
            button.audio-btn-primary label {{
                color: #ffffff;
            }}
            button.audio-btn:hover,
            button.audio-btn-primary:hover {{
                background: {theme.hover_bg};
            }}
            scale trough {{
                min-height: 6px;
                border-radius: 3px;
                background: {theme.panel_bg};
            }}
            scale highlight {{
                background: {theme.accent_color};
                border-radius: 3px;
            }}
            scale slider {{
                min-width: 14px;
                min-height: 14px;
                border-radius: 7px;
                background: {theme.accent_color};
            }}
        """
        if self._css_provider:
            self.get_style_context().remove_provider(self._css_provider)
        self._css_provider = Gtk.CssProvider()
        self._css_provider.load_from_data(css.encode())
        style_targets = [
            self,
            self._name_label,
            self._status_label,
            self._pos_label,
            self._dur_label,
            self._seek,
            self._vol_scale,
            self._play_btn,
            self._play_icon,
            self._stop_btn,
            self._mute_btn,
            self._mute_icon,
        ]
        for w in style_targets:
            w.get_style_context().add_provider(self._css_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
