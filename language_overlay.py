"""Full-screen fading language indicator overlay (PySide6)."""

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPauseAnimation,
    QPropertyAnimation,
    QSequentialAnimationGroup,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

_FONT_FAMILY = "Segoe UI Semibold"
_FONT_SIZE = 48
_HOLD_MS = 400  # hold at full opacity before fading
_FADE_DURATION_MS = 1500  # total fade-out time
_START_OPACITY = 0.92


class _Bridge(QObject):
    show_signal = Signal(str)


class _OverlayWidget(QWidget):
    """Frameless overlay that shows a language name and fades out."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("background: #1a1a1a; border-radius: 8px;")

        screen = QApplication.primaryScreen()
        dpi = screen.logicalDotsPerInch() if screen else 96.0
        scale = dpi / 96.0
        font_size = int(_FONT_SIZE * scale)
        pad_x = int(60 * scale)
        pad_y = int(20 * scale)

        self._label = QLabel("")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("color: #ffffff; background: transparent;")
        font = QFont(_FONT_FAMILY, font_size)
        self._label.setFont(font)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(pad_x, pad_y, pad_x, pad_y)
        layout.addWidget(self._label)

        # Animation group: hold → fade out
        self._group = QSequentialAnimationGroup(self)
        self._pause = QPauseAnimation(_HOLD_MS)
        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setDuration(_FADE_DURATION_MS)
        self._fade.setStartValue(_START_OPACITY)
        self._fade.setEndValue(0.0)
        self._fade.setEasingCurve(QEasingCurve.Type.Linear)
        self._group.addAnimation(self._pause)
        self._group.addAnimation(self._fade)
        self._group.finished.connect(self._on_done)

        self._bridge = _Bridge()
        self._bridge.show_signal.connect(self._do_show)

    @Slot(str)
    def _do_show(self, language: str) -> None:
        self._group.stop()

        text = "English" if language == "en" else "Dutch"
        self._label.setText(text)
        self.adjustSize()

        # Center on primary screen
        screen = self.screen() or QApplication.primaryScreen()
        if screen:
            geom = screen.availableGeometry()
            x = geom.x() + (geom.width() - self.width()) // 2
            y = geom.y() + (geom.height() - self.height()) // 2
            self.move(x, y)

        self.setWindowOpacity(_START_OPACITY)
        super().show()
        self.raise_()
        self._group.start()

    @Slot()
    def _on_done(self) -> None:
        self.hide()


class LanguageOverlay:
    """Shows a large language name centered on screen, then fades out.

    Public API matches the original tkinter version so main.py needs no changes.
    """

    def __init__(self) -> None:
        self._widget: _OverlayWidget | None = None

    def start(self) -> None:
        """Create the widget. Must be called after QApplication exists."""
        self._widget = _OverlayWidget()

    def show(self, language: str) -> None:
        """Show the language name and fade out (thread-safe)."""
        if self._widget:
            self._widget._bridge.show_signal.emit(language)

    def stop(self) -> None:
        """Clean up."""
        if self._widget:
            self._widget.hide()
            self._widget = None
