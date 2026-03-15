"""System tray interface for ScribeVibe."""
import threading

import pystray
import sounddevice as sd
from PIL import Image, ImageDraw

import config
from history_ui import show_history
from select_mic import get_clean_mic_list

# ── Model definitions ───────────────────────────────────────────────

EN_MODELS = [
    ("base.en",   "Base (EN)"),
    ("small.en",  "Small (EN)"),
    ("medium.en", "Medium (EN)"),
    ("Systran/faster-distil-whisper-medium.en", "Distil-Medium (EN)"),
    ("Systran/faster-distil-whisper-large-v3", "Distil-Large-v3 (EN)"),
]

NL_MODELS = [
    ("base",      "Base"),
    ("small",     "Small"),
    ("medium",    "Medium"),
    ("deepdml/faster-whisper-large-v3-turbo-ct2", "Large-v3-Turbo"),
]


def _generate_icon() -> Image.Image:
    """Create a simple 64x64 tray icon (green microphone circle)."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, 60, 60], fill="#1DB954")
    # Simple mic shape
    draw.rounded_rectangle([24, 14, 40, 38], radius=6, fill="white")
    draw.arc([20, 28, 44, 50], start=0, end=180, fill="white", width=3)
    draw.line([32, 50, 32, 56], fill="white", width=3)
    draw.line([24, 56, 40, 56], fill="white", width=3)
    return img


class TrayApp:
    """System tray icon with model-switching menus."""

    def __init__(self, engine=None) -> None:
        self._icon: pystray.Icon | None = None
        self._engine = engine

    # ── mic switching ───────────────────────────────────────────────

    def _switch_mic(self, device_id: int | None) -> None:
        config.set_device(device_id)

    def _is_mic_checked(self, device_id: int | None):
        return lambda _item: config.load().get("device_id") == device_id

    def _make_mic_action(self, device_id: int | None):
        def action(icon, item):
            self._switch_mic(device_id)
        return action

    def _build_mic_menu(self):
        items = [
            pystray.MenuItem(
                "Default",
                self._make_mic_action(None),
                checked=self._is_mic_checked(None),
                radio=True,
            )
        ]
        for device_id, name, _api in get_clean_mic_list():
            items.append(pystray.MenuItem(
                name,
                self._make_mic_action(device_id),
                checked=self._is_mic_checked(device_id),
                radio=True,
            ))
        return pystray.Menu(*items)

    # ── model switching ─────────────────────────────────────────────

    def _switch_en(self, model_size: str) -> None:
        old_model = config.load().get("model_size_en")
        config.set_model_size_en(model_size)
        # Only preload if the GPU currently holds the old English model
        if self._engine and self._engine.current_model == old_model:
            threading.Thread(
                target=self._engine.ensure_model,
                args=(model_size,),
                daemon=True,
            ).start()
    def _switch_nl(self, model_size: str) -> None:
        old_model = config.load().get("model_size_nl")
        config.set_model_size_nl(model_size)
        # Only preload if the GPU currently holds the old Dutch model
        if self._engine and self._engine.current_model == old_model:
            threading.Thread(
                target=self._engine.ensure_model,
                args=(model_size,),
                daemon=True,
            ).start()

    # ── menu builders ───────────────────────────────────────────────

    def _is_en_checked(self, model_size: str):
        return lambda _item: config.load().get("model_size_en") == model_size

    def _is_nl_checked(self, model_size: str):
        return lambda _item: config.load().get("model_size_nl") == model_size

    def _make_en_action(self, ms):
        def action(icon, item):
            self._switch_en(ms)
        return action

    def _make_nl_action(self, ms):
        def action(icon, item):
            self._switch_nl(ms)
        return action

    def _build_en_menu(self):
        return pystray.Menu(*(
            pystray.MenuItem(
                label,
                self._make_en_action(ms),
                checked=self._is_en_checked(ms),
                radio=True,
            )
            for ms, label in EN_MODELS
        ))

    def _build_nl_menu(self):
        return pystray.Menu(*(
            pystray.MenuItem(
                label,
                self._make_nl_action(ms),
                checked=self._is_nl_checked(ms),
                radio=True,
            )
            for ms, label in NL_MODELS
        ))

    def _build_menu(self):
        return pystray.Menu(
            pystray.MenuItem("Microphone", self._build_mic_menu()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("English Model", self._build_en_menu()),
            pystray.MenuItem("Dutch Model", self._build_nl_menu()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("History...", self._open_history),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )

    # ── history ─────────────────────────────────────────────────────

    def _open_history(self, _icon, _item) -> None:
        show_history()

    # ── lifecycle ───────────────────────────────────────────────────

    def _quit(self, _icon, _item) -> None:
        if self._icon:
            self._icon.stop()

    def run(self) -> None:
        """Blocking — run on a dedicated thread."""
        self._icon = pystray.Icon(
            name="ScribeVibe",
            icon=_generate_icon(),
            title="ScribeVibe",
            menu=self._build_menu(),
        )
        self._icon.run()

    def notify(self, message: str, title: str = "ScribeVibe") -> None:
        """Show a Windows toast notification (safe to call before icon is ready)."""
        if self._icon:
            self._icon.notify(message, title)

    def stop(self) -> None:
        if self._icon:
            self._icon.stop()
