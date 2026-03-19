"""
Global hotkey listener and audio feedback for ScribeVibe.

Hotkeys:
  Insert         — toggle recording
  Shift+Insert   — switch language (English ↔ Dutch)
  Escape         — abort recording and discard audio

"Wait & Blitz": record the full utterance, transcribe on stop, type the result.
"""
import ctypes
import ctypes.wintypes as wt
import logging
import os
import queue
import sys
import threading
import time
import winsound

import numpy as np
import sounddevice as sd

import config

logger = logging.getLogger(__name__)
import output_handler
from audio_capture import AudioRecorder, SAMPLE_RATE
from transcriber import WhisperEngine


# ── resource path (PyInstaller-compatible) ──────────────────────────

def get_resource_path(relative_path: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


# ── audio feedback — native async playback ───────────────────────────

def _play(path: str) -> None:
    """Play a WAV file asynchronously — returns instantly, no threads needed."""
    winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)


# ── hotkey listener ─────────────────────────────────────────────────

class HotkeyListener:
    """
    Toggle-based hotkey listener.

    First press  → start recording (plays start.wav)
    Second press → stop, transcribe, type, play done.wav
    """

    def __init__(self, engine: WhisperEngine, indicator=None,
                 language_overlay=None, transcribing_indicator=None,
                 notify_fn=None) -> None:
        self._engine = engine
        self._indicator = indicator
        self._language_overlay = language_overlay
        self._transcribing_indicator = transcribing_indicator
        self._notify_fn = notify_fn
        self._recorder = AudioRecorder()
        self.is_recording = False
        self._active_language = "en"
        self._active_model_size = "small.en"
        self._last_toggle = 0.0  # monotonic timestamp — debounce guard
        self._queue: queue.Queue = queue.Queue()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

        _cfg = config.load()
        self._snd_start = get_resource_path(_cfg["sound_start"])
        self._snd_stop  = get_resource_path(_cfg["sound_stop"])
        self._snd_done  = get_resource_path(_cfg["sound_done"])
        for _p in (self._snd_start, self._snd_stop, self._snd_done):
            try:
                with open(_p, "rb") as _f:
                    _f.read()
            except OSError:
                pass

        # Pre-open mic stream so first Insert press is instant
        cfg = config.load()
        device_id = cfg.get("device_id")
        try:
            self._recorder.open_stream(device_id)
        except RuntimeError as e:
            logger.warning("Could not pre-open mic: %s", e)

    # ── Insert / Shift+Insert — Win32 low-level hook with suppression ──

    def _insert_toggle(self) -> None:
        """Called from the Win32 hook when Insert is pressed."""
        now = time.monotonic()
        if now - self._last_toggle < 0.25:
            return
        self._last_toggle = now

        if not self.is_recording:
            self._start_recording()
        else:
            self._stop_recording()

    def _pause_switch_language(self) -> None:
        """Called from the Win32 hook when Pause is pressed.
        Toggles between English and Dutch, shows overlay, preloads model."""
        # Don't switch while recording
        if self.is_recording:
            return

        cfg = config.load()
        if self._active_language == "en":
            self._active_language = "nl"
            model_key = "model_size_nl"
            fallback = "small"
        else:
            self._active_language = "en"
            model_key = "model_size_en"
            fallback = "small.en"

        self._active_model_size = cfg.get(model_key, fallback)

        label = "ENGLISH" if self._active_language == "en" else "DUTCH"
        logger.info("Language switched to %s — Model: %s", label, self._active_model_size)

        # Show fading overlay
        if self._language_overlay:
            self._language_overlay.show(self._active_language)

        # Preload model in background
        threading.Thread(
            target=self._engine.ensure_model,
            args=(self._active_model_size,),
            daemon=True,
        ).start()

    def _install_key_hooks(self) -> None:
        """Low-level keyboard hook that intercepts Insert (record) and
        Shift+Insert (switch language), suppressing their default behaviour."""
        VK_INSERT = 0x2D
        VK_ESCAPE = 0x1B
        VK_SHIFT = 0xA0   # VK_LSHIFT — used by GetAsyncKeyState

        _u32 = ctypes.WinDLL("user32", use_last_error=True)

        # Define all types using only ctypes primitives (no wintypes aliases)
        LRESULT = ctypes.c_ssize_t
        WPARAM = ctypes.c_size_t
        LPARAM = ctypes.c_ssize_t

        LLKeyboardProc = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, WPARAM, LPARAM)

        _u32.SetWindowsHookExW.argtypes = [
            ctypes.c_int, LLKeyboardProc, ctypes.c_void_p, ctypes.c_ulong,
        ]
        _u32.SetWindowsHookExW.restype = ctypes.c_void_p

        _u32.CallNextHookEx.argtypes = [
            ctypes.c_void_p, ctypes.c_int, WPARAM, LPARAM,
        ]
        _u32.CallNextHookEx.restype = LRESULT

        _u32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        _u32.UnhookWindowsHookEx.restype = ctypes.c_int

        _u32.GetMessageW.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
        ]
        _u32.GetMessageW.restype = ctypes.c_int

        _u32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        _u32.GetAsyncKeyState.restype = ctypes.c_short

        listener_self = self  # prevent closure issues

        def _shift_is_down():
            """Check if either Shift key is currently held."""
            return (_u32.GetAsyncKeyState(0xA0) & 0x8000) or \
                   (_u32.GetAsyncKeyState(0xA1) & 0x8000)

        def hook_proc(nCode, wParam, lParam):
            try:
                if nCode >= 0:
                    # vkCode is the first DWORD in KBDLLHOOKSTRUCT
                    vk = ctypes.cast(lParam, ctypes.POINTER(ctypes.c_ulong)).contents.value
                    is_down = wParam in (0x0100, 0x0104)  # WM_KEYDOWN / WM_SYSKEYDOWN

                    if vk == VK_INSERT:
                        if is_down and _shift_is_down():
                            # Shift+Insert → switch language
                            listener_self._pause_switch_language()
                            return 1  # suppress
                        elif is_down and not _shift_is_down():
                            # Insert alone → toggle recording
                            listener_self._insert_toggle()
                        return 1  # suppress Insert in all cases

                    if vk == VK_ESCAPE:
                        if is_down and listener_self.is_recording:
                            # Escape while recording → abort and discard
                            listener_self._abort_recording()
                            return 1  # suppress only when recording
            except Exception:
                logger.exception("Error in keyboard hook proc — passing event through")
            return _u32.CallNextHookEx(None, nCode, wParam, lParam)

        # prevent GC of the callback
        self._hook_proc_ref = LLKeyboardProc(hook_proc)

        def _run_hook():
            hook = _u32.SetWindowsHookExW(13, self._hook_proc_ref, None, 0)
            if not hook:
                err = ctypes.get_last_error()
                logger.warning("Key hook failed (error %d)", err)
                return
            logger.info("Key hooks installed — Insert (record) + Shift+Insert (switch language) + Escape (abort).")
            msg = (ctypes.c_byte * 48)()  # MSG struct buffer
            while _u32.GetMessageW(msg, None, 0, 0) > 0:
                pass
            _u32.UnhookWindowsHookEx(hook)

        threading.Thread(target=_run_hook, daemon=True).start()

    def _start_recording(self):
        cfg = config.load()
        device_id = cfg.get("device_id")

        model_key = "model_size_en" if self._active_language == "en" else "model_size_nl"
        self._active_model_size = cfg.get(
            model_key, "small.en" if self._active_language == "en" else "small"
        )

        # Fire chime from RAM (SND_ASYNC returns instantly), then open mic
        _play(self._snd_start)

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
            # Feed live audio chunks to the waveform visualizer
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
            target=self._log_recording_start,
            args=(device_id, self._active_language, self._active_model_size),
            daemon=True,
        ).start()

    def _log_recording_start(self, device_id, lang, model):
        label = "ENGLISH" if lang == "en" else "DUTCH"
        mic_name = sd.query_devices(device_id)["name"] if device_id is not None else "default"
        logger.info("RECORDING (%s) — Model: %s — Mic: %s", label, model, mic_name)

    def _stop_recording(self):
        self.is_recording = False
        self._recorder.set_live_callback(None)
        if self._indicator:
            self._indicator.hide()
        _play(self._snd_stop)

        # Grab raw buffer — fast, no concat/resample on this thread
        raw = self._recorder.stop_recording_raw()

        self._queue.put({
            "raw": raw,
            "lang": self._active_language,
            "model_size": self._active_model_size,
        })

    def _abort_recording(self) -> None:
        """Stop recording and discard audio — no transcription queued."""
        self.is_recording = False
        self._recorder.set_live_callback(None)
        if self._indicator:
            self._indicator.hide()
        self._recorder.stop_recording_raw()  # discard captured audio
        _play(self._snd_stop)
        logger.info("Recording aborted.")

    # ── background worker ─────────────────────────────────────────────

    def _worker_loop(self) -> None:
        """Continuously process transcription tasks from the queue."""
        while True:
            task = self._queue.get()
            try:
                self._process_task(task)
            except Exception as e:
                msg = f"Unexpected error: {e}"
                logger.error("Transcription worker error: %s", msg)
                if self._notify_fn:
                    self._notify_fn(msg, title="ScribeVibe — Error")
                if self._transcribing_indicator:
                    self._transcribing_indicator.hide()
            finally:
                self._queue.task_done()

    def _process_task(self, task: dict) -> None:
        language   = task["lang"]
        model_size = task["model_size"]

        # Heavy work: concat + resample (deferred from the hotkey thread)
        audio_data = AudioRecorder.process_raw(task["raw"])

        audio_duration = len(audio_data) / SAMPLE_RATE
        if audio_duration < 0.1:
            _play(self._snd_done)
            return

        logger.info("Processing %.1fs of audio...", audio_duration)
        if self._transcribing_indicator:
            self._transcribing_indicator.show()
        try:
            self._engine.ensure_model(model_size)
            beam_size = config.load().get("beam_size", 2)
            text, transcribe_time = self._engine.transcribe(audio_data, language, beam_size=beam_size)
        except Exception as e:
            if self._transcribing_indicator:
                self._transcribing_indicator.hide()
            msg = f"Transcription error: {e}"
            logger.error(msg)
            if self._notify_fn:
                self._notify_fn(msg, title="ScribeVibe — Error")
            _play(self._snd_done)
            return

        if self._transcribing_indicator:
            self._transcribing_indicator.hide()

        if text:
            rtf = audio_duration / transcribe_time if transcribe_time > 0 else 0
            logger.info("TRANSCRIBED in %.2fs (%.1fx real-time): %s", transcribe_time, rtf, text)
            output_handler.type_text(text)
            output_handler.log_transcription(text, model_size, transcribe_time)
        else:
            logger.warning("Transcription returned empty — speech not detected.")
            if self._notify_fn:
                self._notify_fn("Nothing transcribed — no speech detected.")
        _play(self._snd_done)

    def start(self) -> None:
        self._install_key_hooks()

    def stop(self) -> None:
        pass  # Win32 hook runs on a daemon thread and cleans up on exit

    def join(self) -> None:
        pass
