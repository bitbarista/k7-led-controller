# K7 LED Controller — ESP32-S3 Port

MicroPython port for a **Seeed Studio XIAO ESP32-S3** (or any ESP32-S3 with
8 MB flash / 8 MB PSRAM).  Runs as a self-contained, always-on controller —
no laptop required after setup.

## Network architecture

```
[Lamp AP 192.168.4.1] ← STA — [ESP32-S3] — AP → [Phone/tablet 192.168.5.x]
      K7mini****                K7-Controller          browse to 192.168.5.1
```

- The ESP32 connects permanently to the lamp's own AP (`K7mini****`, `12345678`)
- The ESP32 creates its own AP (`K7-Controller`, `12345678`) for user devices
- Users browse to `http://192.168.5.1` — same web UI as the PC version
- The lamp never touches your home network

## First-time setup

1. Flash MicroPython to the device
2. Install Microdot: `mpremote mip install microdot`
3. Run `./deploy.sh` to copy the firmware (auto-detects USB port)
4. Reset the device
5. On your phone/laptop, connect to the open WiFi network **K7-Setup**
6. Browse to `http://192.168.5.1` and enter the last 4 characters of your lamp's WiFi name
7. The device reboots into normal mode — connect to **K7-Controller** (password `12345678`)

## Deploying updates

```bash
./deploy.sh              # auto-detect port
./deploy.sh /dev/ttyACM1 # specify port
```

`deploy.sh` copies the latest `templates/index.html` (the canonical UI) to
`static/index.html` on the device automatically — no manual sync needed.

> **Note:** The web UI loads Bootstrap and Chart.js from a CDN.  
> User devices connected to the K7-Controller AP have no internet access, so
> these libraries won't load unless the device also has mobile data.  
> Bundling assets locally is a planned improvement.

## Files

| File | Description |
|------|-------------|
| `main.py` | Boot: WiFi AP+STA setup, first-run portal, launches server |
| `server.py` | Microdot async web server — mirrors PC `server.py` |
| `k7mini.py` | Lamp protocol client (stripped PC version, no CLI/YAML) |
| `presets.py` | Lighting presets — identical to PC version |
| `deploy.sh` | Copy firmware to device via mpremote |
| `static/` | Not tracked — populated by `deploy.sh` at deploy time |

## Differences from the PC version

| PC (`server.py`) | ESP32 (`esp32/server.py`) |
|---|---|
| Flask | Microdot |
| `threading.Lock` | `asyncio.Lock` |
| `threading.Thread` | `asyncio.create_task` |
| EspTouch provisioning | Not implemented (not needed) |
| Jinja2 template | Static file served directly |
| `time.localtime().tm_hour` | `time.localtime()[3]` |
| `random.choices()` | `_weighted_choice()` helper |
| `/api/time` — not present | POST timestamp to sync device RTC |

RTC sync: the browser sends `Date.now()` to `/api/time` on page load so the
lightning scheduler has the correct time.  Without this, the ESP32 RTC starts
at the Unix epoch after each reboot.
