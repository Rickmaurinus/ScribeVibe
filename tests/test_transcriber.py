"""Tests for transcriber.py — model loading, hot-swap, and transcription logic."""

from unittest.mock import MagicMock, call, patch

import numpy as np
import pytest


# ── _is_model_cached() ────────────────────────────────────────────────────────


class TestIsModelCached:
    def test_returns_false_when_cache_dir_missing(self, tmp_path, monkeypatch):
        from transcriber import _is_model_cached

        monkeypatch.setattr("os.path.expanduser", lambda _: str(tmp_path))
        assert _is_model_cached("small.en") is False

    def test_returns_true_for_systran_short_name(self, tmp_path, monkeypatch):
        from transcriber import _is_model_cached

        hub = tmp_path / ".cache" / "huggingface" / "hub"
        hub.mkdir(parents=True)
        (hub / "models--Systran--faster-whisper-small.en").mkdir()
        monkeypatch.setattr("os.path.expanduser", lambda _: str(tmp_path))
        assert _is_model_cached("small.en") is True

    def test_returns_true_for_hf_repo_id(self, tmp_path, monkeypatch):
        from transcriber import _is_model_cached

        hub = tmp_path / ".cache" / "huggingface" / "hub"
        hub.mkdir(parents=True)
        (hub / "models--Systran--faster-distil-whisper-large-v3").mkdir()
        monkeypatch.setattr("os.path.expanduser", lambda _: str(tmp_path))
        assert _is_model_cached("Systran/faster-distil-whisper-large-v3") is True

    def test_returns_true_on_oserror(self, monkeypatch):
        """Assume cached on error to avoid false download notifications."""
        from transcriber import _is_model_cached

        monkeypatch.setattr("os.path.isdir", lambda _: (_ for _ in ()).throw(OSError("no perm")))
        # OSError branch returns True
        assert _is_model_cached("small.en") is True


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_whisper_cls():
    with patch("transcriber.WhisperModel") as mock_cls:
        mock_cls.return_value = MagicMock()
        yield mock_cls


@pytest.fixture()
def cached(monkeypatch):
    monkeypatch.setattr("transcriber._is_model_cached", lambda _: True)


@pytest.fixture()
def not_cached(monkeypatch):
    monkeypatch.setattr("transcriber._is_model_cached", lambda _: False)


@pytest.fixture()
def cuda_mock():
    with patch("transcriber.torch.cuda.empty_cache") as m:
        yield m


def _make_engine(notify_fn=None):
    from transcriber import WhisperEngine
    return WhisperEngine(notify_fn=notify_fn)


def _seg(text):
    s = MagicMock()
    s.text = text
    return s


# ── ensure_model() ────────────────────────────────────────────────────────────


class TestEnsureModel:
    def test_loads_model_when_none_present(self, mock_whisper_cls, cached, cuda_mock):
        engine = _make_engine()
        engine.ensure_model("small.en")
        mock_whisper_cls.assert_called_once()
        assert engine.current_model == "small.en"

    def test_model_loaded_with_cuda_and_int8_float16(self, mock_whisper_cls, cached, cuda_mock):
        engine = _make_engine()
        engine.ensure_model("small.en")
        _, kwargs = mock_whisper_cls.call_args
        assert kwargs["device"] == "cuda"
        assert kwargs["compute_type"] == "int8_float16"

    def test_no_reload_for_same_model(self, mock_whisper_cls, cached, cuda_mock):
        engine = _make_engine()
        engine.ensure_model("small.en")
        engine.ensure_model("small.en")
        assert mock_whisper_cls.call_count == 1

    def test_swaps_model_when_different(self, mock_whisper_cls, cached, cuda_mock):
        engine = _make_engine()
        engine.ensure_model("small.en")
        engine.ensure_model("medium.en")
        assert mock_whisper_cls.call_count == 2
        assert engine.current_model == "medium.en"

    def test_calls_gc_and_cuda_clear_on_swap(self, mock_whisper_cls, cached, cuda_mock):
        with patch("transcriber.gc.collect") as mock_gc:
            engine = _make_engine()
            engine.ensure_model("small.en")
            engine.ensure_model("medium.en")
        mock_gc.assert_called()
        cuda_mock.assert_called()

    def test_local_files_only_true_when_cached(self, mock_whisper_cls, cached, cuda_mock):
        engine = _make_engine()
        engine.ensure_model("small.en")
        _, kwargs = mock_whisper_cls.call_args
        assert kwargs["local_files_only"] is True

    def test_local_files_only_false_when_not_cached(self, mock_whisper_cls, not_cached, cuda_mock):
        engine = _make_engine()
        engine.ensure_model("small.en")
        _, kwargs = mock_whisper_cls.call_args
        assert kwargs["local_files_only"] is False

    def test_notifies_on_download(self, mock_whisper_cls, not_cached, cuda_mock):
        notes = []
        engine = _make_engine(notify_fn=lambda msg: notes.append(msg))
        engine.ensure_model("small.en")
        assert len(notes) == 1
        assert "small.en" in notes[0]

    def test_no_notification_when_cached(self, mock_whisper_cls, cached, cuda_mock):
        notes = []
        engine = _make_engine(notify_fn=lambda msg: notes.append(msg))
        engine.ensure_model("small.en")
        assert notes == []

    def test_set_notify_fn_after_construction(self, mock_whisper_cls, not_cached, cuda_mock):
        notes = []
        engine = _make_engine()
        engine.set_notify_fn(lambda msg: notes.append(msg))
        engine.ensure_model("small.en")
        assert len(notes) == 1


# ── transcribe() ──────────────────────────────────────────────────────────────


class TestTranscribe:
    def _engine_with_model(self, model_size, mock_whisper_cls, cuda_mock, cached):
        engine = _make_engine()
        engine.ensure_model(model_size)
        return engine, mock_whisper_cls.return_value

    def test_returns_joined_segment_text(self, mock_whisper_cls, cached, cuda_mock):
        engine, mock_model = self._engine_with_model("small.en", mock_whisper_cls, cuda_mock, cached)
        mock_model.transcribe.return_value = (iter([_seg("Hello"), _seg("world")]), MagicMock())
        text, duration = engine.transcribe(np.zeros(1000, dtype=np.float32))
        assert text == "Hello world"

    def test_duration_is_non_negative_float(self, mock_whisper_cls, cached, cuda_mock):
        engine, mock_model = self._engine_with_model("small.en", mock_whisper_cls, cuda_mock, cached)
        mock_model.transcribe.return_value = (iter([_seg("hi")]), MagicMock())
        _, duration = engine.transcribe(np.zeros(100, dtype=np.float32))
        assert isinstance(duration, float)
        assert duration >= 0.0

    def test_strips_whitespace_from_segments(self, mock_whisper_cls, cached, cuda_mock):
        engine, mock_model = self._engine_with_model("small.en", mock_whisper_cls, cuda_mock, cached)
        mock_model.transcribe.return_value = (iter([_seg("  hello  "), _seg("  world ")]), MagicMock())
        text, _ = engine.transcribe(np.zeros(100, dtype=np.float32))
        assert text == "hello world"

    def test_skips_whitespace_only_segments(self, mock_whisper_cls, cached, cuda_mock):
        engine, mock_model = self._engine_with_model("small.en", mock_whisper_cls, cuda_mock, cached)
        mock_model.transcribe.return_value = (iter([_seg("hello"), _seg("  "), _seg("world")]), MagicMock())
        text, _ = engine.transcribe(np.zeros(100, dtype=np.float32))
        assert text == "hello world"

    def test_empty_segments_returns_empty_string(self, mock_whisper_cls, cached, cuda_mock):
        engine, mock_model = self._engine_with_model("small.en", mock_whisper_cls, cuda_mock, cached)
        mock_model.transcribe.return_value = (iter([]), MagicMock())
        text, _ = engine.transcribe(np.zeros(100, dtype=np.float32))
        assert text == ""

    def test_multilingual_model_passes_language_kwarg(self, mock_whisper_cls, cached, cuda_mock):
        engine, mock_model = self._engine_with_model("small", mock_whisper_cls, cuda_mock, cached)
        mock_model.transcribe.return_value = (iter([]), MagicMock())
        engine.transcribe(np.zeros(100, dtype=np.float32), language="nl")
        kw = mock_model.transcribe.call_args[1]
        assert kw.get("language") == "nl"

    def test_english_only_model_omits_language_kwarg(self, mock_whisper_cls, cached, cuda_mock):
        engine, mock_model = self._engine_with_model("small.en", mock_whisper_cls, cuda_mock, cached)
        mock_model.transcribe.return_value = (iter([]), MagicMock())
        engine.transcribe(np.zeros(100, dtype=np.float32), language="en")
        kw = mock_model.transcribe.call_args[1]
        assert "language" not in kw

    def test_vad_filter_always_enabled(self, mock_whisper_cls, cached, cuda_mock):
        engine, mock_model = self._engine_with_model("small.en", mock_whisper_cls, cuda_mock, cached)
        mock_model.transcribe.return_value = (iter([]), MagicMock())
        engine.transcribe(np.zeros(100, dtype=np.float32))
        kw = mock_model.transcribe.call_args[1]
        assert kw.get("vad_filter") is True

    def test_beam_size_forwarded(self, mock_whisper_cls, cached, cuda_mock):
        engine, mock_model = self._engine_with_model("small.en", mock_whisper_cls, cuda_mock, cached)
        mock_model.transcribe.return_value = (iter([]), MagicMock())
        engine.transcribe(np.zeros(100, dtype=np.float32), beam_size=4)
        args, kw = mock_model.transcribe.call_args
        assert kw.get("beam_size") == 4 or args[1] == 4


# ── warmup() ──────────────────────────────────────────────────────────────────


class TestWarmup:
    def test_warmup_with_no_model_is_noop(self):
        engine = _make_engine()
        engine.warmup()  # must not raise

    def test_warmup_calls_transcribe_with_silence(self, mock_whisper_cls, cached, cuda_mock):
        engine = _make_engine()
        engine.ensure_model("small.en")
        mock_model = mock_whisper_cls.return_value
        mock_model.transcribe.return_value = (iter([]), MagicMock())
        engine.warmup()
        assert mock_model.transcribe.call_count == 1
        audio_arg = mock_model.transcribe.call_args[0][0]
        assert np.all(audio_arg == 0.0)

    def test_warmup_uses_beam_size_1(self, mock_whisper_cls, cached, cuda_mock):
        engine = _make_engine()
        engine.ensure_model("small.en")
        mock_model = mock_whisper_cls.return_value
        mock_model.transcribe.return_value = (iter([]), MagicMock())
        engine.warmup()
        kw = mock_model.transcribe.call_args[1]
        assert kw.get("beam_size") == 1
