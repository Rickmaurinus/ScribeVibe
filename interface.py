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


# ── audio feedback helpers ──────────────────────────────────────────

def _play(path: str) -> None:
    resolved = get_resource_path(path)
    threading.Thread(
        target=winsound.PlaySound,
        args=(resolved, winsound.SND_FILENAME | winsound.SND_ASYNC),
        daemon=True,
    ).start()


def play_start() -> None:
    _play(config.load()["sound_start"])


def play_stop() -> None:
    _play(config.load()["sound_stop"])


def play_done() -> None:
    _play(config.load()["sound_done"])


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
        self._held: set = set()
        self._listener = None
        self._queue: queue.Queue = queue.Queue()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def _settings(self):
        return config.load()

    def _handle_press(self, key):
        cfg = self._settings()
        key_en = _key_from_name(cfg["hotkey_english"])
        key_nl = _key_from_name(cfg["hotkey_dutch"])

        if key in self._held:
            return
        if key not in (key_en, key_nl):
            return
        self._held.add(key)

        if not self.is_recording:
            self._start_recording(key, key_en, cfg)
        else:
            self._stop_recording()

    def _start_recording(self, key, key_en, cfg):
        self._active_language = "en" if key == key_en else "nl"
        device_id = cfg.get("device_id")

        # Capture target model (actual loading deferred to the worker thread)
        model_key = "model_size_en" if self._active_language == "en" else "model_size_nl"
        self._active_model_size = cfg.get(
            model_key, "small.en" if self._active_language == "en" else "small"
        )

        try:
            self._recorder.start_recording(device_id)
        except RuntimeError as e:
            self.is_recording = False
            print(f"ERROR: {e}")
            return

        self.is_recording = True
        play_start()
        label = "ENGLISH" if self._active_language == "en" else "DUTCH"
        mic_name = sd.query_devices(device_id)["name"] if device_id is not None else "default"
        print(f"RECORDING ({label}) — Model: {self._active_model_size} — Mic: {mic_name}")

    def _stop_recording(self):
        self.is_recording = False
        play_stop()

        audio_data = self._recorder.stop_recording()
        duration = len(audio_data) / SAMPLE_RATE
        print(f"STOPPED — {duration:.1f}s captured — queued for transcription")

        # Enqueue the task; the worker thread handles the rest
        self._queue.put({
            "audio": audio_data,
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
        audio_data = task["audio"]
        language   = task["lang"]
        model_size = task["model_size"]

        self._engine.ensure_model(model_size)
        audio_duration = len(audio_data) / SAMPLE_RATE
        text, transcribe_time = self._engine.transcribe(audio_data, language)
        if text:
            rtf = audio_duration / transcribe_time if transcribe_time > 0 else 0
            print(f"TRANSCRIBED in {transcribe_time:.2f}s: {text}")
            print(f"  Speed: {rtf:.1f}x faster than real-time")
            output_handler.type_text(text)
            output_handler.log_transcription(text, model_size, transcribe_time)
        play_done()

    def _handle_release(self, key):
        self._held.discard(key)

    def start(self) -> None:
        self._listener = keyboard.Listener(
            on_press=self._handle_press,
            on_release=self._handle_release,
        )
        self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()

    def join(self) -> None:
        if self._listener:
            self._listener.join()
