#!/bin/bash
set -e
cd "$(dirname "$0")"

# Check Python 3 is available
if ! command -v python3 &>/dev/null; then
    echo "Python 3 not found."
    echo "Install it with:"
    echo "  Ubuntu/Debian:  sudo apt install python3 python3-venv"
    echo "  Fedora:         sudo dnf install python3"
    echo "  macOS:          brew install python3"
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d venv ]; then
    echo "Setting up for the first time..."
    python3 -m venv venv
    venv/bin/pip install --quiet -r requirements.txt
fi

echo "K7 LED Controller starting → http://localhost:5000"

# Open browser after a short delay (works on Linux and macOS)
(sleep 1 && xdg-open http://localhost:5000 2>/dev/null \
        || open      http://localhost:5000 2>/dev/null \
        || true) &

venv/bin/python3 server.py
