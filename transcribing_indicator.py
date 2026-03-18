"""Animated three-dot overlay shown while transcription is in progress."""
from PySide6.QtCore import Qt, Signal, QObject, Slot, QPropertyAnimation, QEasingCurve, QPoint, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QWidget, QHBoxLayout, QLabel

# ── constants ────────────────────────────────────────────────────────
_WIN_W = 114              # wide enough for three spaced dots
_WIN_H = 52
_MARGIN_BOTTOM = 40       # matches recording indicator
_BG_COLOR = "#0a0a0a"
_DOT_ACTIVE = "#00e5ff"   # same cyan as waveform
_DOT_DIM = "#0d2a30"      # barely-visible dark teal
_SLIDE_MS = 280           # slide-in / slide-out duration
_DOT_STEP_MS = 380        # ms per step in the chaser cycle


class _Bridge(QObject):
    show_signal = Signal()
    hide_signal = Signal()


class TranscribingWidget(QWidget):
    """Frameless overlay: three dots that chase left→right while transcribing."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(f"background: {_BG_COLOR}; border-radius: 12px;")
        self.resize(_WIN_W, _WIN_H)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(8)

        font = QFont()
        font.setPointSize(18)

        self._dots: list[QLabel] = []
        for _ in range(3):
            lbl = QLabel("●")
            lbl.setFont(font)
            lbl.setStyleSheet(f"color: {_DOT_DIM}; background: transparent;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(lbl)
            self._dots.append(lbl)

        self._dot_index = 0

        self._dot_timer = QTimer()
        self._dot_timer.setInterval(_DOT_STEP_MS)
        self._dot_timer.timeout.connect(self._cycle_dot)

        # Slide-in: off-screen left → center
        self._anim_in = QPropertyAnimation(self, b"pos")
        self._anim_in.setDuration(_SLIDE_MS)
        self._anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_in.finished.connect(self._on_slide_in_done)

        # Slide-out: current position → off-screen right
        self._anim_out = QPropertyAnimation(self, b"pos")
        self._anim_out.setDuration(_SLIDE_MS)
        self._anim_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._anim_out.finished.connect(super().hide)

        self._bridge = _Bridge()
        self._bridge.show_signal.connect(self._do_show)
        self._bridge.hide_signal.connect(self._do_hide)

    # ── public API (thread-safe) ──────────────────────────────────────

    def show(self) -> None:
        self._bridge.show_signal.emit()

    def hide(self) -> None:
        self._bridge.hide_signal.emit()

    # ── slots (GUI thread) ────────────────────────────────────────────

    @Slot()
    def _do_show(self) -> None:
        left, center, _ = self._positions()
        self._anim_out.stop()
        self._anim_in.stop()
        self._dot_timer.stop()
        self._dot_index = 0
        self._update_dots()
        self.move(left)
        super().show()
        self._anim_in.setStartValue(left)
        self._anim_in.setEndValue(center)
        self._anim_in.start()

    def _on_slide_in_done(self) -> None:
        self._dot_timer.start()

    @Slot()
    def _do_hide(self) -> None:
        self._dot_timer.stop()
        self._anim_in.stop()
        _, _, right = self._positions()
        self._anim_out.setStartValue(self.pos())
        self._anim_out.setEndValue(right)
        self._anim_out.start()

    # ── helpers ───────────────────────────────────────────────────────

    def _positions(self) -> tuple[QPoint, QPoint, QPoint]:
        screen = self.screen() or QApplication.primaryScreen()
        geom = screen.availableGeometry()
        y = geom.y() + geom.height() - self.height() - _MARGIN_BOTTOM
        left   = QPoint(geom.x() - self.width() - 20, y)
        center = QPoint(geom.x() + (geom.width() - self.width()) // 2, y)
        right  = QPoint(geom.x() + geom.width() + 20, y)
        return left, center, right

    def _update_dots(self) -> None:
        for i, dot in enumerate(self._dots):
            color = _DOT_ACTIVE if i == self._dot_index else _DOT_DIM
            dot.setStyleSheet(f"color: {color}; background: transparent;")

    def _cycle_dot(self) -> None:
        self._dot_index = (self._dot_index + 1) % 3
        self._update_dots()


class TranscribingIndicator:
    """Thin wrapper — mirrors the RecordingIndicator API."""

    def __init__(self) -> None:
        self._widget: TranscribingWidget | None = None

    def create_widget(self) -> None:
        self._widget = TranscribingWidget()

    def show(self) -> None:
        if self._widget:
            self._widget.show()

    def hide(self) -> None:
        if self._widget:
            self._widget.hide()
