"""System tray interface for ScribeVibe (PySide6 QSystemTrayIcon)."""
import io
import sys
import threading
import os
import winreg

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QAction, QActionGroup, QIcon, QPixmap, QImage
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QApplication
from PIL import Image, ImageDraw

import config
from history_ui import show_history
from select_mic import get_clean_mic_list

# ── Auto-start helpers ──────────────────────────────────────────────

_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APP_NAME = "ScribeVibe"


def _get_startup_command() -> str:
    """Return the command to launch ScribeVibe at startup."""
    return f'"{sys.executable}" "{os.path.abspath("main.py")}"'


def _is_autostart_enabled() -> bool:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, _APP_NAME)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def _set_autostart(enabled: bool) -> None:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY, 0, winreg.KEY_SET_VALUE)
        if enabled:
            winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, _get_startup_command())
        else:
            try:
                winreg.DeleteValue(key, _APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except OSError as e:
        print(f"Registry error: {e}")

# ── Model definitions ───────────────────────────────────────────────

EN_MODELS = [
    ("base.en",   "Base (EN)"),
    ("small.en",  "Small (EN)"),
    ("medium.en", "Medium (EN)"),
    ("Systran/faster-distil-whisper-medium.en", "Distil-Medium (EN)"),
    ("Systran/faster-distil-whisper-large-v3", "Distil-Large-v3 (EN)"),
]

NL_MODELS = [
    ("base",      "Base"),
    ("small",     "Small"),
    ("medium",    "Medium"),
    ("deepdml/faster-whisper-large-v3-turbo-ct2", "Large-v3-Turbo"),
]

# ── Menu stylesheet ─────────────────────────────────────────────────

_MENU_STYLE = """
QMenu {
    background-color: #f5f5f5;
    color: #1a1a1a;
    border: 1px solid #d0d0d0;
    border-radius: 8px;
    padding: 6px 0px;
}
QMenu::item {
    padding: 6px 28px 6px 12px;
    border-radius: 4px;
    margin: 1px 6px;
}
QMenu::item:selected {
    background-color: #d8e8f8;
    color: #1a1a1a;
}
QMenu::separator {
    height: 1px;
    background: #d0d0d0;
    margin: 4px 8px;
}
QMenu::indicator {
    width: 14px;
    height: 14px;
    margin-left: 6px;
}
"""


def _pil_to_qicon(img: Image.Image) -> QIcon:
    """Convert a PIL Image to a QIcon."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    qimg = QImage()
    qimg.loadFromData(buf.read())
    return QIcon(QPixmap.fromImage(qimg))


def _generate_icon() -> Image.Image:
    """Create a simple 64x64 tray icon (green microphone circle)."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, 60, 60], fill="#1DB954")
    # Simple mic shape
    draw.rounded_rectangle([24, 14, 40, 38], radius=6, fill="white")
    draw.arc([20, 28, 44, 50], start=0, end=180, fill="white", width=3)
    draw.line([32, 50, 32, 56], fill="white", width=3)
    draw.line([24, 56, 40, 56], fill="white", width=3)
    return img


class _NotifyBridge(QObject):
    """Thread-safe bridge for notifications from worker threads."""
    notify_signal = Signal(str, str)


class TrayApp:
    """System tray icon with model-switching menus (Qt-based)."""

    def __init__(self, engine=None) -> None:
        self._tray: QSystemTrayIcon | None = None
        self._engine = engine
        self._bridge = _NotifyBridge()
        self._bridge.notify_signal.connect(self._do_notify)

    # ── mic switching ───────────────────────────────────────────────

    def _switch_mic(self, device_id: int | None) -> None:
        config.set_device(device_id)

    def _build_mic_menu(self, parent: QMenu) -> QMenu:
        menu = QMenu("Microphone", parent)
        menu.setStyleSheet(_MENU_STYLE)
        group = QActionGroup(menu)
        group.setExclusive(True)

        current = config.load().get("device_id")

        action = QAction("Default", menu)
        action.setCheckable(True)
        action.setChecked(current is None)
        action.triggered.connect(lambda: self._switch_mic(None))
        group.addAction(action)
        menu.addAction(action)

        for device_id, name, _api in get_clean_mic_list():
            a = QAction(name, menu)
            a.setCheckable(True)
            a.setChecked(current == device_id)
            did = device_id  # capture
            a.triggered.connect(lambda checked, d=did: self._switch_mic(d))
            group.addAction(a)
            menu.addAction(a)

        return menu

    # ── model switching ─────────────────────────────────────────────

    def _switch_en(self, model_size: str) -> None:
        old_model = config.load().get("model_size_en")
        config.set_model_size_en(model_size)
        if self._engine and self._engine.current_model == old_model:
            threading.Thread(
                target=self._engine.ensure_model,
                args=(model_size,),
                daemon=True,
            ).start()

    def _switch_nl(self, model_size: str) -> None:
        old_model = config.load().get("model_size_nl")
        config.set_model_size_nl(model_size)
        if self._engine and self._engine.current_model == old_model:
            threading.Thread(
                target=self._engine.ensure_model,
                args=(model_size,),
                daemon=True,
            ).start()

    def _build_en_menu(self, parent: QMenu) -> QMenu:
        menu = QMenu("English Model", parent)
        menu.setStyleSheet(_MENU_STYLE)
        group = QActionGroup(menu)
        group.setExclusive(True)
        current = config.load().get("model_size_en")

        for ms, label in EN_MODELS:
            a = QAction(label, menu)
            a.setCheckable(True)
            a.setChecked(current == ms)
            a.triggered.connect(lambda checked, m=ms: self._switch_en(m))
            group.addAction(a)
            menu.addAction(a)
        return menu

    def _build_nl_menu(self, parent: QMenu) -> QMenu:
        menu = QMenu("Dutch Model", parent)
        menu.setStyleSheet(_MENU_STYLE)
        group = QActionGroup(menu)
        group.setExclusive(True)
        current = config.load().get("model_size_nl")

        for ms, label in NL_MODELS:
            a = QAction(label, menu)
            a.setCheckable(True)
            a.setChecked(current == ms)
            a.triggered.connect(lambda checked, m=ms: self._switch_nl(m))
            group.addAction(a)
            menu.addAction(a)
        return menu

    # ── autostart ──────────────────────────────────────────────────

    def _toggle_autostart(self) -> None:
        _set_autostart(not _is_autostart_enabled())
        if self._autostart_action:
            self._autostart_action.setChecked(_is_autostart_enabled())

    # ── menu builder ─────────────────────────────────────────────────

    def _build_menu(self) -> QMenu:
        menu = QMenu()
        menu.setStyleSheet(_MENU_STYLE)

        menu.addMenu(self._build_mic_menu(menu))
        menu.addSeparator()
        menu.addMenu(self._build_en_menu(menu))
        menu.addMenu(self._build_nl_menu(menu))
        menu.addSeparator()

        history_action = menu.addAction("History...")
        history_action.triggered.connect(lambda: show_history())

        self._autostart_action = QAction("Start with Windows", menu)
        self._autostart_action.setCheckable(True)
        self._autostart_action.setChecked(_is_autostart_enabled())
        self._autostart_action.triggered.connect(self._toggle_autostart)
        menu.addAction(self._autostart_action)

        menu.addSeparator()
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self._quit)

        return menu

    # ── lifecycle ───────────────────────────────────────────────────

    def _quit(self) -> None:
        app = QApplication.instance()
        if app:
            app.quit()

    def setup(self) -> None:
        """Create and show the tray icon. Must be called on the main (Qt) thread."""
        from main import __version__
        icon = _pil_to_qicon(_generate_icon())
        self._tray = QSystemTrayIcon(icon)
        self._tray.setToolTip(f"ScribeVibe v{__version__}")
        self._tray.setContextMenu(self._build_menu())
        self._tray.show()

    @Slot(str, str)
    def _do_notify(self, message: str, title: str) -> None:
        if self._tray:
            self._tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 3000)

    def notify(self, message: str, title: str = "ScribeVibe") -> None:
        """Show a Windows toast notification (thread-safe)."""
        self._bridge.notify_signal.emit(message, title)

    def stop(self) -> None:
        if self._tray:
            self._tray.hide()
