#!/bin/bash
# Build a double-clickable Tracker Export.app on macOS.
# Run this ON A MAC. Requires: Xcode CLT, brew libxmp, pip, pyinstaller.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Installing tracker-export + pyinstaller…"
pip install -e .
pip install pyinstaller

echo "==> Locating libxmp…"
LIBXMP="$(find /opt/homebrew/lib /usr/local/lib -name 'libxmp*.dylib' 2>/dev/null | head -1)"
if [ -z "$LIBXMP" ]; then
    echo "libxmp dylib not found. Install it first: brew install libxmp"
    exit 1
fi
echo "    $LIBXMP"

echo "==> Building Tracker Export.app…"
pyinstaller \
    --name "Tracker Export" \
    --windowed \
    --noconfirm \
    --add-binary "$LIBXMP:." \
    macos_launcher.py

echo ""
echo "Done: dist/Tracker Export.app"
echo "The app bundles libxmp, so it runs on Macs without brew libxmp."
echo "Zip it to share:  ditto -c -k --sequesterRsrc dist/Tracker\\ Export.app Tracker-Export-macOS.zip"
