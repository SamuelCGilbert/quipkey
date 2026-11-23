"""Settings (config.json, edited by hand), UI state (state.json) and logging."""
from __future__ import annotations

import json
import logging
import sys

from . import paths
from .meta import APP_NAME

log = logging.getLogger(APP_NAME)

DEFAULT_CONFIG: dict = {
    # Any onnx-asr model id, e.g. "nemo-parakeet-tdt-0.6b-v2" (English, best),
    # "nemo-parakeet-tdt-0.6b-v3" (25 European languages), "onnx-community/whisper-large-v3-turbo".
    "model": "nemo-parakeet-tdt-0.6b-v2",
    # "auto": int8 on the CPU (670 MB download), full precision (fp32, 2.5 GB) on a GPU.
    # Or "int8", or null for fp32.
    "quantization": "auto",
    # "auto": CUDA if this install has onnxruntime-gpu, else CPU.
    # "directml" (Windows builds): any DirectX 12 GPU. Faster on a discrete GPU, but it keeps
    # about 2.5 GB of video memory while the app runs. "cuda" | "cpu".
    "device": "auto",
    "hotkey": "ctrl+shift+d",      # Windows only; on Linux bind it in your desktop's settings
    "input_device": None,          # sounddevice input name/index; null = system default
    "remove_fillers": True,        # drop "um", "uh", ...
    "trailing_space": True,        # add a space after the text so consecutive dictations join
    "pulse_source": None,          # Linux: PulseAudio/PipeWire source name (or a list, first
                                   # one present wins) from `pactl list short sources`
    "linux_typer": "auto",         # "auto" | "uinput" | "wtype" | "ydotool" | "clipboard"
    # "auto": ask KWin which window has focus and send Shift+Insert to terminals, Ctrl+V to
    # everything else. Or a fixed combo: "ctrl+v" | "shift+insert" | "ctrl+shift+v".
    "linux_paste_keys": "auto",
    # Linux, for "auto": substrings of a terminal's window class (case-insensitive).
    "linux_terminal_apps": ["konsole", "yakuake", "terminal", "kitty", "alacritty", "foot",
                            "wezterm", "ghostty", "ptyxis", "xterm", "urxvt", "tilix", "guake",
                            "tilda", "st-256color"],
    # When one of these apps is focused (and the app is idle), the hotkey goes to that app
    # instead (T3 Code has its own Ctrl+Shift+D voice input). Windows: exe names.
    # Linux (KDE): set by the KWin script's config; see the README.
    "passthrough_apps": ["T3 Code (Beta).exe", "T3 Code.exe"],
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    path = paths.config_path()
    if path.exists():
        try:
            user = json.loads(path.read_text(encoding="utf-8"))
            unknown = sorted(set(user) - set(DEFAULT_CONFIG))
            if unknown:
                log.warning("Unknown settings in %s ignored: %s", path, ", ".join(unknown))
            cfg.update({k: v for k, v in user.items() if k in DEFAULT_CONFIG})
        except Exception as e:  # noqa: BLE001
            log.error("Bad %s, using defaults: %s", path, e)
    return cfg


def ensure_config_file():
    """Create config.json with every setting at its default, so there's something to edit."""
    path = paths.config_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n", encoding="utf-8")
    return path


def set_config_value(key: str, value):
    """Change one setting in config.json, keeping the user's other settings."""
    path = paths.config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:  # noqa: BLE001
        log.exception("Couldn't read %s; not saving %s", path, key)
        return
    data[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_state() -> dict:
    try:
        return json.loads(paths.state_path().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_state(**kw):
    st = load_state()
    st.update(kw)
    path = paths.state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(st, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        log.exception("Couldn't save %s", path)


def setup_logging():
    path = paths.log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # keep one old log around, so a long-running install doesn't grow without bound
    try:
        if path.exists() and path.stat().st_size > 2_000_000:
            path.replace(path.with_suffix(".log.1"))
    except OSError:
        pass
    handlers: list[logging.Handler] = [logging.FileHandler(path, encoding="utf-8")]
    if sys.stderr:
        handlers.append(logging.StreamHandler())
    for h in handlers:
        h.addFilter(_quiet_libraries)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=handlers)


_NOISY = ("httpx", "httpcore", "huggingface_hub", "urllib3", "PIL")


def _quiet_libraries(record: logging.LogRecord) -> bool:
    """Drop libraries' info chatter (one line per HTTP request during the model download)."""
    return record.levelno >= logging.ERROR or not record.name.startswith(_NOISY)
