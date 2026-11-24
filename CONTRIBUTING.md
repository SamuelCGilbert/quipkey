# Contributing to Quipkey

Thanks for helping. Bug reports, ideas, docs fixes and code are all welcome.

- **Bugs and feature requests:** use the [issue forms](https://github.com/SamuelCGilbert/quipkey/issues/new/choose).
- **Questions and ideas:** [Discussions](https://github.com/SamuelCGilbert/quipkey/discussions).
- **Code:** for anything bigger than a small fix, open an issue first so we can agree on the approach.

Quipkey is GPL-3.0-or-later. Before your first pull request can be merged, you sign the [Contributor License Agreement](CLA.md): a bot asks you to, and you sign by replying with one sentence. You keep the copyright to your work; the CLA lets the project also offer Quipkey under other terms (for example a paid edition) while the community edition stays GPL. Forks need their own name: see [TRADEMARKS.md](TRADEMARKS.md).

## Development setup

You need Python 3.10+ (3.12 is what the releases use) and, on Linux, `libportaudio2` and `python3-tk`. With [uv](https://docs.astral.sh/uv/):

```sh
uv venv --python 3.12
uv pip install -e ".[dev]"
uv run quipkey            # run from source
uv run pytest            # tests
uv run ruff check src tests scripts
```

Stop an installed copy first, because both want the same hotkey (Windows) or socket (Linux).

Useful while developing:

- `QUIPKEY_TEST_WAV=path/to/16k-mono.wav` replaces the microphone audio with a file, for repeatable end-to-end tests.
- `quipkey paths` shows where settings, the log and models are.
- The log file has every step: model load, which mic, transcription time, which paste method.

## How it's organized

```
src/quipkey/
  meta.py         the app's name, id, version and URL (the only place they're written)
  cli.py          command line; `quipkey toggle` must stay fast, so no heavy imports here
  paths.py        per-user folders on each OS
  config.py       settings (config.json), UI state (state.json), logging
  app.py          the state machine: idle -> recording -> busy -> idle
  audio.py        recording and the microphone list
  transcriber.py  model download and loading, CPU/GPU choice, transcription
  overlay.py      the pill (Tk), which never takes focus
  tray.py         notification-area icon (Windows)
  settings.py     the settings window (applies changes live)
  text.py         clean-up of the recognized text
  platforms/
    base.py       the interface each OS implements
    windows.py    RegisterHotKey, SendInput, no-activate overlay window
    linux.py      unix-socket daemon, uinput virtual keyboard, CopyQ/Klipper/wl-clipboard, KWin focus query
packaging/
  windows/installer.iss   Inno Setup script (per-user install)
  linux/install.sh        installer shipped in the Linux tarball (systemd unit, KDE/GNOME shortcut)
scripts/
  build.py                PyInstaller build + packages for the current OS
  build-linux.sh          the Linux build as CI runs it
  record_demo.py          records docs/demo.gif
  setup-github-repo.sh    repository settings, labels, Discussions
```

### Adding macOS

Write `platforms/macos.py` with a `Platform` subclass (global hotkey, typing, overlay window behavior), return it from `platforms/get_platform()`, and add a build to `scripts/build.py` and `.github/workflows/release.yml`. `paths.py` already has the macOS folders.

## Releasing

1. Update `VERSION` in `src/quipkey/meta.py`.
2. Commit, then tag and push: `git tag v0.2.0 && git push origin main v0.2.0`.
3. The **Release** workflow builds the Windows installer and zip (on `windows-latest`) and the Linux tarball (on `ubuntu-22.04`, for glibc 2.35+), then creates the GitHub release with checksums. It fails if the tag doesn't match `VERSION`.

To build locally: `python scripts/build.py` (Windows; Inno Setup 6 makes the installer) or `scripts/build-linux.sh`. To get CI artifacts without releasing, run the Release workflow by hand.

## Renaming the app

The name is written in as few places as possible:

1. `src/quipkey/meta.py`: `APP_NAME`, `APP_DISPLAY_NAME`, `APP_ID`, `REPO_URL`. Everything at runtime (folders, socket, systemd units, KDE shortcut, KWin script, D-Bus name, tray, installer, build artifacts) comes from these.
2. The package folder `src/quipkey/` and, in `pyproject.toml`, the project name, the `[project.scripts]` entry and the paths. Imports inside the package are relative, so they don't change.
3. The tests (`from quipkey import ...`) and the `QUIPKEY_TEST_WAV` mention in docs (the variable is `<APP_NAME>_TEST_WAV`).
4. Docs and GitHub links: `git grep -i quipkey`.

Existing installs keep their old folders; uninstall the old name first.
