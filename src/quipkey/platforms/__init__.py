"""Platform backends. Each one provides the same small interface (see base.Platform):
global hotkey (or a socket the desktop's shortcut talks to), typing text into the focused app,
overlay window tweaks so it never takes focus, single-instance check, and errors/notifications.

To add macOS: write platforms/macos.py with a `MacPlatform(Platform)` and return it below.
"""
from __future__ import annotations

import sys

from .base import Platform


def get_platform() -> Platform:
    if sys.platform == "win32":
        from .windows import WindowsPlatform

        return WindowsPlatform()
    if sys.platform.startswith("linux"):
        from .linux import LinuxPlatform

        return LinuxPlatform()
    raise SystemExit(f"Sorry, {sys.platform} isn't supported yet.")


__all__ = ["Platform", "get_platform"]
