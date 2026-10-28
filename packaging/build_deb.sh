#!/usr/bin/env bash
# Build the Preen .deb without debhelper (staging tree + dpkg-deb).
# Result: dist/preen_<version>_all.deb
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=$(python3 -c "import sys; sys.path.insert(0,'.'); import preen_tool; print(preen_tool.__version__)")
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
PKG="$STAGE/preen"

# --- Python package ---
SITE="$PKG/usr/lib/python3/dist-packages"
install -d "$SITE/preen_tool/backend" "$SITE/preen_tool/config"
cp preen_tool/*.py "$SITE/preen_tool/"
cp preen_tool/backend/*.py "$SITE/preen_tool/backend/"
cp preen_tool/config/*.json "$SITE/preen_tool/config/"
cp -R preen_tool/assets "$SITE/preen_tool/assets"
find "$PKG" -name '__pycache__' -type d -exec rm -rf {} +

# --- Launcher (desktop entry Exec=preen) ---
install -d "$PKG/usr/bin"
cat > "$PKG/usr/bin/preen" <<'EOF'
#!/usr/bin/python3
import sys
sys.path.insert(0, "/usr/lib/python3/dist-packages")
from preen_tool.app import main
sys.exit(main())
EOF
chmod 755 "$PKG/usr/bin/preen"

# --- Desktop entry + docs ---
install -d "$PKG/usr/share/applications" "$PKG/usr/share/doc/preen" \
          "$PKG/usr/share/icons/hicolor/256x256/apps"
install -m 644 data/preen.desktop data/io.github.mdadeel.Preen.desktop "$PKG/usr/share/applications/"
install -m 644 preen_tool/assets/preen.png "$PKG/usr/share/icons/hicolor/256x256/apps/preen.png"
./packaging/stage_docs.sh "$PKG/usr/share/doc/preen"
install -m 644 debian/copyright "$PKG/usr/share/doc/preen/copyright"
gzip -9 -c debian/changelog > "$PKG/usr/share/doc/preen/changelog.gz"

# --- Control ---
install -d "$PKG/DEBIAN"
{
  echo "Package: preen"
  echo "Version: $VERSION"
  echo "Architecture: all"
  echo "Section: utils"
  echo "Priority: optional"
  echo "Maintainer: Preen contributors <64582744+mdadeel@users.noreply.github.com>"
  echo "Homepage: https://github.com/mdadeel/Preen"
  echo "Depends: python3, python3-gi, gir1.2-gtk-3.0, python3-psutil, polkitd | policykit-1"
  echo "Recommends: flatpak, gsettings-desktop-schemas, power-profiles-daemon"
  echo "Suggests: timeshift, systemd-zram-generator"
  echo "Installed-Size: $(du -sk "$PKG/usr" | cut -f1)"
  echo "Description: Preen — system setup and optimization for Linux"
  echo " Install and remove APT/Flatpak apps, deep-clean caches with a size"
  echo " preview, manage systemd services, tune power/swap/ZRAM and back up"
  echo " user configuration from a single GTK interface."
  echo " Includes a Simulate mode that previews supported maintenance actions."
} > "$PKG/DEBIAN/control"

mkdir -p dist
dpkg-deb --root-owner-group --build "$PKG" "dist/preen_${VERSION}_all.deb"
echo "Built dist/preen_${VERSION}_all.deb"
