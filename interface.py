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
from scipy.io.wavfile import write as wav_write
from pynput import keyboard

import config
from audio_capture import AudioRecorder, SAMPLE_RATE


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


DEBUG_WAV = "debug_recording.wav"


def _save_debug_wav(audio: np.ndarray) -> None:
    pcm = (audio * 32767).astype(np.int16)
    wav_write(DEBUG_WAV, SAMPLE_RATE, pcm)
    print(f"DEBUG: saved {DEBUG_WAV}")


def _key_from_name(name: str) -> keyboard.Key:
    """Convert a config string like 'f13' to a pynput Key enum member."""
    return getattr(keyboard.Key, name.lower())


class HotkeyListener:
    """
    Toggle-based hotkey listener.

    First press of a hotkey starts recording; any hotkey press while
    recording is active stops it. on_start receives a language ('en'/'nl');
    on_stop receives the captured audio as a numpy float32 array.
    """

    def __init__(self, on_start=None, on_stop=None):
        self._on_start = on_start
        self._on_stop = on_stop
        self.is_recording = False
        self._held: set = set()   # tracks physically held keys to suppress OS repeat
        self._listener = None
        self._recorder = AudioRecorder()

    def _settings(self):
        return config.load()

    def _handle_press(self, key):
        cfg = self._settings()
        key_en = _key_from_name(cfg["hotkey_english"])
        key_nl = _key_from_name(cfg["hotkey_dutch"])

        # Suppress OS key-repeat: only act on the first press, not held repeats
        if key in self._held:
            return
        if key not in (key_en, key_nl):
            return
        self._held.add(key)

        if not self.is_recording:
            language = "en" if key == key_en else "nl"
            self.is_recording = True
            device_id = self._settings().get("device_id")
            self._recorder.start_recording(device_id)
            play_start()
            label = "ENGLISH" if language == "en" else "DUTCH"
            mic_name = sd.query_devices(device_id)["name"] if device_id is not None else "default"
            print(f"STARTED RECORDING ({label}) - Using Mic: {mic_name}")
            if self._on_start:
                self._on_start(language)
        else:
            self.is_recording = False
            audio_data = self._recorder.stop_recording()
            play_stop()
            print(f"STOPPED RECORDING — captured {len(audio_data) / SAMPLE_RATE:.2f}s of audio")
            _save_debug_wav(audio_data)
            play_done()
            if self._on_stop:
                self._on_stop(audio_data)

    def _handle_release(self, key):
        # Only used to clear the held-key tracker so the next press fires correctly
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
