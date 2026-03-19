"""Background transcription worker for ScribeVibe."""
import logging
import queue
import threading
import winsound
from typing import Callable, Optional

import config
import output_handler
from audio_capture import AudioRecorder, SAMPLE_RATE
from paths import get_resource_path

logger = logging.getLogger(__name__)


def _play(path: str) -> None:
    winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)


class TranscriptionWorker:
    """Processes transcription tasks from a queue on a background daemon thread."""

    def __init__(self, engine, notify_fn: Optional[Callable] = None) -> None:
        self._engine = engine
        self._notify_fn = notify_fn
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
        language   = task["lang"]
        model_size = task["model_size"]

        audio_data = AudioRecorder.process_raw(task["raw"])
        audio_duration = len(audio_data) / SAMPLE_RATE

        if audio_duration < 0.1:
            _play(self._snd_done)
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
            _play(self._snd_done)
            return

        if text:
            rtf = audio_duration / transcribe_time if transcribe_time > 0 else 0
            logger.info(
                "TRANSCRIBED in %.2fs (%.1fx real-time): %s", transcribe_time, rtf, text
            )
            output_handler.type_text(text)
            output_handler.log_transcription(text, model_size, transcribe_time)
        else:
            logger.warning("Transcription returned empty — speech not detected.")
            if self._notify_fn:
                self._notify_fn("Nothing transcribed — no speech detected.")
        _play(self._snd_done)
