r"""Per-user folders. Light module: no third-party imports (the Linux hotkey client uses it).

Windows: config.json and state.json in %APPDATA%\<app>; the log and models/ in %LOCALAPPDATA%\<app>.
Linux:   config.json in $XDG_CONFIG_HOME/<app>; state.json and the log in $XDG_STATE_HOME/<app>;
         models/ in $XDG_DATA_HOME/<app>; the socket is $XDG_RUNTIME_DIR/<app>.sock.
macOS (later): ~/Library/Application Support/<app>, log in ~/Library/Logs/<app>.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .meta import APP_NAME

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"


def _xdg(var: str, default: str) -> Path:
    v = os.environ.get(var)
    return Path(v) if v and os.path.isabs(v) else Path.home() / default


def config_dir() -> Path:
    if IS_WIN:
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData/Roaming") / APP_NAME
    if IS_MAC:
        return Path.home() / "Library/Application Support" / APP_NAME
    return _xdg("XDG_CONFIG_HOME", ".config") / APP_NAME


def state_dir() -> Path:
    if IS_WIN or IS_MAC:
        return config_dir()
    return _xdg("XDG_STATE_HOME", ".local/state") / APP_NAME


def log_dir() -> Path:
    if IS_WIN:
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / APP_NAME
    if IS_MAC:
        return Path.home() / "Library/Logs" / APP_NAME
    return state_dir()


def data_dir() -> Path:
    if IS_WIN:
        return log_dir()
    if IS_MAC:
        return config_dir()
    return _xdg("XDG_DATA_HOME", ".local/share") / APP_NAME


def config_path() -> Path:
    return config_dir() / "config.json"


def state_path() -> Path:
    return state_dir() / "state.json"


def log_path() -> Path:
    return log_dir() / f"{APP_NAME}.log"


def models_dir() -> Path:
    return data_dir() / "models"


def runtime_socket_path() -> str:
    """Unix socket the Linux daemon listens on (`<app> toggle` writes to it)."""
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/{APP_NAME}-{os.getuid()}"
    os.makedirs(base, mode=0o700, exist_ok=True)
    return os.path.join(base, f"{APP_NAME}.sock")
