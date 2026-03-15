"""
Global hotkey listener and audio feedback for ScribeVibe.

Hotkeys (configurable in config.py / settings.json):
  F13 — toggle recording in English
  F14 — toggle recording in Dutch
"""
import threading
import winsound
import numpy as np
import sounddevice as sd
from pynput import keyboard

import config
import output_handler
from audio_capture import AudioRecorder, SAMPLE_RATE
from transcriber import WhisperEngine


def _play(path: str) -> None:
    """Play a WAV file asynchronously so it never blocks the main thread."""
    threading.Thread(
        target=winsound.PlaySound,
        args=(path, winsound.SND_FILENAME | winsound.SND_ASYNC),
        daemon=True,
    ).start()


def play_start() -> None:
    _play(config.load()["sound_start"])


def play_stop() -> None:
    _play(config.load()["sound_stop"])


def play_done() -> None:
    _play(config.load()["sound_done"])


def _key_from_name(name: str) -> keyboard.Key:
    """Convert a config string like 'f13' to a pynput Key enum member."""
    return getattr(keyboard.Key, name.lower())


class HotkeyListener:
    """
    Toggle-based hotkey listener with integrated transcription.

    F13/F14 first press → start recording (plays start.wav)
    Any hotkey second press → stop recording, transcribe, type output, log
    """

    def __init__(self, engine: WhisperEngine) -> None:
        self._engine = engine
        self._recorder = AudioRecorder()
        self.is_recording = False
        self._active_language = "en"
        self._held: set = set()
        self._listener = None

    def _settings(self):
        return config.load()

    def _handle_press(self, key):
        cfg = self._settings()
        key_en = _key_from_name(cfg["hotkey_english"])
        key_nl = _key_from_name(cfg["hotkey_dutch"])

        # Suppress OS key-repeat
        if key in self._held:
            return
        if key not in (key_en, key_nl):
            return
        self._held.add(key)

        if not self.is_recording:
            self._active_language = "en" if key == key_en else "nl"
            self.is_recording = True
            device_id = cfg.get("device_id")
            try:
                self._recorder.start_recording(device_id)
            except RuntimeError as e:
                self.is_recording = False
                print(f"ERROR: {e}")
                return
            play_start()
            label = "ENGLISH" if self._active_language == "en" else "DUTCH"
            mic_name = sd.query_devices(device_id)["name"] if device_id is not None else "default"
            print(f"STARTED RECORDING ({label}) - Using Mic: {mic_name}")
        else:
            self.is_recording = False
            audio_data = self._recorder.stop_recording()
            play_stop()
            duration = len(audio_data) / SAMPLE_RATE
            print(f"STOPPED RECORDING — captured {duration:.2f}s — transcribing...")
            # Run transcription off the pynput callback thread
            threading.Thread(
                target=self._transcribe_and_output,
                args=(audio_data, self._active_language),
                daemon=True,
            ).start()

    def _transcribe_and_output(self, audio_data: np.ndarray, language: str) -> None:
        text = self._engine.transcribe(audio_data, language)
        print(f"TRANSCRIBED: {text}")
        output_handler.type_text(text)
        output_handler.log_transcription(text)
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
