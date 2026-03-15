"""Transcription history viewer for ScribeVibe."""
import re
import threading
import tkinter as tk

import output_handler

# Matches: [2026-03-15 12:35:43] [model | 1.23s] text
#      or: [2026-03-15 12:35:43] text  (older log format)
_ENTRY_RE = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]"
    r"(?:\s+\[([^\]]+)\])?"
    r"\s+(.+)$"
)

# Claude.ai light-mode palette
_BG     = "#f5f3ef"
_CARD   = "#ffffff"
_BORDER = "#e8e4de"
_SHADOW = "#cac5bd"
_FG     = "#1a1917"
_DIM    = "#9e9894"
_ACCENT = "#c96a3c"

_RADIUS = 5
_PAD    = 14

_open = False
_lock = threading.Lock()

# Handles kept while the window is open (for live updates)
_root_ref        = None
_inner_ref       = None
_first_entry_ref = [None]   # topmost entry widget
_empty_lbl_ref   = [None]   # "no entries yet" label


# ── geometry helpers ──────────────────────────────────────────────────

def _rrect(x1, y1, x2, y2, r):
    """Polygon point list for a smooth rounded rectangle."""
    return [
        x1+r, y1,   x2-r, y1,
        x2,   y1,   x2,   y1+r,
        x2,   y2-r, x2,   y2,
        x2-r, y2,   x1+r, y2,
        x1,   y2,   x1,   y2-r,
        x1,   y1+r, x1,   y1,
    ]


def _bind_hover(widget, on_enter, on_leave):
    """Recursively bind <Enter>/<Leave> to widget and all descendants."""
    widget.bind("<Enter>", on_enter, add="+")
    widget.bind("<Leave>", on_leave, add="+")
    for child in widget.winfo_children():
        _bind_hover(child, on_enter, on_leave)


# ── log parsing ───────────────────────────────────────────────────────

def _parse_log() -> list[tuple[str, str, str]]:
    """Return (timestamp, meta, text) tuples, newest first."""
    entries = []
    try:
        with open(output_handler.LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                m = _ENTRY_RE.match(line)
                if m:
                    entries.append((m.group(1), m.group(2) or "", m.group(3)))
    except FileNotFoundError:
        pass
    return list(reversed(entries))


# ── entry card ────────────────────────────────────────────────────────

def _make_entry(parent: tk.Frame, ts: str, meta: str, text: str,
                before=None) -> tk.Frame:
    """Build a rounded card and return its outer frame."""
    outer = tk.Frame(parent, bg=_BG)
    pack_kw = dict(fill="x", pady=(0, 10))
    if before is not None:
        outer.pack(before=before, **pack_kw)
    else:
        outer.pack(**pack_kw)

    # Canvas draws the rounded background + shadow
    cv = tk.Canvas(outer, bg=_BG, highlightthickness=0, bd=0, height=10)
    cv.pack(fill="x")

    shadow_id = cv.create_polygon([0, 0], smooth=True,
                                  fill=_SHADOW, outline="", state="hidden")
    rect_id   = cv.create_polygon([0, 0], smooth=True,
                                  fill=_CARD, outline=_BORDER, width=1)

    content   = tk.Frame(cv, bg=_CARD)
    frame_win = cv.create_window(_PAD, _PAD, window=content, anchor="nw")

    def _redraw(event=None):
        cw = cv.winfo_width()
        if cw <= 1:
            cv.after(30, _redraw)
            return
        fh = content.winfo_reqheight()
        h  = fh + _PAD * 2
        cv.config(height=h)
        cv.itemconfig(frame_win, width=cw - _PAD * 2)
        # Shadow offset 3 px down-right; card flush top-left
        cv.coords(shadow_id, _rrect(3, 3, cw - 2, h - 1, _RADIUS))
        cv.coords(rect_id,   _rrect(0, 0, cw - 4, h - 3, _RADIUS))

    content.bind("<Configure>", _redraw)
    cv.bind("<Configure>", _redraw)

    # ── hover shadow ──
    _hovered = [False]

    def _enter(e=None):
        if not _hovered[0]:
            _hovered[0] = True
            cv.itemconfig(shadow_id, state="normal")

    def _leave(e=None):
        cv.after(15, _check_leave)

    def _check_leave():
        x, y   = cv.winfo_pointerxy()
        rx, ry = cv.winfo_rootx(), cv.winfo_rooty()
        rw, rh = cv.winfo_width(), cv.winfo_height()
        if not (rx <= x <= rx + rw and ry <= y <= ry + rh):
            _hovered[0] = False
            cv.itemconfig(shadow_id, state="hidden")

    # ── header row ──
    hdr = tk.Frame(content, bg=_CARD)
    hdr.pack(fill="x")

    # Copy icon — packed right first so it anchors to the right edge
    btn = tk.Button(
        hdr, text="⧉",
        bg=_CARD, fg=_DIM,
        activebackground=_CARD, activeforeground=_ACCENT,
        relief="flat", padx=2, pady=0,
        font=("Segoe UI", 11), cursor="hand2",
        highlightthickness=0, borderwidth=0,
    )
    btn.config(command=lambda: _copy(btn, text, cv))
    btn.pack(side="right")

    tk.Label(hdr, text=ts, bg=_CARD, fg=_DIM,
             font=("Segoe UI", 8)).pack(side="left")
    if meta:
        tk.Label(hdr, text=f"· {meta}", bg=_CARD, fg=_ACCENT,
                 font=("Segoe UI", 8)).pack(side="left", padx=(8, 0))

    # Divider
    tk.Frame(content, bg=_BORDER, height=1).pack(fill="x", pady=(6, 0))

    # Transcription text
    text_lbl = tk.Label(
        content, text=text,
        bg=_CARD, fg=_FG,
        font=("Segoe UI", 10),
        wraplength=600, justify="left", anchor="w",
    )
    text_lbl.pack(fill="x", pady=(8, 4))

    def _resize_wrap(event, lbl=text_lbl):
        lbl.config(wraplength=max(100, event.width - 30))
    content.bind("<Configure>", _resize_wrap, add="+")

    # Bind hover to every widget inside the card (done last, after all children exist)
    _bind_hover(cv, _enter, _leave)

    return outer


def _copy(btn: tk.Button, text: str, cv: tk.Canvas) -> None:
    root = cv.winfo_toplevel()
    root.clipboard_clear()
    root.clipboard_append(text)
    btn.config(fg=_ACCENT)
    btn.after(1500, lambda: btn.config(fg=_DIM))


# ── live update ───────────────────────────────────────────────────────

def _on_new_transcription(ts: str, meta: str, text: str) -> None:
    """Called from output_handler hook (non-tk thread) — schedule via after()."""
    root = _root_ref
    if root is None:
        return
    try:
        root.after(0, lambda: _prepend(ts, meta, text))
    except tk.TclError:
        pass


def _prepend(ts: str, meta: str, text: str) -> None:
    """Insert a new card at the top of the list (tk thread)."""
    if _empty_lbl_ref[0] is not None:
        _empty_lbl_ref[0].destroy()
        _empty_lbl_ref[0] = None

    first = _first_entry_ref[0]
    new_entry = _make_entry(_inner_ref, ts, meta, text, before=first)
    _first_entry_ref[0] = new_entry


# ── window ────────────────────────────────────────────────────────────

def _run_window() -> None:
    global _open, _root_ref, _inner_ref

    root = tk.Tk()
    root.title("ScribeVibe — History")
    root.geometry("760x580")
    root.minsize(520, 320)
    root.configure(bg=_BG)
    _root_ref = root

    # Header
    hdr_frame = tk.Frame(root, bg=_BG)
    hdr_frame.pack(fill="x", padx=20, pady=(18, 0))
    tk.Label(hdr_frame, text="Transcription History",
             bg=_BG, fg=_FG,
             font=("Segoe UI", 15, "bold")).pack(side="left")
    tk.Frame(root, bg=_BORDER, height=1).pack(fill="x", padx=20, pady=(10, 0))

    # Scrollable area
    outer = tk.Frame(root, bg=_BG)
    outer.pack(fill="both", expand=True, padx=20, pady=14)

    scrollbar = tk.Scrollbar(outer, orient="vertical",
                             troughcolor=_BG, bg=_BORDER,
                             activebackground=_ACCENT,
                             relief="flat", borderwidth=0)
    scrollbar.pack(side="right", fill="y")

    scroll_cv = tk.Canvas(outer, bg=_BG, highlightthickness=0,
                          yscrollcommand=scrollbar.set)
    scroll_cv.pack(side="left", fill="both", expand=True)
    scrollbar.config(command=scroll_cv.yview)

    inner = tk.Frame(scroll_cv, bg=_BG)
    win_id = scroll_cv.create_window((0, 0), window=inner, anchor="nw")

    inner.bind("<Configure>",
               lambda e: scroll_cv.configure(scrollregion=scroll_cv.bbox("all")))
    scroll_cv.bind("<Configure>",
                   lambda e: scroll_cv.itemconfig(win_id, width=e.width))

    def _on_wheel(event):
        scroll_cv.yview_scroll(int(-1 * (event.delta / 120)), "units")
    scroll_cv.bind_all("<MouseWheel>", _on_wheel)

    _inner_ref = inner

    # Populate with existing entries
    entries = _parse_log()
    if entries:
        first_widget = None
        for ts, meta, text in entries:
            w = _make_entry(inner, ts, meta, text)
            if first_widget is None:
                first_widget = w
        _first_entry_ref[0] = first_widget
        _empty_lbl_ref[0] = None
    else:
        lbl = tk.Label(inner, text="No transcriptions yet.",
                       bg=_BG, fg=_DIM, font=("Segoe UI", 11), pady=40)
        lbl.pack()
        _empty_lbl_ref[0] = lbl
        _first_entry_ref[0] = None

    # Register live-update hook
    output_handler.set_log_hook(_on_new_transcription)

    def _on_close():
        global _open, _root_ref, _inner_ref
        output_handler.set_log_hook(None)
        scroll_cv.unbind_all("<MouseWheel>")
        _root_ref = None
        _inner_ref = None
        _first_entry_ref[0] = None
        _empty_lbl_ref[0] = None
        _open = False
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)
    root.mainloop()
    _open = False


# ── public entry point ────────────────────────────────────────────────

def show_history() -> None:
    """Open the history window (no-op if already open)."""
    global _open
    with _lock:
        if _open:
            return
        _open = True
    threading.Thread(target=_run_window, daemon=True).start()
