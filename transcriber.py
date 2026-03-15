"""Whisper transcription engine — GPU-accelerated via faster-whisper.

Supports hot-swapping models in VRAM via ensure_model().
"""
import gc

import numpy as np
import torch
from faster_whisper import WhisperModel


class WhisperEngine:
    def __init__(self, model_size: str = "small.en") -> None:
        self._model: WhisperModel | None = None
        self.current_model: str | None = None
        self.ensure_model(model_size)

    def ensure_model(self, model_size: str) -> None:
        """Load *model_size* into VRAM, swapping out the current model if different."""
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

    def transcribe(self, audio_array: np.ndarray, language: str = "en") -> str:
        """Transcribe a 16 kHz float32 mono numpy array. Returns the text string."""
        multilingual = not self.current_model.endswith(".en")
        kwargs = {"language": language} if multilingual else {}
        segments, _info = self._model.transcribe(
            audio_array, beam_size=5, **kwargs
        )
        text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
        return text
