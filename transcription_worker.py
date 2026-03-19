"""Background transcription worker for ScribeVibe."""

import logging
import queue
import threading
from collections.abc import Callable

import audio_utils
import config
import output_handler
from audio_capture import SAMPLE_RATE, AudioRecorder
from paths import get_resource_path

logger = logging.getLogger(__name__)


class TranscriptionWorker:
    """Processes transcription tasks from a queue on a background daemon thread."""

    def __init__(self, engine, notify_fn: Callable | None = None, transcribing_indicator=None) -> None:
        self._engine = engine
        self._notify_fn = notify_fn
        self._transcribing_indicator = transcribing_indicator
        cfg = config.load()
        self._snd_done = get_resource_path(cfg["sound_done"])
        self._queue: queue.Queue = queue.Queue()
        threading.Thread(target=self._loop, daemon=True).start()

    def submit(self, task: dict) -> None:
        """Queue a transcription task."""
        self._queue.put(task)

    def _loop(self) -> None:
        while True:
            task = self._queue.get()
            try:
                self._process(task)
            except Exception as e:
                msg = f"Unexpected error: {e}"
                logger.error("Transcription worker error: %s", msg)
                if self._notify_fn:
                    self._notify_fn(msg, title="ScribeVibe — Error")
            finally:
                self._queue.task_done()

    def _process(self, task: dict) -> None:
        if self._transcribing_indicator:
            self._transcribing_indicator.show()
        try:
            self._process_task(task)
        finally:
            if self._transcribing_indicator:
                self._transcribing_indicator.hide()

    def _process_task(self, task: dict) -> None:
        language = task["lang"]
        model_size = task["model_size"]

        audio_data = AudioRecorder.process_raw(task["raw"])
        audio_duration = len(audio_data) / SAMPLE_RATE

        if audio_duration < 0.1:
            audio_utils.play(self._snd_done)
            return

        logger.info("Processing %.1fs of audio...", audio_duration)
        try:
            self._engine.ensure_model(model_size)
            beam_size = config.load().get("beam_size", 2)
            text, transcribe_time = self._engine.transcribe(audio_data, language, beam_size=beam_size)
        except Exception as e:
            msg = f"Transcription error: {e}"
            logger.error(msg)
            if self._notify_fn:
                self._notify_fn(msg, title="ScribeVibe — Error")
            audio_utils.play(self._snd_done)
            return

        if text:
            rtf = audio_duration / transcribe_time if transcribe_time > 0 else 0
            logger.info("TRANSCRIBED in %.2fs (%.1fx real-time): %s", transcribe_time, rtf, text)
            output_handler.type_text(text)
            output_handler.log_transcription(text, model_size, transcribe_time)
        else:
            logger.warning("Transcription returned empty — speech not detected.")
            if self._notify_fn:
                self._notify_fn("Nothing transcribed — no speech detected.")
        audio_utils.play(self._snd_done)
