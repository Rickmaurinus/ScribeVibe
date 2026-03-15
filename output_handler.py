"""Handles text output: paste-at-cursor and logging to file."""
import datetime
import threading
import time
import pyautogui
import win32clipboard
import win32con

LOG_FILE = "transcription_log.txt"

pyautogui.FAILSAFE = False

_paste_lock = threading.Lock()

_log_hook = None  # optional callback(ts, meta, text) set by history_ui


def set_log_hook(callback) -> None:
    global _log_hook
    _log_hook = callback


def type_text(text: str) -> None:
    """Paste text at the current cursor position via clipboard + Ctrl+V."""
    with _paste_lock:
        copy_to_hidden_clipboard(text.strip() + " ")
        time.sleep(0.1)
        pyautogui.hotkey("ctrl", "v")


def copy_to_hidden_clipboard(text: str) -> None:
    """Copy text to clipboard without adding it to Windows Clipboard History."""
    try:
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
        exclude_format = win32clipboard.RegisterClipboardFormat(
            "ExcludeClipboardContentFromMonitorProcessing"
        )
        win32clipboard.SetClipboardData(exclude_format, b'\x00')
    except Exception as e:
        print(f"Clipboard error: {e}")
    finally:
        win32clipboard.CloseClipboard()


def log_transcription(text: str, model_name: str = "", transcription_time: float = 0.0) -> None:
    """Append a timestamped entry with model and timing info to the log file."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    meta = f"{model_name} | {transcription_time:.2f}s"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] [{meta}] {text}\n")
    if _log_hook:
        _log_hook(timestamp, meta, text)
