import json
import os

SETTINGS_FILE = "settings.json"

DEFAULTS = {
    "device_id": None,
    "model_size_en": "small.en",
    "model_size_nl": "small",
    "beam_size": 2,
    "hotkey_english": "f13",
    "hotkey_dutch": "f14",
    "sound_start": "assets/start.wav",
    "sound_stop": "assets/stop.wav",
    "sound_done": "assets/done.wav",
}

_cache: dict | None = None


def load() -> dict:
    global _cache
    if _cache is not None:
        return dict(_cache)
    return _load_from_disk()


def _load_from_disk() -> dict:
    global _cache
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            data = json.load(f)
        _cache = {**DEFAULTS, **data}
    else:
        _cache = dict(DEFAULTS)
    return dict(_cache)


def save(settings: dict) -> None:
    global _cache
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)
    _cache = dict(settings)


def set_device(device_id: int | None) -> None:
    settings = load()
    settings["device_id"] = device_id
    save(settings)


def set_model_size_en(size_name: str) -> None:
    settings = load()
    settings["model_size_en"] = size_name
    save(settings)


def set_model_size_nl(size_name: str) -> None:
    settings = load()
    settings["model_size_nl"] = size_name
    save(settings)
