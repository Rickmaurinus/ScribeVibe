"""Real-time scrolling waveform indicator using PySide6 + PyQtGraph."""

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from languages import LANGUAGES

# ── constants ────────────────────────────────────────────────────────
_BUFFER_LEN = 4000  # samples in the rolling buffer (~0.25s at 16 kHz)
_UPDATE_MS = 30  # refresh interval (~33 fps)
_WIN_W = 420  # window width  (logical px)
_WIN_H = 132  # window height (logical px)
_MARGIN_BOTTOM = 40  # px from bottom of screen
_LINE_WIDTH = 1.5
_LINE_COLOR = "#00e5ff"  # bright cyan
_GRAD_TOP = QColor(0, 229, 255, 90)  # cyan, semi-transparent
_GRAD_MID = QColor(0, 229, 255, 10)  # cyan, nearly transparent
_BG_COLOR = "#0a0a0a"


class _AudioBridge(QObject):
    """Thread-safe bridge: audio callback (any thread) → Qt slot (GUI thread)."""

    chunk_ready = Signal(np.ndarray)
    show_signal = Signal()
    hide_signal = Signal()
    lang_signal = Signal(str)


class WaveformWidget(QWidget):
    """Frameless, transparent, always-on-top waveform overlay."""

    def __init__(self) -> None:
        pg.setConfigOptions(antialias=True)
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool  # hides from taskbar
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(f"background: {_BG_COLOR}; border-radius: 12px;")

        # Rolling buffer
        self._buf = np.zeros(_BUFFER_LEN, dtype=np.float32)
        self._x = np.arange(_BUFFER_LEN, dtype=np.float32)

        # ── layout ───────────────────────────────────────────────────
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(2)

        # Language badge (EN / NL) at the top
        self._lang_label = QLabel("EN")
        self._lang_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        _font = QFont()
        _font.setBold(True)
        _font.setPointSize(11)
        _font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        self._lang_label.setFont(_font)
        self._lang_label.setStyleSheet(f"color: {_LINE_COLOR}; background: transparent; padding-right: 4px;")
        self._lang_label.setFixedHeight(18)
        layout.addWidget(self._lang_label)

        self._pw = pg.PlotWidget()
        self._pw.setBackground(None)  # transparent
        self._pw.setMouseEnabled(False, False)
        self._pw.hideButtons()
        self._pw.setMenuEnabled(False)

        # Hide axes
        for axis in ("left", "bottom", "top", "right"):
            self._pw.getPlotItem().getAxis(axis).setStyle(showValues=False)
            self._pw.getPlotItem().getAxis(axis).setPen(pg.mkPen(None))

        self._pw.setYRange(-1.0, 1.0, padding=0)
        self._pw.setXRange(0, _BUFFER_LEN, padding=0)

        layout.addWidget(self._pw)

        # ── gradient brush for fill ──────────────────────────────────
        grad = QLinearGradient(0, 0, 0, 1)
        grad.setCoordinateMode(QLinearGradient.CoordinateMode.ObjectBoundingMode)
        grad.setColorAt(0.0, _GRAD_TOP)
        grad.setColorAt(1.0, _GRAD_MID)
        fill_brush = QBrush(grad)

        # Upper waveform (positive envelope) with gradient fill
        self._curve_upper = self._pw.plot(
            self._x,
            self._buf,
            pen=pg.mkPen(color=_LINE_COLOR, width=_LINE_WIDTH),
            fillLevel=0,
            fillBrush=fill_brush,
        )

        # Lower mirror (negative envelope) with gradient fill
        grad_lower = QLinearGradient(0, 0, 0, 1)
        grad_lower.setCoordinateMode(QLinearGradient.CoordinateMode.ObjectBoundingMode)
        grad_lower.setColorAt(0.0, _GRAD_MID)
        grad_lower.setColorAt(1.0, _GRAD_TOP)
        fill_brush_lower = QBrush(grad_lower)

        self._curve_lower = self._pw.plot(
            self._x,
            self._buf,
            pen=pg.mkPen(color=_LINE_COLOR, width=_LINE_WIDTH),
            fillLevel=0,
            fillBrush=fill_brush_lower,
        )

        # ── audio bridge ─────────────────────────────────────────────
        self._bridge = _AudioBridge()
        self._bridge.chunk_ready.connect(self._on_chunk)
        self._bridge.show_signal.connect(self._do_show)
        self._bridge.hide_signal.connect(self._do_hide)
        self._bridge.lang_signal.connect(self._do_set_language)

        # ── refresh timer ────────────────────────────────────────────
        self._timer = pg.QtCore.QTimer()
        self._timer.timeout.connect(self._refresh)

        # ── position ─────────────────────────────────────────────────
        self.resize(_WIN_W, _WIN_H)

    # ── public API (called from any thread) ──────────────────────────

    def feed_audio(self, chunk: np.ndarray) -> None:
        """Thread-safe: accepts a chunk from the audio callback."""
        self._bridge.chunk_ready.emit(chunk)

    def set_language(self, lang: str) -> None:
        """Thread-safe: update the language badge before showing."""
        self._bridge.lang_signal.emit(lang)

    def show(self) -> None:
        """Thread-safe show."""
        self._bridge.show_signal.emit()

    def hide(self) -> None:
        """Thread-safe hide."""
        self._bridge.hide_signal.emit()

    # ── slots (always run on the GUI thread) ─────────────────────────

    @Slot()
    def _do_show(self) -> None:
        self._buf[:] = 0
        self._position_on_screen()
        super().show()
        self._timer.start(_UPDATE_MS)

    @Slot()
    def _do_hide(self) -> None:
        self._timer.stop()
        super().hide()

    @Slot(str)
    def _do_set_language(self, lang: str) -> None:
        self._lang_label.setText(LANGUAGES[lang].name)

    # ── internal ─────────────────────────────────────────────────────

    def _position_on_screen(self) -> None:
        screen = self.screen()
        if screen is None:
            return
        geom = screen.availableGeometry()
        x = geom.x() + (geom.width() - self.width()) // 2
        y = geom.y() + geom.height() - self.height() - _MARGIN_BOTTOM
        self.move(x, y)

    @Slot(np.ndarray)
    def _on_chunk(self, chunk: np.ndarray) -> None:
        """Roll new samples into the buffer."""
        flat = chunk.flatten()
        n = len(flat)
        if n >= _BUFFER_LEN:
            self._buf[:] = flat[-_BUFFER_LEN:]
        else:
            self._buf[:-n] = self._buf[n:]
            self._buf[-n:] = flat

    def _refresh(self) -> None:
        """Redraw curves from the current buffer."""
        # Compute an envelope for a cleaner symmetric look:
        # absolute value smoothed slightly, then mirrored.
        env = np.abs(self._buf)
        self._curve_upper.setData(self._x, env)
        self._curve_lower.setData(self._x, -env)


class RecordingIndicator:
    """Drop-in replacement: same start/show/hide/stop API as the old tkinter version."""

    def __init__(self) -> None:
        self._widget: WaveformWidget | None = None

    # Called on the main thread AFTER QApplication exists
    def create_widget(self) -> None:
        self._widget = WaveformWidget()

    def start(self) -> None:
        """No-op — widget creation is deferred to create_widget()."""
        pass

    def show(self, language: str = "en") -> None:
        if self._widget:
            self._widget.set_language(language)
            self._widget.show()

    def hide(self) -> None:
        if self._widget:
            self._widget.hide()

    def feed_audio(self, chunk: np.ndarray) -> None:
        if self._widget:
            self._widget.feed_audio(chunk)

    def stop(self) -> None:
        if self._widget:
            self._widget.hide()
