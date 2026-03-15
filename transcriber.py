"""Whisper transcription engine — GPU-accelerated via faster-whisper.

Supports hot-swapping models in VRAM via ensure_model().
"""
import gc
import threading
import time

import numpy as np
import torch
from faster_whisper import WhisperModel


class WhisperEngine:
    def __init__(self, model_size: str | None = None) -> None:
        self._model: WhisperModel | None = None
        self.current_model: str | None = None
        self._lock = threading.Lock()
        if model_size is not None:
            self.ensure_model(model_size)

    def ensure_model(self, model_size: str) -> None:
        """Load *model_size* into VRAM, swapping out the current model if different."""
        with self._lock:
            if model_size == self.current_model:
                return

            if self._model is not None:
                print(f"Unloading '{self.current_model}' from GPU...")
                del self._model
                self._model = None
                gc.collect()
                torch.cuda.empty_cache()

            print(f"Loading model '{model_size}' onto GPU (int8_float16)...")
            self._model = WhisperModel(
                model_size, device="cuda", compute_type="int8_float16"
            )
            self.current_model = model_size
            print("Model ready.")

    def warmup(self) -> None:
        """Run a dummy inference to trigger PyTorch/CUDA JIT compilation."""
        with self._lock:
            if self._model is None:
                return
            dummy_audio = np.zeros(8000, dtype=np.float32)  # 0.5s of silence at 16kHz
            print("CUDA warm-up: running dummy inference...")
            start = time.perf_counter()
            multilingual = not self.current_model.endswith(".en")
            kwargs = {"language": "en"} if multilingual else {}
            segments, _ = self._model.transcribe(
                dummy_audio, beam_size=1, vad_filter=True,
                condition_on_previous_text=False, without_timestamps=True,
                **kwargs
            )
            # Force evaluation of the generator
            for _ in segments:
                pass
            elapsed = time.perf_counter() - start
            print(f"CUDA warm-up complete in {elapsed:.2f}s — first real transcription will be fast.")

    def transcribe(self, audio_array: np.ndarray, language: str = "en",
                    beam_size: int = 2) -> tuple[str, float]:
        """Transcribe a 16 kHz float32 mono array. Returns (text, duration_seconds).

        Acquires the model lock so it safely waits for any in-flight
        ensure_model() call to finish before running inference.
        """
        with self._lock:
            multilingual = not self.current_model.endswith(".en")
            kwargs = {"language": language} if multilingual else {}
            start_time = time.perf_counter()
            segments, _info = self._model.transcribe(
                audio_array, beam_size=beam_size, vad_filter=True,
                condition_on_previous_text=False, without_timestamps=True,
                **kwargs
            )
            text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
            duration = time.perf_counter() - start_time
            return text, duration
