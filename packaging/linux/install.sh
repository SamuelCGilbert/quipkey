#!/usr/bin/env bash
# @APP_DISPLAY_NAME@ @VERSION@ installer for Linux. Installs for the current user; no root needed.
#
#   ./install.sh                     install or upgrade
#   ./install.sh --shortcut Meta+H   use a different shortcut (default Ctrl+Shift+D)
#   ./install.sh --no-shortcut       don't set up a keyboard shortcut
#   ./install.sh --no-passthrough    KDE: don't install the T3 Code passthrough KWin script
#   ./install.sh --uninstall         remove the app (keeps settings and the downloaded model)
#   ./install.sh --uninstall --purge remove everything
#
# @REPO_URL@
set -euo pipefail

APP="@APP_NAME@"
DISPLAY_NAME="@APP_DISPLAY_NAME@"
VERSION="@VERSION@"
REPO_URL="@REPO_URL@"

SHORTCUT="Ctrl+Shift+D"
DO_SHORTCUT=1
DO_PASSTHROUGH=1
UNINSTALL=0
PURGE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --shortcut) SHORTCUT="${2:?--shortcut needs keys, e.g. Ctrl+Shift+D}"; shift ;;
    --no-shortcut) DO_SHORTCUT=0 ;;
    --no-passthrough) DO_PASSTHROUGH=0 ;;
    --uninstall) UNINSTALL=1 ;;
    --purge) PURGE=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}"
PREFIX="$DATA/$APP"                 # app/ (the program) and models/ (downloaded on first run)
APPDIR="$PREFIX/app"
BIN="$HOME/.local/bin/$APP"
UNITDIR="$CONFIG/systemd/user"
DESKTOP_ID="$APP-toggle.desktop"
DESKTOP_FILE="$DATA/applications/$DESKTOP_ID"
ACTION_NAME="$DISPLAY_NAME (toggle)"
KWIN_ID="$APP-passthrough"
KWIN_DIR="$DATA/kwin/scripts/$KWIN_ID"
ICON="$DATA/icons/hicolor/256x256/apps/$APP.png"
GNOME_KEY="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/$APP/"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
ok() { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }
desktop() { printf '%s' "${XDG_CURRENT_DESKTOP:-}" | tr '[:upper:]' '[:lower:]'; }
is_kde() { case "$(desktop)" in *kde*) return 0 ;; esac; return 1; }
is_gnome() { case "$(desktop)" in *gnome*) return 0 ;; esac; return 1; }
kwrite() { if have kwriteconfig6; then kwriteconfig6 "$@"; else kwriteconfig5 "$@"; fi; }
kread() { if have kreadconfig6; then kreadconfig6 "$@"; else kreadconfig5 "$@"; fi; }
sysd() { systemctl --user "$@"; }

# "Ctrl+Shift+D" -> Qt key code (for kglobalaccel)
qt_keycode() {
  local code=0 part
  IFS='+' read -ra parts <<< "$1"
  for part in "${parts[@]}"; do
    case "${part,,}" in
      ctrl|control) code=$((code | 0x04000000)) ;;
      shift) code=$((code | 0x02000000)) ;;
      alt) code=$((code | 0x08000000)) ;;
      meta|super|win) code=$((code | 0x10000000)) ;;
      f[1-9]|f[1-2][0-9]) code=$((code | (0x01000030 + ${part:1} - 1))) ;;
      space) code=$((code | 0x20)) ;;
      ?) code=$((code | $(printf '%d' "'${part^^}"))) ;;
      *) echo "Unsupported key in shortcut: $part" >&2; return 1 ;;
    esac
  done
  echo "$code"
}

# "Ctrl+Shift+D" -> GNOME accelerator "<Control><Shift>d"
gnome_accel() {
  local out="" part
  IFS='+' read -ra parts <<< "$1"
  for part in "${parts[@]}"; do
    case "${part,,}" in
      ctrl|control) out+="<Control>" ;;
      shift) out+="<Shift>" ;;
      alt) out+="<Alt>" ;;
      meta|super|win) out+="<Super>" ;;
      *) out+="${part,,}" ;;
    esac
  done
  echo "$out"
}

# ------------------------------------------------------------------ KDE
kde_remove() {
  sysd stop "$APP-hk-on.service" "$APP-hk-off.service" 2>/dev/null || true
  rm -f "$UNITDIR/$APP-hk-on.service" "$UNITDIR/$APP-hk-off.service"
  if have gdbus; then
    gdbus call --session -d org.kde.kglobalaccel -o /kglobalaccel \
      -m org.kde.KGlobalAccel.unregister "$DESKTOP_ID" "_launch" >/dev/null 2>&1 || true
  fi
  if have kwriteconfig6 || have kwriteconfig5; then
    kwrite --file kglobalshortcutsrc --group services --group "$DESKTOP_ID" --key _launch --delete || true
    kwrite --file kwinrc --group Plugins --key "${KWIN_ID}Enabled" --delete || true
  fi
  if [ -d "$KWIN_DIR" ] && have gdbus; then
    gdbus call --session -d org.kde.KWin -o /Scripting \
      -m org.kde.kwin.Scripting.unloadScript "$KWIN_ID" >/dev/null 2>&1 || true
  fi
  rm -rf "$KWIN_DIR"
}

kde_setup() {
  local existing keys action
  if ! have gdbus || ! { have kwriteconfig6 || have kwriteconfig5; }; then
    warn "KDE: gdbus or kwriteconfig6 is missing, so no shortcut was set up."
    manual_shortcut_hint
    return
  fi
  # Keep a shortcut the user already changed in System Settings.
  existing="$(kread --file kglobalshortcutsrc --group services --group "$DESKTOP_ID" --key _launch 2>/dev/null || true)"
  if [ -n "$existing" ] && [ "$existing" != "none" ]; then
    SHORTCUT="${existing%%,*}"
  fi
  keys="$(qt_keycode "$SHORTCUT")"
  kwrite --file kglobalshortcutsrc --group services --group "$DESKTOP_ID" --key _launch "$SHORTCUT"
  action="['$DESKTOP_ID','_launch','$ACTION_NAME','$ACTION_NAME']"

  # Two one-shot units grab/release the shortcut. The passthrough KWin script restarts one of
  # them when focus moves, because KWin scripts can't pass int lists over D-Bus themselves.
  cat > "$UNITDIR/$APP-hk-on.service" <<EOF
[Unit]
Description=$DISPLAY_NAME: grab the $SHORTCUT global shortcut
Conflicts=$APP-hk-off.service

[Service]
Type=oneshot
RemainAfterExit=yes
# flags 6 = SetPresent|NoAutoloading
ExecStart=/usr/bin/env gdbus call --session -d org.kde.kglobalaccel -o /kglobalaccel -m org.kde.KGlobalAccel.setShortcut "$action" "[$keys]" 6
EOF
  cat > "$UNITDIR/$APP-hk-off.service" <<EOF
[Unit]
Description=$DISPLAY_NAME: release the global shortcut while a passthrough app is focused
Conflicts=$APP-hk-on.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/env gdbus call --session -d org.kde.kglobalaccel -o /kglobalaccel -m org.kde.KGlobalAccel.setInactive "$action"
EOF
  sysd daemon-reload
  gdbus call --session -d org.kde.kglobalaccel -o /kglobalaccel \
    -m org.kde.KGlobalAccel.doRegister "$action" >/dev/null 2>&1 || true
  if sysd restart "$APP-hk-on.service"; then
    ok "KDE shortcut: $SHORTCUT (change it in System Settings → Keyboard → Shortcuts → $ACTION_NAME)"
  else
    warn "Couldn't activate the shortcut now; it will work after you log in again."
  fi

  if [ "$DO_PASSTHROUGH" = 1 ]; then
    mkdir -p "$KWIN_DIR/contents/code"
    cat > "$KWIN_DIR/metadata.json" <<EOF
{
    "KPlugin": {
        "Id": "$KWIN_ID",
        "Name": "$DISPLAY_NAME: shortcut passthrough",
        "Description": "Releases the $DISPLAY_NAME shortcut while an app with its own use for it (T3 Code) is focused.",
        "Version": "$VERSION",
        "License": "GPL-3.0-or-later",
        "Website": "$REPO_URL",
        "EnabledByDefault": false
    },
    "X-Plasma-API": "javascript",
    "X-Plasma-MainScript": "code/main.js",
    "KPackageStructure": "KWin/Script"
}
EOF
    cat > "$KWIN_DIR/contents/code/main.js" <<EOF
// Release the $DISPLAY_NAME global shortcut while a passthrough app is focused; grab it again
// elsewhere. The app list is a regular expression matched against the window class, set in
// ~/.config/kwinrc: [Script-$KWIN_ID] Apps=t3code|t3 code
// kglobalaccel methods taking int lists can't be called from callDBus, so this restarts one of
// two conflicting systemd user units that do the call; systemd serializes them.
const PASSTHROUGH = new RegExp(readConfig("Apps", "t3code|t3 code"), "i");
let lastState = null;

function isPassthrough(w) {
    return !!w && (PASSTHROUGH.test(w.resourceClass || "") || PASSTHROUGH.test(w.resourceName || ""));
}

function apply(w) {
    const state = isPassthrough(w) ? "off" : "on";
    if (state === lastState) return;
    lastState = state;
    callDBus("org.freedesktop.systemd1", "/org/freedesktop/systemd1",
             "org.freedesktop.systemd1.Manager", "RestartUnit",
             "$APP-hk-" + state + ".service", "replace");
}

workspace.windowActivated.connect(function (w) {
    if (w) apply(w);  // null = transient no-focus (e.g. while switching); keep the current state
});
apply(workspace.activeWindow);
EOF
    kwrite --file kwinrc --group Plugins --key "${KWIN_ID}Enabled" true
    gdbus call --session -d org.kde.KWin -o /Scripting \
      -m org.kde.kwin.Scripting.unloadScript "$KWIN_ID" >/dev/null 2>&1 || true
    gdbus call --session -d org.kde.KWin -o /KWin -m org.kde.KWin.reconfigure >/dev/null 2>&1 || true
    ok "KWin script: the shortcut goes to T3 Code while it's focused (apps: [Script-$KWIN_ID] Apps= in kwinrc)"
  fi
}

# ------------------------------------------------------------------ GNOME
gnome_remove() {
  have gsettings || return 0
  local list
  list="$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings 2>/dev/null || true)"
  case "$list" in
    *"'$GNOME_KEY'"*)
      list="$(printf '%s' "$list" | sed -e "s#, '$GNOME_KEY'##; s#'$GNOME_KEY', ##; s#'$GNOME_KEY'##")"
      [ "$list" = "[]" ] && list="@as []"
      gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$list" ;;
  esac
  gsettings reset-recursively "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$GNOME_KEY" 2>/dev/null || true
}

gnome_setup() {
  if ! have gsettings; then
    warn "GNOME: gsettings is missing, so no shortcut was set up."
    manual_shortcut_hint
    return
  fi
  local list schema="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$GNOME_KEY"
  list="$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings)"
  case "$list" in
    *"'$GNOME_KEY'"*) ;;
    "@as []"|"[]") list="['$GNOME_KEY']" ;;
    *) list="${list%]}, '$GNOME_KEY']" ;;
  esac
  gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$list"
  gsettings set "$schema" name "$ACTION_NAME"
  gsettings set "$schema" command "$BIN toggle"
  gsettings set "$schema" binding "$(gnome_accel "$SHORTCUT")"
  ok "GNOME shortcut: $SHORTCUT (Settings → Keyboard → Custom Shortcuts)"
}

manual_shortcut_hint() {
  info "Bind a keyboard shortcut in your desktop's settings to run:"
  info "  $BIN toggle"
}

# ------------------------------------------------------------------ uninstall
if [ "$UNINSTALL" = 1 ]; then
  bold "Removing $DISPLAY_NAME"
  sysd disable --now "$APP.service" 2>/dev/null || true
  rm -f "$UNITDIR/$APP.service"
  kde_remove
  gnome_remove
  sysd daemon-reload 2>/dev/null || true
  rm -f "$BIN" "$DESKTOP_FILE" "$ICON"
  rm -rf "$APPDIR" "$PREFIX/install.sh"
  if [ "$PURGE" = 1 ]; then
    rm -rf "${PREFIX:?}" "${CONFIG:?}/${APP:?}" "${STATE:?}/${APP:?}"
    ok "Removed the app, settings and downloaded models."
  else
    rmdir "$PREFIX" 2>/dev/null || true
    ok "Removed. Kept your settings ($CONFIG/$APP) and models ($PREFIX/models)."
    info "Run with --uninstall --purge to delete those too."
  fi
  exit 0
fi

# ------------------------------------------------------------------ install
bold "Installing $DISPLAY_NAME $VERSION"
[ "$(uname -m)" = x86_64 ] || { echo "This build is for x86_64 only." >&2; exit 1; }
[ -x "$HERE/$APP/$APP" ] || { echo "Run this from the unpacked release folder." >&2; exit 1; }
have systemctl || { echo "systemd is required (to run $APP in the background)." >&2; exit 1; }

sysd stop "$APP.service" 2>/dev/null || true
mkdir -p "$PREFIX" "$HOME/.local/bin" "$UNITDIR" "$(dirname "$DESKTOP_FILE")" "$(dirname "$ICON")"
rm -rf "$APPDIR.new"
cp -a "$HERE/$APP" "$APPDIR.new"
rm -rf "$APPDIR"
mv "$APPDIR.new" "$APPDIR"
ln -sfn "$APPDIR/$APP" "$BIN"
[ -f "$HERE/$APP.png" ] && cp "$HERE/$APP.png" "$ICON"
[ "$HERE/install.sh" -ef "$PREFIX/install.sh" ] || cp "$HERE/install.sh" "$PREFIX/install.sh"
ok "Program: $APPDIR (command: $BIN)"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=$ACTION_NAME
Comment=Start or stop dictation
Exec=$BIN toggle
Icon=$APP
NoDisplay=true
StartupNotify=false
X-KDE-GlobalAccel-CommandShortcut=true
EOF

cat > "$UNITDIR/$APP.service" <<EOF
[Unit]
Description=$DISPLAY_NAME dictation (start/stop with: $APP toggle)
Documentation=$REPO_URL
PartOf=graphical-session.target
After=graphical-session.target

[Service]
ExecStart=$APPDIR/$APP
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
EOF
sysd daemon-reload
sysd enable "$APP.service" >/dev/null 2>&1
if sysd restart "$APP.service"; then
  ok "Background service: $APP.service (running; starts when you log in)"
else
  warn "The service didn't start. See: journalctl --user -u $APP.service"
fi

if [ "$DO_SHORTCUT" = 1 ]; then
  if is_kde; then
    kde_setup
  elif is_gnome; then
    gnome_setup
  else
    warn "Your desktop (${XDG_CURRENT_DESKTOP:-unknown}) isn't set up automatically."
    manual_shortcut_hint
  fi
fi

# ---- checks
bold "Checks"
if [ ! -e /dev/uinput ]; then
  warn "/dev/uinput doesn't exist, so $DISPLAY_NAME can't press the paste keys. Load the module:"
  info "echo uinput | sudo tee /etc/modules-load.d/uinput.conf && sudo modprobe uinput"
elif [ ! -w /dev/uinput ]; then
  warn "You can't write to /dev/uinput, so $DISPLAY_NAME can't press the paste keys."
  RULE='KERNEL=="uinput", TAG+="uaccess", OPTIONS+="static_node=uinput"'
  info "Fix (gives the logged-in user access, like for game controllers):"
  info "  echo '$RULE' | sudo tee /etc/udev/rules.d/60-$APP-uinput.rules"
  info "  sudo udevadm control --reload && sudo udevadm trigger --name-match=uinput"
  if [ -t 0 ] && have sudo; then
    read -r -p "    Run these now with sudo? [y/N] " reply
    if [[ "$reply" =~ ^[Yy] ]]; then
      echo "$RULE" | sudo tee "/etc/udev/rules.d/60-$APP-uinput.rules" >/dev/null
      sudo udevadm control --reload && sudo udevadm trigger --name-match=uinput
      sleep 1
      if [ -w /dev/uinput ]; then ok "/dev/uinput is writable now"; sysd restart "$APP.service" || true
      else warn "Still not writable; log out and back in."; fi
    fi
  fi
else
  ok "Can type through /dev/uinput"
fi
if ! ls /dev/input/event* >/dev/null 2>&1 || [ ! -r "$(ls /dev/input/event* | head -1)" ]; then
  info "(Optional) Add yourself to the 'input' group so pastes wait until you let go of the"
  info "shortcut keys: sudo usermod -aG input \"\$USER\" (then log in again)."
fi
have pactl || warn "pactl not found (package pulseaudio-utils): the mic picker needs it."
if ! is_kde && ! pgrep -x copyq >/dev/null 2>&1 && ! have wl-copy; then
  warn "No clipboard tool found. Install wl-clipboard (or CopyQ)."
fi
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) info "Note: ~/.local/bin isn't on your PATH; use $BIN" ;;
esac

echo
bold "Done."
info "Press $SHORTCUT in any app, speak, then press it again. The first start downloads"
info "the speech model (about 650 MB) to $PREFIX/models."
info "Settings: $CONFIG/$APP/config.json    Log: $STATE/$APP/$APP.log"
info "Uninstall: $PREFIX/install.sh --uninstall"
