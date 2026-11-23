"""Windows: RegisterHotKey for the global hotkey, SendInput (KEYEVENTF_UNICODE) to type,
so the clipboard is never touched."""
from __future__ import annotations

import ctypes
import logging
import os
import queue
import threading
import time
from ctypes import wintypes

from ..meta import APP_DISPLAY_NAME, APP_ID, APP_NAME
from .base import Platform

log = logging.getLogger(APP_NAME)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CreateMutexW.restype = wintypes.HANDLE
user32.GetForegroundWindow.restype = wintypes.HWND

MOD = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}
MOD_NOREPEAT = 0x4000
WM_HOTKEY, WM_APP = 0x0312, 0x8000
HK_MAIN, HK_ESC = 1, 2
VK_ESCAPE = 0x1B
KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x2, 0x4
ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _U(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def parse_hotkey(s: str):
    mods, vk = 0, None
    for part in s.lower().replace(" ", "").split("+"):
        if part in MOD:
            mods |= MOD[part]
        elif len(part) == 1:
            vk = ord(part.upper())
        elif part.startswith("f") and part[1:].isdigit():
            vk = 0x6F + int(part[1:])
        elif part == "space":
            vk = 0x20
        else:
            raise ValueError(f"Unsupported key in hotkey: {part}")
    if vk is None:
        raise ValueError(f"Hotkey {s!r} has no main key")
    return mods, vk


def foreground_exe() -> str:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
    h = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        kernel32.CloseHandle(h)


def _send(seq):
    arr = (INPUT * len(seq))(*[INPUT(type=1, u=_U(ki=KEYBDINPUT(vk, scan, f, 0, 0)))
                               for vk, scan, f in seq])
    return user32.SendInput(len(seq), arr, ctypes.sizeof(INPUT))


class HotkeyThread(threading.Thread):
    """Owns RegisterHotKey + the message loop. Esc is only grabbed while recording."""

    def __init__(self, hotkey: str, events: queue.Queue, should_passthrough):
        super().__init__(daemon=True, name="hotkey")
        self.mods, self.vk = parse_hotkey(hotkey)
        self.events = events
        self.should_passthrough = should_passthrough
        self.tid = None
        self.ok = threading.Event()
        self.failed = False

    def set_esc(self, on: bool):
        if self.tid:
            user32.PostThreadMessageW(self.tid, WM_APP + (1 if on else 2), 0, 0)

    def run(self):
        self.tid = kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, HK_MAIN, self.mods | MOD_NOREPEAT, self.vk):
            self.failed = True
            self.ok.set()
            return
        self.ok.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                if msg.wParam == HK_MAIN and self.should_passthrough():
                    self._passthrough()
                else:
                    self.events.put("toggle" if msg.wParam == HK_MAIN else "cancel")
            elif msg.message == WM_APP + 1:
                user32.RegisterHotKey(None, HK_ESC, MOD_NOREPEAT, VK_ESCAPE)
            elif msg.message == WM_APP + 2:
                user32.UnregisterHotKey(None, HK_ESC)

    def _passthrough(self):
        """Re-deliver the hotkey to the focused app: drop our registration, replay the key."""
        user32.UnregisterHotKey(None, HK_MAIN)
        try:
            mod_vks = [vk for bit, vk in ((0x2, 0x11), (0x4, 0x10), (0x1, 0x12), (0x8, 0x5B))
                       if self.mods & bit]
            held = [vk for vk in mod_vks if user32.GetAsyncKeyState(vk) & 0x8000]
            press = [vk for vk in mod_vks if vk not in held]  # re-press any already released
            seq = [(vk, 0, 0) for vk in press] + [(self.vk, 0, 0), (self.vk, 0, KEYEVENTF_KEYUP)]
            seq += [(vk, 0, KEYEVENTF_KEYUP) for vk in reversed(press)]
            _send(seq)
            time.sleep(0.15)  # let the replayed key be delivered before we grab it again
        finally:
            if not user32.RegisterHotKey(None, HK_MAIN, self.mods | MOD_NOREPEAT, self.vk):
                log.error("Failed to re-register hotkey after passthrough")


def wait_modifiers_released(timeout=1.5):
    end = time.time() + timeout
    while time.time() < end:
        if not any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in (0x10, 0x11, 0x12, 0x5B, 0x5C)):
            return
        time.sleep(0.02)


class WindowsPlatform(Platform):
    name = "windows"
    font = "Segoe UI"
    transparent_overlay = True
    has_tray = True

    def __init__(self):
        self.hk: HotkeyThread | None = None
        self._mutex = None
        self._hwnd = None

    def setup_process(self):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # crisp overlay on high-DPI displays
        except Exception:  # noqa: BLE001
            pass
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:  # noqa: BLE001
            pass

    def acquire_single_instance(self) -> bool:
        # The installer looks for this mutex (AppMutex) to know the app is running.
        self._mutex = kernel32.CreateMutexW(None, False, APP_ID)
        return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS

    def start_input(self, cfg, events, can_passthrough):
        apps = {a.lower() for a in cfg["passthrough_apps"]}

        def should_passthrough():
            return bool(apps) and can_passthrough() and foreground_exe().lower() in apps

        self.hk = HotkeyThread(cfg["hotkey"], events, should_passthrough)
        self.hk.start()
        self.hk.ok.wait(2)
        if self.hk.failed:
            self.error_box(APP_DISPLAY_NAME,
                           f"Couldn't register the {self.hotkey_label(cfg)} shortcut. Another app "
                           "is probably using it. Pick a different \"hotkey\" in the settings file.")
            raise SystemExit(1)

    def set_cancel_key(self, on):
        if self.hk:
            self.hk.set_esc(on)

    def capture_target(self):
        return user32.GetForegroundWindow()

    def type_text(self, text, target, cfg):
        if not text:
            return
        wait_modifiers_released()
        if target and user32.GetForegroundWindow() != target:
            user32.SetForegroundWindow(target)
            time.sleep(0.05)
        data = text.encode("utf-16-le")
        units = [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]
        seq = [(0, u, f) for u in units
               for f in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]
        sent = _send(seq)
        if sent != len(seq):
            log.warning("SendInput sent %d/%d (target may be elevated)", sent, len(seq))

    # -- overlay: a tool window that never activates, so focus stays in the user's app
    def overlay_init(self, win):
        win.attributes("-transparentcolor", win.cget("bg"))

    def overlay_show(self, win):
        if self._hwnd is None:
            win.deiconify()
            win.update_idletasks()
            hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
            GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = -20, 0x08000000, 0x80
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
            self._hwnd = hwnd
        user32.ShowWindow(self._hwnd, 4)  # SW_SHOWNOACTIVATE
        # HWND_TOPMOST, SWP_NOMOVE|SWP_NOSIZE|SWP_NOACTIVATE
        user32.SetWindowPos(self._hwnd, -1, 0, 0, 0, 0, 0x1 | 0x2 | 0x10)

    def overlay_hide(self, win):
        if self._hwnd:
            user32.ShowWindow(self._hwnd, 0)
        else:
            win.withdraw()

    def error_box(self, title, message):
        user32.MessageBoxW(None, message, title, 0x10)
