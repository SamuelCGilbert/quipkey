"""Microphone recording (16 kHz mono) and the list of mics for the picker."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys

import numpy as np

from .config import load_state, save_state
from .meta import APP_NAME

log = logging.getLogger(APP_NAME)
IS_WIN = sys.platform == "win32"
SAMPLE_RATE = 16000
TEST_WAV_ENV = f"{APP_NAME.upper()}_TEST_WAV"  # debugging: use a 16 kHz mono wav instead of the mic


def _sd():
    if sys.platform.startswith("linux") and getattr(sys, "frozen", False):
        # Frozen Linux build: use the bundled PortAudio (sounddevice only searches the system).
        import ctypes.util

        bundled = os.path.join(getattr(sys, "_MEIPASS", ""), "libportaudio.so.2")
        if os.path.exists(bundled) and not getattr(ctypes.util, "_app_patched", False):
            orig = ctypes.util.find_library
            ctypes.util.find_library = lambda name: bundled if name == "portaudio" else orig(name)
            ctypes.util._app_patched = True
    import sounddevice

    return sounddevice


sd = _sd()


def list_mics() -> list[tuple[str, str]]:
    """[(key, display name)] of the input devices that exist right now."""
    if IS_WIN:
        try:  # re-scan so plugged-in/unplugged devices show up (only call with no stream open)
            sd._terminate()
            sd._initialize()
        except Exception:  # noqa: BLE001
            pass
        out = []
        for d in sd.query_devices():
            api = sd.query_hostapis(d["hostapi"])["name"]
            # DirectSound: full names (MME truncates to 31 chars) and resamples to 16 kHz for us
            if (d["max_input_channels"] > 0 and api == "Windows DirectSound"
                    and d["name"] != "Primary Sound Capture Driver"):
                out.append((d["name"], d["name"]))
        return out
    try:
        res = subprocess.run(["pactl", "-f", "json", "list", "sources"], capture_output=True,
                             text=True, timeout=3)

        def label(s):  # PCI audio = the laptop's own mic; its description is a chipset name
            if (s.get("properties") or {}).get("device.bus") == "pci":
                return "Built-in mic"
            return s.get("description") or s["name"]
        return [(s["name"], label(s)) for s in json.loads(res.stdout)
                if not s["name"].endswith(".monitor")]
    except Exception:  # noqa: BLE001
        try:
            out = subprocess.run(["pactl", "list", "short", "sources"], capture_output=True,
                                 text=True, timeout=3).stdout
            names = [ln.split("\t")[1] for ln in out.splitlines() if "\t" in ln]
            return [(n, n) for n in names if not n.endswith(".monitor")]
        except Exception:  # noqa: BLE001
            return []


def pick_pulse_source(pref):
    """Return the first preferred PulseAudio/PipeWire source that currently exists."""
    prefs = [pref] if isinstance(pref, str) else list(pref)
    try:
        out = subprocess.run(["pactl", "list", "short", "sources"], capture_output=True,
                             text=True, timeout=3).stdout
        present = {line.split("\t")[1] for line in out.splitlines() if "\t" in line}
    except Exception:  # noqa: BLE001
        return prefs[0] if prefs else None
    for name in prefs:
        if name in present:
            return name
    log.warning("None of the preferred sources %s present; using system default", prefs)
    return None


class Recorder:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.chunks: list[np.ndarray] = []
        self.level = 0.0
        self.stream = None
        self.choice = load_state().get("mic")  # None = automatic (config / system default)
        self.mics: list[tuple[str, str]] = []
        self.active_label = ""

    def _cb(self, indata, frames, t, status):
        mono = indata[:, 0].copy()
        self.chunks.append(mono)
        rms = float(np.sqrt(np.mean(mono ** 2)) + 1e-9)
        self.level = max(0.0, min(1.0, (20 * np.log10(rms) + 55) / 45))  # -55dB..-10dB -> 0..1

    def _resolve(self):
        """-> (sounddevice device, display name) for the mic to record from."""
        names = dict(self.mics)
        if IS_WIN:
            if self.choice in names:
                idx = next(i for i, d in enumerate(sd.query_devices())
                           if d["name"] == self.choice and d["max_input_channels"] > 0
                           and sd.query_hostapis(d["hostapi"])["name"] == "Windows DirectSound")
                return idx, self.choice
            device = self.cfg["input_device"]
            try:
                return device, sd.query_devices(device, kind="input")["name"]
            except Exception:  # noqa: BLE001
                return device, "Default mic"
        device = self.cfg["input_device"]
        src = self.choice if self.choice in names else None
        if not src and self.cfg.get("pulse_source"):
            src = pick_pulse_source(self.cfg["pulse_source"])
        if src:
            os.environ["PULSE_SOURCE"] = src
            return device or "pulse", names.get(src, src)
        os.environ.pop("PULSE_SOURCE", None)
        try:
            default = subprocess.run(["pactl", "get-default-source"], capture_output=True,
                                     text=True, timeout=3).stdout.strip()
        except Exception:  # noqa: BLE001
            default = ""
        return device, names.get(default, "Default mic")

    def _open(self):
        device, self.active_label = self._resolve()
        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            device=device, callback=self._cb, blocksize=800,
        )
        self.stream.start()
        log.info("Recording from %s", self.active_label)

    def _close(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    def start(self):
        self.chunks = []
        self.level = 0.0
        self.mics = list_mics()
        if self.choice and self.choice not in dict(self.mics):
            log.warning("Chosen mic %r isn't connected; using the automatic choice", self.choice)
        self._open()

    def choose(self, key):
        """Switch mic (None = automatic). Keeps what was already recorded."""
        self.choice = key
        save_state(mic=key)
        if self.stream:
            self._close()
            self.level = 0.0
            self._open()

    def stop(self) -> np.ndarray:
        self._close()
        test_wav = os.environ.get(TEST_WAV_ENV)
        if test_wav:
            import wave
            with wave.open(test_wav) as w:
                return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        return np.concatenate(self.chunks) if self.chunks else np.zeros(0, dtype=np.float32)
