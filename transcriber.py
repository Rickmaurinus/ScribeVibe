"""Whisper transcription engine — GPU-accelerated via faster-whisper.

Supports hot-swapping models in VRAM via ensure_model().
"""

import gc
import logging
import os
import threading
import time

import numpy as np
import torch
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)


def _is_model_cached(model_size: str) -> bool:
    """Check if a model is already downloaded locally."""
    # Built-in size names are cached by huggingface_hub
    try:
        cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
        if not os.path.isdir(cache_dir):
            return False
        # Check for the model directory pattern
        for entry in os.listdir(cache_dir):
            model_id = model_size.replace("/", "--")
            if model_id in entry or f"models--{model_id}" in entry:
                return True
        # Built-in short names (small.en, medium, etc.) use Systran repos
        systran_id = f"models--Systran--faster-whisper-{model_size}"
        return os.path.isdir(os.path.join(cache_dir, systran_id))
    except OSError:
        return True  # assume cached on error to avoid false notifications


class WhisperEngine:
    def __init__(self, model_size: str | None = None, notify_fn=None) -> None:
        self._model: WhisperModel | None = None
        self.current_model: str | None = None
        self._lock = threading.Lock()
        self._notify_fn = notify_fn
        if model_size is not None:
            self.ensure_model(model_size)

    def set_notify_fn(self, fn) -> None:
        """Set the callback used to surface download notifications to the UI."""
        self._notify_fn = fn

    def ensure_model(self, model_size: str) -> None:
        """Load *model_size* into VRAM, swapping out the current model if different."""
        with self._lock:
            if model_size == self.current_model:
                return

            if self._model is not None:
                logger.info("Unloading '%s' from GPU...", self.current_model)
                del self._model
                self._model = None
                gc.collect()
                torch.cuda.empty_cache()

            downloading = not _is_model_cached(model_size)
            if downloading:
                msg = f"Downloading model '{model_size}'... this may take a minute."
                logger.info(msg)
                if self._notify_fn:
                    self._notify_fn(msg)

            cached = not downloading
            logger.info("Loading model '%s' onto GPU (int8_float16)...", model_size)
            self._model = WhisperModel(
                model_size,
                device="cuda",
                compute_type="int8_float16",
                local_files_only=cached,
            )
            self.current_model = model_size
            logger.info("Model ready.")

    def warmup(self) -> None:
        """Run a dummy inference to trigger PyTorch/CUDA JIT compilation."""
        with self._lock:
            if self._model is None:
                return
            assert self.current_model is not None
            dummy_audio = np.zeros(8000, dtype=np.float32)  # 0.5s of silence at 16kHz
            logger.info("CUDA warm-up: running dummy inference...")
            start = time.perf_counter()
            multilingual = not self.current_model.endswith(".en")
            kwargs = {"language": "en"} if multilingual else {}
            segments, _ = self._model.transcribe(
                dummy_audio,
                beam_size=1,
                vad_filter=True,
                condition_on_previous_text=False,
                without_timestamps=True,
                **kwargs,
            )
            # Force evaluation of the generator
            for _ in segments:
                pass
            elapsed = time.perf_counter() - start
            logger.info("CUDA warm-up complete in %.2fs — first real transcription will be fast.", elapsed)

    def transcribe(self, audio_array: np.ndarray, language: str = "en", beam_size: int = 2) -> tuple[str, float]:
        """Transcribe a 16 kHz float32 mono array. Returns (text, duration_seconds).

        Acquires the model lock so it safely waits for any in-flight
        ensure_model() call to finish before running inference.
        """
        with self._lock:
            assert self.current_model is not None and self._model is not None
            multilingual = not self.current_model.endswith(".en")
            kwargs = {"language": language} if multilingual else {}
            start_time = time.perf_counter()
            segments, _info = self._model.transcribe(
                audio_array,
                beam_size=beam_size,
                vad_filter=True,
                condition_on_previous_text=False,
                without_timestamps=True,
                **kwargs,
            )
            text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
            duration = time.perf_counter() - start_time
            return text, duration
