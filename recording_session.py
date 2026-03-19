"""Recording state machine for ScribeVibe."""

import logging
import threading
import time
from collections.abc import Callable

import sounddevice as sd

import audio_utils
import config
from audio_capture import AudioRecorder
from languages import LANGUAGE_CYCLE, LANGUAGES
from paths import get_resource_path

logger = logging.getLogger(__name__)


class RecordingSession:
    """Manages recording state, audio device, sounds, and language/model selection.

    Calls on_task_ready(task_dict) when a recording stops and needs transcription.
    """

    def __init__(
        self,
        engine,
        indicator=None,
        language_overlay=None,
        notify_fn: Callable | None = None,
        on_task_ready: Callable | None = None,
    ) -> None:
        self._engine = engine
        self._indicator = indicator
        self._language_overlay = language_overlay
        self._notify_fn = notify_fn
        self._on_task_ready = on_task_ready

        self._recorder = AudioRecorder()
        self.is_recording = False
        self._active_language = LANGUAGE_CYCLE[0]
        self._active_model_size = LANGUAGES[self._active_language].default_model
        self._last_toggle = 0.0  # monotonic timestamp — debounce guard

        cfg = config.load()
        self._snd_start = get_resource_path(cfg["sound_start"])
        self._snd_stop = get_resource_path(cfg["sound_stop"])

        # Pre-warm sound files from disk so playback is instant
        for path in (self._snd_start, self._snd_stop):
            try:
                with open(path, "rb") as f:
                    f.read()
            except OSError:
                pass

        device_id = cfg.get("device_id")
        try:
            self._recorder.open_stream(device_id)
        except RuntimeError as e:
            logger.warning("Could not pre-open mic: %s", e)

    def toggle(self) -> None:
        """Toggle recording on/off with debounce."""
        now = time.monotonic()
        if now - self._last_toggle < 0.25:
            return
        self._last_toggle = now

        if not self.is_recording:
            self._start()
        else:
            self._stop()

    def switch_language(self) -> None:
        """Cycle to the next language, show overlay, preload model."""
        if self.is_recording:
            return

        cfg = config.load()
        idx = LANGUAGE_CYCLE.index(self._active_language)
        self._active_language = LANGUAGE_CYCLE[(idx + 1) % len(LANGUAGE_CYCLE)]
        lang = LANGUAGES[self._active_language]
        self._active_model_size = cfg.get(lang.config_key, lang.default_model)
        logger.info("Language switched to %s — Model: %s", lang.name.upper(), self._active_model_size)

        if self._language_overlay:
            self._language_overlay.show(self._active_language)

        threading.Thread(
            target=self._engine.ensure_model,
            args=(self._active_model_size,),
            daemon=True,
        ).start()

    def abort(self) -> bool:
        """Abort recording and discard audio. Returns True if was recording."""
        if not self.is_recording:
            return False
        self.is_recording = False
        self._recorder.set_live_callback(None)
        if self._indicator:
            self._indicator.hide()
        self._recorder.stop_recording_raw()  # discard
        audio_utils.play(self._snd_stop)
        logger.info("Recording aborted.")
        return True

    def _start(self) -> None:
        cfg = config.load()
        device_id = cfg.get("device_id")
        lang = LANGUAGES[self._active_language]
        self._active_model_size = cfg.get(lang.config_key, lang.default_model)

        audio_utils.play(self._snd_start)

        try:
            self._recorder.start_recording(device_id)
        except RuntimeError as e:
            self.is_recording = False
            msg = f"Microphone error: {e}"
            logger.error(msg)
            if self._notify_fn:
                self._notify_fn(msg, title="ScribeVibe — Error")
            return

        self.is_recording = True
        if self._indicator:
            self._recorder.set_live_callback(self._indicator.feed_audio)
            self._indicator.show(self._active_language)

        # Pre-fetch model during recording if a swap is needed
        if self._engine.current_model != self._active_model_size:
            threading.Thread(
                target=self._engine.ensure_model,
                args=(self._active_model_size,),
                daemon=True,
            ).start()

        threading.Thread(
            target=self._log_start,
            args=(device_id, self._active_language, self._active_model_size),
            daemon=True,
        ).start()

    def _stop(self) -> None:
        self.is_recording = False
        self._recorder.set_live_callback(None)
        if self._indicator:
            self._indicator.hide()
        audio_utils.play(self._snd_stop)
        raw = self._recorder.stop_recording_raw()
        if self._on_task_ready:
            self._on_task_ready(
                {
                    "raw": raw,
                    "lang": self._active_language,
                    "model_size": self._active_model_size,
                }
            )

    def _log_start(self, device_id, lang_code, model) -> None:
        lang_name = LANGUAGES[lang_code].name.upper()
        mic_name = sd.query_devices(device_id)["name"] if device_id is not None else "default"
        logger.info("RECORDING (%s) — Model: %s — Mic: %s", lang_name, model, mic_name)
