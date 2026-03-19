"""Animated three-dot overlay shown while transcription is in progress.

Three dots fly in from the left as a group, hover briefly in the center
(with a left→right chaser), then fly out to the right. The cycle repeats
until hide() is called, at which point the current fly-out completes and
the widget disappears.
"""

from enum import Enum, auto

from PySide6.QtCore import QEasingCurve, QObject, QPoint, QPropertyAnimation, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QWidget

# ── constants ────────────────────────────────────────────────────────
_WIN_W = 114
_WIN_H = 52
_MARGIN_BOTTOM = 40  # matches recording indicator
_BG_COLOR = "#0a0a0a"
_DOT_ACTIVE = "#00e5ff"  # same cyan as waveform
_DOT_DIM = "#0d2a30"     # barely-visible dark teal
_SLIDE_MS = 300          # slide-in / slide-out duration
_HOVER_MS = 400          # how long to pause at centre
_DOT_STEP_MS = 220       # ms per step in the chaser cycle


class _State(Enum):
    IDLE = auto()
    FLYING_IN = auto()
    HOVERING = auto()
    FLYING_OUT = auto()           # will loop back to fly-in
    FLYING_OUT_FINAL = auto()     # will hide after fly-out


class _Bridge(QObject):
    show_signal = Signal()
    hide_signal = Signal()


class TranscribingWidget(QWidget):
    """Frameless overlay: three dots fly in→hover→fly out, looping while transcribing."""

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
        self._state = _State.IDLE

        # Chaser timer — cycles through dots during hover
        self._dot_timer = QTimer()
        self._dot_timer.setInterval(_DOT_STEP_MS)
        self._dot_timer.timeout.connect(self._cycle_dot)

        # Single-shot timer that ends the hover phase
        self._hover_timer = QTimer()
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(_HOVER_MS)
        self._hover_timer.timeout.connect(self._start_fly_out)

        # Single animation object reused for both directions
        self._anim = QPropertyAnimation(self, b"pos")
        self._anim.finished.connect(self._on_anim_done)

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
        """(Re)start the animation from the beginning."""
        self._anim.stop()
        self._hover_timer.stop()
        self._dot_timer.stop()
        self._dot_index = 0
        self._update_dots()
        left, _, _ = self._positions()
        self.move(left)
        super().show()
        self._start_fly_in()

    @Slot()
    def _do_hide(self) -> None:
        """Signal intent to stop. If already flying out, just mark it final."""
        if self._state == _State.IDLE:
            return
        if self._state in (_State.FLYING_OUT, _State.FLYING_OUT_FINAL):
            self._state = _State.FLYING_OUT_FINAL
        else:
            # Interrupt fly-in or hover and exit immediately via fly-out
            self._anim.stop()
            self._hover_timer.stop()
            self._dot_timer.stop()
            self._state = _State.FLYING_OUT_FINAL
            _, _, right = self._positions()
            self._anim.setDuration(_SLIDE_MS)
            self._anim.setEasingCurve(QEasingCurve.Type.InCubic)
            self._anim.setStartValue(self.pos())
            self._anim.setEndValue(right)
            self._anim.start()

    # ── animation helpers ─────────────────────────────────────────────

    def _start_fly_in(self) -> None:
        self._state = _State.FLYING_IN
        left, center, _ = self._positions()
        self._anim.setDuration(_SLIDE_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setStartValue(left)
        self._anim.setEndValue(center)
        self._anim.start()

    def _start_fly_out(self) -> None:
        """Called by hover timer; transitions to looping fly-out."""
        self._dot_timer.stop()
        self._state = _State.FLYING_OUT
        _, center, right = self._positions()
        self._anim.setDuration(_SLIDE_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._anim.setStartValue(center)
        self._anim.setEndValue(right)
        self._anim.start()

    @Slot()
    def _on_anim_done(self) -> None:
        if self._state == _State.FLYING_IN:
            self._state = _State.HOVERING
            self._dot_timer.start()
            self._hover_timer.start()
        elif self._state == _State.FLYING_OUT:
            # Loop — teleport back off-screen left and fly in again
            self._start_fly_in()
        elif self._state == _State.FLYING_OUT_FINAL:
            self._state = _State.IDLE
            self._dot_timer.stop()
            super().hide()

    # ── helpers ───────────────────────────────────────────────────────

    def _positions(self) -> tuple[QPoint, QPoint, QPoint]:
        screen = self.screen() or QApplication.primaryScreen()
        geom = screen.availableGeometry()
        y = geom.y() + geom.height() - self.height() - _MARGIN_BOTTOM
        left = QPoint(geom.x() - self.width() - 20, y)
        center = QPoint(geom.x() + (geom.width() - self.width()) // 2, y)
        right = QPoint(geom.x() + geom.width() + 20, y)
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
        """Must be called on the main thread after QApplication exists."""
        self._widget = TranscribingWidget()

    def show(self) -> None:
        if self._widget:
            self._widget.show()

    def hide(self) -> None:
        if self._widget:
            self._widget.hide()
