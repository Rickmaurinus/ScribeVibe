"""Floating recording indicator — pulsing 3D glass-effect red ring."""
import math
import threading
import tkinter as tk


_TRANSPARENT = "#010101"  # keyed out for full transparency

# Canvas / positioning
_CANVAS_SIZE = 40         # px before DPI scaling
_MARGIN_BOTTOM = 40

# Pulse animation
_PULSE_STEP_MS = 25       # ~40 fps
_CIRCLE_SEGMENTS = 160    # polygon resolution for ultra-smooth circles

# Ring dimensions (40% smaller than previous design)
_RING_CENTER_MIN = 7.5    # center-of-ring radius at minimum pulse
_RING_CENTER_MAX = 10.5   # center-of-ring radius at maximum pulse
_RING_HALF_THICK = 3.0    # half the ring's cross-section width

# Glass gradient bands across the ring's cross-section.
# Each band: (position 0.0=outer edge → 1.0=inner edge,
#             (r,g,b) at dimmest pulse, (r,g,b) at brightest pulse)
# Dark edges + bright center = 3-D cylindrical glass tube illusion.
_BANDS = [
    (0.00, ( 55,  8,  8), ( 90, 16, 16)),   # outer edge — darkest
    (0.12, ( 85, 14, 12), (140, 26, 24)),
    (0.25, (120, 24, 20), (190, 44, 38)),
    (0.38, (155, 36, 30), (225, 62, 52)),
    (0.50, (175, 46, 38), (255, 82, 68)),   # center — brightest (specular)
    (0.62, (155, 36, 30), (225, 62, 52)),
    (0.75, (120, 24, 20), (190, 44, 38)),
    (0.88, ( 85, 14, 12), (140, 26, 24)),
    (1.00, ( 55,  8,  8), ( 90, 16, 16)),   # inner edge — darkest
]

# Soft outer glow
_GLOW_PAD = 3.0           # extra radius beyond ring's outer edge
_GLOW_ALPHA = 0.10        # simulated opacity (blended against transparent bg)


class RecordingIndicator:
    """Floating always-on-top transparent window with a pulsing glass ring."""

    def __init__(self) -> None:
        self._root: tk.Tk | None = None
        self._canvas: tk.Canvas | None = None
        self._lock = threading.Lock()
        self._visible = False
        self._pulse_phase = 0.0
        self._after_id = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        # Canvas item IDs populated during _run
        self._glow_id = None
        self._band_ids: list[int] = []
        self._hole_id = None

    # ── lifecycle ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the indicator thread (call once at app startup)."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2)

    def _run(self) -> None:
        root = tk.Tk()
        root.title("")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-transparentcolor", _TRANSPARENT)
        root.configure(bg=_TRANSPARENT)

        dpi = root.winfo_fpixels("1i")
        self._scale = dpi / 96.0

        sz = int(_CANVAS_SIZE * self._scale)

        canvas = tk.Canvas(
            root, width=sz, height=sz,
            bg=_TRANSPARENT, highlightthickness=0, bd=0,
        )
        canvas.pack()

        cx = sz // 2
        cy = sz // 2
        self._cx = cx
        self._cy = cy

        # --- build layered circles (back to front) ---

        # 1. Soft outer glow (large, very dim)
        r_glow = (_RING_CENTER_MIN + _RING_HALF_THICK + _GLOW_PAD) * self._scale
        self._glow_id = self._make_circle(canvas, cx, cy, r_glow, "#1a0505")

        # 2. Gradient bands — each is a filled circle; stacked smallest-on-top
        #    so the visible "band" of each layer is the annular ring between
        #    its own radius and the next-smaller circle on top of it.
        self._band_ids = []
        for i, (pos, dim_rgb, _bright_rgb) in enumerate(_BANDS):
            r = self._band_radius(pos, _RING_CENTER_MIN) * self._scale
            color = f"#{dim_rgb[0]:02x}{dim_rgb[1]:02x}{dim_rgb[2]:02x}"
            cid = self._make_circle(canvas, cx, cy, r, color)
            self._band_ids.append(cid)

        # 3. Transparent hole in the middle
        r_hole = (_RING_CENTER_MIN - _RING_HALF_THICK) * self._scale
        self._hole_id = self._make_circle(canvas, cx, cy, r_hole, _TRANSPARENT)

        self._root = root
        self._canvas = canvas

        # Position: bottom-center of primary screen
        root.update_idletasks()
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()
        x = (screen_w - sz) // 2
        y = screen_h - sz - int(_MARGIN_BOTTOM * self._scale)
        root.geometry(f"{sz}x{sz}+{x}+{y}")

        root.withdraw()
        self._ready.set()
        root.mainloop()

    # ── circle helpers ───────────────────────────────────────────────────

    @staticmethod
    def _make_circle(canvas: tk.Canvas, cx: int, cy: int,
                     r: float, fill: str) -> int:
        pts: list[float] = []
        for i in range(_CIRCLE_SEGMENTS):
            a = 2 * math.pi * i / _CIRCLE_SEGMENTS
            pts.append(cx + r * math.cos(a))
            pts.append(cy + r * math.sin(a))
        return canvas.create_polygon(pts, fill=fill, outline="", smooth=False)

    def _move_circle(self, item_id: int, cx: int, cy: int, r: float) -> None:
        pts: list[float] = []
        for i in range(_CIRCLE_SEGMENTS):
            a = 2 * math.pi * i / _CIRCLE_SEGMENTS
            pts.append(cx + r * math.cos(a))
            pts.append(cy + r * math.sin(a))
        self._canvas.coords(item_id, *pts)

    @staticmethod
    def _band_radius(pos: float, center_r: float) -> float:
        """Radius of a gradient band circle.  pos 0 = outer edge, 1 = inner edge."""
        return center_r + _RING_HALF_THICK * (1.0 - 2.0 * pos)

    # ── show / hide ──────────────────────────────────────────────────────

    def show(self) -> None:
        with self._lock:
            if self._visible or self._root is None:
                return
            self._visible = True
            self._pulse_phase = 0.0
        try:
            self._root.after(0, self._do_show)
        except tk.TclError:
            pass

    def hide(self) -> None:
        with self._lock:
            if not self._visible or self._root is None:
                return
            self._visible = False
        try:
            self._root.after(0, self._do_hide)
        except tk.TclError:
            pass

    def _do_show(self) -> None:
        if self._root:
            self._root.deiconify()
            self._animate()

    def _do_hide(self) -> None:
        if self._root:
            if self._after_id is not None:
                self._root.after_cancel(self._after_id)
                self._after_id = None
            self._root.withdraw()

    # ── animation ────────────────────────────────────────────────────────

    def _animate(self) -> None:
        if not self._visible or self._canvas is None:
            return

        self._pulse_phase += 0.06
        t = (math.sin(self._pulse_phase) + 1.0) / 2.0  # 0 → 1

        center_r = _RING_CENTER_MIN + t * (_RING_CENTER_MAX - _RING_CENTER_MIN)
        cx, cy, s = self._cx, self._cy, self._scale

        # Update glow
        r_glow = (center_r + _RING_HALF_THICK + _GLOW_PAD) * s
        self._move_circle(self._glow_id, cx, cy, r_glow)
        # Glow color: blend red against transparent-key colour
        ga = _GLOW_ALPHA * t
        gr = int(229 * ga + 1 * (1 - ga))
        gg = int(57 * ga + 1 * (1 - ga))
        gb = int(53 * ga + 1 * (1 - ga))
        self._canvas.itemconfig(self._glow_id, fill=f"#{gr:02x}{gg:02x}{gb:02x}")

        # Update gradient bands
        for i, (pos, dim_rgb, bright_rgb) in enumerate(_BANDS):
            r = self._band_radius(pos, center_r) * s
            self._move_circle(self._band_ids[i], cx, cy, r)
            # Interpolate dim → bright based on pulse
            rv = int(dim_rgb[0] + t * (bright_rgb[0] - dim_rgb[0]))
            gv = int(dim_rgb[1] + t * (bright_rgb[1] - dim_rgb[1]))
            bv = int(dim_rgb[2] + t * (bright_rgb[2] - dim_rgb[2]))
            self._canvas.itemconfig(self._band_ids[i],
                                    fill=f"#{rv:02x}{gv:02x}{bv:02x}")

        # Update transparent hole
        r_hole = (center_r - _RING_HALF_THICK) * s
        self._move_circle(self._hole_id, cx, cy, r_hole)

        self._after_id = self._root.after(_PULSE_STEP_MS, self._animate)

    # ── shutdown ─────────────────────────────────────────────────────────

    def stop(self) -> None:
        if self._root:
            try:
                self._root.after(0, self._root.quit)
            except tk.TclError:
                pass
