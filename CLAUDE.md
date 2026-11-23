# hotmic

Push-to-talk dictation for the whole desktop. Press **Ctrl+Shift+D** in any app: a small "Listening" pill appears at the bottom of the screen. Press again to stop. The speech is transcribed locally (NVIDIA Parakeet TDT 0.6B v2 through [onnx-asr](https://github.com/istupakov/onnx-asr)) and typed into the focused app. No cloud, no account.

License: GPL-3.0-or-later. Dependencies are MIT/BSD/Apache, plus pystray (LGPL-3.0, Windows tray). The model weights are CC-BY-4.0 (NVIDIA): downloaded at runtime, credited in the README.

**The name may still change.** Never hard-code it: use `meta.py` (`APP_NAME`, `APP_DISPLAY_NAME`, `APP_ID`, `REPO_URL`). Build scripts and installers read it from there. CONTRIBUTING.md → "Renaming" lists the few other places.

## Layout

See CONTRIBUTING.md → "How it's organized". Key points:

- `cli.py` must stay light: the Linux shortcut runs `hotmic toggle`, which only writes to a unix socket. Don't import numpy/onnxruntime/Tk there or in `meta.py`/`paths.py`.
- `app.py`: state machine `idle → recording → busy`, all on the Tk thread. Other threads (hotkey, socket, model loader, tray) only post to `App.events`. A job counter lets a cancel drop an in-flight transcription.
- `transcriber.py`: models go to `<data dir>/models` (HF cache layout) unless `HF_HOME`/`HF_HUB_CACHE` is set. Download progress is shown by watching that folder grow. `device: auto` = CUDA if present, else CPU; DirectML only when chosen (tray toggle or config), because it holds ~2.5 GB VRAM. `quantization: auto` = int8 on CPU, fp32 on GPU.
- Per-user dirs (`paths.py`): Windows `%APPDATA%\hotmic` (config, state) and `%LOCALAPPDATA%\hotmic` (log, models); Linux `~/.config/hotmic`, `~/.local/state/hotmic` (state, log), `~/.local/share/hotmic` (app, models).

### Windows
- Hotkey: `RegisterHotKey` on a message-loop thread. Esc is registered only while recording, to cancel.
- Typing: `SendInput` with `KEYEVENTF_UNICODE`, so the clipboard is never touched.
- Passthrough: if the foreground exe is in `passthrough_apps` (T3 Code by default) and the app is idle, unregister the hotkey, replay it with `SendInput`, then re-register.
- Single instance: a named mutex (`APP_ID`). Tray icon via pystray.
- Build: PyInstaller onedir, windowed + Inno Setup per-user installer (`packaging/windows/installer.iss`) + portable zip. ~51 MB installer.

### Linux (developed on KDE Plasma 6 Wayland)
- A daemon listens on `$XDG_RUNTIME_DIR/hotmic.sock`. The DE binds the shortcut to `hotmic toggle` (KDE: `hotmic-toggle.desktop` + `kglobalshortcutsrc`; GNOME: a custom keybinding). `install.sh` sets these up.
- Typing: a pure-Python uinput virtual keyboard sends the paste keys.
  - Needs write access to `/dev/uinput` (logind uaccess ACL or a udev rule).
  - Create the device at startup: KWin needs about 1 s to pick up a new device.
  - Wait until the user releases Ctrl/Shift (read `/dev/input/event*` with `EVIOCGKEY`), or the app receives Ctrl+Shift+V.
- Clipboard order: CopyQ (`copyq eval`, restores the previous clipboard including images) → Klipper over D-Bus → wl-clipboard. **wl-copy steals focus on KWin.**
- Paste key `auto`: ask KWin (a one-shot KWin script calling back over D-Bus as `APP_ID`) for the focused window class. Terminals get Shift+Insert, everything else Ctrl+V.
- T3 Code passthrough on KDE: KWin script `hotmic-passthrough` watches the active window and restarts `hotmic-hk-on/off.service`, which grab/release the shortcut through kglobalaccel. App regex: kwinrc `[Script-hotmic-passthrough] Apps=`.
- Build: PyInstaller onedir with uv's managed Python 3.12 (includes Tk 9), bundled `libportaudio.so.2`, system `libasound` (removed from the bundle so ALSA plugins match). The frozen app sets `LD_LIBRARY_PATH`; child processes (copyq, qdbus6, wl-copy, notify-send) must get the cleaned env (`_clean_env()`). Release builds run on ubuntu-22.04 (glibc 2.35+).

## Gotchas
- onnxruntime-gpu 1.2x+ needs CUDA 13 DLLs. Install `onnxruntime-gpu[cuda,cudnn]` and call `ort.preload_dlls()` (done for `device: cuda`). It can't be installed next to onnxruntime-directml.
- DirectML needs `enable_mem_pattern=False` and sequential execution. int8 on DirectML is no faster than CPU.
- Never write a literal NUL or tab into the source through shell patches (both have happened).
- `HOTMIC_TEST_WAV=<16k mono wav>` (`<APP_NAME>_TEST_WAV`) replaces mic audio with a file, for end-to-end tests.
- The Windows dev install and an installed copy fight over the hotkey/mutex: stop one before testing the other.
