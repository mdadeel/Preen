#!/usr/bin/env bash
# Build Preen as an AppImage (AppDir + appimagetool).
# Uses the host's Python and GTK rather than bundling a runtime; the host must
# provide the required Python, GTK and PyGObject packages.
# Result: dist/Preen-<version>-x86_64.AppImage
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=$(python3 -c "import sys; sys.path.insert(0,'.'); import preen_tool; print(preen_tool.__version__)")
TOOL=${APPIMAGETOOL:-/tmp/appimagetool-x86_64.AppImage}
APPDIR=$(mktemp -d)
trap 'rm -rf "$APPDIR"' EXIT

if [ ! -x "$TOOL" ]; then
  echo "Downloading appimagetool..."
  curl -sL -o "$TOOL" \
    https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
  chmod +x "$TOOL"
fi

# --- Python package ---
SITE="$APPDIR/usr/lib/python3/dist-packages"
install -d "$SITE/preen_tool/backend" "$SITE/preen_tool/config"
cp preen_tool/*.py "$SITE/preen_tool/"
cp preen_tool/backend/*.py "$SITE/preen_tool/backend/"
cp preen_tool/config/*.json "$SITE/preen_tool/config/"
cp -R preen_tool/assets "$SITE/preen_tool/assets"
find "$APPDIR" -name '__pycache__' -type d -exec rm -rf {} +

# --- Launcher + AppRun ---
install -d "$APPDIR/usr/bin"
cat > "$APPDIR/usr/bin/preen" <<'EOF'
#!/usr/bin/python3
import sys
from preen_tool.app import main
sys.exit(main())
EOF
chmod 755 "$APPDIR/usr/bin/preen"

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
export PYTHONPATH="$HERE/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
exec python3 "$HERE/usr/bin/preen" "$@"
EOF
chmod 755 "$APPDIR/AppRun"

# --- Desktop entry + icons ---
install -d "$APPDIR/usr/share/applications" \
          "$APPDIR/usr/share/icons/hicolor/256x256/apps"
install -m 644 data/io.github.mdadeel.Preen.desktop "$APPDIR/io.github.mdadeel.Preen.desktop"
install -m 644 data/io.github.mdadeel.Preen.desktop "$APPDIR/usr/share/applications/io.github.mdadeel.Preen.desktop"
install -m 644 preen_tool/assets/preen.png "$APPDIR/preen.png"
install -m 644 preen_tool/assets/preen.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/preen.png"
ln -sf preen.png "$APPDIR/.DirIcon"

# License, privacy information and documentation travel with the AppImage.
./packaging/stage_docs.sh "$APPDIR/usr/share/doc/preen"

mkdir -p dist
ARCH=x86_64 "$TOOL" --appimage-extract-and-run "$APPDIR" \
  "dist/Preen-${VERSION}-x86_64.AppImage"
echo "Built dist/Preen-${VERSION}-x86_64.AppImage"
