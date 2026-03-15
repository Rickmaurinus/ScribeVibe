"""Background audio capture using sounddevice."""
import queue
import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "float32"


class AudioRecorder:
    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._stream: sd.InputStream | None = None

    def start_recording(self, device_id: int | None = None) -> None:
        """Open an input stream and start pushing chunks into the queue."""
        # Flush any leftover data from a previous session
        while not self._queue.empty():
            self._queue.get_nowait()

        def _callback(indata, frames, time, status):
            self._queue.put(indata.copy())

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            device=device_id,
            callback=_callback,
        )
        self._stream.start()

    def stop_recording(self) -> np.ndarray:
        """Stop the stream, drain the queue, and return a single audio array."""
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        chunks = []
        while not self._queue.empty():
            chunks.append(self._queue.get_nowait())

        if chunks:
            return np.concatenate(chunks, axis=0).flatten()
        return np.zeros(0, dtype=DTYPE)
