"""The app: idle -> recording -> busy (transcribing) -> idle.

All state changes happen on the Tk thread. Other threads (hotkey, socket, model loader, tray)
only put events into `self.events`, which `_pump` drains every 30 ms.
"""
from __future__ import annotations

import logging
import queue
import threading
import time

from .audio import SAMPLE_RATE, Recorder
from .config import load_config, load_state, save_state, setup_logging
from .meta import APP_DISPLAY_NAME, APP_NAME, VERSION
from .overlay import Overlay
from .platforms import Platform, get_platform
from .text import clean_text, short_mic_name
from .transcriber import Transcriber

log = logging.getLogger(APP_NAME)


class App:
    def __init__(self, platform: Platform):
        import tkinter as tk

        self.platform = platform
        self.cfg = load_config()
        self.events: queue.Queue = queue.Queue()
        self.recorder = Recorder(self.cfg)
        self.state = "idle"
        self.target = None
        self.last_text = ""  # the last transcript, for "Copy last transcript" in the tray
        self.job = 0
        self.model_status = "Loading speech model…"
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(APP_DISPLAY_NAME)
        self.overlay = Overlay(self.root, platform, lambda: self.recorder.level,
                               mic_label=lambda: self.recorder.active_label,
                               mic_options=self._mic_options, on_mic=self._choose_mic)
        self.tray = None
        self.transcriber = self._new_transcriber()
        platform.start_input(self.cfg, self.events, lambda: self.state == "idle")
        if platform.has_tray:
            try:
                from .tray import Tray

                self.tray = Tray(self)
            except Exception:  # noqa: BLE001
                log.exception("No tray icon")
        log.info("%s %s ready. Start dictation with %s", APP_NAME, VERSION,
                 platform.hotkey_label(self.cfg) if platform.name == "windows" else f"`{APP_NAME} toggle`")
        self.root.after(30, self._pump)

    # -- model
    def _new_transcriber(self) -> Transcriber:
        self.model_status = "Loading speech model…"
        return Transcriber(self.cfg, status=lambda s: self.events.put(("status", s)),
                           on_ready=lambda err: self.events.put(("model_ready", err)))

    def reload_model(self):
        """Load the model again with the current settings (after a device change or a failure)."""
        self.transcriber = self._new_transcriber()
        self._tray_update()

    def _on_status(self, text):
        if self.transcriber.ready.is_set():
            return
        if text:
            self.model_status = text
            if self.state == "idle":
                self.overlay.set("busy", text)
        elif self.state == "idle":
            self.overlay.set("hidden")
        self._tray_update()

    def _on_model_ready(self, err):
        hotkey = self.platform.hotkey_label(self.cfg)
        if err:
            self.model_status = "Speech model failed to load (see the log)"
            if self.state == "idle":
                self._flash("Couldn't load the speech model")
            self.notify(f"Couldn't load the speech model: {err[:200]}")
        else:
            dev = {"cpu": "CPU", "directml": "GPU (DirectML)", "cuda": "GPU (CUDA)"}.get(
                self.transcriber.device, self.transcriber.device)
            self.model_status = f"Ready on {dev}: press {hotkey}"
            if self.state == "idle" and self.overlay.state == "busy":
                self._flash(f"Ready. Press {hotkey} to dictate", 3000)
            if not load_state().get("welcomed"):
                save_state(welcomed=True)
                self.notify(f"Running in the background. Press {hotkey} in any app, speak, "
                            "then press it again.")
        self._tray_update()

    # -- mics
    def _mic_options(self):
        rec = self.recorder
        names = dict(rec.mics)
        auto = ("Automatic" if self.platform.name == "linux" and self.cfg.get("pulse_source")
                else "System default")
        chosen = rec.choice if rec.choice in names else None
        return [(None, auto, chosen is None)] + [(k, short_mic_name(v), k == chosen)
                                                 for k, v in rec.mics]

    def _choose_mic(self, key):
        if self.state != "recording":
            return
        try:
            self.recorder.choose(key)
        except Exception as e:  # noqa: BLE001
            log.exception("Couldn't switch to mic %r; going back to automatic", key)
            try:
                self.recorder.choose(None)  # the chip then shows which mic is really in use
            except Exception:  # noqa: BLE001
                log.exception("Automatic mic failed too")
                self._handle("cancel")
                self._flash(f"Mic error: {str(e)[:28]}")

    # -- events
    def _pump(self):
        try:
            while True:
                ev = self.events.get_nowait()
                if isinstance(ev, tuple):
                    kind, arg = ev[0], (ev[1] if len(ev) > 1 else None)
                    if kind == "status":
                        self._on_status(arg)
                    elif kind == "model_ready":
                        self._on_model_ready(arg)
                    elif kind == "call":
                        arg()
                    elif kind == "quit":
                        self.quit()
                        return
                else:
                    self._handle(ev)
        except queue.Empty:
            pass
        self.root.after(30, self._pump)

    def _handle(self, ev):
        if ev == "toggle":
            ev = "start" if self.state == "idle" else "stop"
        if ev == "start" and self.state == "idle":
            if self.transcriber.error:
                self.reload_model()  # e.g. the download failed while offline: try again
            self.target = self.platform.capture_target()
            try:
                self.recorder.start()
            except Exception as e:  # noqa: BLE001
                log.exception("Mic error")
                self._flash(f"Mic error: {str(e)[:28]}")
                return
            self.state = "recording"
            self.platform.set_cancel_key(True)
            self.overlay.set("recording")
        elif ev == "stop" and self.state == "recording":
            audio = self.recorder.stop()
            self.platform.set_cancel_key(False)
            self.state = "busy"
            self.job += 1
            ready = self.transcriber.ready.is_set()
            self.overlay.set("busy", "Transcribing" if ready else self.model_status)
            threading.Thread(target=self._work, args=(self.transcriber, audio, self.job),
                             daemon=True).start()
        elif ev == "cancel":
            if self.state == "recording":
                self.recorder.stop()
            self.platform.set_cancel_key(False)
            self.job += 1  # drop any in-flight transcription
            self.state = "idle"
            self.overlay.set("hidden")
        self._tray_update()

    def _work(self, transcriber, audio, job):
        t = time.time()
        try:
            text = clean_text(transcriber.transcribe(audio), self.cfg)
            log.info("%.1fs audio -> %.2fs: %r", audio.size / SAMPLE_RATE, time.time() - t, text)
        except Exception:  # noqa: BLE001
            log.exception("Transcription failed")
            text = None
        self.events.put(("call", lambda: self._done(text, job)))

    def _done(self, text, job):
        if job != self.job:
            return
        self.state = "idle"
        self._tray_update()
        if text is None:
            self._flash("Transcription failed")
            return
        if not text:
            self._flash("Didn't catch that")
            return
        self.last_text = text
        self._tray_update()
        self.overlay.set("hidden")
        self.root.update_idletasks()
        if self.platform.type_text(text, self.target, self.cfg) is False:
            self.copy_last()
            self.notify("Couldn't type into the window you started in, so the text is on the "
                        "clipboard. Press Ctrl+V to paste it.")

    def copy_last(self) -> bool:
        """Put the last transcript on the clipboard (UI thread)."""
        if not self.last_text:
            return False
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.last_text)
            self.root.update()
        except Exception:  # noqa: BLE001
            log.exception("Couldn't copy to the clipboard")
            return False
        return True

    def _flash(self, msg, ms=1400):
        self.overlay.set("info", msg)
        self.root.after(ms, lambda: self.state == "idle" and self.overlay.state == "info"
                        and self.overlay.msg == msg and self.overlay.set("hidden"))

    def notify(self, message: str):
        if self.tray:
            self.tray.notify(message)
        else:
            self.platform.notify(APP_DISPLAY_NAME, message)

    def _tray_update(self):
        if self.tray:
            self.tray.update()

    def quit(self):
        log.info("Quitting")
        if self.state == "recording":
            self.recorder.stop()
        if self.tray:
            self.tray.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def run():
    platform = get_platform()
    platform.setup_process()
    setup_logging()
    if not platform.acquire_single_instance():
        platform.error_box(APP_DISPLAY_NAME, f"{APP_DISPLAY_NAME} is already running. Look for "
                           "its icon in the notification area (system tray).")
        raise SystemExit(0)
    log.info("Starting %s %s", APP_NAME, VERSION)
    try:
        App(platform).run()
    except SystemExit:
        raise
    except Exception as e:
        log.exception("Crashed")
        platform.error_box(APP_DISPLAY_NAME, f"{APP_DISPLAY_NAME} stopped because of an error:\n\n"
                           f"{e}\n\nDetails are in the log file.")
        raise
