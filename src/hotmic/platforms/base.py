"""The interface every platform backend implements."""
from __future__ import annotations

import queue
from collections.abc import Callable


class Platform:
    name = "unknown"
    font = "Sans"
    # Overlay: True if the window can have see-through corners (a "transparent color" key).
    transparent_overlay = False
    # Optional system tray icon (Windows only for now; on Linux the app runs as a service).
    has_tray = False

    def hotkey_label(self, cfg: dict) -> str:
        """How the user starts dictation, for messages: 'Ctrl+Shift+D'."""
        return "+".join(p.capitalize() if len(p) > 1 else p.upper()
                        for p in cfg["hotkey"].replace(" ", "").split("+"))

    def setup_process(self):
        """Called first, before any window exists (DPI awareness and the like)."""

    def acquire_single_instance(self) -> bool:
        """False if another copy is already running."""
        return True

    def start_input(self, cfg: dict, events: queue.Queue, can_passthrough: Callable[[], bool]):
        """Start delivering "toggle" / "start" / "stop" / "cancel" strings into `events`.
        `can_passthrough()` is True while idle: the hotkey may then go to a passthrough app."""
        raise NotImplementedError

    def set_cancel_key(self, on: bool):
        """Grab Esc (to cancel) while recording, where the platform supports it."""

    def capture_target(self):
        """Remember the focused window when recording starts (to type into it later)."""
        return None

    def type_text(self, text: str, target, cfg: dict):
        """Type `text` into the focused app. May block briefly; called on the UI thread."""
        raise NotImplementedError

    # -- overlay window
    def overlay_init(self, win):
        """Called once on the overlay's Tk Toplevel."""

    def overlay_show(self, win):
        win.deiconify()
        win.lift()

    def overlay_hide(self, win):
        win.withdraw()

    # -- messages
    def error_box(self, title: str, message: str):
        import sys

        print(f"{title}: {message}", file=sys.stderr)

    def notify(self, title: str, message: str):
        """A desktop notification, where available."""
