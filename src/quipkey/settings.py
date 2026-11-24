"""The settings window. Every change applies and saves at once; there's no Save button.

Plain Tk, drawn to look like a modern settings page: rounded cards, toggle switches, light or
dark to match the system. Pillow renders the round shapes smoothly when it's available.
"""
from __future__ import annotations

import logging
import os
import sys
import webbrowser

from . import paths
from .config import ensure_config_file, set_config_value
from .meta import APP_DISPLAY_NAME, APP_NAME, REPO_URL, VERSION

log = logging.getLogger(APP_NAME)

DARK = {"bg": "#161618", "card": "#212124", "line": "#2e2e33", "fg": "#f2f2f3",
        "dim": "#9b9ba4", "ctl": "#2c2c31", "ctl_hover": "#36363c", "accent": "#5b8cff",
        "off": "#4a4a52", "knob": "#ffffff", "danger": "#ff6b6b"}
LIGHT = {"bg": "#f3f3f5", "card": "#ffffff", "line": "#e4e4e9", "fg": "#17171a",
         "dim": "#6b6b75", "ctl": "#f0f0f3", "ctl_hover": "#e6e6eb", "accent": "#2f6bff",
         "off": "#c4c4cc", "knob": "#ffffff", "danger": "#d93636"}

DEVICE_NAMES = {"cpu": "the CPU", "directml": "the GPU (DirectML)", "cuda": "the GPU (CUDA)"}


def _open_path(path):
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            import subprocess

            from .platforms.linux import _clean_env
            subprocess.Popen(["xdg-open", str(path)], env=_clean_env())
    except Exception:  # noqa: BLE001
        log.exception("Couldn't open %s", path)


class Shapes:
    """Antialiased round shapes as Tk images (Pillow), cached. None without Pillow."""

    def __init__(self, master, scale: float):
        self.master, self.s, self.cache = master, scale, {}
        try:
            from PIL import Image, ImageDraw, ImageTk  # noqa: F401

            self.ok = True
        except ImportError:
            self.ok = False

    def _img(self, key, w, h, draw):
        if key not in self.cache:
            from PIL import Image, ImageDraw, ImageTk

            k = 4  # draw big, shrink: smooth edges
            img = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
            draw(ImageDraw.Draw(img), k)
            self.cache[key] = ImageTk.PhotoImage(img.resize((w, h), Image.LANCZOS),
                                                 master=self.master)
        return self.cache[key]

    def toggle(self, on: bool, hover: bool, th: dict):
        w, h = round(40 * self.s), round(22 * self.s)

        def draw(d, k):
            track = th["accent"] if on else th["off"]
            d.rounded_rectangle((0, 0, w * k - 1, h * k - 1), radius=h * k / 2, fill=track)
            pad = 3 * self.s * k
            r = h * k / 2 - pad
            cx = (w * k - h * k / 2) if on else h * k / 2
            if hover:
                r += 0.6 * self.s * k
            d.ellipse((cx - r, h * k / 2 - r, cx + r, h * k / 2 + r), fill=th["knob"])
        return self._img(("toggle", on, hover, th["accent"]), w, h, draw)

    def corners(self, th: dict, r: int):
        """Four corner images that round off a card drawn as a frame with a 1 px border."""
        size = 2 * r + 2

        def full(d, k):
            d.rectangle((0, 0, size * k, size * k), fill=th["bg"])
            d.rounded_rectangle((0, 0, size * k - 1, size * k - 1), radius=r * k,
                                fill=th["card"], outline=th["line"], width=k)
        if not self.ok:
            return None
        key = ("corners", r, th["bg"])
        if key not in self.cache:
            from PIL import Image, ImageDraw, ImageTk

            k = 4
            img = Image.new("RGBA", (size * k, size * k))
            full(ImageDraw.Draw(img), k)
            img = img.resize((size, size), Image.LANCZOS)
            boxes = {"nw": (0, 0, r + 1, r + 1), "ne": (size - r - 1, 0, size, r + 1),
                     "sw": (0, size - r - 1, r + 1, size), "se": (size - r - 1, size - r - 1, size, size)}
            self.cache[key] = {a: ImageTk.PhotoImage(img.crop(b), master=self.master)
                               for a, b in boxes.items()}
        return self.cache[key]

    def icon(self, size: int):
        if not self.ok:
            return None
        key = ("icon", size)
        if key not in self.cache:
            from PIL import ImageTk

            from .icon import make_icon
            self.cache[key] = ImageTk.PhotoImage(make_icon(size), master=self.master)
        return self.cache[key]


class SettingsWindow:
    def __init__(self, app):
        self.app = app
        self.win = None
        self.capturing = False
        self.status_label = None

    # -- open / close
    def show(self):
        import tkinter as tk

        if self.win is not None and self.win.winfo_exists():
            self.win.deiconify()
            self.app.platform.activate_window(self.win)
            return
        p = self.app.platform
        self.th = DARK if p.dark_mode() else LIGHT
        self.win = tk.Toplevel(self.app.root)
        self.win.withdraw()
        self.win.title(f"{APP_DISPLAY_NAME} settings")
        self.win.configure(bg=self.th["bg"])
        self.win.resizable(False, False)
        self.s = self.win.winfo_fpixels("1i") / 96
        self.shapes = Shapes(self.win, self.s)
        icon = self.shapes.icon(64)
        if icon:
            self.win.iconphoto(False, icon)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.bind("<Escape>", lambda e: self.capturing or self.close())
        self.f = (p.font, 10)
        self.f_small = (p.font, 9)
        self.f_head = (p.font, 9, "bold")
        self.f_title = (p.font, 15, "bold")
        self.body = None
        self.render()
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        self.win.geometry(f"+{(sw - w) // 2}+{max(0, (sh - h) // 3)}")
        p.style_window(self.win, self.th is DARK)
        self.win.deiconify()
        p.activate_window(self.win)

    def close(self):
        if self.capturing:
            self._end_capture(None)
        if self.win is not None:
            self.win.destroy()
        self.win = None
        self.status_label = None

    def refresh_status(self):
        """Called by the app when the model status changes."""
        if self.status_label is not None and self.win is not None and self.win.winfo_exists():
            self.status_label.config(text=self._status_text())

    # -- building blocks
    def px(self, n):
        return round(n * self.s)

    def label(self, parent, text, font=None, fg=None, bg=None, **kw):
        import tkinter as tk

        return tk.Label(parent, text=text, font=font or self.f, fg=fg or self.th["fg"],
                        bg=bg or self.th["card"], anchor="w", justify="left", **kw)

    def link(self, parent, text, command, bg=None):
        lb = self.label(parent, text, font=self.f_small, fg=self.th["accent"], bg=bg or self.th["bg"],
                        cursor="hand2")
        lb.bind("<Button-1>", lambda e: command())
        return lb

    def button(self, parent, text, command, width=None):
        import tkinter as tk

        th = self.th
        b = tk.Label(parent, text=text, font=self.f, fg=th["fg"], bg=th["ctl"], cursor="hand2",
                     padx=self.px(12), pady=self.px(5), highlightthickness=1,
                     highlightbackground=th["line"], width=width)
        b.bind("<Enter>", lambda e: b.config(bg=th["ctl_hover"]))
        b.bind("<Leave>", lambda e: b.config(bg=th["ctl"]))
        b.bind("<Button-1>", lambda e: command())
        return b

    def toggle(self, parent, value: bool, command):
        import tkinter as tk

        th = self.th
        state = {"on": value, "hover": False}
        if self.shapes.ok:
            w = tk.Label(parent, bg=th["card"], cursor="hand2", bd=0)

            def draw():
                w.config(image=self.shapes.toggle(state["on"], state["hover"], th))
        else:
            w = tk.Canvas(parent, width=self.px(40), height=self.px(22), bg=th["card"],
                          highlightthickness=0, cursor="hand2")

            def draw():
                w.delete("all")
                W, H = self.px(40), self.px(22)
                col = th["accent"] if state["on"] else th["off"]
                w.create_oval(0, 0, H, H, fill=col, outline=col)
                w.create_oval(W - H, 0, W, H, fill=col, outline=col)
                w.create_rectangle(H / 2, 0, W - H / 2, H, fill=col, outline=col)
                x = W - H / 2 if state["on"] else H / 2
                r = H / 2 - self.px(3)
                w.create_oval(x - r, H / 2 - r, x + r, H / 2 + r, fill=th["knob"], outline="")

        def click(_e):
            state["on"] = not state["on"]
            draw()
            command(state["on"])

        def hover(on):
            state["hover"] = on
            draw()
        w.bind("<Button-1>", click)
        w.bind("<Enter>", lambda e: hover(True))
        w.bind("<Leave>", lambda e: hover(False))
        draw()
        return w

    def section(self, title, note=None):
        import tkinter as tk

        th = self.th
        self.label(self.body, title.upper(), font=self.f_head, fg=th["dim"], bg=th["bg"]).pack(
            fill="x", padx=self.px(4), pady=(self.px(16), self.px(2) if note else self.px(6)))
        if note:
            self.label(self.body, note, font=self.f_small, fg=th["dim"], bg=th["bg"],
                       wraplength=self.px(460)).pack(fill="x", padx=self.px(4), pady=(0, self.px(6)))
        card = tk.Frame(self.body, bg=th["card"], highlightthickness=1,
                        highlightbackground=th["line"])
        card.pack(fill="x")
        r = self.px(8)
        corners = self.shapes.corners(th, r)
        if corners:
            for anchor, (rx, ry) in {"nw": (0, 0), "ne": (1, 0), "sw": (0, 1), "se": (1, 1)}.items():
                c = tk.Label(card, image=corners[anchor], bd=0, bg=th["card"])
                # offsets cover the frame's 1 px border too
                c.place(relx=rx, rely=ry, anchor=anchor, x=1 if rx else -1, y=1 if ry else -1)
                c.lift()
        card._rows = 0
        return card

    def row(self, card, title, desc=None):
        """-> (left column, right-hand container for the control). No title: left is empty."""
        import tkinter as tk

        th = self.th
        if card._rows:
            tk.Frame(card, bg=th["line"], height=1).pack(fill="x", padx=self.px(16))
        card._rows += 1
        row = tk.Frame(card, bg=th["card"])
        row.pack(fill="x", padx=self.px(16), pady=self.px(10))
        right = tk.Frame(row, bg=th["card"])
        right.pack(side="right", padx=(self.px(16), 0))
        left = tk.Frame(row, bg=th["card"])
        left.pack(side="left", fill="x", expand=True)
        if title:
            self.label(left, title).pack(fill="x")
        if desc:
            self.label(left, desc, font=self.f_small, fg=th["dim"],
                       wraplength=self.px(300)).pack(fill="x", pady=(self.px(2), 0))
        return left, right

    # -- the page
    def render(self):
        import tkinter as tk

        th, app, p = self.th, self.app, self.app.platform
        if self.body is not None:
            self.body.destroy()
        self.body = tk.Frame(self.win, bg=th["bg"], padx=self.px(24), pady=self.px(20))
        self.body.pack(fill="both", expand=True)
        self.body.configure(width=self.px(520))

        head = tk.Frame(self.body, bg=th["bg"])
        head.pack(fill="x")
        icon = self.shapes.icon(self.px(40))
        if icon:
            tk.Label(head, image=icon, bg=th["bg"], bd=0).pack(side="left", padx=(0, self.px(12)))
        txt = tk.Frame(head, bg=th["bg"])
        txt.pack(side="left", fill="x", expand=True)
        self.label(txt, APP_DISPLAY_NAME, font=self.f_title, bg=th["bg"]).pack(fill="x")
        how = (f"Press {p.hotkey_label(app.cfg)} in any app, speak, then press it again."
               if p.name == "windows" else "Press your shortcut in any app, speak, then press it again.")
        self.label(txt, how, font=self.f_small, fg=th["dim"], bg=th["bg"]).pack(fill="x")

        # General
        card = self.section("General")
        if p.can_set_hotkey:
            _, right = self.row(card, "Shortcut", "Starts and stops dictation. Esc cancels.")
            self.hotkey_btn = self.button(right, p.hotkey_label(app.cfg), self._begin_capture)
            self.hotkey_btn.pack()
        else:
            self.row(card, "Shortcut", p.hotkey_help())
        _, right = self.row(card, "Microphone")
        self.mic_btn = self.button(right, self._mic_text() + "  ▾", self._mic_menu)
        self.mic_btn.pack()
        startup = p.startup_enabled()
        if startup is not None:
            _, right = self.row(card, "Start when I sign in")
            self.toggle(right, startup, self._set_startup).pack()

        # Speech recognition
        from .transcriber import gpu_device

        card = self.section("Speech recognition")
        gpu = gpu_device()
        left, right = self.row(card, "Use the GPU" if gpu else "Speech model",
                               "Faster for long dictations. Uses about 2.5 GB of video memory: "
                               "turn it off for games." if gpu else None)
        if gpu:
            self.toggle(right, str(app.cfg["device"]).lower() != "cpu", self._set_gpu).pack()
        self.status_label = self.label(left, self._status_text(), font=self.f_small,
                                       fg=th["accent"], wraplength=self.px(330))
        self.status_label.pack(fill="x", pady=(self.px(4), 0))

        # Text
        card = self.section("Text")
        _, right = self.row(card, "Remove filler words", "Drops “um”, “uh” and the like.")
        self.toggle(right, bool(app.cfg["remove_fillers"]),
                    lambda v: self._set("remove_fillers", v)).pack()
        _, right = self.row(card, "Add a space after each dictation",
                            "So the next dictation doesn't run into this one.")
        self.toggle(right, bool(app.cfg["trailing_space"]),
                    lambda v: self._set("trailing_space", v)).pack()

        # Passthrough apps (Windows; on KDE a KWin script does it)
        if p.name == "windows":
            card = self.section(
                "Apps that keep the shortcut",
                f"While one of these is in front, {p.hotkey_label(app.cfg)} goes to it instead of "
                f"{APP_DISPLAY_NAME}.")
            for exe in app.cfg["passthrough_apps"]:
                _, right = self.row(card, exe)
                self.link(right, "Remove", lambda e=exe: self._remove_app(e), bg=th["card"]).pack()
            left, right = self.row(card, None)
            self.app_entry = tk.Entry(left, font=self.f, bg=th["ctl"], fg=th["fg"], relief="flat",
                                      insertbackground=th["fg"], highlightthickness=1,
                                      highlightbackground=th["line"], highlightcolor=th["accent"])
            self.app_entry.pack(fill="x", ipady=self.px(5))
            self.app_entry.bind("<Return>", lambda e: self._add_app())
            self._placeholder(self.app_entry, "Program file name, like app.exe")
            self.button(right, "Add", self._add_app).pack()

        # Footer
        foot = tk.Frame(self.body, bg=th["bg"])
        foot.pack(fill="x", pady=(self.px(18), 0))
        for text, cmd in (("Settings file", self._open_config),
                          ("Log folder", lambda: _open_path(paths.log_dir())),
                          ("Help and bug reports", lambda: webbrowser.open(REPO_URL))):
            self.link(foot, text, cmd).pack(side="left", padx=(0, self.px(14)))
        self.label(foot, f"v{VERSION}", font=self.f_small, fg=th["dim"], bg=th["bg"]).pack(side="right")

    def _placeholder(self, entry, text):
        th = self.th

        def show(_e=None):
            if not entry.get():
                entry.insert(0, text)
                entry.config(fg=th["dim"])
                entry._ph = True

        def hide(_e=None):
            if getattr(entry, "_ph", False):
                entry.delete(0, "end")
                entry.config(fg=th["fg"])
                entry._ph = False
        entry.bind("<FocusIn>", hide, add="+")
        entry.bind("<FocusOut>", show, add="+")
        show()

    # -- texts
    def _mic_text(self):
        from .text import short_mic_name

        rec = self.app.recorder
        if rec.choice:
            return short_mic_name(rec.choice)[:28]
        return self.app._mic_options()[0][1]

    def _status_text(self):
        t = self.app.transcriber
        if t.ready.is_set() and not t.error:
            return f"Ready. Running on {DEVICE_NAMES.get(t.device, t.device)}."
        return self.app.model_status

    # -- actions
    def _set(self, key, value):
        self.app.cfg[key] = value
        set_config_value(key, value)
        log.info("Setting %s = %r", key, value)

    def _set_gpu(self, on):
        self._set("device", "auto" if on else "cpu")
        self.app.reload_model()
        self.refresh_status()

    def _set_startup(self, on):
        try:
            self.app.platform.set_startup(on)
        except Exception as e:  # noqa: BLE001
            log.exception("Couldn't change start at sign-in")
            self.app.notify(f"Couldn't change that: {e}")
            self.render()

    def _mic_menu(self):
        import tkinter as tk

        from .audio import list_mics

        app, th = self.app, self.th
        try:
            app.recorder.mics = list_mics()
        except Exception:  # noqa: BLE001
            log.exception("Couldn't list mics")
        m = tk.Menu(self.win, tearoff=False, bg=th["card"], fg=th["fg"], bd=0,
                    activebackground=th["ctl_hover"], activeforeground=th["fg"], font=self.f)
        for key, label, selected in app._mic_options():
            m.add_command(label=("✓  " if selected else "     ") + label,
                          command=lambda k=key: self._choose_mic(k))
        b = self.mic_btn
        m.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())

    def _choose_mic(self, key):
        app = self.app
        if app.state == "recording":
            app._choose_mic(key)
        else:
            app.recorder.choice = key
            from .config import save_state
            save_state(mic=key)
        self.mic_btn.config(text=self._mic_text() + "  ▾")

    def _begin_capture(self):
        if self.capturing:
            return
        self.capturing = True
        self.app.platform.set_hotkey(None)  # so pressing the current shortcut doesn't record
        self.hotkey_btn.config(text="Press a shortcut…", fg=self.th["accent"],
                               highlightbackground=self.th["accent"])
        self.win.bind("<KeyPress>", self._on_key)
        self.win.focus_force()

    def _on_key(self, e):
        if e.keysym == "Escape":
            self._end_capture(None)
            return "break"
        combo = self.app.platform.hotkey_from_event(e)
        if combo:
            self._end_capture(combo)
        return "break"

    def _end_capture(self, combo):
        p, app = self.app.platform, self.app
        self.capturing = False
        self.win.unbind("<KeyPress>")
        if combo and combo != app.cfg["hotkey"]:
            err = p.set_hotkey(combo)
            if err:
                app.notify(err)
                p.set_hotkey(app.cfg["hotkey"])
            else:
                self._set("hotkey", combo)
        else:
            p.set_hotkey(app.cfg["hotkey"])
        self.render()

    def _add_app(self):
        name = "" if getattr(self.app_entry, "_ph", False) else self.app_entry.get()
        name = name.strip().strip('"')
        if not name:
            return
        if not name.lower().endswith(".exe"):
            name += ".exe"
        apps = list(self.app.cfg["passthrough_apps"])
        if name.lower() not in (a.lower() for a in apps):
            apps.append(name)
            self._set("passthrough_apps", apps)
        self.render()

    def _remove_app(self, exe):
        self._set("passthrough_apps", [a for a in self.app.cfg["passthrough_apps"] if a != exe])
        self.render()

    def _open_config(self):
        _open_path(ensure_config_file())
