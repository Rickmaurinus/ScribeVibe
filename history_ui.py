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
        with output_handler._file_lock:
            open(output_handler.LOG_FILE, "w").close()
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

        self._view.setHtml(_HTML, QUrl("local://scribevibe/"))
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

    def closeEvent(self, event):
        event.ignore()
        output_handler.set_log_hook(None)
        self.hide()


# ── Manager (thread-safe show/hide) ──────────────────────────────────

class _HistoryManager(QObject):
    _show_signal = Signal()

    def __init__(self):
        super().__init__()
        self._window = None
        self._show_signal.connect(self._on_show)

    @Slot()
    def _on_show(self):
        if self._window is not None:
            if self._window.isVisible():
                self._window.raise_()
                self._window.activateWindow()
                return
            # Re-hook live updates and refresh entries for hidden window
            output_handler.set_log_hook(self._window._bridge.push_entry)
            self._window._on_load_finished()
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
            output_handler.set_log_hook(None)

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


# ── HTML/CSS/JS ───────────────────────────────────────────────────────

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
    --bg: #f5f3ef;
    --card: #ffffff;
    --border: #e8e4de;
    --shadow: #cac5bd;
    --fg: #1a1917;
    --dim: #9e9894;
    --accent: #c96a3c;
    --highlight: #fde68a;
    --danger: #c44;
}

html, body {
    height: 100%;
    font-family: 'Segoe UI', system-ui, sans-serif;
    background: var(--bg);
    color: var(--fg);
    overflow: hidden;
    user-select: none;
}

/* ── Header ────────────────────────────── */
.header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 18px 20px 10px;
    background: var(--bg);
}
.header h1 {
    font-size: 15px;
    font-weight: 700;
}
.btn-clear {
    background: var(--card);
    color: var(--accent);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 3px 10px;
    font-size: 9pt;
    cursor: pointer;
    font-family: inherit;
}
.btn-clear:hover { background: var(--border); }

.divider {
    height: 1px;
    background: var(--border);
    margin: 0 20px;
}

/* ── Search bar ────────────────────────── */
.search-bar {
    display: flex;
    align-items: center;
    margin: 10px 20px 0;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 0 8px;
    transition: border-color 0.15s;
}
.search-bar:focus-within {
    border-color: var(--accent);
}
.search-bar input {
    flex: 1;
    border: none;
    outline: none;
    background: transparent;
    font-size: 10pt;
    font-family: inherit;
    color: var(--fg);
    padding: 8px 4px;
}
.search-bar input::placeholder { color: var(--dim); }
.search-count {
    font-size: 8pt;
    color: var(--dim);
    white-space: nowrap;
    padding: 0 6px;
    user-select: none;
}
.btn-x {
    background: none;
    border: none;
    color: var(--dim);
    font-size: 14pt;
    cursor: pointer;
    padding: 0 4px;
    line-height: 1;
    display: none;
}
.btn-x:hover { color: var(--accent); }

/* ── Entries container ─────────────────── */
.entries {
    flex: 1;
    overflow-y: auto;
    padding: 14px 20px;
    scroll-behavior: smooth;
}

.layout {
    display: flex;
    flex-direction: column;
    height: 100vh;
}

/* ── Card ──────────────────────────────── */
.card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 5px;
    padding: 14px;
    margin-bottom: 10px;
    transition: box-shadow 0.15s;
    animation: fadeIn 0.2s ease-out;
}
.card:hover {
    box-shadow: 3px 3px 6px rgba(0,0,0,0.08);
}
.card-header {
    display: flex;
    align-items: center;
    font-size: 8pt;
    color: var(--dim);
    margin-bottom: 6px;
}
.card-ts { user-select: none; }
.card-meta {
    color: var(--accent);
    margin-left: 8px;
    user-select: none;
}
.card-actions {
    margin-left: auto;
    display: flex;
    gap: 6px;
}
.card-btn {
    background: none;
    border: none;
    color: var(--dim);
    cursor: pointer;
    font-size: 11pt;
    padding: 0 2px;
    line-height: 1;
}
.card-btn:hover { color: var(--accent); }
.card-btn.delete:hover { color: var(--danger); }
.card-btn.copied { color: var(--accent); }

.card-divider {
    height: 1px;
    background: var(--border);
    margin-bottom: 8px;
}
.card-text {
    font-size: 10pt;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-word;
    user-select: text;
    cursor: text;
}
.card-text mark {
    background: var(--highlight);
    color: var(--fg);
    border-radius: 2px;
    padding: 0 1px;
}

/* ── Empty state ───────────────────────── */
.empty {
    text-align: center;
    color: var(--dim);
    font-size: 11pt;
    padding: 40px 0;
}

/* ── Fade-out for delete ───────────────── */
.card.removing {
    opacity: 0;
    transform: translateY(-10px);
    transition: opacity 0.2s, transform 0.2s;
}

/* ── Fade-in ───────────────────────────── */
@keyframes fadeIn {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0); }
}

/* ── Context menu ──────────────────────── */
.ctx-menu {
    position: fixed;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 4px;
    box-shadow: 2px 4px 12px rgba(0,0,0,0.12);
    padding: 4px 0;
    z-index: 999;
    min-width: 140px;
    display: none;
}
.ctx-menu div {
    padding: 6px 14px;
    font-size: 9pt;
    cursor: pointer;
    user-select: none;
}
.ctx-menu div:hover {
    background: var(--border);
}

/* ── Scrollbar styling ─────────────────── */
.entries::-webkit-scrollbar { width: 8px; }
.entries::-webkit-scrollbar-track { background: var(--bg); }
.entries::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: 4px;
}
.entries::-webkit-scrollbar-thumb:hover { background: var(--shadow); }
</style>
</head>
<body>
<div class="layout">
    <div class="header">
        <h1>Transcription History</h1>
        <button class="btn-clear" id="btnClear">Clear History</button>
    </div>
    <div class="divider"></div>
    <div class="search-bar">
        <input type="text" id="searchInput" placeholder="Search transcriptions…">
        <span class="search-count" id="searchCount"></span>
        <button class="btn-x" id="btnSearchClear">&times;</button>
    </div>
    <div class="entries" id="entries"></div>
</div>

<!-- Custom context menu -->
<div class="ctx-menu" id="ctxMenu">
    <div id="ctxCopySelection">Copy selection</div>
    <div id="ctxCopyAll">Copy all</div>
</div>

<script>
// ── State ──────────────────────────────────
let allEntries = [];
let debounceTimer = null;
let api = null;

const entriesEl   = document.getElementById('entries');
const searchInput = document.getElementById('searchInput');
const searchCount = document.getElementById('searchCount');
const btnX        = document.getElementById('btnSearchClear');
const btnClear    = document.getElementById('btnClear');
const ctxMenu     = document.getElementById('ctxMenu');
let ctxCardText   = '';

// ── Init via QWebChannel ───────────────────
new QWebChannel(qt.webChannelTransport, function(channel) {
    api = channel.objects.api;

    // Listen for live updates pushed from Python
    api.newEntry.connect(function(entryJson) {
        window.addNewEntry(JSON.parse(entryJson));
    });
});

// Called from Python via loadFinished -> runJavaScript
window.loadEntries = function(entries) {
    allEntries = entries || [];
    renderEntries();
};

// ── Search ─────────────────────────────────
searchInput.addEventListener('input', function() {
    btnX.style.display = searchInput.value ? 'block' : 'none';
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(function() { renderEntries(getQuery()); }, 200);
});

searchInput.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        clearSearch();
        searchInput.blur();
    }
});

btnX.addEventListener('click', function() {
    clearSearch();
    searchInput.blur();
});

document.addEventListener('keydown', function(e) {
    if (e.ctrlKey && e.key === 'f') {
        e.preventDefault();
        searchInput.focus();
        searchInput.select();
    }
});

function getQuery() {
    return searchInput.value.trim().toLowerCase();
}

function clearSearch() {
    searchInput.value = '';
    btnX.style.display = 'none';
    renderEntries();
}

function matches(query, entry) {
    return entry.text.toLowerCase().indexOf(query) !== -1
        || entry.ts.toLowerCase().indexOf(query) !== -1
        || entry.meta.toLowerCase().indexOf(query) !== -1;
}

// ── Render ──────────────────────────────────
function renderEntries(query) {
    query = query || '';
    entriesEl.innerHTML = '';
    var filtered = query
        ? allEntries.filter(function(e) { return matches(query, e); })
        : allEntries;

    updateCount(filtered.length, allEntries.length, query);

    if (!filtered.length) {
        entriesEl.innerHTML = '<div class="empty">' +
            (query ? 'No matching transcriptions.' : 'No transcriptions yet.') +
            '</div>';
        return;
    }

    // Batch render with requestAnimationFrame
    var idx = 0;
    var BATCH = 50;
    function loadBatch() {
        var frag = document.createDocumentFragment();
        var end = Math.min(idx + BATCH, filtered.length);
        for (; idx < end; idx++) {
            frag.appendChild(createCard(filtered[idx], query));
        }
        entriesEl.appendChild(frag);
        if (idx < filtered.length) requestAnimationFrame(loadBatch);
    }
    loadBatch();
}

function createCard(entry, query) {
    query = query || '';
    var card = document.createElement('div');
    card.className = 'card';

    var metaHtml = entry.meta
        ? '<span class="card-meta">&middot; ' + esc(entry.meta) + '</span>'
        : '';
    var textHtml = query ? highlight(entry.text, query) : esc(entry.text);

    card.innerHTML =
        '<div class="card-header">' +
            '<span class="card-ts">' + esc(entry.ts) + '</span>' +
            metaHtml +
            '<div class="card-actions">' +
                '<button class="card-btn copy" title="Copy">&#x29C9;</button>' +
                '<button class="card-btn delete" title="Delete">&#x2715;</button>' +
            '</div>' +
        '</div>' +
        '<div class="card-divider"></div>' +
        '<div class="card-text">' + textHtml + '</div>';

    // Copy button
    card.querySelector('.copy').addEventListener('click', function(e) {
        e.stopPropagation();
        copyText(entry.text);
        var btn = card.querySelector('.copy');
        btn.classList.add('copied');
        setTimeout(function() { btn.classList.remove('copied'); }, 1500);
    });

    // Delete button
    card.querySelector('.delete').addEventListener('click', function(e) {
        e.stopPropagation();
        card.classList.add('removing');
        setTimeout(function() {
            if (api) {
                api.delete_entry(entry.ts, entry.meta, entry.text);
            }
            var i = allEntries.indexOf(entry);
            if (i !== -1) allEntries.splice(i, 1);
            card.remove();
            updateCount(
                entriesEl.querySelectorAll('.card').length,
                allEntries.length,
                getQuery()
            );
            if (!entriesEl.querySelector('.card')) {
                var q = getQuery();
                entriesEl.innerHTML = '<div class="empty">' +
                    (q ? 'No matching transcriptions.' : 'No transcriptions yet.') +
                    '</div>';
            }
        }, 200);
    });

    // Right-click context menu on card text
    card.querySelector('.card-text').addEventListener('contextmenu', function(e) {
        e.preventDefault();
        ctxCardText = entry.text;
        var sel = window.getSelection().toString();
        document.getElementById('ctxCopySelection').style.display = sel ? 'block' : 'none';
        ctxMenu.style.left = e.clientX + 'px';
        ctxMenu.style.top  = e.clientY + 'px';
        ctxMenu.style.display = 'block';
    });

    return card;
}

// ── Context menu actions ────────────────────
document.getElementById('ctxCopySelection').addEventListener('click', function() {
    var sel = window.getSelection().toString();
    if (sel) copyText(sel);
    ctxMenu.style.display = 'none';
});

document.getElementById('ctxCopyAll').addEventListener('click', function() {
    copyText(ctxCardText);
    ctxMenu.style.display = 'none';
});

document.addEventListener('click', function() {
    ctxMenu.style.display = 'none';
});

// ── Clear history ──────────────────────────
btnClear.addEventListener('click', function() {
    if (api) api.clear_history();
    allEntries = [];
    clearSearch();
});

// ── Live update (called from Python or signal) ──
window.addNewEntry = function(entry) {
    allEntries.unshift(entry);
    var query = getQuery();
    if (!query || matches(query, entry)) {
        var empty = entriesEl.querySelector('.empty');
        if (empty) empty.remove();
        var card = createCard(entry, query);
        entriesEl.prepend(card);
    }
    updateCount(
        entriesEl.querySelectorAll('.card').length,
        allEntries.length,
        query
    );
};

// ── Helpers ─────────────────────────────────
function updateCount(filtered, total, query) {
    if (!total) {
        searchCount.textContent = '';
    } else if (query) {
        searchCount.textContent = filtered + ' of ' + total;
    } else {
        searchCount.textContent = String(total);
    }
}

function highlight(text, query) {
    var escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return esc(text).replace(
        new RegExp(escaped, 'gi'),
        function(match) { return '<mark>' + match + '</mark>'; }
    );
}

function esc(str) {
    var d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

function copyText(text) {
    try {
        navigator.clipboard.writeText(text);
    } catch(e) {
        var ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        ta.remove();
    }
}

// ── Click outside cards unfocuses search ────
entriesEl.addEventListener('mousedown', function(e) {
    if (document.activeElement === searchInput && e.target === entriesEl) {
        searchInput.blur();
    }
});
</script>
</body>
</html>
"""
