"""Centralised app-data paths for ScribeVibe.

All persistent files live under %APPDATA%\ScribeVibe so the app
works correctly regardless of the working directory.
"""
import os
from pathlib import Path

# %APPDATA%\ScribeVibe — falls back to ~ if APPDATA is unset
APP_DIR: Path = Path(os.environ.get("APPDATA", Path.home())) / "ScribeVibe"
APP_DIR.mkdir(parents=True, exist_ok=True)

SETTINGS_FILE: Path = APP_DIR / "settings.json"
LOG_FILE: Path = APP_DIR / "transcription_log.txt"
APP_LOG: Path = APP_DIR / "scribevibe.log"
