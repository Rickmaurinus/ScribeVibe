"""Win32 low-level keyboard hook for ScribeVibe."""
import ctypes
import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)


class KeyHook:
    """Installs a Win32 WH_KEYBOARD_LL hook on a daemon thread.

    Callbacks:
      on_record_toggle   — Insert pressed alone
      on_language_switch — Shift+Insert pressed
      on_abort           — Escape pressed; should return True to suppress the key
    """

    def __init__(
        self,
        on_record_toggle: Callable,
        on_language_switch: Callable,
        on_abort: Callable[[], bool],
    ) -> None:
        self._on_record_toggle = on_record_toggle
        self._on_language_switch = on_language_switch
        self._on_abort = on_abort
        self._hook_proc_ref = None  # keep alive to prevent GC

    def install(self) -> None:
        """Install the keyboard hook on a background daemon thread."""
        VK_INSERT = 0x2D
        VK_ESCAPE = 0x1B

        _u32 = ctypes.WinDLL("user32", use_last_error=True)

        LRESULT = ctypes.c_ssize_t
        WPARAM  = ctypes.c_size_t
        LPARAM  = ctypes.c_ssize_t

        LLKeyboardProc = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, WPARAM, LPARAM)

        _u32.SetWindowsHookExW.argtypes = [
            ctypes.c_int, LLKeyboardProc, ctypes.c_void_p, ctypes.c_ulong,
        ]
        _u32.SetWindowsHookExW.restype = ctypes.c_void_p

        _u32.CallNextHookEx.argtypes = [
            ctypes.c_void_p, ctypes.c_int, WPARAM, LPARAM,
        ]
        _u32.CallNextHookEx.restype = LRESULT

        _u32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        _u32.UnhookWindowsHookEx.restype = ctypes.c_int

        _u32.GetMessageW.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
        ]
        _u32.GetMessageW.restype = ctypes.c_int

        _u32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        _u32.GetAsyncKeyState.restype = ctypes.c_short

        on_record_toggle   = self._on_record_toggle
        on_language_switch = self._on_language_switch
        on_abort           = self._on_abort

        def _shift_is_down() -> bool:
            return bool(
                (_u32.GetAsyncKeyState(0xA0) & 0x8000)
                or (_u32.GetAsyncKeyState(0xA1) & 0x8000)
            )

        def hook_proc(nCode, wParam, lParam):
            try:
                if nCode >= 0:
                    vk = ctypes.cast(lParam, ctypes.POINTER(ctypes.c_ulong)).contents.value
                    is_down = wParam in (0x0100, 0x0104)  # WM_KEYDOWN / WM_SYSKEYDOWN

                    if vk == VK_INSERT:
                        if is_down and _shift_is_down():
                            on_language_switch()
                            return 1  # suppress
                        elif is_down and not _shift_is_down():
                            on_record_toggle()
                        return 1  # suppress Insert in all cases

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
                "Key hooks installed — Insert (record) + Shift+Insert (language) + Escape (abort)."
            )
            msg = (ctypes.c_byte * 48)()
            while _u32.GetMessageW(msg, None, 0, 0) > 0:
                pass
            _u32.UnhookWindowsHookEx(hook)

        threading.Thread(target=_run_hook, daemon=True).start()
