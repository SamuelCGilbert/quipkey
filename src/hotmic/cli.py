"""Command line. Kept light: `<app> toggle` (bound to the Linux desktop shortcut) must answer
fast, so nothing heavy (numpy, onnxruntime, Tk) is imported until the app itself starts."""
from __future__ import annotations

import os
import socket
import subprocess
import sys

from .meta import APP_DISPLAY_NAME, APP_NAME, REPO_URL, VERSION

CLIENT_CMDS = ("toggle", "start", "stop", "cancel")

USAGE = f"""{APP_NAME} {VERSION}: press a hotkey, speak, and the text is typed into the focused app.

Usage:
  {APP_NAME}            Start (runs in the background; Windows: Ctrl+Shift+D)
  {APP_NAME} toggle     Linux: start/stop dictation (bind this to a keyboard shortcut)
  {APP_NAME} start | stop | cancel
  {APP_NAME} devices    List audio devices
  {APP_NAME} paths      Show where settings, logs and models are kept
  {APP_NAME} --version

Docs and bug reports: {REPO_URL}
"""


def send_command(cmd: str) -> bool:
    from .paths import runtime_socket_path

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(2)
        s.connect(runtime_socket_path())
        s.sendall(cmd.encode())
        return True
    except OSError:
        return False
    finally:
        s.close()


def _client(cmd: str) -> int:
    if sys.platform == "win32":
        print(f"On Windows the hotkey is built in; just run {APP_NAME}.", file=sys.stderr)
        return 2
    if send_command(cmd):
        return 0
    msg = f"{APP_DISPLAY_NAME} isn't running. Start it with: systemctl --user start {APP_NAME}"
    print(msg, file=sys.stderr)
    try:
        env = dict(os.environ)
        if "LD_LIBRARY_PATH_ORIG" in env:
            env["LD_LIBRARY_PATH"] = env.pop("LD_LIBRARY_PATH_ORIG")
        else:
            env.pop("LD_LIBRARY_PATH", None)
        subprocess.run(["notify-send", "-a", APP_DISPLAY_NAME, "-t", "4000", APP_DISPLAY_NAME, msg],
                       env=env, timeout=5)
    except Exception:  # noqa: BLE001
        pass
    return 1


def _paths():
    from . import paths

    print(f"settings: {paths.config_path()}")
    print(f"state:    {paths.state_path()}")
    print(f"log:      {paths.log_path()}")
    print(f"models:   {paths.models_dir()}")


def main(argv: list[str] | None = None):
    args = sys.argv[1:] if argv is None else argv
    cmd = args[0] if args else ""
    if cmd in CLIENT_CMDS:
        raise SystemExit(_client(cmd))
    if cmd in ("-h", "--help", "help"):
        print(USAGE)
        return
    if cmd in ("-V", "--version", "version"):
        print(f"{APP_NAME} {VERSION}")
        return
    if cmd == "paths":
        _paths()
        return
    if cmd == "devices":
        from .audio import sd

        print(sd.query_devices())
        return
    if cmd:
        print(f"Unknown command: {cmd}\n\n{USAGE}", file=sys.stderr)
        raise SystemExit(2)

    from .app import run

    run()
