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
}


class Config:
    def __init__(self, settings_file: Path | str = SETTINGS_FILE) -> None:
        self._settings_file = settings_file
        self._cache: dict | None = None

    def load(self) -> dict:
        if self._cache is not None:
            return dict(self._cache)
        return self._load_from_disk()

    def _load_from_disk(self) -> dict:
        if os.path.exists(self._settings_file):
            with open(self._settings_file) as f:
                data = json.load(f)
            self._cache = {**DEFAULTS, **data}
        else:
            self._cache = dict(DEFAULTS)
        return dict(self._cache)

    def save(self, settings: dict) -> None:
        with open(self._settings_file, "w") as f:
            json.dump(settings, f, indent=2)
        self._cache = dict(settings)

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
