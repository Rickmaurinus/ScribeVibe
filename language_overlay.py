"""Full-screen fading language indicator overlay."""
import threading
import tkinter as tk


_FONT_FAMILY = "Segoe UI Semibold"
_FONT_SIZE = 48
_FADE_DURATION_MS = 1500  # total fade-out time
_FADE_STEPS = 30          # number of opacity steps
_HOLD_MS = 400            # hold at full opacity before fading


class LanguageOverlay:
    """Shows a large language name centered on screen, then fades out."""

    def __init__(self) -> None:
        self._root: tk.Tk | None = None
        self._label: tk.Label | None = None
        self._lock = threading.Lock()
        self._after_id = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    def start(self) -> None:
        """Start the overlay thread (call once at app startup)."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2)

    def _run(self) -> None:
        root = tk.Tk()
        root.title("")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg="#1a1a1a")

        dpi = root.winfo_fpixels("1i")
        scale = dpi / 96.0
        font_size = int(_FONT_SIZE * scale)
        pad_x = int(60 * scale)
        pad_y = int(20 * scale)

        label = tk.Label(
            root, text="", fg="#ffffff", bg="#1a1a1a",
            font=(_FONT_FAMILY, font_size),
            padx=pad_x, pady=pad_y,
        )
        label.pack()

        self._root = root
        self._label = label
        root.withdraw()
        self._ready.set()
        root.mainloop()

    def show(self, language: str) -> None:
        """Show the language name and fade out."""
        with self._lock:
            if self._root is None:
                return
        try:
            self._root.after(0, lambda: self._do_show(language))
        except tk.TclError:
            pass

    def _do_show(self, language: str) -> None:
        if not self._root or not self._label:
            return

        # Cancel any in-progress fade
        if self._after_id is not None:
            self._root.after_cancel(self._after_id)
            self._after_id = None

        text = "English" if language == "en" else "Dutch"
        self._label.config(text=text)

        # Size and center the window
        self._root.attributes("-alpha", 0.92)
        self._root.update_idletasks()
        w = self._root.winfo_reqwidth()
        h = self._root.winfo_reqheight()
        screen_w = self._root.winfo_screenwidth()
        screen_h = self._root.winfo_screenheight()
        x = (screen_w - w) // 2
        y = (screen_h - h) // 2
        self._root.geometry(f"{w}x{h}+{x}+{y}")
        self._root.deiconify()

        # Hold, then start fading
        self._after_id = self._root.after(_HOLD_MS, self._start_fade)

    def _start_fade(self) -> None:
        self._fade_step = 0
        self._fade()

    def _fade(self) -> None:
        if not self._root:
            return
        self._fade_step += 1
        if self._fade_step >= _FADE_STEPS:
            self._root.withdraw()
            self._after_id = None
            return

        alpha = 0.92 * (1.0 - self._fade_step / _FADE_STEPS)
        self._root.attributes("-alpha", alpha)
        interval = _FADE_DURATION_MS // _FADE_STEPS
        self._after_id = self._root.after(interval, self._fade)

    def stop(self) -> None:
        if self._root:
            try:
                self._root.after(0, self._root.quit)
            except tk.TclError:
                pass
