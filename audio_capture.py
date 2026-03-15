"""Background audio capture using sounddevice."""
import math
import queue
import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly

TARGET_SAMPLE_RATE = 16000   # Whisper expects 16 kHz
CHANNELS = 1
DTYPE = "float32"

# Keep SAMPLE_RATE as an alias so other modules that import it still work
SAMPLE_RATE = TARGET_SAMPLE_RATE


class AudioRecorder:
    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._stream: sd.InputStream | None = None
        self._native_rate: int = TARGET_SAMPLE_RATE

    def start_recording(self, device_id: int | None = None) -> None:
        """Open an input stream at the device's native rate and buffer chunks."""
        while not self._queue.empty():
            self._queue.get_nowait()

        # Use the device's native sample rate to avoid PortAudio rejection
        device_info = sd.query_devices(device_id if device_id is not None else sd.default.device[0])
        self._native_rate = int(device_info["default_samplerate"])

        def _callback(indata, frames, time, status):
            self._queue.put(indata.copy())

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
        """Stop stream, drain queue, resample to 16 kHz, return flat array."""
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        chunks = []
        while not self._queue.empty():
            chunks.append(self._queue.get_nowait())

        if not chunks:
            return np.zeros(0, dtype=DTYPE)

        audio = np.concatenate(chunks, axis=0).flatten()

        if self._native_rate == TARGET_SAMPLE_RATE:
            return audio

        # Resample: find GCD to keep up/down integers small
        gcd = math.gcd(TARGET_SAMPLE_RATE, self._native_rate)
        up = TARGET_SAMPLE_RATE // gcd
        down = self._native_rate // gcd
        resampled = resample_poly(audio, up, down).astype(DTYPE)
        return resampled
