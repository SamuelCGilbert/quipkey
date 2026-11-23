"""Record docs/demo.gif (Windows): runs the real app in-process with a test WAV instead of the mic,
types into a small editor window, and screen-grabs the area around the overlay.

    python scripts/record_demo.py path/to/16k-mono.wav

Uses a throwaway settings folder and the hotkey Ctrl+Alt+F9, so it doesn't touch your setup.
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
WAV = Path(sys.argv[1]).resolve()
tmp = Path(tempfile.mkdtemp())
os.environ["APPDATA"] = str(tmp / "roaming")
os.environ["LOCALAPPDATA"] = str(tmp / "local")
os.environ.setdefault("HF_HUB_CACHE", str(Path.home() / ".cache/huggingface/hub"))
sys.path.insert(0, str(ROOT / "src"))

from quipkey import paths  # noqa: E402

paths.config_dir().mkdir(parents=True)
paths.config_path().write_text(json.dumps({"hotkey": "ctrl+alt+f9"}))
paths.state_path().write_text(json.dumps({"welcomed": True}))
os.environ["QUIPKEY_TEST_WAV"] = str(WAV)

from PIL import Image, ImageGrab  # noqa: E402

from quipkey.app import App  # noqa: E402
from quipkey.config import setup_logging  # noqa: E402
from quipkey.platforms import get_platform  # noqa: E402

with wave.open(str(WAV)) as w:
    audio = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
REC_SECONDS = min(4.0, len(audio) / 16000)

platform = get_platform()
platform.setup_process()
setup_logging()
app = App(platform)
app.tray and app.tray.stop()
root = app.root

# audio level from the WAV (the real mic is open but the room is quiet)
t_rec = [0.0]


class Level:
    def __get__(self, obj, owner):
        i = int((time.time() - t_rec[0]) * 16000)
        chunk = audio[max(0, i - 800):i]
        if chunk.size == 0:
            return 0.0
        rms = float(np.sqrt(np.mean(chunk ** 2)) + 1e-9)
        return max(0.0, min(1.0, (20 * np.log10(rms) + 55) / 45))

    def __set__(self, obj, value):  # ignore the real mic
        pass


type(app.recorder).level = Level()

import tkinter as tk  # noqa: E402

sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
# The overlay's bottom edge is 96 px above the screen bottom; stop the capture above the taskbar.
W, H = 760, 300
x0, y0 = (sw - W) // 2, sh - 84 - (H + 40)
ed = tk.Toplevel(root)
ed.overrideredirect(True)
ed.geometry(f"{W}x{H + 40}+{x0}+{y0}")
ed.configure(bg="#f6f6f7")
bar = tk.Label(ed, text="  notes.txt", anchor="w", bg="#e9e9ec", fg="#333", font=("Segoe UI", 10))
bar.pack(fill="x", ipady=6)
txt = tk.Text(ed, font=("Segoe UI", 13), bg="#f6f6f7", fg="#1c1c1f", relief="flat", padx=28,
              pady=18, wrap="word", insertwidth=2, highlightthickness=0)
txt.pack(fill="both", expand=True)
txt.insert("end", "Notes for Tuesday\n\n")
frames: list[Image.Image] = []
box = (x0, y0, x0 + W, y0 + H + 40)
start = [0.0]


def grab():
    frames.append(ImageGrab.grab(bbox=box, all_screens=True).convert("RGB"))


def step(phase="wait"):
    now = time.time()
    if phase == "wait":
        if not app.transcriber.ready.is_set():
            root.after(200, step, "wait")
            return
        ed.lift()
        ed.focus_force()
        txt.focus_set()
        txt.mark_set("insert", "end")
        start[0] = now
        root.after(600, step, "start")
        return
    if phase == "rec":
        app.recorder.active_label = "USB Microphone"  # don't show the real device name
    grab()
    if phase == "start" and now - start[0] > 1.2:
        t_rec[0] = time.time()
        app.events.put("start")
        phase = "rec"
    elif phase == "rec" and now - t_rec[0] > REC_SECONDS:
        app.events.put("stop")
        phase = "after"
        start[0] = now
    elif phase == "after" and now - start[0] > 3.0:
        out = ROOT / "docs" / "demo.gif"
        small = [f.resize((W * 3 // 4, (H + 40) * 3 // 4), Image.LANCZOS) for f in frames]
        pal = [f.quantize(colors=64, method=Image.Quantize.MEDIANCUT) for f in small]
        pal[0].save(out, save_all=True, append_images=pal[1:], duration=80, loop=0, optimize=True)
        rec = next((f for i, f in enumerate(frames) if i > len(frames) // 3), frames[-1])
        rec.save(ROOT / "docs" / "screenshot.png")
        print(f"wrote {out} ({len(frames)} frames, {out.stat().st_size // 1024} KB)")
        app.quit()
        return
    root.after(80, step, phase)


ctypes.windll.user32.SetProcessDPIAware()
root.after(300, step)
app.run()
