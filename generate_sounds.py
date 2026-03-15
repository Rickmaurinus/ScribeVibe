"""Run this once to generate placeholder beep sounds in the assets/ directory."""
import numpy as np
from scipy.io.wavfile import write

SAMPLE_RATE = 44100


def make_beep(freq: float, duration: float, volume: float = 0.4) -> np.ndarray:
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    wave = volume * np.sin(2 * np.pi * freq * t)
    # Short fade-out to avoid click
    fade = int(SAMPLE_RATE * 0.02)
    wave[-fade:] *= np.linspace(1, 0, fade)
    return (wave * 32767).astype(np.int16)


def make_double_beep(f1: float, f2: float, duration: float, gap: float = 0.05) -> np.ndarray:
    b1 = make_beep(f1, duration)
    silence = np.zeros(int(SAMPLE_RATE * gap), dtype=np.int16)
    b2 = make_beep(f2, duration)
    return np.concatenate([b1, silence, b2])


# start.wav — bright high beep (recording begins)
write("assets/start.wav", SAMPLE_RATE, make_beep(freq=880, duration=0.12))

# stop.wav — lower soft beep (recording ends)
write("assets/stop.wav", SAMPLE_RATE, make_beep(freq=440, duration=0.12))

# done.wav — two-tone ascending chime (transcription ready)
write("assets/done.wav", SAMPLE_RATE, make_double_beep(f1=660, f2=990, duration=0.1))

print("Generated: assets/start.wav, assets/stop.wav, assets/done.wav")
