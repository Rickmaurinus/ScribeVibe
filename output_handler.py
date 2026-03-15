"""Handles text output: typing at cursor and logging to file."""
import datetime
import pyautogui

LOG_FILE = "transcription_log.txt"

# Disable pyautogui's fail-safe (moving mouse to corner) during typing
pyautogui.FAILSAFE = False


def type_text(text: str) -> None:
    """Type text at the current cursor position with a trailing space."""
    pyautogui.write(text + " ", interval=0.005)


def log_transcription(text: str) -> None:
    """Append a timestamped entry to the transcription log file."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {text}\n")
