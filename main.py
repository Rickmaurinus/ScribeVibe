"""ScribeVibe — GPU-accelerated push-to-talk transcription."""
import threading

import config
from transcriber import WhisperEngine
from interface import HotkeyListener
from tray_app import TrayApp


def _warmup(engine: WhisperEngine, tray: TrayApp, model_size: str) -> None:
    """Background: load the default model and run a CUDA warm-up pass."""
    engine.ensure_model(model_size)
    engine.warmup()
    tray.notify("Model loaded & CUDA warm-up done — ready to transcribe!")


if __name__ == "__main__":
    cfg = config.load()
    engine = WhisperEngine()

    tray = TrayApp(engine=engine)
    tray_thread = threading.Thread(target=tray.run, daemon=True)
    tray_thread.start()

    listener = HotkeyListener(engine=engine)
    listener.start()

    # Eager model load + CUDA warm-up in background
    threading.Thread(
        target=_warmup,
        args=(engine, tray, cfg["model_size_en"]),
        daemon=True,
    ).start()

    print(f"\nScribeVibe ready. F13=English  F14=Dutch  Ctrl+C to quit.\n")
    try:
        listener.join()
    except KeyboardInterrupt:
        listener.stop()
        tray.stop()
        print("\nExiting.")
