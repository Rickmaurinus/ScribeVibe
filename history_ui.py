"""Transcription history viewer for ScribeVibe — QWebEngine edition."""
import json
import re

from PySide6.QtCore import QObject, Signal, Slot, QUrl, QTimer
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWidgets import QMainWindow, QApplication

import output_handler

# Matches: [2026-03-15 12:35:43] [model | 1.23s] text
#      or: [2026-03-15 12:35:43] text  (older log format)
_ENTRY_RE = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]"
    r"(?:\s+\[([^\]]+)\])?"
    r"\s+(.+)$"
)


# ── log parsing ───────────────────────────────────────────────────────

def _parse_log() -> list[dict]:
    """Return [{ts, meta, text}, ...] newest first."""
    entries = []
    try:
        with open(output_handler.LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                m = _ENTRY_RE.match(line)
                if m:
                    entries.append({
                        "ts": m.group(1),
                        "meta": m.group(2) or "",
                        "text": m.group(3),
                    })
    except FileNotFoundError:
        pass
    entries.reverse()
    return entries


# ── JS bridge ─────────────────────────────────────────────────────────

class _HistoryBridge(QObject):
    """Exposed to JavaScript via QWebChannel as 'api'."""
    newEntry = Signal(str)  # JSON string pushed to JS

    @Slot(str, str, str, result=str)
    def delete_entry(self, ts, meta, text):
        output_handler.delete_log_entry(ts, meta, text)
        return json.dumps({"ok": True})

    @Slot(result=str)
    def clear_history(self):
        output_handler.clear_log()
        return json.dumps({"ok": True})

    def push_entry(self, ts: str, meta: str, text: str):
        """Called from any thread — emits signal to JS on the Qt thread."""
        entry = json.dumps({"ts": ts, "meta": meta, "text": text})
        self.newEntry.emit(entry)


# ── Window ────────────────────────────────────────────────────────────

class _HistoryWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ScribeVibe \u2014 History")
        self.resize(760, 580)
        self.setMinimumSize(520, 320)

        self._bridge = _HistoryBridge()
        self._bridge.newEntry.connect(self._push_to_js)

        self._view = QWebEngineView()
        self.setCentralWidget(self._view)

        # Set up web channel
        channel = QWebChannel()
        channel.registerObject("api", self._bridge)
        self._view.page().setWebChannel(channel)

        self._view.setHtml(_load_html(), QUrl("local://scribevibe/"))
        self._view.loadFinished.connect(self._on_load_finished)

        # Register live-update hook
        output_handler.set_log_hook(self._bridge.push_entry)

    @Slot()
    def _on_load_finished(self):
        """Push all existing entries to JS once the page is ready."""
        entries = _parse_log()
        entries_json = json.dumps(entries)
        self._view.page().runJavaScript(f"window.loadEntries({entries_json})")

    @Slot(str)
    def _push_to_js(self, entry_json):
        self._view.page().runJavaScript(f"window.addNewEntry({entry_json})")

    def _mark_dirty(self, ts: str, meta: str, text: str):
        """Lightweight log hook — just flags that entries changed while hidden."""
        _manager._dirty = True

    def closeEvent(self, event):
        event.ignore()
        output_handler.set_log_hook(self._mark_dirty)
        self.hide()


# ── Manager (thread-safe show/hide) ──────────────────────────────────

class _HistoryManager(QObject):
    _show_signal = Signal()

    def __init__(self):
        super().__init__()
        self._window = None
        self._dirty = False
        self._show_signal.connect(self._on_show)

    @Slot()
    def _on_show(self):
        if self._window is not None:
            if self._window.isVisible():
                self._window.raise_()
                self._window.activateWindow()
                return
            # Re-hook live updates and refresh entries only if changed
            output_handler.set_log_hook(self._window._bridge.push_entry)
            if self._dirty:
                self._window._on_load_finished()
                self._dirty = False
            self._window.show()
            self._window.raise_()
            self._window.activateWindow()
            return
        self._window = _HistoryWindow()
        self._window.show()

    def _ensure_window(self):
        """Pre-create the window hidden so Chromium initializes in the background."""
        if self._window is None:
            self._window = _HistoryWindow()
            self._window.hide()
            output_handler.set_log_hook(self._window._mark_dirty)

    def request_show(self):
        """Can be called from any thread."""
        self._show_signal.emit()


_manager: _HistoryManager | None = None


def init():
    """Initialize the history manager. Must be called from the main (Qt) thread."""
    global _manager
    _manager = _HistoryManager()
    QTimer.singleShot(10_000, _manager._ensure_window)


def show_history() -> None:
    """Open the history window (can be called from any thread)."""
    if _manager is not None:
        _manager.request_show()


def _load_html() -> str:
    """Load the history UI HTML from the assets directory."""
    from interface import get_resource_path
    path = get_resource_path("assets/history.html")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
