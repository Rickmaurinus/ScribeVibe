"""Win32 low-level keyboard hook for ScribeVibe."""

import ctypes
import logging
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class KeyHook:
    """Installs a Win32 WH_KEYBOARD_LL hook on a daemon thread.

    Hotkeys are configurable via update_hotkeys().  Each hotkey is a dict:
        {"vk": <Win32 VK code>, "shift": bool, "ctrl": bool, "alt": bool}

    Callbacks:
      on_record_toggle   — configured record hotkey pressed
      on_language_switch — configured language hotkey pressed
      on_abort           — Escape pressed (hardcoded); should return True to suppress
    """

    def __init__(
        self,
        on_record_toggle: Callable,
        on_language_switch: Callable,
        on_abort: Callable[[], bool],
        record_hotkey: dict | None = None,
        language_hotkey: dict | None = None,
    ) -> None:
        self._on_record_toggle = on_record_toggle
        self._on_language_switch = on_language_switch
        self._on_abort = on_abort
        self._hook_proc_ref: Any = None  # keep alive to prevent GC
        self._paused: bool = False
        self._record_hotkey: dict = record_hotkey or {"vk": 0x2D, "shift": False, "ctrl": False, "alt": False}
        self._language_hotkey: dict = language_hotkey or {"vk": 0x2D, "shift": True, "ctrl": False, "alt": False}

    def pause(self) -> None:
        """Pause hook action processing (key events pass through unchanged)."""
        self._paused = True

    def resume(self) -> None:
        """Resume hook action processing."""
        self._paused = False

    def update_hotkeys(self, record_hotkey: dict, language_hotkey: dict) -> None:
        """Update hotkey config. Takes effect on the next keypress (no reinstall needed)."""
        self._record_hotkey = record_hotkey
        self._language_hotkey = language_hotkey
        logger.info(
            "Hotkeys updated — record: %s  language: %s",
            record_hotkey,
            language_hotkey,
        )

    def install(self) -> None:
        """Install the keyboard hook on a background daemon thread."""
        VK_ESCAPE = 0x1B

        _u32 = ctypes.WinDLL("user32", use_last_error=True)

        LRESULT = ctypes.c_ssize_t
        WPARAM = ctypes.c_size_t
        LPARAM = ctypes.c_ssize_t

        LLKeyboardProc = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, WPARAM, LPARAM)

        _u32.SetWindowsHookExW.argtypes = [
            ctypes.c_int,
            LLKeyboardProc,
            ctypes.c_void_p,
            ctypes.c_ulong,
        ]
        _u32.SetWindowsHookExW.restype = ctypes.c_void_p

        _u32.CallNextHookEx.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            WPARAM,
            LPARAM,
        ]
        _u32.CallNextHookEx.restype = LRESULT

        _u32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        _u32.UnhookWindowsHookEx.restype = ctypes.c_int

        _u32.GetMessageW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_uint,
        ]
        _u32.GetMessageW.restype = ctypes.c_int

        _u32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        _u32.GetAsyncKeyState.restype = ctypes.c_short

        on_record_toggle = self._on_record_toggle
        on_language_switch = self._on_language_switch
        on_abort = self._on_abort

        def _shift_down() -> bool:
            return bool((_u32.GetAsyncKeyState(0xA0) & 0x8000) or (_u32.GetAsyncKeyState(0xA1) & 0x8000))

        def _ctrl_down() -> bool:
            return bool((_u32.GetAsyncKeyState(0xA2) & 0x8000) or (_u32.GetAsyncKeyState(0xA3) & 0x8000))

        def _alt_down() -> bool:
            return bool((_u32.GetAsyncKeyState(0xA4) & 0x8000) or (_u32.GetAsyncKeyState(0xA5) & 0x8000))

        def hook_proc(nCode, wParam, lParam):
            try:
                if self._paused:
                    return _u32.CallNextHookEx(None, nCode, wParam, lParam)
                if nCode >= 0:
                    vk = ctypes.cast(lParam, ctypes.POINTER(ctypes.c_ulong)).contents.value
                    is_down = wParam in (0x0100, 0x0104)  # WM_KEYDOWN / WM_SYSKEYDOWN

                    # Snapshot modifier state once to avoid race between checks
                    shift = _shift_down()
                    ctrl = _ctrl_down()
                    alt = _alt_down()

                    def mods_match(hk: dict) -> bool:
                        return (
                            hk.get("shift", False) == shift
                            and hk.get("ctrl", False) == ctrl
                            and hk.get("alt", False) == alt
                        )

                    # Read hotkey config (may be updated from the Qt thread)
                    rec = self._record_hotkey
                    lang = self._language_hotkey

                    # Check language switch first — it typically has more modifiers
                    if vk == lang["vk"] and mods_match(lang):
                        if is_down:
                            on_language_switch()
                        return 1  # suppress both key-down and key-up

                    if vk == rec["vk"] and mods_match(rec):
                        if is_down:
                            on_record_toggle()
                        return 1  # suppress both key-down and key-up

                    if vk == VK_ESCAPE and is_down:
                        if on_abort():
                            return 1  # suppress only when abort was handled
            except Exception:
                logger.exception("Error in keyboard hook proc — passing event through")
            return _u32.CallNextHookEx(None, nCode, wParam, lParam)

        self._hook_proc_ref = LLKeyboardProc(hook_proc)

        def _run_hook():
            hook = _u32.SetWindowsHookExW(13, self._hook_proc_ref, None, 0)
            if not hook:
                logger.warning("Key hook failed (error %d)", ctypes.get_last_error())
                return
            logger.info(
                "Key hooks installed — record: %s  language: %s  Escape=Abort",
                self._record_hotkey,
                self._language_hotkey,
            )
            msg = (ctypes.c_byte * 48)()
            while _u32.GetMessageW(msg, None, 0, 0) > 0:
                pass
            _u32.UnhookWindowsHookEx(hook)

        threading.Thread(target=_run_hook, daemon=True).start()
