#!/usr/bin/env python3
"""
K7 controller push latency probe.

Sends repeated /api/push requests and correlates them with serial log lines
to show exactly where delays occur.

Requirements: pip install pyserial requests

Usage:
    python3 tools/push_latency_probe.py [controller_ip] [serial_port]
    Defaults: 192.168.5.1  /dev/ttyACM0

Close pio device monitor before running (serial port can't be shared).
"""

import sys, time, threading, queue, json
import urllib.request

try:
    import serial as ser_mod
    HAVE_SERIAL = True
except ImportError:
    HAVE_SERIAL = False
    print("WARNING: pyserial not installed — serial timing disabled.")
    print("         pip install pyserial  (or activate your venv first)\n")

CTRL_IP    = sys.argv[1] if len(sys.argv) > 1 else "192.168.5.1"
SERIAL_DEV = sys.argv[2] if len(sys.argv) > 2 else "/dev/ttyACM0"
ROUNDS     = 8
GAP_S      = 4.0   # seconds between rounds

serial_q: queue.Queue = queue.Queue()

def read_serial(port):
    try:
        s = ser_mod.Serial(port, 115200, timeout=0.1)
        print(f"Serial open: {port}\n")
    except Exception as e:
        print(f"[serial] Cannot open {port}: {e}\n")
        return
    while True:
        try:
            line = s.readline().decode("utf-8", errors="replace").rstrip()
            if line:
                serial_q.put((time.monotonic(), line))
        except Exception:
            pass

def drain_serial():
    cutoff = time.monotonic() - 0.5
    drained = []
    while not serial_q.empty():
        try:
            item = serial_q.get_nowait()
            if item[0] >= cutoff:
                drained.append(item)
        except queue.Empty:
            break
    for item in drained:
        serial_q.put(item)

def http_get(path, timeout=5):
    url = f"http://{CTRL_IP}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"GET {path} failed: {e}")
        return None

def http_post(path, payload, timeout=10):
    url = f"http://{CTRL_IP}{path}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data,
                                  headers={"Content-Type": "application/json"},
                                  method="POST")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            t1 = time.monotonic()
            return t0, t1, body
    except Exception as e:
        t1 = time.monotonic()
        print(f"POST {path} failed: {e}")
        return t0, t1, None

def collect_serial_events(t_ref, keywords, window_s=6.0):
    """Return dict of {keyword: ms_since_t_ref} for first match of each keyword."""
    found = {}
    deadline = time.monotonic() + window_s
    while time.monotonic() < deadline and len(found) < len(keywords):
        try:
            t, line = serial_q.get(timeout=0.1)
            if "[api/push]" in line or "[lamp] push" in line:
                print(f"         serial +{(t - t_ref)*1000:>6.0f} ms: {line}")
            for kw in keywords:
                if kw not in found and kw in line:
                    found[kw] = (t - t_ref) * 1000
        except queue.Empty:
            pass
    return found

# ── Start serial thread ────────────────────────────────────────────────────────
if HAVE_SERIAL:
    threading.Thread(target=read_serial, args=(SERIAL_DEV,), daemon=True).start()
    time.sleep(0.5)

# ── Get current state to use as push payload ───────────────────────────────────
print(f"Fetching state from {CTRL_IP}...")
state = http_get("/api/state")
if not state:
    print("Cannot reach controller. Are you connected to the controller's WiFi?")
    sys.exit(1)
print(f"  mode={state.get('mode')}  preset={state.get('active_preset')}\n")

# Build two alternating states — visually distinct so you can see the lamp change.
# Always push as manual so handLuminance uses the manual values we send,
# not the schedule interpolation (which would be the same every round).
manual_a = state["manual"]
manual_b = [100 if i == 0 else 0 for i in range(len(state["manual"]))]

def make_payload(manual, sched):
    return {"schedule": sched, "manual": manual, "mode": "manual"}

sched = state["schedule"]

print(f"Alternating between two states every push so you can see the lamp change.")
print(f"  State A (odd rounds):  manual={manual_a[:3]}")
print(f"  State B (even rounds): manual={manual_b[:3]}")
print(f"Note the moment the lamp VISUALLY changes and compare to 'withLamp ms'.")
print()
print(f"{'Rnd':>3}  {'State':>5}  {'HTTP ms':>8}  {'dequeue ms':>11}  {'withLamp ms':>13}  Notes")
print("─" * 66)

for rnd in range(1, ROUNDS + 1):
    drain_serial()

    label   = "A" if rnd % 2 == 1 else "B"
    manual  = manual_a if rnd % 2 == 1 else manual_b
    push_payload = make_payload(manual, sched)

    t_send, t_resp, resp = http_post("/api/push", push_payload)
    http_ms = (t_resp - t_send) * 1000

    notes = []
    if resp is None:
        notes.append("HTTP FAIL")
    elif b'"ok":true' not in resp:
        notes.append(f"resp={resp[:40]}")

    serial_events = {}
    if HAVE_SERIAL:
        serial_events = collect_serial_events(
            t_send,
            ["[lamp] push autoMode", "[lamp] push withLamp"],
            window_s=6.0
        )

    dq  = serial_events.get("[lamp] push autoMode")
    wl  = serial_events.get("[lamp] push withLamp")

    dq_str = f"{dq:>9.0f}" if dq is not None else "    timeout"
    wl_str = f"{wl:>11.0f}" if wl is not None else "      timeout"

    if wl is not None and wl > 3000:
        notes.append("slow!")
    if dq is not None and dq > 500:
        notes.append("slow dequeue!")

    print(f"{rnd:>3}  {label:>5}  {http_ms:>8.0f}  {dq_str}  {wl_str}  {' '.join(notes)}")

    time.sleep(GAP_S)

print()
print("─" * 60)
print("Column guide:")
print("  HTTP ms     — time from sending push to receiving HTTP 200")
print("                (includes: ESP32 JSON parse + saveEffectState + queuePush)")
print("  dequeue ms  — time from send to lampWorkerTask picking up the job")
print("  withLamp ms — time from send to TCP push completing on the lamp")
print()
print("If withLamp ms is small but the lamp changed later → lamp-side processing delay.")
print("If dequeue ms is large → lampWorkerTask is being blocked (mutex or backoff).")
print("If HTTP ms is large → saveEffectState or JSON parse is slow.")
