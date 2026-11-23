"""Notification-area (tray) icon: status, settings, quit. Windows only for now.

pystray runs its own thread; menu callbacks only post events to the app's queue.
"""
from __future__ import annotations

import logging
import os
import webbrowser

from . import paths
from .config import ensure_config_file, set_config_value
from .icon import make_icon
from .meta import APP_DISPLAY_NAME, APP_NAME, REPO_URL, VERSION

log = logging.getLogger(APP_NAME)


def _has_directml() -> bool:
    try:
        import onnxruntime as ort

        return "DmlExecutionProvider" in ort.get_available_providers()
    except Exception:  # noqa: BLE001
        return False


def _open(path):
    try:
        os.startfile(path)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        log.exception("Couldn't open %s", path)


class Tray:
    def __init__(self, app):
        import pystray

        self.app = app
        self.pystray = pystray
        self.images = {False: make_icon(64), True: make_icon(64, recording=True)}
        self._recording = False
        item, sep = pystray.MenuItem, pystray.Menu.SEPARATOR
        gpu = []
        if _has_directml():
            gpu = [item("Use the GPU (DirectML)", self._toggle_gpu,
                        checked=lambda _: str(app.cfg["device"]).lower() == "directml")]
        menu = pystray.Menu(
            item(f"{APP_DISPLAY_NAME} {VERSION}", None, enabled=False),
            item(lambda _: app.model_status, None, enabled=False),
            sep,
            *gpu,
            item("Settings file", self._settings),
            item("Log folder", lambda: _open(paths.log_dir())),
            item("Help and bug reports", lambda: webbrowser.open(REPO_URL)),
            sep,
            item("Quit", lambda: app.events.put(("quit",))),
        )
        self.icon = pystray.Icon(APP_NAME, self.images[False], self._title(), menu)
        self.icon.run_detached()

    def _title(self):
        return f"{APP_DISPLAY_NAME}: {self.app.model_status}"[:127]

    def _settings(self):
        path = ensure_config_file()
        self.notify("Quit and start the app again after you edit the settings.")
        _open(path)

    def _toggle_gpu(self):
        def change():
            app = self.app
            new = "cpu" if str(app.cfg["device"]).lower() == "directml" else "directml"
            set_config_value("device", new)
            app.cfg["device"] = new
            log.info("Device changed to %s from the tray menu", new)
            app.reload_model()
        self.app.events.put(("call", change))

    def update(self):
        """Called on the Tk thread after state changes."""
        try:
            rec = self.app.state == "recording"
            if rec != self._recording:
                self._recording = rec
                self.icon.icon = self.images[rec]
            self.icon.title = self._title()
            self.icon.update_menu()
        except Exception:  # noqa: BLE001
            log.debug("tray update failed", exc_info=True)

    def notify(self, message: str):
        try:
            self.icon.notify(message, APP_DISPLAY_NAME)
        except Exception:  # noqa: BLE001
            log.debug("tray notify failed", exc_info=True)

    def stop(self):
        try:
            self.icon.stop()
        except Exception:  # noqa: BLE001
            pass
