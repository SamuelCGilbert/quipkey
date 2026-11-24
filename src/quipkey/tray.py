"""Notification-area (tray) icon: status, settings window, last transcript, quit. Windows only for now.

pystray runs its own thread; menu callbacks only post events to the app's queue.
"""
from __future__ import annotations

import logging
import webbrowser

from .icon import make_icon
from .meta import APP_DISPLAY_NAME, APP_NAME, REPO_URL, VERSION

log = logging.getLogger(APP_NAME)


class Tray:
    def __init__(self, app):
        import pystray

        self.app = app
        self.pystray = pystray
        self.images = {False: make_icon(64), True: make_icon(64, recording=True)}
        self._recording = False
        item, sep = pystray.MenuItem, pystray.Menu.SEPARATOR
        menu = pystray.Menu(
            item(f"{APP_DISPLAY_NAME} {VERSION}", None, enabled=False),
            item(lambda _: app.model_status, None, enabled=False),
            sep,
            item("Settings…", lambda: app.events.put("settings"), default=True),
            item("Copy last transcript", self._copy_last, enabled=lambda _: bool(app.last_text)),
            item("Help and bug reports", lambda: webbrowser.open(REPO_URL)),
            sep,
            item("Quit", lambda: app.events.put(("quit",))),
        )
        self.icon = pystray.Icon(APP_NAME, self.images[False], self._title(), menu)
        self.icon.run_detached()

    def _title(self):
        return f"{APP_DISPLAY_NAME}: {self.app.model_status}"[:127]

    def _copy_last(self):
        self.app.events.put(("call", self.app.copy_last))

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
