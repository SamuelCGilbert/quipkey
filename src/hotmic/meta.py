"""The app's name and identity, in one place.

Everything user-visible or on disk that carries the app's name (per-user folders, the Linux
socket, systemd units, the KDE shortcut, the KWin script, the Windows installer, the tray icon)
is derived from these values. The build scripts read this file too, so renaming the app means
changing it here, plus the package folder name (src/hotmic) and pyproject.toml; see
CONTRIBUTING.md, "Renaming".

Keep this module free of imports: the Linux hotkey client and the build scripts load it.
"""

APP_NAME = "hotmic"                 # folders, binaries, unit/socket names: lowercase, no spaces
APP_DISPLAY_NAME = "hotmic"         # shown in the tray, notifications and dialogs
APP_ID = "io.github.samuelcgilbert.hotmic"  # reverse-DNS id (D-Bus name, Windows AppUserModelID)
VERSION = "0.1.0"
REPO_URL = "https://github.com/SamuelCGilbert/hotmic"
DESCRIPTION = "Press a hotkey, speak, and the text is typed into any app. Local speech recognition."
