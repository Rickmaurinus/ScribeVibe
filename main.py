"""ScribeVibe — GPU-accelerated push-to-talk transcription."""
import config
from transcriber import WhisperEngine
from interface import HotkeyListener

if __name__ == "__main__":
    cfg = config.load()
    model_en = cfg.get("model_size_en", "small.en")
    model_nl = cfg.get("model_size_nl", "small")

    print(f"English model: {model_en}  |  Dutch model: {model_nl}")

    # Pre-load the English model (most common starting language)
    engine = WhisperEngine(model_size=model_en)

    listener = HotkeyListener(engine=engine)
    listener.start()

    print(f"\nScribeVibe ready. F13=English  F14=Dutch  Ctrl+C to quit.\n")
    try:
        listener.join()
    except KeyboardInterrupt:
        listener.stop()
        print("\nExiting.")
