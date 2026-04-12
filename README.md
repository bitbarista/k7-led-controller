# K7 LED Controller

An unofficial web-based controller for **Noo-Psyche K7 Mini** and **K7 Pro** LED aquarium lamps.

> This is an independent, community-developed project. It is not affiliated with or endorsed by Noo-Psyche.

## Features

- Read the current schedule and mode directly from the lamp
- Edit the 24-hour lighting schedule on an interactive drag-and-drop chart
- Additive colour preview strip showing the blended light output for each hour
- Built-in presets for Fish Only, LPS Reef, SPS Reef, and Mixed Reef
- Master brightness slider and per-channel on/off toggles
- Day-shift control to slide the entire schedule forward or back (e.g. peak at 18:00 instead of midday)
- Manual mode with live preview
- Supports K7 Mini (3 channels) and K7 Pro (6 channels)
- Works on Windows, Linux, and macOS — no app required

## Requirements

- Python 3.9 or later
- The lamp must be accessible on your local network (connected via its own AP or your home WiFi)

## Quick start

### Windows

Double-click `run.bat`. On first run it will create a virtual environment and install dependencies automatically, then open the controller in your browser.

### Linux / macOS

```bash
./run.sh
```

On first run this sets up a virtual environment, installs Flask, and opens the controller in your browser.

### Manual setup

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt   # Linux/macOS
venv\Scripts\pip install -r requirements.txt  # Windows

venv/bin/python3 server.py   # Linux/macOS
venv\Scripts\python server.py  # Windows
```

Then open `http://localhost:5000` in your browser.

## Connecting to the lamp

By default the controller connects to `192.168.4.1:8266` — the lamp's own access point.

1. Connect your computer to the lamp's WiFi network (SSID: `k7mini` or similar)
2. Open the controller — it will read the current schedule automatically

If the lamp is joined to your home network, enter its IP address in the host field at the top of the page.

## Device support

| Device  | Channels |
|---------|----------|
| K7 Mini | White, Royal Blue, Blue |
| K7 Pro  | UV, Royal Blue, Blue, White, Warm White, Red |

## Protocol

The lamp communicates over TCP on port 8266 using a simple binary framing protocol (`AA A5 [CMD HI LO] [data] BB`). The full implementation is in `k7mini.py`.

## Licence

[MIT](LICENSE)
