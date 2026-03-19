"""Tests for transcription_worker.py — queue processing, error handling, edge cases."""

import collections
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from audio_capture import DTYPE, TARGET_SAMPLE_RATE


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_raw(n_samples, needs_resample=False, stream_rate=TARGET_SAMPLE_RATE):
    """Build a raw task dict with n_samples of silence."""
    chunk = np.zeros((n_samples, 1), dtype=DTYPE)
    return {
        "chunks": collections.deque([chunk]),
        "needs_resample": needs_resample,
        "stream_rate": stream_rate,
    }


def _make_worker(engine=None, notify_fn=None):
    from transcription_worker import TranscriptionWorker

    with patch("transcription_worker.get_resource_path", return_value="done.wav"), patch(
        "transcription_worker.config.load", return_value={"beam_size": 2, "sound_done": "done.wav"}
    ):
        return TranscriptionWorker(engine or MagicMock(), notify_fn=notify_fn)


def _run(worker, task):
    """Submit one task and block until the queue drains."""
    worker.submit(task)
    worker._queue.join()


# ── Short audio (<0.1s) ───────────────────────────────────────────────────────


class TestShortAudio:
    def test_skips_transcription(self):
        engine = MagicMock()
        worker = _make_worker(engine)
        task = {"raw": _make_raw(100), "lang": "en", "model_size": "small.en"}

        with patch("transcription_worker.winsound.PlaySound"), patch(
            "transcription_worker.output_handler.type_text"
        ) as mock_type:
            _run(worker, task)

        engine.transcribe.assert_not_called()
        mock_type.assert_not_called()

    def test_plays_done_sound_anyway(self):
        worker = _make_worker()
        task = {"raw": _make_raw(100), "lang": "en", "model_size": "small.en"}

        with patch("transcription_worker.winsound.PlaySound") as mock_play:
            _run(worker, task)

        mock_play.assert_called_once()


# ── Successful transcription ──────────────────────────────────────────────────


class TestSuccessfulTranscription:
    def _run_success(self, engine, text="hello world", beam_size=2):
        engine.transcribe.return_value = (text, 0.4)
        worker = _make_worker(engine)
        task = {"raw": _make_raw(16_000), "lang": "en", "model_size": "small.en"}

        with patch("transcription_worker.winsound.PlaySound"), patch(
            "transcription_worker.output_handler.type_text"
        ) as mock_type, patch(
            "transcription_worker.output_handler.log_transcription"
        ) as mock_log, patch(
            "transcription_worker.config.load", return_value={"beam_size": beam_size}
        ):
            _run(worker, task)
            return mock_type, mock_log

    def test_calls_ensure_model_with_task_model_size(self):
        engine = MagicMock()
        engine.transcribe.return_value = ("text", 0.3)
        worker = _make_worker(engine)
        task = {"raw": _make_raw(16_000), "lang": "en", "model_size": "small.en"}

        with patch("transcription_worker.winsound.PlaySound"), patch(
            "transcription_worker.output_handler.type_text"
        ), patch("transcription_worker.output_handler.log_transcription"), patch(
            "transcription_worker.config.load", return_value={"beam_size": 2}
        ):
            _run(worker, task)

        engine.ensure_model.assert_called_with("small.en")

    def test_types_transcribed_text(self):
        engine = MagicMock()
        mock_type, _ = self._run_success(engine, text="hello world")
        mock_type.assert_called_once_with("hello world")

    def test_logs_transcription_with_model_and_timing(self):
        engine = MagicMock()
        _, mock_log = self._run_success(engine, text="logged text")
        mock_log.assert_called_once()
        args = mock_log.call_args[0]
        assert args[0] == "logged text"
        assert args[1] == "small.en"
        assert isinstance(args[2], float)

    def test_plays_done_sound_after_success(self):
        engine = MagicMock()
        engine.transcribe.return_value = ("words", 0.3)
        worker = _make_worker(engine)
        task = {"raw": _make_raw(16_000), "lang": "en", "model_size": "small.en"}

        with patch("transcription_worker.winsound.PlaySound") as mock_play, patch(
            "transcription_worker.output_handler.type_text"
        ), patch("transcription_worker.output_handler.log_transcription"), patch(
            "transcription_worker.config.load", return_value={"beam_size": 2}
        ):
            _run(worker, task)

        mock_play.assert_called_once()

    def test_beam_size_read_from_config(self):
        engine = MagicMock()
        engine.transcribe.return_value = ("text", 0.2)
        worker = _make_worker(engine)
        task = {"raw": _make_raw(16_000), "lang": "en", "model_size": "small.en"}

        with patch("transcription_worker.winsound.PlaySound"), patch(
            "transcription_worker.output_handler.type_text"
        ), patch("transcription_worker.output_handler.log_transcription"), patch(
            "transcription_worker.config.load", return_value={"beam_size": 4}
        ):
            _run(worker, task)

        _, kw = engine.transcribe.call_args
        assert kw.get("beam_size") == 4

    def test_language_forwarded_to_transcribe(self):
        engine = MagicMock()
        engine.transcribe.return_value = ("tekst", 0.3)
        worker = _make_worker(engine)
        task = {"raw": _make_raw(16_000), "lang": "nl", "model_size": "small"}

        with patch("transcription_worker.winsound.PlaySound"), patch(
            "transcription_worker.output_handler.type_text"
        ), patch("transcription_worker.output_handler.log_transcription"), patch(
            "transcription_worker.config.load", return_value={"beam_size": 2}
        ):
            _run(worker, task)

        _, kw = engine.transcribe.call_args
        assert kw.get("language") == "nl" or engine.transcribe.call_args[0][1] == "nl"


# ── Empty transcription result ────────────────────────────────────────────────


class TestEmptyTranscription:
    def test_no_type_text_when_empty(self):
        engine = MagicMock()
        engine.transcribe.return_value = ("", 0.5)
        worker = _make_worker(engine)
        task = {"raw": _make_raw(16_000), "lang": "en", "model_size": "small.en"}

        with patch("transcription_worker.winsound.PlaySound"), patch(
            "transcription_worker.output_handler.type_text"
        ) as mock_type, patch(
            "transcription_worker.config.load", return_value={"beam_size": 2}
        ):
            _run(worker, task)

        mock_type.assert_not_called()

    def test_notifies_user_on_empty_result(self):
        engine = MagicMock()
        engine.transcribe.return_value = ("", 0.5)
        notes = []
        worker = _make_worker(engine, notify_fn=lambda msg, **kw: notes.append(msg))
        task = {"raw": _make_raw(16_000), "lang": "en", "model_size": "small.en"}

        with patch("transcription_worker.winsound.PlaySound"), patch(
            "transcription_worker.output_handler.type_text"
        ), patch("transcription_worker.config.load", return_value={"beam_size": 2}):
            _run(worker, task)

        assert len(notes) >= 1

    def test_plays_done_sound_on_empty(self):
        engine = MagicMock()
        engine.transcribe.return_value = ("", 0.5)
        worker = _make_worker(engine)
        task = {"raw": _make_raw(16_000), "lang": "en", "model_size": "small.en"}

        with patch("transcription_worker.winsound.PlaySound") as mock_play, patch(
            "transcription_worker.output_handler.type_text"
        ), patch("transcription_worker.config.load", return_value={"beam_size": 2}):
            _run(worker, task)

        mock_play.assert_called_once()


# ── Transcription error ───────────────────────────────────────────────────────


class TestTranscriptionError:
    def test_engine_exception_notifies_user(self):
        engine = MagicMock()
        engine.transcribe.side_effect = RuntimeError("CUDA OOM")
        notes = []
        worker = _make_worker(engine, notify_fn=lambda msg, **kw: notes.append(msg))
        task = {"raw": _make_raw(16_000), "lang": "en", "model_size": "small.en"}

        with patch("transcription_worker.winsound.PlaySound"), patch(
            "transcription_worker.config.load", return_value={"beam_size": 2}
        ):
            _run(worker, task)

        assert len(notes) >= 1

    def test_engine_exception_plays_done_sound(self):
        engine = MagicMock()
        engine.transcribe.side_effect = RuntimeError("fail")
        worker = _make_worker(engine)
        task = {"raw": _make_raw(16_000), "lang": "en", "model_size": "small.en"}

        with patch("transcription_worker.winsound.PlaySound") as mock_play, patch(
            "transcription_worker.config.load", return_value={"beam_size": 2}
        ):
            _run(worker, task)

        mock_play.assert_called_once()

    def test_worker_loop_survives_error(self):
        """The worker daemon must keep running after a failing task."""
        engine = MagicMock()
        call_count = [0]

        def flaky(audio, lang, beam_size=2):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("first task fails")
            return ("recovered", 0.3)

        engine.transcribe.side_effect = flaky
        worker = _make_worker(engine)

        with patch("transcription_worker.winsound.PlaySound"), patch(
            "transcription_worker.output_handler.type_text"
        ) as mock_type, patch(
            "transcription_worker.output_handler.log_transcription"
        ), patch(
            "transcription_worker.config.load", return_value={"beam_size": 2}
        ):
            worker.submit({"raw": _make_raw(16_000), "lang": "en", "model_size": "small.en"})
            worker.submit({"raw": _make_raw(16_000), "lang": "nl", "model_size": "small"})
            worker._queue.join()

        mock_type.assert_called_once_with("recovered")


# ── Queue ordering ────────────────────────────────────────────────────────────


class TestQueueOrdering:
    def test_tasks_processed_fifo(self):
        engine = MagicMock()
        langs_seen = []

        def record_lang(audio, lang, beam_size=2):
            langs_seen.append(lang)
            return ("x", 0.1)

        engine.transcribe.side_effect = record_lang
        worker = _make_worker(engine)

        with patch("transcription_worker.winsound.PlaySound"), patch(
            "transcription_worker.output_handler.type_text"
        ), patch("transcription_worker.output_handler.log_transcription"), patch(
            "transcription_worker.config.load", return_value={"beam_size": 2}
        ):
            worker.submit({"raw": _make_raw(16_000), "lang": "en", "model_size": "small.en"})
            worker.submit({"raw": _make_raw(16_000), "lang": "nl", "model_size": "small"})
            worker._queue.join()

        assert langs_seen == ["en", "nl"]
