#!/usr/bin/env sh
set -eu

REPO_ROOT="/home/carl/Projects/k7mini_controller"
DIST_DIR="$REPO_ROOT/dist/pc-bridge"

if [ ! -d "$DIST_DIR" ]; then
    echo "pc-bridge output directory not found: $DIST_DIR" >&2
    exit 1
fi

package_dir="$(
    find "$DIST_DIR" -maxdepth 1 -type d -name 'k7-pc-bridge-linux-amd64-*' | sort | tail -n 1
)"

if [ -z "${package_dir:-}" ] || [ ! -x "$package_dir/run-k7-bridge.sh" ]; then
    echo "no runnable pc-bridge package found under $DIST_DIR" >&2
    echo "expected a directory like k7-pc-bridge-linux-amd64-*/run-k7-bridge.sh" >&2
    exit 1
fi

exec "$package_dir/run-k7-bridge.sh" "$@"
