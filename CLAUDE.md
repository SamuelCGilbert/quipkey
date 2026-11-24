# Quipkey

Push-to-talk dictation for the whole desktop. Press **Ctrl+Shift+D** in any app: a small "Listening" pill appears at the bottom of the screen. Press again to stop. The speech is transcribed locally (NVIDIA Parakeet TDT 0.6B v2 through [onnx-asr](https://github.com/istupakov/onnx-asr)) and typed into the focused app. No cloud, no account.

License: GPL-3.0-or-later. Dependencies are MIT/BSD/Apache, plus pystray (LGPL-3.0, Windows tray). The model weights are CC-BY-4.0 (NVIDIA): downloaded at runtime, credited in the README.

**Name:** Quipkey (display), `quipkey` (commands, folders), renamed from hotmic on 2026-11-23. Never hard-code it: use `meta.py` (`APP_NAME`, `APP_DISPLAY_NAME`, `APP_ID` = `dev.quipkey.Quipkey`, `REPO_URL`, `HOMEPAGE_URL`). Never change `APP_ID` after a release: it's the installer AppId, mutex and D-Bus name. Build scripts and installers read it from there. CONTRIBUTING.md → "Renaming" lists the few other places.

**Open core:** the GPL app stays free; a paid edition may come later. Contributions need the CLA (`CLA.md`, enforced by `.github/workflows/cla.yml`), so never merge outside code without it. Pro features and license checks never go in this public repo. The name/logo are covered by `TRADEMARKS.md`.

## Layout

See CONTRIBUTING.md → "How it's organized". Key points:

- `cli.py` must stay light: the Linux shortcut runs `quipkey toggle`, which only writes to a unix socket. Don't import numpy/onnxruntime/Tk there or in `meta.py`/`paths.py`.
- `app.py`: state machine `idle → recording → busy`, all on the Tk thread. Other threads (hotkey, socket, model loader, tray) only post to `App.events`. A job counter lets a cancel drop an in-flight transcription.
- `transcriber.py`: models go to `<data dir>/models` (HF cache layout) unless `HF_HOME`/`HF_HUB_CACHE` is set. Download progress is shown by watching that folder grow. `device: auto` = GPU when available (CUDA, then DirectML), else CPU; falls back to CPU if the GPU load fails. "Use the GPU" off = `device: cpu`. `quantization: auto` = int8 on CPU, fp32 on GPU.
- `settings.py`: the settings window (Tk, custom-drawn: cards, toggles, light/dark from the system; Pillow for smooth shapes). Changes save to config.json and apply live. Platform hooks in `platforms/base.py` (`set_hotkey`, `startup_enabled`/`set_startup`, `dark_mode`, `style_window`, `listen_for_show`). Opened from the tray (default item), by starting the app again (Windows: named event `<APP_ID>.show`), or `quipkey settings` (Linux: over the socket).
- Per-user dirs (`paths.py`): Windows `%APPDATA%\quipkey` (config, state) and `%LOCALAPPDATA%\quipkey` (log, models); Linux `~/.config/quipkey`, `~/.local/state/quipkey` (state, log), `~/.local/share/quipkey` (app, models).

### Windows
- Hotkey: `RegisterHotKey` on a message-loop thread. Esc is registered only while recording, to cancel.
- Typing: `SendInput` with `KEYEVENTF_UNICODE`, so the clipboard is normally never touched. The window that was in front at record start is brought back first (`focus_window`, using `AttachThreadInput`). If it's gone, it can't be brought back, or `SendInput` is short (an elevated window), `type_text` returns False and the app copies the text to the clipboard and notifies. The tray has **Copy last transcript**.
- Passthrough: if the foreground exe is in `passthrough_apps` (T3 Code by default) and the app is idle, unregister the hotkey, replay it with `SendInput`, then re-register.
- Single instance: a named mutex (`APP_ID`). A second start signals the event `<APP_ID>.show` and exits; the running copy opens Settings. Tray icon via pystray.
- Start at sign-in: HKCU `...\CurrentVersion\Run` value `Quipkey` (installer task + settings toggle; the uninstaller deletes it). Early builds used a Startup-folder shortcut, which the installer removes.
- Build: PyInstaller onedir, windowed + Inno Setup per-user installer (`packaging/windows/installer.iss`) + portable zip. ~51 MB installer.

### Linux (developed on KDE Plasma 6 Wayland)
- A daemon listens on `$XDG_RUNTIME_DIR/quipkey.sock`. The DE binds the shortcut to `quipkey toggle` (KDE: `quipkey-toggle.desktop` + `kglobalshortcutsrc`; GNOME: a custom keybinding). `install.sh` sets these up.
- Typing: a pure-Python uinput virtual keyboard sends the paste keys.
  - Needs write access to `/dev/uinput` (logind uaccess ACL or a udev rule).
  - Create the device at startup: KWin needs about 1 s to pick up a new device.
  - Wait until the user releases Ctrl/Shift (read `/dev/input/event*` with `EVIOCGKEY`), or the app receives Ctrl+Shift+V.
- Clipboard order: CopyQ (`copyq eval`, restores the previous clipboard including images) → Klipper over D-Bus → wl-clipboard. **wl-copy steals focus on KWin.**
- Paste key `auto`: ask KWin (a one-shot KWin script calling back over D-Bus as `APP_ID`) for the focused window class. Terminals get Shift+Insert, everything else Ctrl+V.
- T3 Code passthrough on KDE: KWin script `quipkey-passthrough` watches the active window and restarts `quipkey-hk-on/off.service`, which grab/release the shortcut through kglobalaccel. App regex: kwinrc `[Script-quipkey-passthrough] Apps=`.
- Build: PyInstaller onedir with the **system** Python 3 (`python3-tk`, `python3-dev`), not uv's managed Python: uv's Tk has no Xft and only sees bitmap X core fonts, so text looks broken. `PIL._tkinter_finder` is a hidden import (ImageTk needs it). Bundled `libportaudio.so.2`, system `libasound` (removed from the bundle so ALSA plugins match). The frozen app sets `LD_LIBRARY_PATH`; child processes (copyq, qdbus6, wl-copy, notify-send) must get the cleaned env (`_clean_env()`). Release builds run on ubuntu-22.04 (glibc 2.35+).

## Gotchas
- onnxruntime-gpu 1.2x+ needs CUDA 13 DLLs. Install `onnxruntime-gpu[cuda,cudnn]` and call `ort.preload_dlls()` (done for `device: cuda`). It can't be installed next to onnxruntime-directml.
- DirectML needs `enable_mem_pattern=False` and sequential execution. int8 on DirectML is no faster than CPU.
- Never write a literal NUL or tab into the source through shell patches (both have happened).
- `QUIPKEY_TEST_WAV=<16k mono wav>` (`<APP_NAME>_TEST_WAV`) replaces mic audio with a file, for end-to-end tests.
- The Windows dev install and an installed copy fight over the hotkey/mutex: stop one before testing the other.
