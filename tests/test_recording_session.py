"""Tests for recording_session.py — state machine, debounce, language switching."""

from unittest.mock import MagicMock, patch

import pytest

import recording_session as rs


# ── Test config / constants ───────────────────────────────────────────────────

_CFG = {
    "device_id": None,
    "model_size_en": "small.en",
    "model_size_nl": "small",
    "sound_start": "start.wav",
    "sound_stop": "stop.wav",
}


class _SyncThread:
    """Runs target synchronously in start() — eliminates timing non-determinism."""

    def __init__(self, target, args=(), kwargs=None, daemon=False):
        self._target = target
        self._args = args

    def start(self):
        self._target(*self._args)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_recorder():
    m = MagicMock()
    m.stop_recording_raw.return_value = {"chunks": [], "needs_resample": False, "stream_rate": 16_000}
    return m


@pytest.fixture(autouse=True)
def patch_deps(monkeypatch, mock_recorder):
    """Patch all external dependencies for every test in this module."""
    monkeypatch.setattr(rs, "AudioRecorder", lambda: mock_recorder)
    monkeypatch.setattr(rs.config, "load", lambda: dict(_CFG))
    monkeypatch.setattr(rs, "get_resource_path", lambda p: p)
    monkeypatch.setattr(rs.threading, "Thread", _SyncThread)


@pytest.fixture()
def session_factory(mock_recorder):
    """Return a factory that creates a RecordingSession with optional overrides."""

    def factory(**kwargs):
        defaults = {"engine": MagicMock(), "on_task_ready": MagicMock()}
        defaults.update(kwargs)
        return rs.RecordingSession(**defaults)

    return factory


@pytest.fixture()
def session(session_factory):
    return session_factory()


# ── Initial state ─────────────────────────────────────────────────────────────


class TestInitialState:
    def test_not_recording_at_start(self, session):
        assert session.is_recording is False

    def test_default_language_is_english(self, session):
        assert session._active_language == "en"

    def test_default_model_size_is_english(self, session):
        assert session._active_model_size == _CFG["model_size_en"]

    def test_pre_opens_mic_stream(self, session, mock_recorder):
        # session construction should have called open_stream on the recorder
        mock_recorder.open_stream.assert_called_once_with(None)


# ── toggle() debounce ─────────────────────────────────────────────────────────


class TestDebounce:
    def test_rapid_second_toggle_is_ignored(self, session):
        session.toggle()
        assert session.is_recording
        session.toggle()  # within debounce window
        assert session.is_recording  # still recording

    def test_toggle_allowed_after_resetting_debounce_clock(self, session):
        session.toggle()
        session._last_toggle = 0.0  # manually expire the debounce window
        session.toggle()
        assert not session.is_recording


# ── toggle() start/stop ───────────────────────────────────────────────────────


class TestToggleStartStop:
    def test_first_toggle_starts_recording(self, session):
        session.toggle()
        assert session.is_recording

    def test_second_toggle_stops_recording(self, session):
        session.toggle()
        session._last_toggle = 0.0
        session.toggle()
        assert not session.is_recording

    def test_start_calls_recorder_start_recording(self, session, mock_recorder):
        session.toggle()
        mock_recorder.start_recording.assert_called_once_with(None)

    def test_stop_calls_recorder_stop_recording_raw(self, session, mock_recorder):
        session.toggle()
        session._last_toggle = 0.0
        session.toggle()
        mock_recorder.stop_recording_raw.assert_called_once()

    def test_stop_calls_on_task_ready(self, session):
        on_task_ready = session._on_task_ready
        session.toggle()
        session._last_toggle = 0.0
        session.toggle()
        on_task_ready.assert_called_once()

    def test_task_dict_has_required_keys(self, session):
        session.toggle()
        session._last_toggle = 0.0
        session.toggle()
        task = session._on_task_ready.call_args[0][0]
        assert "raw" in task
        assert "lang" in task
        assert "model_size" in task

    def test_task_lang_matches_active_language(self, session):
        session.toggle()
        session._last_toggle = 0.0
        session.toggle()
        task = session._on_task_ready.call_args[0][0]
        assert task["lang"] == "en"

    def test_task_model_size_matches_config(self, session):
        session.toggle()
        session._last_toggle = 0.0
        session.toggle()
        task = session._on_task_ready.call_args[0][0]
        assert task["model_size"] == _CFG["model_size_en"]


# ── toggle() with indicator ───────────────────────────────────────────────────


class TestIndicator:
    def test_indicator_shown_on_start(self, session_factory):
        indicator = MagicMock()
        s = session_factory(indicator=indicator)
        s.toggle()
        indicator.show.assert_called_once()

    def test_indicator_hidden_on_stop(self, session_factory):
        indicator = MagicMock()
        s = session_factory(indicator=indicator)
        s.toggle()
        s._last_toggle = 0.0
        s.toggle()
        indicator.hide.assert_called_once()


# ── abort() ───────────────────────────────────────────────────────────────────


class TestAbort:
    def test_abort_when_not_recording_returns_false(self, session):
        assert session.abort() is False

    def test_abort_when_recording_returns_true(self, session):
        session.toggle()
        assert session.abort() is True

    def test_abort_clears_recording_flag(self, session):
        session.toggle()
        session.abort()
        assert session.is_recording is False

    def test_abort_discards_audio_buffer(self, session, mock_recorder):
        session.toggle()
        session.abort()
        mock_recorder.stop_recording_raw.assert_called_once()

    def test_abort_does_not_call_on_task_ready(self, session):
        on_task_ready = session._on_task_ready
        session.toggle()
        session.abort()
        on_task_ready.assert_not_called()

    def test_abort_hides_indicator(self, session_factory):
        indicator = MagicMock()
        s = session_factory(indicator=indicator)
        s.toggle()
        s.abort()
        indicator.hide.assert_called_once()

    def test_abort_clears_live_callback(self, session, mock_recorder):
        session.toggle()
        session.abort()
        mock_recorder.set_live_callback.assert_called_with(None)


# ── Mic error during start ────────────────────────────────────────────────────


class TestMicError:
    def test_mic_error_leaves_recording_false(self, session, mock_recorder):
        mock_recorder.start_recording.side_effect = RuntimeError("device unavailable")
        session.toggle()
        assert session.is_recording is False

    def test_mic_error_notifies_user(self, session_factory, mock_recorder):
        mock_recorder.start_recording.side_effect = RuntimeError("device unavailable")
        notes = []
        s = session_factory(notify_fn=lambda msg, **kw: notes.append(msg))
        s.toggle()
        assert len(notes) == 1

    def test_mic_error_does_not_call_on_task_ready(self, session, mock_recorder):
        mock_recorder.start_recording.side_effect = RuntimeError("broken")
        on_task_ready = session._on_task_ready
        session.toggle()
        on_task_ready.assert_not_called()


# ── switch_language() ─────────────────────────────────────────────────────────


class TestSwitchLanguage:
    def test_switch_while_recording_is_noop(self, session):
        session.toggle()
        session.switch_language()
        assert session._active_language == "en"

    def test_switch_en_to_nl(self, session):
        session.switch_language()
        assert session._active_language == "nl"

    def test_switch_nl_to_en(self, session):
        session.switch_language()
        session.switch_language()
        assert session._active_language == "en"

    def test_switch_updates_model_size_to_nl(self, session):
        session.switch_language()
        assert session._active_model_size == _CFG["model_size_nl"]

    def test_switch_updates_model_size_back_to_en(self, session):
        session.switch_language()
        session.switch_language()
        assert session._active_model_size == _CFG["model_size_en"]

    def test_switch_preloads_model(self, session):
        session.switch_language()
        session._engine.ensure_model.assert_called_once_with(_CFG["model_size_nl"])

    def test_switch_shows_language_overlay(self, session_factory):
        overlay = MagicMock()
        s = session_factory(language_overlay=overlay)
        s.switch_language()
        overlay.show.assert_called_once_with("nl")

    def test_switch_back_shows_en_overlay(self, session_factory):
        overlay = MagicMock()
        s = session_factory(language_overlay=overlay)
        s.switch_language()
        s.switch_language()
        assert overlay.show.call_args[0][0] == "en"
