"""Always-on audio capture — stream stays open, recording toggles a flag."""
import numpy as np
import sounddevice as sd
import soxr

TARGET_SAMPLE_RATE = 16000   # Whisper expects 16 kHz
CHANNELS = 1
DTYPE = "float32"
SAMPLE_RATE = TARGET_SAMPLE_RATE  # public alias

FALLBACK_RATE = 48000


class AudioRecorder:
    """Keeps the mic stream open permanently; start/stop just flips a flag."""

    def __init__(self) -> None:
        self._buffer: list[np.ndarray] = []
        self._capturing = False
        self._stream: sd.InputStream | None = None
        self._stream_rate: int = TARGET_SAMPLE_RATE
        self._needs_resample: bool = False
        self._current_device: int | None = None
        self._live_callback = None  # called with each audio chunk while capturing

    # ── stream lifecycle (called once, or when mic changes) ──────────

    def open_stream(self, device_id: int | None = None) -> None:
        """Open the mic stream and leave it running. Call once at startup."""
        if self._stream is not None and self._current_device == device_id:
            return  # already open on the right device

        self._close_stream()
        self._current_device = device_id

        def _callback(indata, frames, time_info, status):
            if self._capturing:
                chunk = indata.copy()
                self._buffer.append(chunk)
                if self._live_callback is not None:
                    try:
                        self._live_callback(chunk)
                    except Exception:
                        pass

        # Try native 16 kHz first — lets PortAudio handle resampling in hardware
        try:
            self._stream = sd.InputStream(
                samplerate=TARGET_SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                device=device_id,
                callback=_callback,
            )
            self._stream.start()
            self._stream_rate = TARGET_SAMPLE_RATE
            self._needs_resample = False
            print(f"Mic stream opened at native 16 kHz — no resampling needed.")
            return
        except (sd.PortAudioError, ValueError):
            # Device doesn't support 16 kHz — fall back to 48 kHz + soxr
            if self._stream is not None:
                try:
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

        # Fallback: open at 48 kHz, resample later with soxr
        device_info = sd.query_devices(
            device_id if device_id is not None else sd.default.device[0]
        )
        self._stream = sd.InputStream(
            samplerate=FALLBACK_RATE,
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

        self._stream_rate = FALLBACK_RATE
        self._needs_resample = True
        print(f"Mic stream opened at 48 kHz — will resample to 16 kHz via soxr.")

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
            "stream_rate": self._stream_rate,
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

        return soxr.resample(audio, raw["stream_rate"], TARGET_SAMPLE_RATE).astype(DTYPE)
