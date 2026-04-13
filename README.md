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
- **Smooth Ramp** — sends per-minute interpolated brightness values so transitions are smooth rather than stepped
- **Lightning effect** — random white-dominant flashes with optional time-of-day schedule
- **Lunar Cycle** — varies the royal blue channel over the 29.5-day synodic cycle, tracking the actual current moon phase
- Supports K7 Mini (3 channels) and K7 Pro (6 channels)

---

## Hardware

A **XIAO ESP32-S3** sits between your lamp and your devices, creating its own WiFi network. No PC required — the controller runs 24/7 and is always accessible from any phone or browser.

| Item | Notes |
|------|-------|
| **Seeed XIAO ESP32-S3** | Available from Seeed Studio, Mouser, or similar. The standard (non-Sense) variant works; the Sense variant (with PSRAM) also works and gives more headroom. |
| USB-C cable | For flashing and power |

The board draws ~80 mA and can run from any USB phone charger.

---

## Flashing

### 1 — Flash MicroPython + firmware (easiest)

Visit **[bitbarista.github.io/k7-led-controller/flash.html](https://bitbarista.github.io/k7-led-controller/flash.html)** — connect your XIAO ESP32-S3 via USB and click Install. Works in Chrome, Edge, and Opera. No software required.

If the device is not detected, hold the **BOOT (B)** button while pressing **RST**, then click Install again.

### 2 — Deploy the controller firmware

```bash
pip install mpremote
cd esp32
./deploy.sh            # auto-detects port
./deploy.sh /dev/ttyACM1  # or specify port
```

Then reset the device:
```bash
mpremote reset
```

---

## First-time WiFi setup

After flashing, the device starts a setup portal:

1. On your phone or laptop, connect to the **K7-Setup** WiFi network (open, no password)
2. Browse to **http://192.168.5.1** — the device scans for nearby K7 lamps automatically
3. Select your lamp from the list and tap **Connect & Save**
4. The device reboots. Connect to **K7-Controller** WiFi (password: `12345678`)
5. Browse to **http://192.168.5.1** — the controller loads and reads the lamp

> If your lamp is not found, make sure it is powered on. You can also enter the SSID manually.

---

## Network architecture

```
Your phone/browser ── K7-Controller WiFi (192.168.5.1) ── [XIAO ESP32-S3] ── K7 lamp AP (192.168.4.1)
```

The ESP32-S3 bridges your devices to the lamp. Your home network is never involved — the lamp does not need to be on your router.

---

## Notes

- Profiles and settings are saved to flash and survive power cycles
- The lightning effect, smooth ramp, and lunar cycle run entirely on the device — no browser needed once configured
- Reflashing MicroPython erases all saved profiles and config; run `deploy.sh` again afterwards

---

## Device support

| Device  | Channels |
|---------|----------|
| K7 Mini | White, Royal Blue, Blue |
| K7 Pro  | UV, Royal Blue, Blue, White, Warm White, Red |

## Protocol

The lamp communicates over TCP on port 8266 using a simple binary framing protocol (`AA A5 [CMD] [data] BB`). The full implementation is in `esp32/k7mini.py`.

## Licence

[MIT](LICENSE)
