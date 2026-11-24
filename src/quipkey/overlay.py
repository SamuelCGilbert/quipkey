"""Small always-on-top pill near the bottom of the screen that never takes focus."""
from __future__ import annotations

import time

from .platforms import Platform
from .text import short_mic_name


class Overlay:
    W, H = 340, 46
    ROW, PAD, GAP = 30, 6, 6                   # mic menu rows (opens above the pill)
    CHIP_X0 = 214                              # mic chip: x from here to W - 8
    BG, FG, DIM, REC, KEY = "#1c1c1f", "#f2f2f3", "#8b8b93", "#ff4d4f", "#010203"
    CHIP, HOVER = "#2e2e34", "#3a3a42"

    def __init__(self, root, platform: Platform, get_level, mic_label=lambda: "",
                 mic_options=lambda: [], on_mic=lambda key: None):
        import tkinter as tk

        self.root = root
        self.platform = platform
        self.get_level = get_level
        self.mic_label, self.mic_options, self.on_mic = mic_label, mic_options, on_mic
        self.menu: list | None = None          # [(key, label, selected)] while the menu is open
        self.hover = None                      # "chip" or a menu row index
        self.state = "hidden"
        self.msg = ""
        self.levels = [0.0] * 9
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        bg = self.KEY if platform.transparent_overlay else self.BG
        self.win.config(bg=bg)
        platform.overlay_init(self.win)
        self.c = tk.Canvas(self.win, width=self.W, height=self.H, highlightthickness=0, bg=bg)
        self.c.pack()
        self.c.bind("<Button-1>", self._click)
        self.c.bind("<Motion>", self._motion)
        self.c.bind("<Leave>", lambda e: self._set_hover(None))
        self.win.withdraw()
        fam = platform.ui_font(root)
        self.font = (fam, 10)
        self.small = (fam, 9)
        self._tick()

    # -- geometry: the window grows upward when the mic menu is open; the pill stays put
    def _menu_h(self):
        return len(self.menu) * self.ROW + 2 * self.PAD + self.GAP if self.menu else 0

    def _total_h(self):
        return self.H + self._menu_h()

    def _place(self):
        area = self.platform.overlay_area(self.win)
        if area is None:
            area = (0, 0, self.win.winfo_screenwidth(), self.win.winfo_screenheight())
        ax, ay, aw, ah = area
        h = self._total_h()
        self.c.config(height=h)
        self.win.geometry(f"{self.W}x{h}+{ax + (aw - self.W) // 2}+{ay + ah - h - 96}")

    def _hit(self, x, y):
        top = self._menu_h()
        if self.menu and y < top - self.GAP:
            i = int((y - self.PAD) // self.ROW)
            return i if 0 <= i < len(self.menu) else None
        if self.state == "recording" and top <= y and self.CHIP_X0 <= x <= self.W - 8:
            return "chip"
        return None

    def _set_hover(self, h):
        if h != self.hover:
            self.hover = h
            self.c.config(cursor="hand2" if h is not None else "")
            self._draw()

    def _motion(self, e):
        self._set_hover(self._hit(e.x, e.y))

    def _click(self, e):
        h = self._hit(e.x, e.y)
        if h == "chip":
            self.menu = None if self.menu else self.mic_options()
        elif isinstance(h, int):
            key = self.menu[h][0]
            self.menu = None
            self.on_mic(key)
        else:
            self.menu = None
        self.hover = None
        self._place()
        self._draw()

    def set(self, state: str, msg: str = ""):
        """state: "hidden" | "recording" | "busy" (spinner + msg) | "info" (msg)."""
        prev, self.state, self.msg = self.state, state, msg
        if state != "recording" and self.menu:
            self.menu = None
            self._place()
        if state == "hidden":
            self.platform.overlay_hide(self.win)
        elif prev == "hidden":
            self.levels = [0.0] * len(self.levels)
            self._place()
            self.platform.overlay_show(self.win)
        self._draw()

    def _round_rect(self, x0, y0, x1, y1, r, fill):
        c = self.c
        for cx, cy in ((x0, y0), (x1 - 2 * r, y0), (x0, y1 - 2 * r), (x1 - 2 * r, y1 - 2 * r)):
            c.create_oval(cx, cy, cx + 2 * r, cy + 2 * r, fill=fill, outline=fill)
        c.create_rectangle(x0 + r, y0, x1 - r, y1, fill=fill, outline=fill)
        c.create_rectangle(x0, y0 + r, x1, y1 - r, fill=fill, outline=fill)

    @staticmethod
    def _fit(text, n):
        return text if len(text) <= n else text[: n - 1].rstrip() + "…"

    def _pill(self, x0, y0, x1, y1, r, **kw):
        c = self.c
        c.create_oval(x0, y0, x0 + 2 * r, y1, **kw)
        c.create_oval(x1 - 2 * r, y0, x1, y1, **kw)
        c.create_rectangle(x0 + r, y0, x1 - r, y1, **kw)

    def _draw(self):
        c = self.c
        c.delete("all")
        if self.state == "hidden":
            return
        font, small = self.font, self.small
        if self.menu:
            self._round_rect(1, 0, self.W - 1, self._menu_h() - self.GAP, 12, self.BG)
            for i, (_key, label, selected) in enumerate(self.menu):
                y0 = self.PAD + i * self.ROW
                if self.hover == i:
                    self._round_rect(5, y0, self.W - 5, y0 + self.ROW, 8, self.HOVER)
                if selected:
                    c.create_text(20, y0 + self.ROW / 2, text="✓", fill=self.FG, font=font)
                c.create_text(36, y0 + self.ROW / 2, text=self._fit(label, 42), anchor="w",
                              fill=self.FG if selected or self.hover == i else self.DIM, font=small)
        top = self._menu_h()
        self._pill(1, top + 1, self.W - 1, top + self.H - 1, (self.H - 2) // 2, fill=self.BG,
                   outline=self.BG)
        cy = top + self.H // 2
        if self.state == "recording":
            blink = (time.time() * 2) % 2 < 1.4
            c.create_oval(18, cy - 5, 28, cy + 5, fill=self.REC if blink else "#7a2a2b", outline="")
            c.create_text(40, cy, text="Listening", anchor="w", fill=self.FG, font=font)
            x = 122
            for lv in self.levels:
                h = 3 + lv * 24
                c.create_rectangle(x, cy - h / 2, x + 4, cy + h / 2, fill=self.FG, outline="")
                x += 9
            # mic chip: click to pick a different mic
            chip = self.HOVER if self.hover == "chip" or self.menu else self.CHIP
            self._round_rect(self.CHIP_X0, cy - 14, self.W - 8, cy + 14, 14, chip)
            c.create_text(self.CHIP_X0 + 12, cy, text=self._fit(short_mic_name(self.mic_label()), 14),
                          anchor="w", fill=self.FG, font=small)
            c.create_text(self.W - 20, cy, text="▾", fill=self.DIM, font=small)
        elif self.state == "busy":
            n = int(time.time() * 6) % 3
            for i in range(3):
                col = self.FG if i == n else self.DIM
                c.create_oval(20 + i * 10, cy - 3, 26 + i * 10, cy + 3, fill=col, outline="")
            c.create_text(58, cy, text=self._fit(self.msg or "Transcribing", 38), anchor="w",
                          fill=self.FG, font=font)
        elif self.state == "info":
            c.create_text(self.W // 2, cy, text=self._fit(self.msg, 44), fill=self.FG, font=font)

    def _tick(self):
        if self.state == "recording":
            self.levels = self.levels[1:] + [self.get_level()]
        if self.state in ("recording", "busy"):
            self._draw()
        self.root.after(50, self._tick)
