import json
import os
from pathlib import Path

import paths

SETTINGS_FILE = paths.SETTINGS_FILE

DEFAULTS = {
    "device_id": None,
    "model_size_en": "small.en",
    "model_size_nl": "small",
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

    def set_model_size_en(self, size_name: str) -> None:
        settings = self.load()
        settings["model_size_en"] = size_name
        self.save(settings)

    def set_model_size_nl(self, size_name: str) -> None:
        settings = self.load()
        settings["model_size_nl"] = size_name
        self.save(settings)


# Module-level singleton — all callers unchanged
_instance = Config()


def load() -> dict:
    return _instance.load()


def save(settings: dict) -> None:
    _instance.save(settings)


def set_device(device_id) -> None:
    _instance.set_device(device_id)


def set_model_size_en(size_name) -> None:
    _instance.set_model_size_en(size_name)


def set_model_size_nl(size_name) -> None:
    _instance.set_model_size_nl(size_name)
