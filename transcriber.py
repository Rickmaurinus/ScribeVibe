"""Whisper transcription engine — runs on GPU via float16."""
import numpy as np
import torch
from transformers import pipeline


class WhisperEngine:
    def __init__(self, model_name: str = "openai/whisper-base") -> None:
        print(f"Loading model '{model_name}' onto GPU (float16)...")
        self._pipe = pipeline(
            task="automatic-speech-recognition",
            model=model_name,
            device="cuda:0",
            dtype=torch.float16,
        )
        # English-only models (name ends in '.en') don't accept a language arg
        self._multilingual = not model_name.endswith(".en")
        print("Model ready.")

    def transcribe(self, audio_array: np.ndarray, language: str = "en") -> str:
        """Transcribe a 16 kHz float32 mono numpy array. Returns the text string."""
        kwargs = {"generate_kwargs": {"language": language}} if self._multilingual else {}
        result = self._pipe(audio_array, **kwargs)
        return result["text"].strip()
