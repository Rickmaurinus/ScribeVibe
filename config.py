import json
import os
from pathlib import Path

import paths
from languages import LANGUAGES

SETTINGS_FILE = paths.SETTINGS_FILE

DEFAULTS = {
    "device_id": None,
    **{lang.config_key: lang.default_model for lang in LANGUAGES.values()},
    "beam_size": 2,
    "sound_start": "assets/start.wav",
    "sound_stop": "assets/stop.wav",
    "sound_done": "assets/done.wav",
    # Hotkeys — stored as {"vk": <Win32 VK code>, "shift": bool, "ctrl": bool, "alt": bool}
    # Defaults: Insert = record, Shift+Insert = language switch
    "hotkey_record": {"vk": 0x2D, "shift": False, "ctrl": False, "alt": False},
    "hotkey_language": {"vk": 0x2D, "shift": True, "ctrl": False, "alt": False},
}


class Config:
    def __init__(self, settings_file: Path | str = SETTINGS_FILE) -> None:
        self._settings_file = settings_file
        self._cache: dict | None = None
        self._cache_mtime: float = 0.0

    def load(self) -> dict:
        if self._cache is not None:
            try:
                if os.path.getmtime(self._settings_file) == self._cache_mtime:
                    return dict(self._cache)
            except OSError:
                return dict(self._cache)
        return self._load_from_disk()

    def _load_from_disk(self) -> dict:
        if os.path.exists(self._settings_file):
            try:
                with open(self._settings_file) as f:
                    data = json.load(f)
                self._cache = {**DEFAULTS, **data}
                self._cache_mtime = os.path.getmtime(self._settings_file)
            except json.JSONDecodeError:
                import logging

                logging.getLogger(__name__).warning(
                    "settings.json is corrupted — falling back to defaults"
                )
                self._cache = dict(DEFAULTS)
                self._cache_mtime = 0.0
        else:
            self._cache = dict(DEFAULTS)
            self._cache_mtime = 0.0
        return dict(self._cache)

    def save(self, settings: dict) -> None:
        with open(self._settings_file, "w") as f:
            json.dump(settings, f, indent=2)
        self._cache = dict(settings)
        try:
            self._cache_mtime = os.path.getmtime(self._settings_file)
        except OSError:
            self._cache_mtime = 0.0

    def set_device(self, device_id: int | None) -> None:
        settings = self.load()
        settings["device_id"] = device_id
        self.save(settings)

    def set_model_size(self, lang_code: str, size_name: str) -> None:
        config_key = LANGUAGES[lang_code].config_key
        settings = self.load()
        settings[config_key] = size_name
        self.save(settings)


# Module-level singleton — all callers unchanged
_instance = Config()


def load() -> dict:
    return _instance.load()


def save(settings: dict) -> None:
    _instance.save(settings)


def set_device(device_id) -> None:
    _instance.set_device(device_id)


def set_model_size(lang_code: str, size_name: str) -> None:
    _instance.set_model_size(lang_code, size_name)
