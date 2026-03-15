"""ScribeVibe — GPU-accelerated push-to-talk transcription."""
__version__ = "1.0.0"

import ctypes
import logging
import sys
import threading

# Enable DPI awareness BEFORE any UI is created — must be first
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import config
from transcriber import WhisperEngine
from interface import HotkeyListener
from language_overlay import LanguageOverlay
from recording_indicator import RecordingIndicator
from tray_app import TrayApp


def _setup_logging() -> None:
    """Configure logging to both console and a rotating log file."""
    from logging.handlers import RotatingFileHandler

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    # File handler — 1 MB max, keep 1 backup
    fh = RotatingFileHandler("scribevibe.log", maxBytes=1_000_000,
                             backupCount=1, encoding="utf-8")
    fh.setFormatter(fmt)
    root_logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root_logger.addHandler(ch)

    # Redirect uncaught exceptions to the log
    def _handle_exception(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logging.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))

    sys.excepthook = _handle_exception


def _warmup(engine: WhisperEngine, tray: TrayApp, model_size: str) -> None:
    """Background: load the default model and run a CUDA warm-up pass."""
    engine.ensure_model(model_size)
    engine.warmup()
    tray.notify("Model loaded & CUDA warm-up done — ready to transcribe!")


if __name__ == "__main__":
    _setup_logging()
    logging.info(f"ScribeVibe v{__version__} starting...")

    cfg = config.load()
    engine = WhisperEngine()

    tray = TrayApp(engine=engine)
    tray_thread = threading.Thread(target=tray.run, daemon=True)
    tray_thread.start()

    # Wire up download notifications
    engine._notify_fn = tray.notify

    indicator = RecordingIndicator()
    indicator.start()

    lang_overlay = LanguageOverlay()
    lang_overlay.start()

    listener = HotkeyListener(engine=engine, indicator=indicator,
                              language_overlay=lang_overlay)
    listener.start()

    # Eager model load + CUDA warm-up in background
    threading.Thread(
        target=_warmup,
        args=(engine, tray, cfg["model_size_en"]),
        daemon=True,
    ).start()

    print(f"\nScribeVibe ready. F13=English  F14=Dutch  Insert=Record  Pause=Switch language  Ctrl+C to quit.\n")
    try:
        listener.join()
    except KeyboardInterrupt:
        listener.stop()
        tray.stop()
        print("\nExiting.")
