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
from transcribing_indicator import TranscribingIndicator
from tray_app import TrayApp
import history_ui
import output_handler


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

    # PySide6 QApplication must live on the main thread
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)

    history_ui.init()  # must be called after QApplication exists

    cfg = config.load()
    engine = WhisperEngine()

    tray = TrayApp(engine=engine)
    tray.setup()  # Qt tray icon — runs on main thread

    # Wire up download notifications
    engine._notify_fn = tray.notify

    indicator = RecordingIndicator()
    indicator.create_widget()  # must be called after QApplication exists

    transcribing = TranscribingIndicator()
    transcribing.create_widget()

    lang_overlay = LanguageOverlay()
    lang_overlay.start()

    listener = HotkeyListener(engine=engine, indicator=indicator,
                              language_overlay=lang_overlay,
                              transcribing_indicator=transcribing,
                              notify_fn=tray.notify)
    listener.start()

    # Eager model load + CUDA warm-up in background
    threading.Thread(
        target=_warmup,
        args=(engine, tray, cfg["model_size_en"]),
        daemon=True,
    ).start()

    def _shutdown():
        logging.info("Shutting down...")
        listener._recorder._close_stream()
        lang_overlay.stop()
        tray.stop()
        output_handler.set_log_hook(None)
        logging.shutdown()

    app.aboutToQuit.connect(_shutdown)

    print(f"\nScribeVibe ready. Insert=Record  Shift+Insert=Switch language  Escape=Abort  Ctrl+C to quit.\n")

    # Run the Qt event loop on the main thread (required by PySide6)
    sys.exit(app.exec())
