"""Simple background audio capture — no VAD, no threads, just buffer and return."""
import math

import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly

TARGET_SAMPLE_RATE = 16000   # Whisper expects 16 kHz
CHANNELS = 1
DTYPE = "float32"
SAMPLE_RATE = TARGET_SAMPLE_RATE  # public alias


class AudioRecorder:
    """Opens an InputStream, buffers all audio, returns it on stop."""

    def __init__(self) -> None:
        self._buffer: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._native_rate: int = TARGET_SAMPLE_RATE
        self._needs_resample: bool = False
        self._up: int = 1
        self._down: int = 1

    def start_recording(self, device_id: int | None = None) -> None:
        self._buffer.clear()

        device_info = sd.query_devices(
            device_id if device_id is not None else sd.default.device[0]
        )
        self._native_rate = int(device_info["default_samplerate"])

        if self._native_rate == TARGET_SAMPLE_RATE:
            self._needs_resample = False
        else:
            self._needs_resample = True
            gcd = math.gcd(TARGET_SAMPLE_RATE, self._native_rate)
            self._up = TARGET_SAMPLE_RATE // gcd
            self._down = self._native_rate // gcd

        def _callback(indata, frames, time, status):
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

    def stop_recording(self) -> np.ndarray:
        """Stop stream, concatenate buffer, resample to 16 kHz, return flat array."""
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        if not self._buffer:
            return np.zeros(0, dtype=DTYPE)

        audio = np.concatenate(self._buffer, axis=0).flatten()
        self._buffer.clear()

        if not self._needs_resample:
            return audio

        return resample_poly(audio, self._up, self._down).astype(DTYPE)
