# K7 PC Bridge

Experimental local bridge for controlling a Noo-Psyche K7 lamp directly from a
PC, without an ESP32-S3 controller in the middle.

Current scope:

- Serve a local HTTP API on the PC.
- Talk to the lamp over raw TCP at `192.168.4.1:8266`.
- Prove direct read, preview/manual output, and native schedule push.

The PC bridge is an addition to the ESP32 controller, not a replacement. The
ESP32 remains the advanced always-on controller for Smooth Ramp, lunar tracking,
acclimation, seasonal adjustment, feed/maintenance timers, diagnostics, and
other runtime behaviour that requires a controller to keep running.

## Build

This directory is a standalone Go module.

```bash
cd pc-bridge
go build ./cmd/k7-bridge
```

The first intended release targets are Linux and Windows. Android will reuse the
shared web UI later with a native mobile TCP bridge. macOS can be cross-built
later, but is not an initial test target.

## Run

Connect the PC to the lamp WiFi first, then run:

```bash
./k7-bridge
```

The bridge listens on:

```text
http://127.0.0.1:8787
```

Open the shared UI at:

```text
http://127.0.0.1:8787/
```

Open the bridge diagnostic page at:

```text
http://127.0.0.1:8787/diagnostic/
```

Useful early endpoints:

- `GET /api/capabilities`
- `GET /api/config`
- `POST /api/config`
- `GET /api/lamp/read`
- `GET /api/state`
- `GET /api/profiles`
- `POST /api/profiles`
- `DELETE /api/profiles/<name>`
- `GET /api/backup`
- `POST /api/backup`
- `POST /api/preview`
- `POST /api/hand`
- `POST /api/push`

The bridge store path defaults to `k7-pc-bridge.json`. It contains the lamp
connection settings, last known local state, and saved profiles. `GET
/api/state` returns this local state without contacting the lamp; use `GET
/api/lamp/read` when you want a live TCP read from the lamp.

Example transport checks:

```bash
curl -sS http://127.0.0.1:8787/api/lamp/read

curl -sS \
  -H 'Content-Type: application/json' \
  -d '{"channels":[0,1,1,0,0,0]}' \
  http://127.0.0.1:8787/api/preview
```

The existing Web UI has not been moved onto this bridge yet. This first slice is
for validating the direct TCP transport.
