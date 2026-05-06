# K7 PC Bridge

Experimental local bridge for controlling a Noo-Psyche K7 lamp directly from a
PC, without an ESP32-S3 controller in the middle.

Current scope:

- Serve a local HTTP API on the PC.
- Talk to the lamp over raw TCP at `192.168.4.1:8266`.
- Serve the shared controller UI with PC-only capability hiding.
- Read, preview/manual output, save profiles/backups, and push native schedules.

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

To build distributable Linux and Windows archives from the repository root:

```bash
python3 tools/build_pc_bridge.py
```

The archives are written under `dist/pc-bridge/`. Each package contains the
bridge binary, a short README, and a small launcher script.

Private test builds can also be made from GitHub Actions without creating a
public GitHub Release:

1. Open **Actions** in the repository.
2. Run the **PC Bridge** workflow.
3. Download the `k7-pc-bridge-...` artifact from the workflow run.

These workflow artifacts are for people with repository access. They do not
publish a release, update the website, or create a version tag.

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

By default the bridge opens this URL in your default browser automatically. Use
`--no-open` if you want to keep it from launching a browser while debugging.

Open the shared UI at:

```text
http://127.0.0.1:8787/
```

Open the bridge diagnostic page at:

```text
http://127.0.0.1:8787/diagnostic/
```

The UI shows `PC Bridge · Direct Lamp` in the top bar when it is running through
the local bridge. On the PC bridge, the Read button performs a live lamp read
before loading the editor state. Push/Apply is blocked until a live read has
succeeded, reducing the chance of accidentally pushing stale local data.

Useful early endpoints:

- `GET /api/capabilities`
- `GET /api/config`
- `POST /api/config`
- `GET /api/presets`
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

Built-in presets are generated from `arduino/src/Presets.h`:

```bash
python3 ../tools/generate_pc_bridge_presets.py
```

Use `--check` in CI or before commits to confirm the embedded PC bridge preset
copy is still in sync with the firmware definitions.

Example transport checks:

```bash
curl -sS http://127.0.0.1:8787/api/lamp/read

curl -sS \
  -H 'Content-Type: application/json' \
  -d '{"channels":[0,1,1,0,0,0]}' \
  http://127.0.0.1:8787/api/preview
```

The shared Web UI is embedded in the bridge. Runtime capability flags hide the
ESP32-only controls on the PC bridge while keeping the same HTML source for the
ESP32 and PC variants.
