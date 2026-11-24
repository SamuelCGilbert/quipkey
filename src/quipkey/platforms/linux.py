"""Linux (developed on KDE Plasma 6 Wayland).

Wayland apps can't grab global hotkeys, so the app runs as a daemon on a unix socket and the
desktop's shortcut runs `<app> toggle`. Text goes in through the clipboard plus a paste
keystroke from a virtual uinput keyboard; the previous clipboard is restored afterwards.
"""
from __future__ import annotations

import logging
import os
import queue
import socket
import subprocess
import sys
import threading
import time
from shutil import which

from ..cli import CLIENT_CMDS, send_command
from ..meta import APP_DISPLAY_NAME, APP_ID, APP_NAME
from ..paths import runtime_socket_path
from .base import Platform

log = logging.getLogger(APP_NAME)


def _kde() -> bool:
    return "kde" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower()


class SocketListener(threading.Thread):
    def __init__(self, events: queue.Queue):
        super().__init__(daemon=True, name="socket")
        self.events = events
        path = runtime_socket_path()
        if os.path.exists(path):
            if send_command("ping"):
                raise SystemExit(f"{APP_NAME} is already running")
            os.unlink(path)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(path)
        os.chmod(path, 0o600)
        self.sock.listen(4)

    def run(self):
        while True:
            conn, _ = self.sock.accept()
            with conn:
                cmd = conn.recv(64).decode(errors="ignore").strip()
            if cmd in CLIENT_CMDS:
                self.events.put(cmd)


class UInputKeyboard:
    """Minimal virtual keyboard on /dev/uinput (pure Python, no ydotool daemon needed).
    Requires write access to /dev/uinput (logind 'uaccess' ACL or a udev rule)."""

    KEYS = {"ctrl": 29, "shift": 42, "alt": 56, "insert": 110, "v": 47, "meta": 125}

    def __init__(self):
        import fcntl
        import struct

        self.struct = struct
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, 0x40045564, 0x01)  # UI_SET_EVBIT EV_KEY
        for code in self.KEYS.values():
            fcntl.ioctl(self.fd, 0x40045565, code)  # UI_SET_KEYBIT
        name = f"{APP_NAME} virtual keyboard".encode()[:79]
        dev = struct.pack("80sHHHHi", name, 0x06, 0x1209, 0x5649, 1, 0) + b"\0" * (4 * 64 * 4)
        os.write(self.fd, dev)
        fcntl.ioctl(self.fd, 0x5501)  # UI_DEV_CREATE
        time.sleep(1.0)  # give the compositor time to pick up the new device (KWin: ~1 s)

    def _ev(self, typ, code, val):
        os.write(self.fd, self.struct.pack("llHHi", 0, 0, typ, code, val))

    def combo(self, keys: str):
        codes = [self.KEYS[k] for k in keys.lower().split("+")]
        for c in codes:
            self._ev(1, c, 1)
            self._ev(0, 0, 0)
            time.sleep(0.008)
        for c in reversed(codes):
            self._ev(1, c, 0)
            self._ev(0, 0, 0)
            time.sleep(0.008)


_uinput = None
_uinput_lock = threading.Lock()


def get_uinput():
    global _uinput
    with _uinput_lock:
        if _uinput is None:
            _uinput = UInputKeyboard()
    return _uinput


# ---- physical modifier state (so Shift+Insert isn't sent as Ctrl+Shift+Insert while the user
# is still holding the Ctrl+Shift+D chord). Needs read access to /dev/input/event* (group "input").

_MOD_KEYS = (29, 97, 42, 54, 56, 100, 125, 126)  # L/R ctrl, L/R shift, L/R alt, L/R meta
_EVIOCGKEY = 0x80000000 | (96 << 16) | (ord("E") << 8) | 0x18  # _IOR('E', 0x18, 96 bytes)


def _held_modifiers() -> list | None:
    """Modifier keycodes currently held on any physical keyboard; None if we can't tell."""
    import fcntl
    import glob

    held, readable = set(), False
    for path in glob.glob("/dev/input/event*"):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            buf = bytearray(96)
            fcntl.ioctl(fd, _EVIOCGKEY, buf)
            readable = True
            held.update(k for k in _MOD_KEYS if buf[k // 8] >> (k % 8) & 1)
        except OSError:
            pass
        finally:
            os.close(fd)
    return sorted(held) if readable else None


def wait_modifiers_released(timeout=1.5):
    t0 = time.time()
    held = _held_modifiers()
    if held is None:
        time.sleep(0.15)  # can't read key state; give the user a moment to let go of the chord
        return
    while held and time.time() - t0 < timeout:
        time.sleep(0.02)
        held = _held_modifiers() or []
    if held:
        log.warning("Modifier keys %s still held after %.1fs; pasting anyway", held, timeout)
    elif time.time() - t0 > 0.03:
        log.info("Waited %.2fs for modifier keys to be released", time.time() - t0)


# ---- CopyQ backend. Talks to the running CopyQ server over its local socket, so it creates no
# window/surface and can't move keyboard focus (unlike wl-copy/wl-paste on KWin).

# Runs inside the CopyQ server. argv: text. Saves the clipboard (all text formats and image/png, so
# images survive; Qt's dozens of on-the-fly image conversions are skipped because reading them
# takes seconds), sets the text, waits until the clipboard really holds it, prints
# "ready"/"timeout", then blocks on stdin until the caller has sent the paste keys and closed stdin.
# Then, unless something else was copied meanwhile, restores the previous clipboard: re-selects its
# CopyQ history item if one matches exactly, else re-copies the saved data. CopyQ doesn't record
# clipboard it set itself, so the dictated text is inserted into history at row 1 (below the
# restored item) so it can be recovered if a paste ever goes astray.
_COPYQ_PASTE_JS = r"""
var NL = String.fromCharCode(10);
var text = str(arguments[1]);
function fmts(list) {
  return str(list).split(NL).filter(function (f) {
    return f.indexOf('/') > 0 && f.indexOf('application/x-copyq-') != 0 && f != 'application/x-qt-image';
  });
}
var cur = fmts(clipboard('?')), png = cur.indexOf('image/png') >= 0;
var snap = {}, nsnap = 0;
cur.forEach(function (f) {
  if (png && f.indexOf('image/') == 0 && f != 'image/png') return;
  snap[f] = clipboard(f); nsnap++;
});
copy(text);
var ok = false;
for (var i = 0; i < 50; i++) { if (str(clipboard()) == text) { ok = true; break; } sleep(10); }
print((ok ? 'ready ' : 'timeout ') + nsnap + NL);
input();
var msg;
if (str(clipboard()) != text) {
  msg = 'kept: clipboard changed meanwhile';
} else if (nsnap == 0) {
  msg = 'kept: clipboard was empty';
} else {
  var row = -1, n = Math.min(size(), 20);
  for (var r = 0; r < n && row < 0; r++) {
    var fs = fmts(read('?', r)), m = fs.length > 0;
    for (var k = 0; m && k < fs.length; k++)
      m = (fs[k] in snap) && toBase64(read(fs[k], r)) == toBase64(snap[fs[k]]);
    if (m) row = r;
  }
  if (row >= 0) { select(row); msg = 'restored: history row ' + row; }
  else {
    var a = []; for (var f in snap) a.push(f, snap[f]);
    copy.apply(this, a); msg = 'restored: saved ' + Object.keys(snap).join(' ');
  }
}
insert(size() > 0 ? 1 : 0, text);
print(msg + NL);
"""


def _clean_env() -> dict:
    """Environment for desktop tools we start. A frozen (PyInstaller) build points
    LD_LIBRARY_PATH at its own bundled libraries; system programs must not see that."""
    env = dict(os.environ)
    orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if orig is not None:
        env["LD_LIBRARY_PATH"] = orig
    elif getattr(sys, "frozen", False):
        env.pop("LD_LIBRARY_PATH", None)
    for k in [k for k in env if k.startswith(("_PYI_", "_MEIPASS"))]:
        del env[k]  # PyInstaller's own bookkeeping; would confuse another frozen program
    return env


def _run(args, **kw):
    kw.setdefault("env", _clean_env())
    return subprocess.run(args, **kw)


def _copyq_client():
    """(argv0, env) for talking to the running CopyQ server, or None if it isn't running.
    Uses the server's own binary and COPYQ_* settings paths (e.g. a CopyQ build started by
    a wrapper with its own config dir), since a different copyq can't reach that server."""
    try:
        pids = _run(["pgrep", "-u", str(os.getuid()), "-x", "copyq"],
                    capture_output=True, text=True, timeout=2).stdout.split()
    except Exception:  # noqa: BLE001
        return None
    for pid in pids:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                argv = f.read().split(b"\0")
            if any(a.startswith(b"--clipboard-access") for a in argv):
                continue  # helper process, not the server
            exe = os.readlink(f"/proc/{pid}/exe")
            with open(f"/proc/{pid}/environ", "rb") as f:
                penv = dict(kv.split(b"=", 1) for kv in f.read().split(b"\0") if b"=" in kv)
        except OSError:
            continue
        env = {k: v for k, v in _clean_env().items() if not k.startswith("COPYQ")}
        env.update({k.decode(): v.decode() for k, v in penv.items()
                    if k.startswith(b"COPYQ") and k not in (b"COPYQ_ACTION_ID",)})
        try:
            subprocess.run([exe, "eval", "--", "true"], env=env, capture_output=True,
                           timeout=3, check=True)
            return exe, env
        except Exception as e:  # noqa: BLE001
            log.warning("CopyQ server (pid %s, %s) not answering: %s", pid, exe, e)
    return None


def _copyq_paste(client, text: str, keys: str):
    import select as _select

    exe, env = client
    p = subprocess.Popen([exe, "eval", "--", _COPYQ_PASTE_JS, text], env=env,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True)
    try:
        status = ""
        if _select.select([p.stdout], [], [], 5)[0]:
            status = p.stdout.readline().strip()
        if not status.startswith("ready"):
            p.stdin.close()
            p.wait(timeout=2)
            err = p.stderr.read()[-300:].strip()
            raise RuntimeError(f"CopyQ couldn't set the clipboard ({status or 'no reply'}) {err}")
        get_uinput().combo(keys)
        time.sleep(0.4)  # the app fetches the clipboard data asynchronously after the keypress
        p.stdin.close()
        p.wait(timeout=5)
        out, err = p.stdout.read().strip(), p.stderr.read().strip()
        log.info("Pasted %d chars via CopyQ (%s); %s", len(text), status, out or err[-300:])
    finally:
        if p.poll() is None:
            p.kill()


def _klipper(method, *args):
    r = _run(["qdbus6", "org.kde.klipper", "/klipper", "org.kde.klipper.klipper." + method,
              *args], capture_output=True, text=True, timeout=3, check=True)
    return r.stdout[:-1] if r.stdout.endswith("\n") else r.stdout


def _klipper_ok() -> bool:
    if not _kde() or not which("qdbus6"):
        return False
    try:
        _klipper("getClipboardContents")
        return True
    except Exception:  # noqa: BLE001
        return False


# ---- focused window (KWin), to pick the paste keys. Wayland gives clients no way to ask, so we
# load a one-line KWin script that calls back over D-Bus with workspace.activeWindow. Talks D-Bus
# through libsystemd's sd-bus via ctypes (no extra Python packages); a query takes ~2 ms.

class KWinFocus:
    BUS_NAME = APP_ID.encode()
    SCRIPT = (f'var w = workspace.activeWindow; callDBus("{APP_ID}", "/Focus", '
              f'"{APP_ID}", "Focus", w ? [w.resourceClass, w.resourceName, '
              'w.caption].join("\\n") : "");')

    def __init__(self):
        import ctypes

        self.ct = ct = ctypes
        self.sd = sd = ctypes.CDLL("libsystemd.so.0")
        self.bus = ct.c_void_p()
        if sd.sd_bus_open_user(ct.byref(self.bus)) < 0:
            raise OSError("can't connect to the session bus")
        if sd.sd_bus_request_name(self.bus, self.BUS_NAME, ct.c_uint64(0)) < 0:
            raise OSError(f"D-Bus name {APP_ID} is taken")
        self._handler = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, ct.c_void_p, ct.c_void_p)(self._on_call)
        sd.sd_bus_add_object(self.bus, None, b"/Focus", self._handler, None)
        self.script_path = os.path.join(os.path.dirname(runtime_socket_path()),
                                        f"{APP_NAME}-focus.js")
        with open(self.script_path, "w") as f:
            f.write(self.SCRIPT)
        self.lock = threading.Lock()
        self.result = None
        self.n = 0

    def _on_call(self, msg, _userdata, _err):
        s = self.ct.c_char_p()
        if self.sd.sd_bus_message_read(self.ct.c_void_p(msg), b"s", self.ct.byref(s)) >= 0:
            self.result = (s.value or b"").decode(errors="replace")
        self.sd.sd_bus_reply_method_return(self.ct.c_void_p(msg), b"")
        return 1

    def _kwin(self, path, iface, member, sig, *args):
        ct, reply, ret = self.ct, self.ct.c_void_p(), None
        r = self.sd.sd_bus_call_method(self.bus, b"org.kde.KWin", path, iface, member, None,
                                       ct.byref(reply), sig, *args)
        if r >= 0 and member == b"loadScript":
            i = ct.c_int(-1)
            self.sd.sd_bus_message_read(reply, b"i", ct.byref(i))
            ret = i.value
        self.sd.sd_bus_message_unref(reply)
        if r < 0:
            raise OSError(-r, f"KWin {member.decode()} failed")
        return ret

    def query(self, timeout=0.3) -> str | None:
        """'resourceClass\\nresourceName\\ncaption' of the active window, '' if none, None on timeout."""
        with self.lock:
            self.n += 1
            name = f"{APP_NAME}-focus-{os.getpid()}-{self.n}".encode()
            self.result = None
            sid = self._kwin(b"/Scripting", b"org.kde.kwin.Scripting", b"loadScript", b"ss",
                             self.script_path.encode(), name)
            try:
                if sid is None or sid < 0:
                    raise OSError("KWin wouldn't load the focus script")
                self._kwin(b"/Scripting/Script%d" % sid, b"org.kde.kwin.Script", b"run", b"")
                t0 = time.time()
                while self.result is None and time.time() - t0 < timeout:
                    while self.sd.sd_bus_process(self.bus, None) > 0:
                        pass
                    if self.result is None:
                        self.sd.sd_bus_wait(self.bus, self.ct.c_uint64(20000))
            finally:
                self._kwin(b"/Scripting", b"org.kde.kwin.Scripting", b"unloadScript", b"s", name)
            return self.result


_kwin_focus = None


def focused_window() -> str | None:
    global _kwin_focus
    if not _kde():
        return None
    try:
        if _kwin_focus is None:
            _kwin_focus = KWinFocus()
        return _kwin_focus.query()
    except Exception as e:  # noqa: BLE001
        log.warning("Couldn't ask KWin for the focused window: %s", e)
        return None


def paste_keys(cfg: dict) -> str:
    keys = cfg["linux_paste_keys"]
    if keys != "auto":
        return keys
    win = focused_window()
    if win is None:
        # Unknown window. Plain Qt/GTK apps, browsers and terminals all take Shift+Insert, but KDE
        # apps only if it's in the global "Paste" shortcut (which isn't the case by default).
        keys = "ctrl+v" if _kde() else "shift+insert"
        log.warning("Focused window unknown; pasting with %s", keys)
        return keys
    ident = " ".join(win.split("\n")[:2]).lower()
    term = any(t.lower() in ident for t in cfg["linux_terminal_apps"])
    keys = "shift+insert" if term else "ctrl+v"
    log.info("Focused window %r -> %s", ident, keys)
    return keys


def notify(title: str, message: str, ms: int = 3000):
    if which("notify-send"):
        try:
            _run(["notify-send", "-a", APP_DISPLAY_NAME, "-t", str(ms), title, message], timeout=5)
        except Exception:  # noqa: BLE001
            pass


def type_text(text: str, cfg: dict):
    if not text:
        return
    mode = cfg["linux_typer"]
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if mode == "auto":
        if os.access("/dev/uinput", os.W_OK):
            mode = "uinput"
        elif which("wtype") and "gnome" not in desktop and "kde" not in desktop:
            mode = "wtype"
        elif which("ydotool"):
            mode = "ydotool"
        else:
            mode = "clipboard"
    wait_modifiers_released()  # else the paste keys arrive as Ctrl+Shift+Insert etc.
    backend = mode
    try:
        if mode == "uinput":
            keys = paste_keys(cfg)
            # On KWin, wl-copy/wl-paste map a tiny window to get clipboard access; when it
            # closes, focus can land on a different window than the user's, so the paste goes
            # astray. CopyQ (if running) and Klipper set the clipboard over IPC instead.
            copyq = _copyq_client()
            if copyq:
                backend = "copyq"
                _copyq_paste(copyq, text, keys)
                return
            if _klipper_ok():
                # (Text only: a non-text clipboard, e.g. an image, isn't restored.)
                backend = "klipper"
                old = _klipper("getClipboardContents")
                _klipper("setClipboardContents", text)
                time.sleep(0.1)
                get_uinput().combo(keys)
                time.sleep(0.4)
                if old:
                    _klipper("setClipboardContents", old)
                log.info("Pasted %d chars via Klipper", len(text))
                return
            backend = "wl-clipboard"
            old = _run(["wl-paste", "-n"], capture_output=True, timeout=2).stdout
            _run(["wl-copy", "--", text], check=True, timeout=2)
            time.sleep(0.08)
            get_uinput().combo(keys)
            time.sleep(0.4)
            if old:
                _run(["wl-copy"], input=old, timeout=2)
            log.info("Pasted %d chars via wl-clipboard", len(text))
        elif mode == "wtype":
            _run(["wtype", "--", text], check=True, timeout=10)
        elif mode == "ydotool":
            # Paste via clipboard (layout-independent, handles unicode), then restore it.
            old = _run(["wl-paste", "-n"], capture_output=True, timeout=2).stdout
            _run(["wl-copy", "--", text], check=True, timeout=2)
            time.sleep(0.05)
            _run(["ydotool", "key", "29:1", "47:1", "47:0", "29:0"], check=True, timeout=5)
            time.sleep(0.3)
            if old:
                _run(["wl-copy"], input=old, timeout=2)
        else:
            _run(["wl-copy", "--", text], check=True, timeout=2)
            notify(APP_DISPLAY_NAME, "Copied to the clipboard (no way to type here)", 2500)
    except Exception as e:  # noqa: BLE001
        log.exception("Typing failed (mode=%s, clipboard backend=%s)", mode, backend)
        log.error("Paste failed (%s); transcript: %r", e, text)
        notify(f"{APP_DISPLAY_NAME}: paste failed", text, 20000)


class LinuxPlatform(Platform):
    name = "linux"

    def hotkey_label(self, cfg):
        return "your shortcut"

    def start_input(self, cfg, events, can_passthrough):
        # Passthrough on KDE is done by a KWin script that releases the global shortcut while a
        # passthrough app is focused (installed by install.sh), not here.
        SocketListener(events).start()
        if os.access("/dev/uinput", os.W_OK) and cfg["linux_typer"] in ("auto", "uinput"):
            threading.Thread(target=get_uinput, daemon=True).start()  # create device early

    def type_text(self, text, target, cfg):
        threading.Thread(target=type_text, args=(text, cfg), daemon=True).start()

    def hotkey_help(self):
        if _kde():
            return (f"Change it in System Settings → Keyboard → Shortcuts → "
                    f"{APP_DISPLAY_NAME} (toggle).")
        if "gnome" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower():
            return "Change it in Settings → Keyboard → Keyboard Shortcuts → Custom Shortcuts."
        return f"Set in your desktop's keyboard settings: it runs `{APP_NAME} toggle`."

    def _systemctl(self, *args):
        return _run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=10)

    def startup_enabled(self):
        try:
            r = self._systemctl("is-enabled", f"{APP_NAME}.service")
        except Exception:  # noqa: BLE001
            return None
        state = r.stdout.strip()
        if state in ("enabled", "enabled-runtime"):
            return True
        if state == "disabled":
            return False
        return None  # no unit installed (a source checkout)

    def set_startup(self, on):
        r = self._systemctl("enable" if on else "disable", f"{APP_NAME}.service")
        if r.returncode:
            raise RuntimeError(r.stderr.strip() or "systemctl failed")
        log.info("Start at sign-in: %s", on)

    def dark_mode(self):
        try:  # KDE: the window background of the active color scheme
            cfg = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                               "kdeglobals")
            section = ""
            with open(cfg, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("["):
                        section = line
                    elif section == "[Colors:Window]" and line.startswith("BackgroundNormal="):
                        r, g, b = (int(x) for x in line.split("=", 1)[1].split(",")[:3])
                        return 0.299 * r + 0.587 * g + 0.114 * b < 128
        except Exception:  # noqa: BLE001
            pass
        try:  # GNOME and others
            r = _run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                     capture_output=True, text=True, timeout=3)
            if r.returncode == 0 and r.stdout.strip():
                return "dark" in r.stdout
        except Exception:  # noqa: BLE001
            pass
        return True

    def overlay_init(self, win):
        try:
            win.wm_attributes("-type", "notification")
        except Exception:  # noqa: BLE001
            pass

    def error_box(self, title, message):
        log.error("%s: %s", title, message)
        notify(title, message, 10000)

    def notify(self, title, message):
        notify(title, message)
