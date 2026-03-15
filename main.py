"""ScribeVibe — GPU-accelerated push-to-talk transcription."""
import config
from transcriber import WhisperEngine
from interface import HotkeyListener

if __name__ == "__main__":
    cfg = config.load()
    engine = WhisperEngine(model_name=cfg["model_name"])

    listener = HotkeyListener(engine=engine)
    listener.start()

    print(f"\nScribeVibe ready. F13=English  F14=Dutch  Ctrl+C to quit.\n")
    try:
        listener.join()
    except KeyboardInterrupt:
        listener.stop()
        print("\nExiting.")
