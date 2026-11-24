"""Speech recognition: downloads the model on first use, picks the ONNX Runtime provider."""
from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

from . import paths
from .meta import APP_NAME

log = logging.getLogger(APP_NAME)
SAMPLE_RATE = 16000

# Models live in our own data folder (so they're easy to find and delete), unless the user
# already points Hugging Face somewhere. Must be set before huggingface_hub is imported.
if not (os.environ.get("HF_HOME") or os.environ.get("HF_HUB_CACHE")):
    os.environ["HF_HUB_CACHE"] = str(paths.models_dir())
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")  # no console in windowed builds
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_VERBOSITY", "error")  # no "unauthenticated requests" warning
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")  # Windows without Developer Mode
# Plain HTTPS downloads: Xet keeps its own chunk cache outside the models folder (where we can't
# show progress, and which the uninstaller wouldn't clean up).
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

PROVIDERS = {
    "cuda": "CUDAExecutionProvider",
    "directml": "DmlExecutionProvider",
    "cpu": "CPUExecutionProvider",
}


def _repo_cache_dir(model: str) -> Path | None:
    """Hugging Face cache folder for a model id, to show download progress."""
    try:
        from onnx_asr.resolver import model_repos
    except Exception:  # noqa: BLE001
        log.warning("Can't show download progress: onnx_asr's model list isn't available")
        model_repos = {}
    repo = model if "/" in model else model_repos.get(model)
    if not repo:
        return None
    return Path(os.environ["HF_HUB_CACHE"] if os.environ.get("HF_HUB_CACHE")
                else Path(os.environ["HF_HOME"]) / "hub") / ("models--" + repo.replace("/", "--"))


def _dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def gpu_device(avail: list[str] | None = None) -> str | None:
    """The GPU provider this build can use ("cuda" first, then "directml"), or None."""
    if avail is None:
        import onnxruntime as ort

        avail = ort.get_available_providers()
    for dev in ("cuda", "directml"):
        if PROVIDERS[dev] in avail:
            return dev
    return None


class Transcriber:
    """Loads the model in a background thread. `status(text | None)` reports download progress
    ("Downloading speech model… 120 MB") and None when the download ends; `on_ready(error)` is
    called once loading finished (error None) or failed. Both run on the loader thread."""

    def __init__(self, cfg: dict, status: Callable[[str | None], None] = lambda s: None,
                 on_ready: Callable[[str | None], None] = lambda err: None):
        self.cfg = cfg
        self.status = status
        self.on_ready = on_ready
        self.model = None
        self.error: str | None = None
        self.device = ""
        self.ready = threading.Event()
        threading.Thread(target=self._load, daemon=True, name="model-load").start()

    # -- provider choice
    def _plan(self) -> tuple[str, str | None]:
        """-> (device, quantization) to try first."""
        import onnxruntime as ort

        avail = ort.get_available_providers()
        dev = str(self.cfg["device"]).lower()
        if dev == "auto":
            dev = gpu_device(avail) or "cpu"
        if dev not in PROVIDERS:
            log.warning("Unknown device %r; using the CPU", self.cfg["device"])
            dev = "cpu"
        if PROVIDERS[dev] not in avail:
            log.warning("%s isn't available in this build (have: %s); using the CPU",
                        PROVIDERS[dev], ", ".join(avail))
            dev = "cpu"
        q = self.cfg["quantization"]
        if q == "auto":
            q = "int8" if dev == "cpu" else None
        return dev, q

    def _session_args(self, dev: str) -> dict:
        import onnxruntime as ort

        if dev == "cuda":
            try:
                ort.preload_dlls()  # picks up CUDA/cuDNN from the nvidia-* pip wheels
            except Exception as e:  # noqa: BLE001
                log.warning("preload_dlls failed: %s", e)
        so = ort.SessionOptions()
        if dev == "directml":  # required by the DirectML provider
            so.enable_mem_pattern = False
            so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        providers = [PROVIDERS[dev]] + (["CPUExecutionProvider"] if dev != "cpu" else [])
        return {"providers": providers, "sess_options": so}

    def _watch_download(self, done: threading.Event):
        try:
            cache = _repo_cache_dir(self.cfg["model"])
            start = _dir_size(cache) if cache and cache.exists() else 0
            shown = False
            while not done.wait(0.5):
                got = (_dir_size(cache) if cache and cache.exists() else 0) - start
                if got > 1_000_000:  # only say "downloading" once bytes really arrive
                    if not shown:
                        log.info("Downloading the speech model into %s", cache)
                    shown = True
                    self.status(f"Downloading speech model… {got // 1_000_000} MB")
            if shown:
                self.status(None)
        except Exception:  # noqa: BLE001
            log.exception("Download progress watcher failed")

    def _load_one(self, dev: str, quant: str | None):
        import onnx_asr

        self.model = onnx_asr.load_model(self.cfg["model"], quantization=quant,
                                         **self._session_args(dev))
        self.model.recognize(np.zeros(SAMPLE_RATE // 2, dtype=np.float32))  # warm-up
        self.device = dev

    def _load(self):
        t = time.time()
        done = threading.Event()
        try:
            # Import before the watcher thread starts: it reads onnx_asr's model list, and
            # importing from two threads at once can hand it a half-initialized module.
            import onnx_asr  # noqa: F401
        except Exception:  # noqa: BLE001
            pass  # reported by _load_one below
        threading.Thread(target=self._watch_download, args=(done,), daemon=True).start()
        try:
            dev, quant = self._plan()
            try:
                self._load_one(dev, quant)
            except Exception:
                if dev == "cpu":
                    raise
                log.exception("Loading on %s failed; falling back to the CPU", dev)
                q = self.cfg["quantization"]
                dev, quant = "cpu", ("int8" if q == "auto" else q)
                self._load_one(dev, quant)
            log.info("Model %s (%s) ready on %s in %.1fs", self.cfg["model"], quant or "fp32",
                     dev, time.time() - t)
        except Exception as e:  # noqa: BLE001
            log.exception("Couldn't load the speech model")
            self.error = f"{type(e).__name__}: {e}"
        finally:
            done.set()
            self.ready.set()
            self.on_ready(self.error)

    def transcribe(self, audio: np.ndarray) -> str:
        self.ready.wait()
        if self.model is None:
            raise RuntimeError(f"Speech model isn't loaded: {self.error}")
        if audio.size < SAMPLE_RATE * 0.25:
            return ""
        # pad a little silence at the end; helps the decoder finish the last word
        audio = np.concatenate([audio, np.zeros(SAMPLE_RATE // 4, dtype=np.float32)])
        text = self.model.recognize(audio, sample_rate=SAMPLE_RATE)
        return text if isinstance(text, str) else str(text)
