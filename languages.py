"""Language definitions for ScribeVibe.

Adding a new language requires only:
  1. Add a Language entry to LANGUAGES.
  2. Append its code to LANGUAGE_CYCLE.

No other file needs to change.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str                             # ISO 639-1 code, e.g. "en"
    name: str                             # Display name, e.g. "English"
    config_key: str                       # settings.json key, e.g. "model_size_en"
    default_model: str                    # Fallback model ID when config is absent
    models: tuple[tuple[str, str], ...]  # (model_id, menu_label) pairs


LANGUAGES: dict[str, Language] = {
    "en": Language(
        code="en",
        name="English",
        config_key="model_size_en",
        default_model="small.en",
        models=(
            ("base.en", "Base (EN)"),
            ("small.en", "Small (EN)"),
            ("medium.en", "Medium (EN)"),
            ("Systran/faster-distil-whisper-medium.en", "Distil-Medium (EN)"),
            ("Systran/faster-distil-whisper-large-v3", "Distil-Large-v3 (EN)"),
        ),
    ),
    "nl": Language(
        code="nl",
        name="Dutch",
        config_key="model_size_nl",
        default_model="small",
        models=(
            ("base", "Base"),
            ("small", "Small"),
            ("medium", "Medium"),
            ("deepdml/faster-whisper-large-v3-turbo-ct2", "Large-v3-Turbo"),
        ),
    ),
}

# Ordered cycle for switch_language() — append new codes here to include in rotation.
LANGUAGE_CYCLE: list[str] = ["en", "nl"]
