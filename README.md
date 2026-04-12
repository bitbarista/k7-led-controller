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
- Save and reload your own named profiles (stored on the controller, persists across sessions)
- Manual mode with live preview
- Lightning effect — random white-dominant flashes with optional time-of-day schedule
- Supports K7 Mini (3 channels) and K7 Pro (6 channels)

---

## Option 1 — Dedicated ESP32 controller (recommended)

A small ESP32-C3 board sits between your lamp and your devices, creating its own WiFi network. No PC required — the controller runs 24/7 and is always accessible from any phone or browser on the same WiFi.

### Hardware

| Item | Notes |
|------|-------|
| **ESP32-C3 Super Mini** | ~£2–3 from AliExpress, Amazon, or similar. Any ESP32-C3 board with 4 MB flash works. |
| USB-C cable | For flashing and power |

The board draws ~80 mA and can run from any USB phone charger.

### Flashing

1. Connect the ESP32-C3 to your computer via USB
2. Open the [flash page](https://bitbarista.github.io/k7-led-controller/flash.html) in **Chrome, Edge, or Opera**
3. Click **Install Firmware** and follow the prompts

> If the device is not detected, hold the **BOOT** button while clicking Install.

### First-time WiFi setup

After flashing, the device starts a setup portal:

1. On your phone or laptop, connect to the **K7-Setup** WiFi network (open, no password)
2. Browse to **http://192.168.5.1** — the device scans for nearby K7 lamps automatically
3. Select your lamp from the list and tap **Connect & Save**
4. The device reboots. Connect to **K7-Controller** WiFi (password: `12345678`)
5. Browse to **http://192.168.5.1** — the controller loads and reads the lamp

> If your lamp is not found, make sure it is powered on. You can also enter the SSID manually using the *Enter manually* option.

### Network architecture

```
Your phone/browser ── K7-Controller WiFi (192.168.5.1) ── [ESP32-C3] ── K7 lamp AP (192.168.4.1)
```

The ESP32 bridges your devices to the lamp. Your home network is never involved — the lamp does not need to be on your router.

### Notes

- Profiles and settings are saved to the ESP32's flash and survive power cycles
- The lightning effect and its scheduler run entirely on the device — no browser needed once configured
- Flashing the firmware erases all saved profiles and config; the first-run setup portal runs again

---

## Option 2 — PC server

Runs the controller as a local Python server. Requires a PC to be running whenever you want to use the controller.

### Requirements

- Python 3.9 or later
- The lamp accessible on your network (AP mode or LAN mode)

### Quick start

**Windows:** Double-click `run.bat`. On first run it creates a virtual environment and installs dependencies automatically, then opens the controller in your browser.

**Linux / macOS:**
```bash
./run.sh
```

**Manual setup:**
```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt   # Linux/macOS
venv\Scripts\pip install -r requirements.txt  # Windows

venv/bin/python3 server.py   # Linux/macOS
venv\Scripts\python server.py  # Windows
```

Then open `http://localhost:5000` in your browser.

### Connecting to the lamp

**AP mode (direct connection)** — the lamp creates its own WiFi network by default:

| | K7 Mini | K7 Pro |
|---|---|---|
| SSID | `K7mini…` | `K7_Pro…` |
| Password | `12345678` | `12345678` |
| IP | `192.168.4.1` | `192.168.4.1` |

Connect your computer to the lamp's WiFi, then open the controller. While connected you will have no internet access.

**LAN mode** — use the official Noo-Psyche app to switch the lamp to your home WiFi. Once connected, enter its local IP in the host field at the top of the controller. To check or switch modes, press the R button on the lamp: two blue flashes = LAN, two red flashes = AP.

### Notes

The lightning effect is managed by the server process. Once enabled it continues running even if the browser is closed, and stops when the server is stopped or you disable it in the browser.

---

## Device support

| Device  | Channels |
|---------|----------|
| K7 Mini | White, Royal Blue, Blue |
| K7 Pro  | UV, Royal Blue, Blue, White, Warm White, Red |

## Protocol

The lamp communicates over TCP on port 8266 using a simple binary framing protocol (`AA A5 [CMD] [data] BB`). The full implementation is in `k7mini.py`.

## Licence

[MIT](LICENSE)
