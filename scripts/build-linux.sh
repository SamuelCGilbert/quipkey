#!/usr/bin/env bash
# Build the Linux release tarball into dist/.
# Needs: uv, the system Python 3 with Tk and its shared library (Ubuntu/Debian:
# python3-tk python3-dev), and libportaudio2 (bundled into the build).
# CI runs this on ubuntu-22.04, so the result works on glibc 2.35+ (Ubuntu 22.04, Debian 12, ...).
set -euo pipefail
cd "$(dirname "$0")/.."
# The system Python, not uv's standalone builds: their Tk has no Xft, so it only sees old
# bitmap X fonts and the overlay and settings window look broken. Distro Tk uses fontconfig.
PY="${PYTHON:-/usr/bin/python3}"
if ! "$PY" -c "import tkinter" 2>/dev/null; then
  echo "$PY has no Tk. Install it first (Ubuntu/Debian: sudo apt install python3-tk python3-dev)." >&2
  exit 1
fi
rm -rf .venv-build
uv venv --python "$PY" --no-managed-python .venv-build
uv pip install --python .venv-build ".[dev]"
.venv-build/bin/python scripts/build.py "$@"
