"""ScribeVibe — GPU-accelerated push-to-talk transcription (system tray app)."""
import threading

import config
from transcriber import WhisperEngine
from interface import HotkeyListener
from tray_app import TrayApp

if __name__ == "__main__":
    cfg = config.load()
    model_en = cfg.get("model_size_en", "small.en")
    model_nl = cfg.get("model_size_nl", "small")

    print(f"English model: {model_en}  |  Dutch model: {model_nl}")

    # Pre-load the English model
    engine = WhisperEngine(model_size=model_en)

    # Start hotkey listener on a background thread
    listener = HotkeyListener(engine=engine)
    listener.start()

    print(f"\nScribeVibe ready. F13=English  F14=Dutch")
    print("Running in system tray — right-click the icon to switch models.\n")

    # Run the tray icon on the main thread (pystray requires it on Windows)
    tray = TrayApp(engine=engine)
    try:
        tray.run()  # blocks until Quit is selected
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
        print("Exiting.")
