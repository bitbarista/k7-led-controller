#!/usr/bin/env bash
# Deploy K7 Controller firmware to XIAO ESP32-S3 via mpremote.
#
# Usage:
#   ./deploy.sh              # auto-detect port
#   ./deploy.sh /dev/ttyACM1 # specify port
#
# Prerequisites:
#   pip install mpremote
#   MicroPython flashed to the device
#   Microdot installed on the device:
#     mpremote mip install microdot
#
# Note: XIAO ESP32-S3 native USB (/dev/ttyACM0) resets on port open.
#   mpremote handles this correctly; do NOT use raw serial tools.

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${1:-}"
MP="mpremote${PORT:+ connect $PORT}"

echo "=== Syncing HTML templates ==="
cp "$SCRIPT_DIR/../templates/index.html"  "$SCRIPT_DIR/static/index.html"
cp "$SCRIPT_DIR/../templates/mobile.html" "$SCRIPT_DIR/static/mobile.html"

echo "=== Creating directories on device ==="
$MP mkdir :static 2>/dev/null || true
$MP mkdir :static/vendor 2>/dev/null || true

echo "=== Copying Python files ==="
for f in main.py server.py k7mini.py presets.py moon.py setup.py; do
    echo "  $f"
    $MP cp "$SCRIPT_DIR/$f" ":$f"
done

echo "=== Copying static assets ==="
echo "  static/index.html"
$MP cp "$SCRIPT_DIR/static/index.html" ":static/index.html"
echo "  static/mobile.html"
$MP cp "$SCRIPT_DIR/static/mobile.html" ":static/mobile.html"

VENDOR_SRC="$SCRIPT_DIR/../static/vendor"
for f in bootstrap.min.css chart.umd.min.js chartjs-plugin-dragdata.min.js; do
    echo "  static/vendor/$f"
    $MP cp "$VENDOR_SRC/$f" ":static/vendor/$f"
done

echo "=== Done. Reset the device to apply. ==="
echo "    $MP reset"
