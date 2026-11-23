#!/usr/bin/env bash
# Build the Linux release tarball into dist/. Needs: uv, libportaudio2 (bundled into the build).
# CI runs this on ubuntu-22.04, so the result works on glibc 2.35+ (Ubuntu 22.04, Debian 12, ...).
set -euo pipefail
cd "$(dirname "$0")/.."
# uv's Python builds include Tk, so no system Tk packages are needed.
uv venv --allow-existing --python 3.12 --managed-python .venv-build
uv pip install --python .venv-build ".[dev]"
.venv-build/bin/python scripts/build.py "$@"
