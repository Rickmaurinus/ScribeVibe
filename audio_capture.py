"""Always-on audio capture — stream stays open, recording toggles a flag."""
import math

import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly

TARGET_SAMPLE_RATE = 16000   # Whisper expects 16 kHz
CHANNELS = 1
DTYPE = "float32"
SAMPLE_RATE = TARGET_SAMPLE_RATE  # public alias


class AudioRecorder:
    """Keeps the mic stream open permanently; start/stop just flips a flag."""

    def __init__(self) -> None:
        self._buffer: list[np.ndarray] = []
        self._capturing = False
        self._stream: sd.InputStream | None = None
        self._native_rate: int = TARGET_SAMPLE_RATE
        self._needs_resample: bool = False
        self._up: int = 1
        self._down: int = 1
        self._current_device: int | None = None

    # ── stream lifecycle (called once, or when mic changes) ──────────

    def open_stream(self, device_id: int | None = None) -> None:
        """Open the mic stream and leave it running. Call once at startup."""
        if self._stream is not None and self._current_device == device_id:
            return  # already open on the right device

        self._close_stream()

        device_info = sd.query_devices(
            device_id if device_id is not None else sd.default.device[0]
        )
        self._native_rate = int(device_info["default_samplerate"])
        self._current_device = device_id

        if self._native_rate == TARGET_SAMPLE_RATE:
            self._needs_resample = False
        else:
            self._needs_resample = True
            gcd = math.gcd(TARGET_SAMPLE_RATE, self._native_rate)
            self._up = TARGET_SAMPLE_RATE // gcd
            self._down = self._native_rate // gcd

        def _callback(indata, frames, time_info, status):
            if self._capturing:
                self._buffer.append(indata.copy())

        self._stream = sd.InputStream(
            samplerate=self._native_rate,
            channels=CHANNELS,
            dtype=DTYPE,
            device=device_id,
            callback=_callback,
        )
        try:
            self._stream.start()
        except sd.PortAudioError as e:
            self._stream.close()
            self._stream = None
            raise RuntimeError(
                f"Cannot open device {device_id} ({device_info['name']}): {e}\n"
                "Run select_mic.py to choose a different microphone."
            ) from e

    def _close_stream(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    # ── recording toggle (instant — just a flag flip) ────────────────

    def start_recording(self, device_id: int | None = None) -> None:
        """Begin capturing audio. Opens stream if needed."""
        # Re-open stream only if device changed or not yet open
        if self._stream is None or self._current_device != device_id:
            self.open_stream(device_id)

        self._buffer.clear()
        self._capturing = True

    def stop_recording_raw(self) -> dict:
        """Stop capturing and return raw buffer — fast, no processing.

        Stream stays open for the next recording.
        """
        self._capturing = False

        raw = {
            "chunks": self._buffer,
            "needs_resample": self._needs_resample,
            "up": self._up,
            "down": self._down,
            "native_rate": self._native_rate,
        }
        self._buffer = []  # swap — worker holds the old reference
        return raw

    def stop_recording(self) -> np.ndarray:
        """Stop capturing, concatenate, resample to 16 kHz, return flat array."""
        return AudioRecorder.process_raw(self.stop_recording_raw())

    @staticmethod
    def process_raw(raw: dict) -> np.ndarray:
        """Concatenate and resample raw chunks to 16 kHz (heavy — call off main thread)."""
        chunks = raw["chunks"]
        if not chunks:
            return np.zeros(0, dtype=DTYPE)

        audio = np.concatenate(chunks, axis=0).flatten()

        if not raw["needs_resample"]:
            return audio

        return resample_poly(audio, raw["up"], raw["down"]).astype(DTYPE)

    @staticmethod
    def vad_trim(audio: np.ndarray, sample_rate: int = TARGET_SAMPLE_RATE,
                 frame_ms: int = 20, threshold_rms: float = 0.01,
                 pad_ms: int = 100) -> np.ndarray | None:
        """Trim leading/trailing silence using RMS energy.

        Returns the trimmed array, or None if the entire clip is silence.
        """
        if len(audio) == 0:
            return None

        frame_len = int(sample_rate * frame_ms / 1000)
        n_frames = len(audio) // frame_len
        if n_frames == 0:
            return None

        # RMS per frame — vectorised
        frames = audio[:n_frames * frame_len].reshape(n_frames, frame_len)
        rms = np.sqrt(np.mean(frames ** 2, axis=1))

        voiced = np.where(rms > threshold_rms)[0]
        if len(voiced) == 0:
            return None  # all silence — drop

        first_sample = voiced[0] * frame_len
        last_sample = (voiced[-1] + 1) * frame_len

        # Safety buffer
        pad_samples = int(sample_rate * pad_ms / 1000)
        start = max(0, first_sample - pad_samples)
        end = min(len(audio), last_sample + pad_samples)

        return audio[start:end]
