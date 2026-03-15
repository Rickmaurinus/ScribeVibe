"""ScribeVibe — GPU-accelerated push-to-talk transcription (system tray app)."""
import threading

import numpy as np

import config
from transcriber import WhisperEngine
from interface import HotkeyListener
from tray_app import TrayApp


def _warmup(engine: WhisperEngine, model_size: str, tray: TrayApp) -> None:
    """Pre-load model + run a dummy transcription to warm CUDA kernels."""
    engine.ensure_model(model_size)

    # Tiny dummy inference to JIT-compile CUDA kernels
    silence = np.zeros(8000, dtype="float32")  # 0.5s of silence
    engine.transcribe(silence, beam_size=1)

    print(f"Engine warmed up ({model_size}).")
    tray.notify(f"Engine warmed up ({model_size})", "ScribeVibe")


if __name__ == "__main__":
    cfg = config.load()
    model_en = cfg.get("model_size_en", "small.en")
    model_nl = cfg.get("model_size_nl", "small")

    print(f"English model: {model_en}  |  Dutch model: {model_nl}")

    engine = WhisperEngine()

    # Start hotkey listener on a background thread
    listener = HotkeyListener(engine=engine)
    listener.start()

    print(f"\nScribeVibe ready. F13=English  F14=Dutch")
    print("Running in system tray — right-click the icon to switch models.\n")

    # Run the tray icon on the main thread (pystray requires it on Windows)
    tray = TrayApp()

    # Warm up engine in background — tray appears immediately
    threading.Thread(
        target=_warmup, args=(engine, model_en, tray), daemon=True
    ).start()

    try:
        tray.run()  # blocks until Quit is selected
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
        print("Exiting.")
