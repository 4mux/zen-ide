"""Tests for editor/preview/audio_player.py — GStreamer-backed audio playback widget."""

from types import SimpleNamespace

import pytest


@pytest.fixture
def fake_theme():
    return SimpleNamespace(
        main_bg="#111",
        fg_color="#eee",
        fg_dim="#888",
        panel_bg="#222",
        border_color="#333",
        accent_color="#4af",
        hover_bg="#2a2a2a",
        warning_color="#f80",
    )


@pytest.fixture
def audio_module(monkeypatch, fake_theme):
    """Import audio_player with external deps (fonts/icons/themes) stubbed."""
    import fonts
    import icons
    import themes

    monkeypatch.setattr(fonts, "get_font_settings", lambda _name: {"family": "Mono", "size": 12})
    monkeypatch.setattr(icons, "get_icon_font_name", lambda: "Nerd")
    monkeypatch.setattr(themes, "get_theme", lambda: fake_theme)
    monkeypatch.setattr(themes, "subscribe_theme_change", lambda _cb: None)

    from editor.preview import audio_player

    return audio_player


@pytest.fixture
def player(audio_module, tmp_path):
    f = tmp_path / "sample.mp3"
    f.write_bytes(b"")
    p = audio_module.AudioPlayer(str(f))
    yield p
    p.stop()


class TestFormatTime:
    def test_zero(self, audio_module):
        assert audio_module._format_time(0) == "0:00"

    def test_seconds_only(self, audio_module):
        assert audio_module._format_time(7) == "0:07"

    def test_minutes_seconds(self, audio_module):
        assert audio_module._format_time(65) == "1:05"

    def test_hours(self, audio_module):
        assert audio_module._format_time(3725) == "1:02:05"

    def test_negative_clamps_to_zero(self, audio_module):
        assert audio_module._format_time(-5) == "0:00"

    def test_nan_clamps_to_zero(self, audio_module):
        assert audio_module._format_time(float("nan")) == "0:00"

    def test_fractional_truncates(self, audio_module):
        assert audio_module._format_time(59.9) == "0:59"


class TestEnsureGst:
    def test_idempotent(self, audio_module):
        audio_module._ensure_gst()
        audio_module._ensure_gst()
        assert audio_module._gst_initialized is True


class TestConstruction:
    def test_playbin_created_with_file_uri(self, player, tmp_path):
        uri = player._playbin.get_property("uri")
        assert uri.startswith("file://")
        assert uri.endswith("sample.mp3")

    def test_initial_labels(self, player):
        assert player._pos_label.get_label() == "0:00"
        assert player._dur_label.get_label() == "0:00"
        assert player._status_label.get_visible() is False

    def test_name_label_shows_basename(self, player):
        assert player._name_label.get_label() == "sample.mp3"


class TestVolumeAndMute:
    def test_volume_change_updates_playbin(self, player):
        player._vol_scale.set_value(0.5)
        assert player._playbin.get_property("volume") == pytest.approx(0.5)

    def test_volume_above_zero_stores_saved(self, player, audio_module):
        player._vol_scale.set_value(0.7)
        assert player._saved_volume == pytest.approx(0.7)
        assert player._mute_icon.get_label() == audio_module._ICON_VOLUME

    def test_volume_zero_shows_mute_icon(self, player, audio_module):
        player._vol_scale.set_value(0.0)
        assert player._mute_icon.get_label() == audio_module._ICON_MUTE

    def test_mute_toggle_from_audible_to_muted(self, player):
        player._vol_scale.set_value(0.8)
        player._on_mute_toggle(None)
        assert player._vol_scale.get_value() == pytest.approx(0.0)
        assert player._saved_volume == pytest.approx(0.8)

    def test_mute_toggle_restores_saved_volume(self, player):
        player._vol_scale.set_value(0.8)
        player._on_mute_toggle(None)  # mute
        player._on_mute_toggle(None)  # unmute
        assert player._vol_scale.get_value() == pytest.approx(0.8)


class TestSeek:
    def test_seek_noop_when_no_duration(self, player):
        # _duration_ns is 0 before anything plays
        result = player._on_user_seek(None, None, 0.5)
        assert result is False
        # Label untouched
        assert player._pos_label.get_label() == "0:00"

    def test_seek_updates_position_label(self, player):
        from gi.repository import Gst

        player._duration_ns = 60 * Gst.SECOND  # fake a 60s duration
        player._on_user_seek(None, None, 0.5)
        assert player._pos_label.get_label() == "0:30"

    def test_seek_clamps_fraction(self, player):
        from gi.repository import Gst

        player._duration_ns = 60 * Gst.SECOND
        player._on_user_seek(None, None, 2.0)  # beyond 1.0
        assert player._pos_label.get_label() == "1:00"


class TestBusMessageHandling:
    def test_error_message_sets_status_visible(self, player):
        from gi.repository import GLib, Gst

        err = GLib.Error.new_literal(Gst.CoreError.quark(), "boom", int(Gst.CoreError.FAILED))
        msg = Gst.Message.new_error(player._playbin, err, "dbg")
        player._on_bus_message(None, msg)
        assert player._status_label.get_visible() is True
        assert "boom" in player._status_label.get_label()
        assert player._error_text == "boom"

    def test_eos_resets_position(self, player, audio_module):
        from gi.repository import Gst

        player._pos_label.set_label("1:23")
        msg = Gst.Message.new_eos(player._playbin)
        player._on_bus_message(None, msg)
        assert player._pos_label.get_label() == "0:00"
        assert player._play_icon.get_label() == audio_module._ICON_PLAY


class TestStop:
    def test_stop_clears_bus_and_is_idempotent(self, audio_module, tmp_path):
        from gi.repository import Gst

        f = tmp_path / "x.mp3"
        f.write_bytes(b"")
        p = audio_module.AudioPlayer(str(f))
        p.stop()
        assert p._bus is None
        _ok, state, _pending = p._playbin.get_state(0)
        assert state == Gst.State.NULL
        # Second call must not raise
        p.stop()
