# K7 LED Controller

An unofficial web-based controller for **Noo-Psyche K7 Mini** and **K7 Pro** LED aquarium lamps.

> This is an independent, community-developed project. It is not affiliated with or endorsed by Noo-Psyche.

## Features

- Read the current schedule and mode directly from the lamp
- Edit the 24-hour lighting schedule on an interactive drag-and-drop chart
- Additive colour preview strip showing the blended light output for each hour
- Built-in presets for Fish Only, LPS Reef, SPS Reef, and Mixed Reef
- Master brightness slider and per-channel intensity sliders (absolute output ceiling per channel)
- Per-channel visibility toggles — hidden channels are zeroed when pushing to the device
- Day-shift control to slide the entire schedule forward or back (e.g. peak at 18:00 instead of midday)
- Save and reload your own named profiles (stored on the server, persists across sessions)
- Manual mode with live preview
- Lightning effect — random white-dominant flashes to simulate storm lighting
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

### AP mode (direct connection)

The lamp creates its own WiFi access point by default.

| | K7 Mini | K7 Pro |
|---|---|---|
| SSID | `K7mini****` | `K7_Pro****` |
| Password | `12345678` | `12345678` |
| IP | `192.168.4.1` | `192.168.4.1` |

(`****` = last 4 digits unique to your lamp)

1. Connect your computer to the lamp's WiFi network
2. Open the controller — it will read the current schedule automatically

> **Note:** while connected to the lamp's AP your computer will have no internet access.

### LAN mode (home network)

To connect the lamp to your home WiFi network, use the official Noo-Psyche app to switch it to LAN mode. Once connected, enter the lamp's local IP address in the host field at the top of the controller page.

To check or switch connection mode, click the R button on the lamp — two blue flashes means LAN mode, two red flashes means AP mode.

## Device support

| Device  | Channels |
|---------|----------|
| K7 Mini | White, Royal Blue, Blue |
| K7 Pro  | UV, Royal Blue, Blue, White, Warm White, Red |

## Protocol

The lamp communicates over TCP on port 8266 using a simple binary framing protocol (`AA A5 [CMD HI LO] [data] BB`). The full implementation is in `k7mini.py`.

## Notes

### Lightning effect

The lightning effect is managed by the server process. Once enabled via the browser, it continues firing even if the browser is closed — the server sends flashes directly to the lamp on a random 15–90 second interval. It stops when you disable it in the browser, or when the server process is stopped.

The schedule itself runs autonomously on the lamp and does not require the server to be running. Only the lightning effect requires the server.

## Licence

[MIT](LICENSE)
