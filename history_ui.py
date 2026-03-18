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
_BG        = "#f5f3ef"
_CARD      = "#ffffff"
_BORDER    = "#e8e4de"
_SHADOW    = "#cac5bd"
_FG        = "#1a1917"
_DIM       = "#9e9894"
_ACCENT    = "#c96a3c"
_HIGHLIGHT = "#fde68a"
_DANGER    = "#d44"

_RADIUS = 5
_PAD    = 14
_FADE_STEPS = 8
_FADE_MS    = 20  # ms between steps (~160ms total)

_PLACEHOLDER = "Search transcriptions\u2026"

_open = False
_lock = threading.Lock()

# Handles kept while the window is open (for live updates)
_root_ref         = None
_inner_ref        = None
_first_entry_ref  = [None]   # topmost entry widget
_empty_lbl_ref    = [None]   # "no entries yet" label
_scroll_cv_ref    = [None]   # scrollable canvas
_search_entry_ref = [None]   # tk.Entry widget
_count_lbl_ref    = [None]   # result count label
_clear_btn_ref    = [None]   # clear search button
_all_entries: list[tuple[str, str, str]] = []   # full data, newest first
_hovered_text     = [None]   # text of currently hovered card (for Ctrl+C)


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


def _lerp_color(c1: str, c2: str, t: float) -> str:
    """Interpolate between two hex colors. t=0 gives c1, t=1 gives c2."""
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


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
                before=None, query: str = "", fade: bool = False) -> tk.Frame:
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

    _last_size = [0, 0]  # [width, height] — skip redraw if unchanged

    def _redraw(event=None):
        cw = cv.winfo_width()
        if cw <= 1:
            cv.after(30, _redraw)
            return
        fh = content.winfo_reqheight()
        h  = fh + _PAD * 2
        if _last_size[0] == cw and _last_size[1] == h:
            return
        _last_size[0], _last_size[1] = cw, h
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
            _hovered_text[0] = text
            cv.itemconfig(shadow_id, state="normal")

    def _leave(e=None):
        cv.after(15, _check_leave)

    def _check_leave():
        x, y   = cv.winfo_pointerxy()
        rx, ry = cv.winfo_rootx(), cv.winfo_rooty()
        rw, rh = cv.winfo_width(), cv.winfo_height()
        if not (rx <= x <= rx + rw and ry <= y <= ry + rh):
            _hovered[0] = False
            if _hovered_text[0] == text:
                _hovered_text[0] = None
            cv.itemconfig(shadow_id, state="hidden")

    # ── header row ──
    hdr = tk.Frame(content, bg=_CARD)
    hdr.pack(fill="x")

    # Delete button — packed right first (furthest right)
    del_btn = tk.Button(
        hdr, text="\u2715",
        bg=_CARD, fg=_DIM,
        activebackground=_CARD, activeforeground=_DANGER,
        relief="flat", padx=2, pady=0,
        font=("Segoe UI", 9), cursor="hand2",
        highlightthickness=0, borderwidth=0,
    )
    del_btn.config(command=lambda: _delete_entry(outer, ts, meta, text))
    del_btn.pack(side="right")

    # Copy icon
    btn = tk.Button(
        hdr, text="\u29c9",
        bg=_CARD, fg=_DIM,
        activebackground=_CARD, activeforeground=_ACCENT,
        relief="flat", padx=2, pady=0,
        font=("Segoe UI", 11), cursor="hand2",
        highlightthickness=0, borderwidth=0,
    )
    btn.config(command=lambda: _copy(btn, text, cv))
    btn.pack(side="right", padx=(0, 4))

    tk.Label(hdr, text=ts, bg=_CARD, fg=_DIM,
             font=("Segoe UI", 8)).pack(side="left")
    if meta:
        tk.Label(hdr, text=f"\u00b7 {meta}", bg=_CARD, fg=_ACCENT,
                 font=("Segoe UI", 8)).pack(side="left", padx=(8, 0))

    # Divider
    tk.Frame(content, bg=_BORDER, height=1).pack(fill="x", pady=(6, 0))

    # Transcription text — use Text widget for match highlighting
    text_w = tk.Text(
        content, wrap="word",
        bg=_CARD, fg=_FG,
        font=("Segoe UI", 10),
        relief="flat", bd=0, highlightthickness=0,
        cursor="arrow", padx=0, pady=0,
        height=1, width=1,
    )
    text_w.tag_configure("match", background=_HIGHLIGHT, foreground=_FG)
    text_w.insert("1.0", text)

    # Apply highlighting if there's a search query
    if query:
        start_idx = "1.0"
        while True:
            pos = text_w.search(query, start_idx, stopindex="end", nocase=True)
            if not pos:
                break
            end_pos = f"{pos}+{len(query)}c"
            text_w.tag_add("match", pos, end_pos)
            start_idx = end_pos

    text_w.config(state="disabled")
    text_w.configure(cursor="ibeam")
    text_w.pack(fill="x", pady=(8, 4))

    # Auto-size the Text widget height based on content
    def _autosize(event=None):
        text_w.update_idletasks()
        # Count display lines after wrapping
        line_count = int(text_w.index("end-1c").split(".")[0])
        if line_count != int(text_w.cget("height")):
            text_w.config(height=line_count)

    text_w.bind("<Configure>", _autosize)

    # Block editing keys but allow selection and Ctrl+C
    text_w.bind("<Key>", lambda e: "break" if e.state & 4 == 0 else None)

    # Right-click context menu with Copy
    def _show_context_menu(e):
        menu = tk.Menu(text_w, tearoff=0,
                       bg=_CARD, fg=_FG, activebackground=_BORDER,
                       activeforeground=_FG, font=("Segoe UI", 9))
        try:
            sel = text_w.get("sel.first", "sel.last")
        except tk.TclError:
            sel = ""
        if sel:
            menu.add_command(label="Copy selection",
                             command=lambda: _ctx_copy(text_w, sel))
        menu.add_command(label="Copy all",
                         command=lambda: _ctx_copy(text_w, text))
        menu.tk_popup(e.x_root, e.y_root)

    text_w.bind("<Button-3>", _show_context_menu)

    # Click on card area removes focus from search bar
    def _on_card_click(e):
        root = cv.winfo_toplevel()
        root.focus_set()

    for w in (cv, content, hdr):
        w.bind("<Button-1>", _on_card_click)

    # Bind hover to every widget inside the card (done last, after all children exist)
    _bind_hover(cv, _enter, _leave)

    # Fade-in animation — transition colors from background to card colors
    if fade:
        # Collect all child widgets that need color transitions
        _fade_widgets = []
        for child in content.winfo_children():
            try:
                bg = child.cget("bg")
                if bg == _CARD:
                    _fade_widgets.append((child, "bg", _CARD))
                fg = child.cget("fg")
                if fg in (_FG, _DIM, _ACCENT):
                    _fade_widgets.append((child, "fg", fg))
            except tk.TclError:
                pass
            # Recurse one level into header frame children
            for sub in child.winfo_children():
                try:
                    bg = sub.cget("bg")
                    if bg == _CARD:
                        _fade_widgets.append((sub, "bg", _CARD))
                    fg = sub.cget("fg")
                    if fg in (_FG, _DIM, _ACCENT):
                        _fade_widgets.append((sub, "fg", fg))
                except tk.TclError:
                    pass

        # Set initial state — everything blends into background
        cv.itemconfig(rect_id, fill=_BG, outline=_BG)
        content.config(bg=_BG)
        text_w.config(bg=_BG)
        for widget, prop, _ in _fade_widgets:
            try:
                widget.config(**{prop: _BG})
            except tk.TclError:
                pass

        def _fade_step(step=0):
            if step > _FADE_STEPS:
                return
            t = step / _FADE_STEPS
            # Card background and border
            bg_c = _lerp_color(_BG, _CARD, t)
            border_c = _lerp_color(_BG, _BORDER, t)
            try:
                cv.itemconfig(rect_id, fill=bg_c, outline=border_c)
                content.config(bg=bg_c)
                text_w.config(bg=bg_c)
                for widget, prop, target in _fade_widgets:
                    c = _lerp_color(_BG, target, t)
                    widget.config(**{prop: c})
            except tk.TclError:
                return
            cv.after(_FADE_MS, lambda: _fade_step(step + 1))

        cv.after(1, _fade_step)

    return outer


def _copy(btn: tk.Button, text: str, cv: tk.Canvas) -> None:
    root = cv.winfo_toplevel()
    root.clipboard_clear()
    root.clipboard_append(text)
    btn.config(fg=_ACCENT)
    btn.after(1500, lambda: btn.config(fg=_DIM))


def _ctx_copy(widget: tk.Widget, text: str) -> None:
    """Copy text to clipboard from a context menu action."""
    root = widget.winfo_toplevel()
    root.clipboard_clear()
    root.clipboard_append(text)


def _delete_entry(card_frame: tk.Frame, ts: str, meta: str, text: str) -> None:
    """Remove one entry from memory, disk, and UI."""
    try:
        _all_entries.remove((ts, meta, text))
    except ValueError:
        pass

    output_handler.delete_log_entry(ts, meta, text)

    card_frame.destroy()

    inner = _inner_ref
    if inner is not None:
        children = inner.winfo_children()
        _first_entry_ref[0] = children[0] if children else None
        if not children:
            lbl = tk.Label(inner, text="No transcriptions yet.",
                           bg=_BG, fg=_DIM, font=("Segoe UI", 11), pady=40)
            lbl.pack()
            _empty_lbl_ref[0] = lbl

    _update_count()


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
    _all_entries.insert(0, (ts, meta, text))

    # If a search is active and the new entry doesn't match, skip the UI
    query = _get_search_query()
    if query and not _matches(query, ts, meta, text):
        _update_count()
        return

    if _empty_lbl_ref[0] is not None:
        _empty_lbl_ref[0].destroy()
        _empty_lbl_ref[0] = None

    first = _first_entry_ref[0]
    new_entry = _make_entry(_inner_ref, ts, meta, text, before=first, query=query,
                            fade=True)
    _first_entry_ref[0] = new_entry
    _update_count()


# ── search / filter ───────────────────────────────────────────────────

def _get_search_query() -> str:
    """Return the current search string, or '' if empty/placeholder."""
    entry = _search_entry_ref[0]
    if entry is None:
        return ""
    val = entry.get().strip()
    if not val or val == _PLACEHOLDER:
        return ""
    return val.lower()


def _matches(query: str, ts: str, meta: str, text: str) -> bool:
    return query in text.lower() or query in ts.lower() or query in meta.lower()


def _update_count() -> None:
    """Update the result count label."""
    lbl = _count_lbl_ref[0]
    if lbl is None:
        return
    total = len(_all_entries)
    query = _get_search_query()
    if query:
        filtered = sum(1 for e in _all_entries if _matches(query, *e))
        lbl.config(text=f"{filtered} of {total}")
    else:
        lbl.config(text=str(total) if total else "")


def _apply_filter() -> None:
    """Clear and rebuild cards matching the current search query."""
    inner = _inner_ref
    root = _root_ref
    if inner is None or root is None:
        return

    scroll_cv = _scroll_cv_ref[0]

    # Cancel any in-progress smooth scroll
    if _scroll_anim["job"] is not None:
        root.after_cancel(_scroll_anim["job"])
        _scroll_anim["job"] = None

    for child in inner.winfo_children():
        child.destroy()
    _first_entry_ref[0] = None
    _empty_lbl_ref[0] = None

    # Reset scroll to top
    if scroll_cv is not None:
        scroll_cv.yview_moveto(0)
        _scroll_anim["target"] = 0.0
        _scroll_anim["current"] = 0.0

    query = _get_search_query()

    if query:
        matching = [(ts, m, t) for ts, m, t in _all_entries
                    if _matches(query, ts, m, t)]
    else:
        matching = list(_all_entries)

    _update_count()

    if not matching:
        msg = "No matching transcriptions." if query else "No transcriptions yet."
        lbl = tk.Label(inner, text=msg,
                       bg=_BG, fg=_DIM, font=("Segoe UI", 11), pady=40)
        lbl.pack()
        _empty_lbl_ref[0] = lbl
        return

    _BATCH = 20

    def _load_batch(idx=0):
        batch = matching[idx:idx + _BATCH]
        if not batch:
            return
        for i, (ts, meta, text) in enumerate(batch):
            w = _make_entry(inner, ts, meta, text, query=query,
                            fade=True)
            if _first_entry_ref[0] is None:
                _first_entry_ref[0] = w
        if idx + _BATCH < len(matching):
            root.after(10, lambda: _load_batch(idx + _BATCH))

    root.after(1, _load_batch)


# ── smooth scroll ─────────────────────────────────────────────────────

_scroll_anim = {"target": 0.0, "current": 0.0, "job": None}


def _animate_scroll():
    """Lerp toward the scroll target for smooth movement."""
    scroll_cv = _scroll_cv_ref[0]
    if scroll_cv is None:
        _scroll_anim["job"] = None
        return

    target = _scroll_anim["target"]
    current = _scroll_anim["current"]

    diff = target - current
    if abs(diff) < 0.0005:
        scroll_cv.yview_moveto(target)
        _scroll_anim["current"] = target
        _scroll_anim["job"] = None
        return

    # Move 20% of remaining distance each frame (ease-out)
    new_pos = current + diff * 0.2
    scroll_cv.yview_moveto(new_pos)
    _scroll_anim["current"] = new_pos

    # ~16ms per frame = ~60fps
    _scroll_anim["job"] = scroll_cv.after(16, _animate_scroll)


# ── window ────────────────────────────────────────────────────────────

def _run_window() -> None:
    global _open, _root_ref, _inner_ref

    root = tk.Tk()
    root.title("ScribeVibe \u2014 History")
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

    def _clear_history():
        # Clear the log file
        open(output_handler.LOG_FILE, "w").close()
        _all_entries.clear()
        # Reset search box
        _clear_search()
        # Remove all cards from the UI
        for child in inner.winfo_children():
            child.destroy()
        _first_entry_ref[0] = None
        lbl = tk.Label(inner, text="No transcriptions yet.",
                       bg=_BG, fg=_DIM, font=("Segoe UI", 11), pady=40)
        lbl.pack()
        _empty_lbl_ref[0] = lbl
        _update_count()

    tk.Button(hdr_frame, text="Clear History",
              bg=_CARD, fg=_ACCENT,
              activebackground=_BORDER, activeforeground=_ACCENT,
              relief="flat", padx=10, pady=2,
              font=("Segoe UI", 9), cursor="hand2",
              highlightthickness=0, borderwidth=1,
              command=_clear_history).pack(side="right")
    tk.Frame(root, bg=_BORDER, height=1).pack(fill="x", padx=20, pady=(10, 0))

    # Search bar
    search_frame = tk.Frame(root, bg=_BG)
    search_frame.pack(fill="x", padx=20, pady=(10, 0))

    search_border = tk.Frame(search_frame, bg=_CARD,
                             highlightthickness=1, highlightcolor=_ACCENT,
                             highlightbackground=_BORDER)
    search_border.pack(fill="x")

    search_entry = tk.Entry(
        search_border,
        bg=_CARD, fg=_DIM, insertbackground=_FG,
        font=("Segoe UI", 10),
        relief="flat", highlightthickness=0, borderwidth=0,
    )
    search_entry.insert(0, _PLACEHOLDER)
    search_entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(8, 4))
    _search_entry_ref[0] = search_entry

    # Clear search button (x) — hidden initially
    clear_btn = tk.Button(
        search_border, text="\u00d7",
        bg=_CARD, fg=_DIM,
        activebackground=_CARD, activeforeground=_ACCENT,
        relief="flat", padx=6, pady=0,
        font=("Segoe UI", 12), cursor="hand2",
        highlightthickness=0, borderwidth=0,
    )
    _clear_btn_ref[0] = clear_btn
    # Don't pack yet — shown when there's search text

    # Result count label
    count_lbl = tk.Label(
        search_border, text="", bg=_CARD, fg=_DIM,
        font=("Segoe UI", 8), padx=6,
    )
    count_lbl.pack(side="right")
    _count_lbl_ref[0] = count_lbl

    def _clear_search():
        search_entry.delete(0, "end")
        search_entry.config(fg=_DIM)
        search_entry.insert(0, _PLACEHOLDER)
        clear_btn.pack_forget()
        root.focus_set()
        _apply_filter()

    clear_btn.config(command=_clear_search)

    def _on_focus_in(e):
        if search_entry.get() == _PLACEHOLDER:
            search_entry.delete(0, "end")
        search_entry.config(fg=_FG)

    def _on_focus_out(e):
        if not search_entry.get().strip():
            search_entry.delete(0, "end")
            search_entry.config(fg=_DIM)
            search_entry.insert(0, _PLACEHOLDER)
            clear_btn.pack_forget()

    search_entry.bind("<FocusIn>", _on_focus_in)
    search_entry.bind("<FocusOut>", _on_focus_out)

    # Debounced filtering via KeyRelease — 200ms after last keystroke
    _pending_filter = [None]

    def _on_key(event=None):
        # Show/hide clear button
        val = search_entry.get().strip()
        if val and val != _PLACEHOLDER:
            clear_btn.pack(side="right", padx=(0, 2))
        else:
            clear_btn.pack_forget()
        if _pending_filter[0] is not None:
            root.after_cancel(_pending_filter[0])
        _pending_filter[0] = root.after(200, _apply_filter)

    search_entry.bind("<KeyRelease>", _on_key)

    # Escape in search clears it
    def _on_escape(e):
        _clear_search()
        return "break"

    search_entry.bind("<Escape>", _on_escape)

    # Ctrl+F focuses the search bar
    def _ctrl_f(e):
        search_entry.focus_set()
        _on_focus_in(None)
        # Select all existing text for easy replacement
        val = search_entry.get()
        if val and val != _PLACEHOLDER:
            search_entry.select_range(0, "end")
        return "break"

    root.bind("<Control-f>", _ctrl_f)

    # Ctrl+C copies hovered card text
    def _ctrl_c(e):
        # Don't intercept if focus is on the search entry
        if root.focus_get() == search_entry:
            return
        if _hovered_text[0] is not None:
            root.clipboard_clear()
            root.clipboard_append(_hovered_text[0])
            return "break"

    root.bind("<Control-c>", _ctrl_c)

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
    _scroll_cv_ref[0] = scroll_cv

    inner = tk.Frame(scroll_cv, bg=_BG)
    win_id = scroll_cv.create_window((0, 0), window=inner, anchor="nw")

    _last_inner_h = [0]

    def _update_scrollregion(e):
        h = inner.winfo_reqheight()
        if h != _last_inner_h[0]:
            _last_inner_h[0] = h
            scroll_cv.configure(scrollregion=scroll_cv.bbox("all"))

    inner.bind("<Configure>", _update_scrollregion)
    scroll_cv.bind("<Configure>",
                   lambda e: scroll_cv.itemconfig(win_id, width=e.width))

    # Smooth scroll via mousewheel
    def _on_wheel(event):
        bbox = scroll_cv.bbox("all")
        if bbox is None:
            return
        content_height = bbox[3] - bbox[1]
        visible_height = scroll_cv.winfo_height()
        if content_height <= visible_height:
            return

        # Each wheel tick scrolls ~60px worth of the total content
        delta = -event.delta / 120  # positive = scroll down
        scroll_fraction = (60 * delta) / content_height

        # Initialize from current position if no animation running
        if _scroll_anim["job"] is None:
            current_pos = scroll_cv.yview()[0]
            _scroll_anim["current"] = current_pos
            _scroll_anim["target"] = current_pos

        _scroll_anim["target"] += scroll_fraction
        _scroll_anim["target"] = max(0.0, min(1.0, _scroll_anim["target"]))

        if _scroll_anim["job"] is None:
            _animate_scroll()

    scroll_cv.bind_all("<MouseWheel>", _on_wheel)

    # Click on empty scroll area removes focus from search bar
    scroll_cv.bind("<Button-1>", lambda e: root.focus_set())

    _inner_ref = inner

    # Populate with existing entries (batch-load for responsiveness)
    entries = _parse_log()
    _all_entries.clear()
    _all_entries.extend(entries)
    _BATCH = 20  # entries per render batch

    def _load_batch(idx=0):
        batch = entries[idx:idx + _BATCH]
        if not batch:
            return
        for ts, meta, text in batch:
            w = _make_entry(inner, ts, meta, text)
            if _first_entry_ref[0] is None:
                _first_entry_ref[0] = w
        if idx + _BATCH < len(entries):
            root.after(10, lambda: _load_batch(idx + _BATCH))

    if entries:
        _empty_lbl_ref[0] = None
        _first_entry_ref[0] = None
        root.after(1, _load_batch)
    else:
        lbl = tk.Label(inner, text="No transcriptions yet.",
                       bg=_BG, fg=_DIM, font=("Segoe UI", 11), pady=40)
        lbl.pack()
        _empty_lbl_ref[0] = lbl
        _first_entry_ref[0] = None

    _update_count()

    # Register live-update hook
    output_handler.set_log_hook(_on_new_transcription)

    def _on_close():
        global _open, _root_ref, _inner_ref
        output_handler.set_log_hook(None)
        scroll_cv.unbind_all("<MouseWheel>")
        root.unbind("<Control-f>")
        root.unbind("<Control-c>")
        if _scroll_anim["job"] is not None:
            root.after_cancel(_scroll_anim["job"])
            _scroll_anim["job"] = None
        _root_ref = None
        _inner_ref = None
        _first_entry_ref[0] = None
        _empty_lbl_ref[0] = None
        _search_entry_ref[0] = None
        _scroll_cv_ref[0] = None
        _count_lbl_ref[0] = None
        _clear_btn_ref[0] = None
        _hovered_text[0] = None
        _all_entries.clear()
        _open = False
        root.withdraw()
        root.quit()

    root.protocol("WM_DELETE_WINDOW", _on_close)
    root.mainloop()
    root.destroy()
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
