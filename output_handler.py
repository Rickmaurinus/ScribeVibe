"""Handles text output: paste-at-cursor and logging to file."""
import datetime
import time
import pyautogui
import win32clipboard
import win32con

LOG_FILE = "transcription_log.txt"

pyautogui.FAILSAFE = False


def type_text(text: str) -> None:
    """Paste text at the current cursor position via clipboard + Ctrl+V."""
    copy_to_hidden_clipboard(text)
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


def log_transcription(text: str) -> None:
    """Append a timestamped entry to the transcription log file."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {text}\n")
