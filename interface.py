"""
Global hotkey listener and audio feedback for ScribeVibe.

Hotkeys (configurable in config.py / settings.json):
  F13 — toggle recording in English
  F14 — toggle recording in Dutch

"Wait & Blitz": record the full utterance, transcribe on stop, type the result.
"""
import os
import queue
import sys
import threading
import time
import winsound

import numpy as np
import sounddevice as sd
from pynput import keyboard

import config
import output_handler
from audio_capture import AudioRecorder, SAMPLE_RATE
from transcriber import WhisperEngine


# ── resource path (PyInstaller-compatible) ──────────────────────────

def get_resource_path(relative_path: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


# ── audio feedback — cached file paths, native async playback ────────

_cfg = config.load()
_SND_START: str = get_resource_path(_cfg["sound_start"])
_SND_STOP:  str = get_resource_path(_cfg["sound_stop"])
_SND_DONE:  str = get_resource_path(_cfg["sound_done"])
del _cfg

# Pre-warm the OS file cache by reading each file once at startup
for _p in (_SND_START, _SND_STOP, _SND_DONE):
    with open(_p, "rb") as _f:
        _f.read()


def _play(path: str) -> None:
    """Play a WAV file asynchronously — returns instantly, no threads needed."""
    winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)


def _key_from_name(name: str) -> keyboard.Key:
    return getattr(keyboard.Key, name.lower())


# ── hotkey listener ─────────────────────────────────────────────────

class HotkeyListener:
    """
    Toggle-based hotkey listener.

    First press  → start recording (plays start.wav)
    Second press → stop, transcribe, type, play done.wav
    """

    def __init__(self, engine: WhisperEngine) -> None:
        self._engine = engine
        self._recorder = AudioRecorder()
        self.is_recording = False
        self._active_language = "en"
        self._active_model_size = "small.en"
        self._last_toggle = 0.0  # monotonic timestamp — debounce guard
        self._listener = None
        self._queue: queue.Queue = queue.Queue()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

        # Cache hotkey objects — avoids config.load() + getattr on every keypress
        cfg = config.load()
        self._key_en = _key_from_name(cfg["hotkey_english"])
        self._key_nl = _key_from_name(cfg["hotkey_dutch"])

        # Pre-open mic stream so first F13 press is instant
        device_id = cfg.get("device_id")
        try:
            self._recorder.open_stream(device_id)
        except RuntimeError as e:
            print(f"WARNING: Could not pre-open mic: {e}")

    def _handle_press(self, key):
        # Fast reject for non-hotkey presses — no disk I/O
        if key not in (self._key_en, self._key_nl):
            return

        # Debounce: ignore presses within 250ms of last toggle
        now = time.monotonic()
        if now - self._last_toggle < 0.25:
            return
        self._last_toggle = now

        if not self.is_recording:
            self._start_recording(key)
        else:
            self._stop_recording()

    def _start_recording(self, key):
        cfg = config.load()
        self._active_language = "en" if key == self._key_en else "nl"
        device_id = cfg.get("device_id")

        model_key = "model_size_en" if self._active_language == "en" else "model_size_nl"
        self._active_model_size = cfg.get(
            model_key, "small.en" if self._active_language == "en" else "small"
        )

        # Fire chime from RAM (SND_ASYNC returns instantly), then open mic
        _play(_SND_START)

        try:
            self._recorder.start_recording(device_id)
        except RuntimeError as e:
            self.is_recording = False
            print(f"ERROR: {e}")
            return

        self.is_recording = True
        threading.Thread(
            target=self._log_recording_start,
            args=(device_id, self._active_language, self._active_model_size),
            daemon=True,
        ).start()

    def _log_recording_start(self, device_id, lang, model):
        label = "ENGLISH" if lang == "en" else "DUTCH"
        mic_name = sd.query_devices(device_id)["name"] if device_id is not None else "default"
        print(f"RECORDING ({label}) — Model: {model} — Mic: {mic_name}")

    def _stop_recording(self):
        self.is_recording = False
        _play(_SND_STOP)

        # Grab raw buffer — fast, no concat/resample on this thread
        raw = self._recorder.stop_recording_raw()

        self._queue.put({
            "raw": raw,
            "lang": self._active_language,
            "model_size": self._active_model_size,
        })

    # ── background worker ─────────────────────────────────────────────

    def _worker_loop(self) -> None:
        """Continuously process transcription tasks from the queue."""
        while True:
            task = self._queue.get()
            try:
                self._process_task(task)
            finally:
                self._queue.task_done()

    def _process_task(self, task: dict) -> None:
        language   = task["lang"]
        model_size = task["model_size"]

        # Heavy work: concat + resample (deferred from the hotkey thread)
        audio_data = AudioRecorder.process_raw(task["raw"])
        audio_duration = len(audio_data) / SAMPLE_RATE
        if audio_duration < 0.1:
            _play(_SND_DONE)
            return

        print(f"Processing {audio_duration:.1f}s of audio...")
        self._engine.ensure_model(model_size)
        beam_size = config.load().get("beam_size", 2)
        text, transcribe_time = self._engine.transcribe(audio_data, language, beam_size=beam_size)
        if text:
            rtf = audio_duration / transcribe_time if transcribe_time > 0 else 0
            print(f"TRANSCRIBED in {transcribe_time:.2f}s: {text}")
            print(f"  Speed: {rtf:.1f}x faster than real-time")
            output_handler.type_text(text)
            output_handler.log_transcription(text, model_size, transcribe_time)
        _play(_SND_DONE)

    def start(self) -> None:
        self._listener = keyboard.Listener(
            on_press=self._handle_press,
        )
        self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()

    def join(self) -> None:
        if self._listener:
            self._listener.join()
