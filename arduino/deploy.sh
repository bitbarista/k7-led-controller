#!/usr/bin/env bash
# Deploy K7 Controller (Arduino/C++) to XIAO ESP32-S3 via PlatformIO.
#
# Usage:
#   ./arduino/deploy.sh          # build + upload firmware + filesystem
#   ./arduino/deploy.sh fw       # firmware only
#   ./arduino/deploy.sh fs       # filesystem only
#
# Prerequisites:
#   pip install platformio  (or install PlatformIO IDE extension)

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MODE="${1:-all}"

echo "=== Syncing HTML templates to data/static/ ==="
mkdir -p "$SCRIPT_DIR/data/static/vendor"
cp "$ROOT_DIR/templates/index.html"  "$SCRIPT_DIR/data/static/index.html"
cp "$ROOT_DIR/templates/mobile.html" "$SCRIPT_DIR/data/static/mobile.html"

echo "=== Copying vendor assets ==="
cp "$ROOT_DIR/static/vendor/bootstrap.min.css"              "$SCRIPT_DIR/data/static/vendor/"
cp "$ROOT_DIR/static/vendor/chart.umd.min.js"               "$SCRIPT_DIR/data/static/vendor/"
cp "$ROOT_DIR/static/vendor/chartjs-plugin-dragdata.min.js" "$SCRIPT_DIR/data/static/vendor/"

cd "$SCRIPT_DIR"

if [[ "$MODE" == "fw" ]]; then
    echo "=== Building and uploading firmware ==="
    pio run --target upload
elif [[ "$MODE" == "fs" ]]; then
    echo "=== Building and uploading filesystem ==="
    pio run --target uploadfs
else
    echo "=== Building and uploading firmware ==="
    pio run --target upload
    echo "=== Building and uploading filesystem ==="
    pio run --target uploadfs
fi

echo "=== Done. Device will reset automatically. ==="
