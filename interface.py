"""Global hotkey listener for ScribeVibe.

Hotkeys are user-configurable via settings_ui.  Defaults:
  Insert         — toggle recording
  Shift+Insert   — switch language (English ↔ Dutch)
  Escape         — abort recording and discard audio (hardcoded)
"""

import logging

import config
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
        cfg = config.load()
        self._hook = KeyHook(
            on_record_toggle=self._session.toggle,
            on_language_switch=self._session.switch_language,
            on_abort=self._session.abort,
            record_hotkey=cfg.get("hotkey_record"),
            language_hotkey=cfg.get("hotkey_language"),
        )

    @property
    def hook(self) -> KeyHook:
        return self._hook

    @property
    def is_recording(self) -> bool:
        return self._session.is_recording

    def start(self) -> None:
        self._hook.install()

    def stop(self) -> None:
        self._worker.stop()  # drain queue and wait for current task to finish

    def join(self) -> None:
        pass
