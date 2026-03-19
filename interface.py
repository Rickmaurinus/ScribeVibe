"""Global hotkey listener for ScribeVibe.

Hotkeys:
  Insert         — toggle recording
  Shift+Insert   — switch language (English ↔ Dutch)
  Escape         — abort recording and discard audio
"""

import logging

from key_hook import KeyHook
from recording_session import RecordingSession
from transcriber import WhisperEngine
from transcription_worker import TranscriptionWorker

logger = logging.getLogger(__name__)


class HotkeyListener:
    """Wires KeyHook, RecordingSession, and TranscriptionWorker together."""

    def __init__(
        self,
        engine: WhisperEngine,
        indicator=None,
        language_overlay=None,
        notify_fn=None,
    ) -> None:
        self._worker = TranscriptionWorker(engine, notify_fn=notify_fn)
        self._session = RecordingSession(
            engine=engine,
            indicator=indicator,
            language_overlay=language_overlay,
            notify_fn=notify_fn,
            on_task_ready=self._worker.submit,
        )
        self._hook = KeyHook(
            on_record_toggle=self._session.toggle,
            on_language_switch=self._session.switch_language,
            on_abort=self._session.abort,
        )

    @property
    def is_recording(self) -> bool:
        return self._session.is_recording

    def start(self) -> None:
        self._hook.install()

    def stop(self) -> None:
        pass  # hook runs on a daemon thread and exits with the process

    def join(self) -> None:
        pass
