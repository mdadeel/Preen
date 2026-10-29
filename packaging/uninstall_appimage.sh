#!/usr/bin/env bash
# Uninstall a Preen AppImage installed by install_appimage.sh.
# Removes the AppImage, its menu entry and launcher icon; --purge also
# deletes the app's settings in ~/.config/preen.
#
# Usage: uninstall_appimage.sh [--system] [--purge]
set -euo pipefail

DESKTOP_ID=io.github.mdadeel.Preen.desktop
HANDLER_ID=io.github.mdadeel.Preen.appimage.desktop
ICON_NAME=preen.png

usage() {
  cat <<'EOF'
Usage: uninstall_appimage.sh [--system] [--purge]

Remove an AppImage install created by install_appimage.sh.

  --system   remove the system-wide install (/opt/preen + /usr/share, needs root)
  --purge    also delete Preen's settings in ~/.config/preen
EOF
}

die() { echo "error: $*" >&2; exit 1; }

SYSTEM=0
PURGE=0
for arg in "$@"; do
  case "$arg" in
    -h|--help) usage; exit 0 ;;
    --system) SYSTEM=1 ;;
    --purge) PURGE=1 ;;
    *) usage >&2; die "unknown argument: $arg" ;;
  esac
done

if [ "$SYSTEM" -eq 1 ]; then
  [ "$(id -u)" -eq 0 ] || die "--system needs root; rerun with: sudo $0 --system"
  APP_DIR=/opt/preen
  APPS_DIR=/usr/share/applications
  ICONS_DIR=/usr/share/icons/hicolor/256x256/apps
  SCOPE=system
else
  DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
  APP_DIR="$DATA_HOME/preen"
  APPS_DIR="$DATA_HOME/applications"
  ICONS_DIR="$DATA_HOME/icons/hicolor/256x256/apps"
  SCOPE=user
fi

# In system scope the same paths can be owned by the deb; never fight dpkg.
if [ "$SCOPE" = system ]; then
  for f in "$APPS_DIR/$DESKTOP_ID" "$ICONS_DIR/$ICON_NAME"; do
    if [ -e "$f" ] && command -v dpkg >/dev/null 2>&1 && dpkg -S "$f" >/dev/null 2>&1; then
      die "$f belongs to the 'preen' deb package — remove it with: sudo apt remove preen"
    fi
  done
fi

REMOVED=0
if [ -d "$APP_DIR" ]; then
  rm -rf "$APP_DIR"
  echo "Removed $APP_DIR"
  REMOVED=1
fi
for f in "$APPS_DIR/$DESKTOP_ID" "$APPS_DIR/$HANDLER_ID" "$ICONS_DIR/$ICON_NAME"; do
  if [ -e "$f" ]; then
    rm -f "$f"
    echo "Removed $f"
    REMOVED=1
  fi
done

if [ "$PURGE" -eq 1 ]; then
  CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
  if [ -d "$CONFIG_HOME/preen" ]; then
    rm -rf "$CONFIG_HOME/preen"
    echo "Removed settings: $CONFIG_HOME/preen"
  fi
fi

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi

if [ "$REMOVED" -eq 0 ]; then
  echo "No AppImage install found ($SCOPE scope); nothing to do."
fi
