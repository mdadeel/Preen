#!/usr/bin/env bash
# Install a Preen AppImage with desktop integration.
# Copies the AppImage into place, writes a menu entry pointing at it and
# installs the launcher icon, so it shows up in the app grid like the deb.
#
# Usage: install_appimage.sh [APPIMAGE] [--system]
#   APPIMAGE   path to the AppImage (default: newest dist/Preen-*.AppImage)
#   --system   install to /opt/preen + /usr/share (needs root); the default is
#              a per-user install under ~/.local/share
# Uninstall with: uninstall_appimage.sh [--system]
set -euo pipefail

DESKTOP_ID=io.github.mdadeel.Preen.desktop
ICON_NAME=preen.png
APPIMAGE_NAME=Preen.AppImage
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

usage() {
  cat <<EOF
Usage: install_appimage.sh [APPIMAGE] [--system]

Install a Preen AppImage with a menu entry and launcher icon.

  APPIMAGE   path to the AppImage file (default: newest dist/Preen-*.AppImage)
  --system   install system-wide (/opt/preen + /usr/share, needs root);
             default is a per-user install under ~/.local/share

Uninstall with: uninstall_appimage.sh [--system] [--purge]
EOF
}

die() { echo "error: $*" >&2; exit 1; }

APPIMAGE_ARG=""
SYSTEM=0
for arg in "$@"; do
  case "$arg" in
    -h|--help) usage; exit 0 ;;
    --system) SYSTEM=1 ;;
    -*) usage >&2; die "unknown option: $arg" ;;
    *) APPIMAGE_ARG=$arg ;;
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

# --- locate the AppImage ----------------------------------------------------
if [ -n "$APPIMAGE_ARG" ]; then
  APPIMAGE=$APPIMAGE_ARG
else
  APPIMAGE=$(find "$REPO_ROOT/dist" -maxdepth 1 -name 'Preen-*.AppImage' 2>/dev/null | sort -V | tail -n 1 || true)
  [ -n "$APPIMAGE" ] || die "no AppImage in $REPO_ROOT/dist — build one first: make appimage"
fi
[ -f "$APPIMAGE" ] || die "not a file: $APPIMAGE"

INSTALLED_APPIMAGE="$APP_DIR/$APPIMAGE_NAME"

# --- pull the desktop entry and icon out of the AppImage ---------------------
# Type-2 AppImages extract without fuse; the fallbacks cover running the
# installer straight from a checkout that has no built AppImage in hand.
EXTRACT_TMP=$(mktemp -d)
trap 'rm -rf "$EXTRACT_TMP"' EXIT
(
  cd "$EXTRACT_TMP"
  "$APPIMAGE" --appimage-extract "$DESKTOP_ID" >/dev/null 2>&1 || true
  "$APPIMAGE" --appimage-extract "$ICON_NAME" >/dev/null 2>&1 || true
)
SRC_DESKTOP="$EXTRACT_TMP/squashfs-root/$DESKTOP_ID"
SRC_ICON="$EXTRACT_TMP/squashfs-root/$ICON_NAME"
[ -s "$SRC_DESKTOP" ] || SRC_DESKTOP="$REPO_ROOT/data/$DESKTOP_ID"
[ -s "$SRC_ICON" ] || SRC_ICON="$REPO_ROOT/preen_tool/assets/$ICON_NAME"
[ -s "$SRC_DESKTOP" ] || die "could not get $DESKTOP_ID from $APPIMAGE or this checkout"
HAVE_ICON=1
[ -s "$SRC_ICON" ] || { HAVE_ICON=0; echo "warning: no icon found; the menu entry gets a generic icon" >&2; }

# --- rewrite Exec for the installed path --------------------------------------
# The embedded entry says Exec=preen, which only resolves for the deb. Quote
# the path only when it has characters outside the safe set; inside double
# quotes escape \ " ` $ per the desktop entry spec.
case "$INSTALLED_APPIMAGE" in
  *[!A-Za-z0-9/._-]*)
    EXEC_VALUE=$(printf '%s' "$INSTALLED_APPIMAGE" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/`/\\`/g' -e 's/\$/\\$/g')
    EXEC_VALUE="\"$EXEC_VALUE\""
    ;;
  *) EXEC_VALUE=$INSTALLED_APPIMAGE ;;
esac

VERSION=$(basename "$APPIMAGE" | sed -n 's/^Preen-\([0-9][0-9.]*\)-[^-]*\.AppImage$/\1/p')

DESKTOP_OUT="$EXTRACT_TMP/$DESKTOP_ID"
grep -v -e '^Exec=' -e '^X-AppImage-Version=' "$SRC_DESKTOP" > "$DESKTOP_OUT" || true
if [ -s "$DESKTOP_OUT" ] && [ -n "$(tail -c 1 "$DESKTOP_OUT")" ]; then
  printf '\n' >> "$DESKTOP_OUT"
fi
printf 'Exec=%s\n' "$EXEC_VALUE" >> "$DESKTOP_OUT"
if [ -n "$VERSION" ]; then
  printf 'X-AppImage-Version=%s\n' "$VERSION" >> "$DESKTOP_OUT"
fi

# --- install ------------------------------------------------------------------
install -d "$APP_DIR" "$APPS_DIR" "$ICONS_DIR"
rm -f "$APP_DIR"/Preen-*.AppImage  # stale versioned names from older installs
if [ "$APPIMAGE" -ef "$INSTALLED_APPIMAGE" ]; then
  chmod 755 "$INSTALLED_APPIMAGE"
else
  install -m 755 "$APPIMAGE" "$INSTALLED_APPIMAGE"
fi
install -m 644 "$DESKTOP_OUT" "$APPS_DIR/$DESKTOP_ID"
if [ "$HAVE_ICON" -eq 1 ]; then
  install -m 644 "$SRC_ICON" "$ICONS_DIR/$ICON_NAME"
fi

if [ "$SCOPE" = user ] && [ -e "/usr/share/applications/$DESKTOP_ID" ]; then
  echo "note: a system-wide Preen install (deb) exists; this user entry takes priority" >&2
fi

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "${ICONS_DIR%/256x256/apps}" >/dev/null 2>&1 || true
fi
if command -v desktop-file-validate >/dev/null 2>&1; then
  if ! out=$(desktop-file-validate "$APPS_DIR/$DESKTOP_ID" 2>&1); then
    echo "warning: $out" >&2
  fi
fi

echo "Installed Preen ($SCOPE scope):"
echo "  AppImage:   $INSTALLED_APPIMAGE"
echo "  Menu entry: $APPS_DIR/$DESKTOP_ID"
if [ "$HAVE_ICON" -eq 1 ]; then
  echo "  Icon:       $ICONS_DIR/$ICON_NAME"
fi
if [ "$SYSTEM" -eq 1 ]; then
  echo "Uninstall: sudo $(dirname "$0")/uninstall_appimage.sh --system"
else
  echo "Uninstall: $(dirname "$0")/uninstall_appimage.sh"
fi
