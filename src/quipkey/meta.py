"""The app's name and identity, in one place.

Everything user-visible or on disk that carries the app's name (per-user folders, the Linux
socket, systemd units, the KDE shortcut, the KWin script, the Windows installer, the tray icon)
is derived from these values. The build scripts read this file too, so renaming the app means
changing it here, plus the package folder name (src/quipkey) and pyproject.toml; see
CONTRIBUTING.md, "Renaming".

Keep this module free of imports: the Linux hotkey client and the build scripts load it.
"""

APP_NAME = "quipkey"                 # folders, binaries, unit/socket names: lowercase, no spaces
APP_DISPLAY_NAME = "Quipkey"         # shown in the tray, notifications and dialogs
APP_ID = "dev.quipkey.Quipkey"       # reverse-DNS id (D-Bus name, Windows AppUserModelID,
                                     # installer AppId): never change it after a release
VERSION = "0.1.0"
REPO_URL = "https://github.com/SamuelCGilbert/quipkey"
HOMEPAGE_URL = "https://quipkey.dev"      # not live yet; link it once the site exists
DESCRIPTION = "Press a hotkey, speak, and the text is typed into any app. Local speech recognition."
