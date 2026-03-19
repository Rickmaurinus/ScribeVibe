"""Settings dialog for ScribeVibe — hotkey configuration."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

import config
from key_hook import KeyHook

logger = logging.getLogger(__name__)

# ── Qt key → Win32 VK code mapping ───────────────────────────────────

_QT_TO_VK: dict[Qt.Key, int] = {
    Qt.Key.Key_Escape: 0x1B,
    Qt.Key.Key_Tab: 0x09,
    Qt.Key.Key_Backspace: 0x08,
    Qt.Key.Key_Return: 0x0D,
    Qt.Key.Key_Enter: 0x0D,
    Qt.Key.Key_Insert: 0x2D,
    Qt.Key.Key_Delete: 0x2E,
    Qt.Key.Key_Home: 0x24,
    Qt.Key.Key_End: 0x23,
    Qt.Key.Key_PageUp: 0x21,
    Qt.Key.Key_PageDown: 0x22,
    Qt.Key.Key_Pause: 0x13,
    Qt.Key.Key_Print: 0x2C,
    Qt.Key.Key_CapsLock: 0x14,
    Qt.Key.Key_ScrollLock: 0x91,
    Qt.Key.Key_NumLock: 0x90,
}

# F1–F24
for _i in range(1, 25):
    _fkey = getattr(Qt.Key, f"Key_F{_i}", None)
    if _fkey is not None:
        _QT_TO_VK[_fkey] = 0x70 + _i - 1

# A–Z  (Qt.Key.Key_A == 65 == VK_A)
for _c in range(ord("A"), ord("Z") + 1):
    _QT_TO_VK[Qt.Key(_c)] = _c

# 0–9  (Qt.Key.Key_0 == 0x30 == VK_0)
for _n in range(10):
    _QT_TO_VK[Qt.Key(0x30 + _n)] = 0x30 + _n

# ── VK code → human-readable name ────────────────────────────────────

_VK_NAMES: dict[int, str] = {
    0x1B: "Escape",
    0x09: "Tab",
    0x08: "Backspace",
    0x0D: "Enter",
    0x2D: "Insert",
    0x2E: "Delete",
    0x24: "Home",
    0x23: "End",
    0x21: "Page Up",
    0x22: "Page Down",
    0x13: "Pause",
    0x2C: "Print Screen",
    0x14: "Caps Lock",
    0x91: "Scroll Lock",
    0x90: "Num Lock",
}

for _i in range(1, 25):
    _VK_NAMES[0x70 + _i - 1] = f"F{_i}"

for _c in range(ord("A"), ord("Z") + 1):
    _VK_NAMES[_c] = chr(_c)

for _n in range(10):
    _VK_NAMES[0x30 + _n] = str(_n)

_MODIFIER_KEYS = frozenset({
    Qt.Key.Key_Shift,
    Qt.Key.Key_Control,
    Qt.Key.Key_Alt,
    Qt.Key.Key_Meta,
    Qt.Key.Key_AltGr,
})


def _hotkey_label(hk: dict) -> str:
    """Return a human-readable label like 'Shift+Insert' for a hotkey dict."""
    parts = []
    if hk.get("ctrl"):
        parts.append("Ctrl")
    if hk.get("alt"):
        parts.append("Alt")
    if hk.get("shift"):
        parts.append("Shift")
    parts.append(_VK_NAMES.get(hk.get("vk", 0), f"0x{hk.get('vk', 0):02X}"))
    return "+".join(parts)


# ── Key capture button ────────────────────────────────────────────────


class _KeyCaptureButton(QPushButton):
    """Button that displays the current hotkey and captures a new one when clicked."""

    _IDLE_STYLE = ""
    _CAPTURE_STYLE = "background-color: #fff3cd; color: #856404; font-style: italic;"

    def __init__(self, hotkey: dict, hook: KeyHook | None = None, parent=None) -> None:
        super().__init__(parent)
        self._hotkey = dict(hotkey)
        self._hook = hook
        self._capturing = False
        self._update_label()
        self.setMinimumWidth(160)
        self.clicked.connect(self._start_capture)

    @property
    def hotkey(self) -> dict:
        return dict(self._hotkey)

    def _update_label(self) -> None:
        self.setText(_hotkey_label(self._hotkey))
        self.setStyleSheet(self._IDLE_STYLE)

    def _start_capture(self) -> None:
        if self._hook:
            self._hook.pause()
        self._capturing = True
        self.setText("Press a key…  (Esc to cancel)")
        self.setStyleSheet(self._CAPTURE_STYLE)
        self.grabKeyboard()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._capturing:
            super().keyPressEvent(event)
            return

        key = Qt.Key(event.key())

        # Ignore bare modifier presses — wait for the main key
        if key in _MODIFIER_KEYS:
            return

        # Escape cancels without changing the binding
        if key == Qt.Key.Key_Escape:
            self._capturing = False
            self.releaseKeyboard()
            if self._hook:
                self._hook.resume()
            self._update_label()
            return

        vk = _QT_TO_VK.get(key)
        if vk is None:
            # Unsupported key — keep waiting rather than silently accepting
            return

        mods = event.modifiers()
        self._hotkey = {
            "vk": vk,
            "shift": bool(mods & Qt.KeyboardModifier.ShiftModifier),
            "ctrl": bool(mods & Qt.KeyboardModifier.ControlModifier),
            "alt": bool(mods & Qt.KeyboardModifier.AltModifier),
        }
        self._capturing = False
        self.releaseKeyboard()
        if self._hook:
            self._hook.resume()
        self._update_label()

    def focusOutEvent(self, event) -> None:
        if self._capturing:
            self._capturing = False
            self.releaseKeyboard()
            if self._hook:
                self._hook.resume()
            self._update_label()
        super().focusOutEvent(event)


# ── Settings dialog ───────────────────────────────────────────────────

_DIALOG_STYLE = """
QDialog {
    background-color: #f5f5f5;
}
QLabel#section {
    font-weight: bold;
    font-size: 13px;
    color: #1a1a1a;
}
QLabel {
    color: #1a1a1a;
}
QPushButton {
    padding: 5px 14px;
    border: 1px solid #c0c0c0;
    border-radius: 4px;
    background-color: #ffffff;
    color: #1a1a1a;
}
QPushButton:hover {
    background-color: #e8e8e8;
}
QPushButton#apply {
    background-color: #1DB954;
    color: #ffffff;
    border: none;
    font-weight: bold;
}
QPushButton#apply:hover {
    background-color: #17a348;
}
"""


class SettingsDialog(QDialog):
    def __init__(self, hook: KeyHook, parent=None) -> None:
        super().__init__(parent)
        self._hook = hook

        self.setWindowTitle("ScribeVibe — Settings")
        self.setMinimumWidth(380)
        self.setStyleSheet(_DIALOG_STYLE)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 20, 24, 20)

        # ── Hotkeys section ──
        section_label = QLabel("Hotkeys")
        section_label.setObjectName("section")
        layout.addWidget(section_label)

        hint = QLabel("Click a button, then press the key combination you want to use.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #555; font-size: 11px;")
        layout.addWidget(hint)

        cfg = config.load()
        self._record_btn = _KeyCaptureButton(cfg.get("hotkey_record"), hook=self._hook)
        self._language_btn = _KeyCaptureButton(cfg.get("hotkey_language"), hook=self._hook)

        form = QFormLayout()
        form.setSpacing(10)
        form.setContentsMargins(0, 4, 0, 0)
        form.addRow("Record:", self._record_btn)
        form.addRow("Language switch:", self._language_btn)
        layout.addLayout(form)

        layout.addStretch()

        # ── Buttons ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)

        apply_btn = QPushButton("Apply")
        apply_btn.setObjectName("apply")
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self._apply)

        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(apply_btn)
        layout.addLayout(btn_row)

    def _apply(self) -> None:
        rec_hk = self._record_btn.hotkey
        lang_hk = self._language_btn.hotkey

        cfg = config.load()
        cfg["hotkey_record"] = rec_hk
        cfg["hotkey_language"] = lang_hk
        config.save(cfg)

        self._hook.update_hotkeys(rec_hk, lang_hk)
        logger.info("Settings saved.")
        self.accept()


# ── Public API ────────────────────────────────────────────────────────


def show_settings(hook: KeyHook) -> None:
    """Open the settings dialog (must be called from the Qt main thread)."""
    dialog = SettingsDialog(hook)
    dialog.exec()
