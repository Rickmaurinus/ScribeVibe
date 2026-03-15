"""Handles text output: paste-at-cursor and logging to file."""
import ctypes
import datetime
import threading
import time
import win32clipboard
import win32con

LOG_FILE = "transcription_log.txt"

_paste_lock = threading.Lock()

_log_hook = None  # optional callback(ts, meta, text) set by history_ui


# ── Keyboard simulation ──────────────────────────────────────────────

VK_CONTROL = 0x11
VK_V = 0x56
KEYEVENTF_KEYUP = 0x0002

_keybd_event = ctypes.windll.user32.keybd_event

def _send_ctrl_v() -> None:
    """Send Ctrl+V via Win32 keybd_event — simple and reliable."""
    _keybd_event(VK_CONTROL, 0, 0, 0)           # Ctrl down
    _keybd_event(VK_V, 0, 0, 0)                 # V down
    _keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)   # V up
    _keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)  # Ctrl up


# ── public API ───────────────────────────────────────────────────────

def set_log_hook(callback) -> None:
    global _log_hook
    _log_hook = callback


def _wait_clipboard_ready(expected: str, timeout_ms: int = 50) -> None:
    """Poll until clipboard contains the expected text, or timeout."""
    deadline = time.perf_counter() + timeout_ms / 1000
    while time.perf_counter() < deadline:
        try:
            win32clipboard.OpenClipboard()
            data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()
            if data == expected:
                return
        except Exception:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
        time.sleep(0.002)


def type_text(text: str) -> None:
    """Paste text at the current cursor position via clipboard + Ctrl+V."""
    with _paste_lock:
        content = text.strip() + " "
        copy_to_hidden_clipboard(content)
        _wait_clipboard_ready(content)
        _send_ctrl_v()


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
