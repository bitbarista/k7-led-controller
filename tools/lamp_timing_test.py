#!/usr/bin/env python3
"""
K7 lamp TCP timing / ack probe.

Run this while connected DIRECTLY to the lamp's WiFi (K7mini… SSID, pw 12345678)
with the ESP32 controller powered OFF so the lamp's TCP port is free.

Usage:
    python3 tools/lamp_timing_test.py [lamp_ip]
    Default lamp IP: 192.168.4.1
"""

import socket, time, sys, struct

LAMP_IP   = sys.argv[1] if len(sys.argv) > 1 else "192.168.4.1"
LAMP_PORT = 8266

PKT_START         = bytes([0xAA, 0xA5])
PKT_END           = bytes([0xBB])
CMD_HAND_LUMINANCE = bytes([0x10, 0x05])
CMD_ALL_SET        = bytes([0x10, 0x07])
CMD_ALL_READ       = bytes([0x10, 0x08])
CMD_CHANGE_MODE    = bytes([0x10, 0x04])

# K7 Mini = 3 meaningful channels; firmware always sends 6 bytes (zeros for unused)
NUM_CH = 6

# Two distinct brightness states to toggle between
STATE_A = bytes([80, 100, 100, 0, 0, 0])   # bright bluish
STATE_B = bytes([30,  20,  10, 0, 0, 0])   # dim warm

def pkt(cmd, data=b''):
    return PKT_START + cmd + data + PKT_END

def connect(timeout=3.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    t0 = time.monotonic()
    try:
        s.connect((LAMP_IP, LAMP_PORT))
    except Exception as e:
        return None, time.monotonic() - t0, f"CONNECT FAILED: {e}"
    elapsed = time.monotonic() - t0
    # drain greeting (lamp sends nothing, but be safe)
    s.settimeout(0.05)
    greeting = b''
    try: greeting = s.recv(64)
    except: pass
    s.settimeout(timeout)
    return s, elapsed, greeting

def recv_with_timeout(s, timeout=0.5):
    s.settimeout(timeout)
    data = b''
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            chunk = s.recv(256)
            if not chunk:
                break
            data += chunk
        except socket.timeout:
            break
    return data

def send_and_recv(s, packet, ack_timeout=0.5):
    t0 = time.monotonic()
    s.sendall(packet)
    ack = recv_with_timeout(s, ack_timeout)
    return ack, time.monotonic() - t0

def close(s):
    try: s.close()
    except: pass

def hex_or_none(data):
    return data.hex() if data else "(none)"

def parse_read_response(data):
    """Extract current channel values from CMD_ALL_READ response.

    The lamp often delivers queued acks (AB AA A5 A1/A2) on the next
    connection before the actual response. Search for the CMD_ALL_READ
    response header AB AA 10 08 rather than assuming data starts cleanly.
    """
    HEADER = bytes([0xAB, 0xAA, 0x10, 0x08])
    pos = data.find(HEADER)
    if pos == -1:
        return None
    pos += 4  # skip header, channels start here
    if pos + NUM_CH > len(data):
        return None
    return list(data[pos:pos + NUM_CH])

# ── separator ────────────────────────────────────────────────────────────────
def sep(title=""):
    print()
    print("─" * 60)
    if title:
        print(f"  {title}")
        print("─" * 60)

# ═══════════════════════════════════════════════════════════════════════════
sep("TEST 1 — ACK PROBE: what does the lamp send back?")
# Send CMD_HAND_LUMINANCE and CMD_ALL_SET with a generous ack window
# and log every byte received.
# ═══════════════════════════════════════════════════════════════════════════

def make_all_set(state):
    return (state
            + bytes([24])
            + b''.join(bytes([h, 0]) + state for h in range(24))
            + bytes([0x00])   # manual mode
            + bytes([12, 0, 0]))

for label, cmd, data in [
    ("CMD_HAND_LUMINANCE (state A)", CMD_HAND_LUMINANCE, STATE_A),
    ("CMD_HAND_LUMINANCE (state B)", CMD_HAND_LUMINANCE, STATE_B),
    ("CMD_ALL_SET (state A, manual)", CMD_ALL_SET, make_all_set(STATE_A)),
]:
    s, conn_ms, greeting = connect()
    if s is None:
        print(f"  [{label}] {greeting}")
        continue
    print(f"  [{label}]")
    print(f"    connect: {conn_ms*1000:.0f} ms  greeting: {hex_or_none(greeting)}")
    ack, elapsed = send_and_recv(s, pkt(cmd, data), ack_timeout=1.0)
    print(f"    ack ({elapsed*1000:.0f} ms wait): {hex_or_none(ack)}")
    close(s)
    time.sleep(0.5)

# ═══════════════════════════════════════════════════════════════════════════
sep("TEST 2 — CMD_ALL_READ: baseline state")
# ═══════════════════════════════════════════════════════════════════════════

s, conn_ms, _ = connect()
if s:
    s.sendall(pkt(CMD_ALL_READ))
    # discard short echo
    recv_with_timeout(s, 0.3)
    # read full state
    data = recv_with_timeout(s, 5.0)
    ch = parse_read_response(data)
    print(f"  Current channels: {ch}  (raw {len(data)} bytes: {data[:20].hex()}…)")
    close(s)
    time.sleep(0.5)

# ═══════════════════════════════════════════════════════════════════════════
sep("TEST 3 — INTERVAL SWEEP: min gap between consecutive connections")
# Set state A, close, wait N ms, set state B, read back, check if B stuck.
# ═══════════════════════════════════════════════════════════════════════════

intervals_ms = [0, 50, 100, 200, 300, 500, 750, 1000, 1500, 2000]
print(f"  {'Gap (ms)':>10}  {'Connect (ms)':>14}  {'Ack bytes':>12}  {'Readback ch0-2':>18}  Result")

for gap_ms in intervals_ms:
    # Push state A
    s, _, _ = connect()
    if s is None:
        print(f"  {gap_ms:>10}  CONNECT FAILED (push A)")
        continue
    send_and_recv(s, pkt(CMD_HAND_LUMINANCE, STATE_A), ack_timeout=0.15)
    close(s)

    time.sleep(gap_ms / 1000)

    # Push state B
    s, conn_ms, _ = connect()
    if s is None:
        print(f"  {gap_ms:>10}  CONNECT FAILED (push B, gap={gap_ms}ms)")
        time.sleep(1.0)
        continue
    ack, _ = send_and_recv(s, pkt(CMD_HAND_LUMINANCE, STATE_B), ack_timeout=0.15)
    close(s)

    time.sleep(0.3)

    # Read back
    s, _, _ = connect()
    if s is None:
        print(f"  {gap_ms:>10}  CONNECT FAILED (readback)")
        time.sleep(1.0)
        continue
    s.sendall(pkt(CMD_ALL_READ))
    recv_with_timeout(s, 0.3)
    raw = recv_with_timeout(s, 5.0)
    close(s)
    ch = parse_read_response(raw)

    if ch is None:
        result = "PARSE FAIL"
        ch_str = "?"
    else:
        ch_str = f"{ch[0]:3d} {ch[1]:3d} {ch[2]:3d}"
        # STATE_B = [30, 20, 10] — if it stuck we should see those values
        ok = (ch[0] == STATE_B[0] and ch[1] == STATE_B[1] and ch[2] == STATE_B[2])
        result = "OK — B stuck" if ok else "MISS — A or intermediate"

    print(f"  {gap_ms:>10}  {conn_ms*1000:>12.0f}  {hex_or_none(ack):>12}  {ch_str:>18}  {result}")
    time.sleep(1.0)  # cool down between rounds

# ═══════════════════════════════════════════════════════════════════════════
sep("TEST 4 — CMD_ALL_SET interference")
# Same interval sweep but with CMD_ALL_SET before CMD_HAND_LUMINANCE
# (mirrors what our firmware does). Does CMD_ALL_SET cause more misses?
# ═══════════════════════════════════════════════════════════════════════════

intervals_ms2 = [0, 100, 300, 500, 1000]
print(f"  {'Gap (ms)':>10}  {'set_ack':>10}  {'lum_ack':>10}  {'Readback ch0-2':>18}  Result")

for gap_ms in intervals_ms2:
    # Push state A via ALL_SET + HAND_LUMINANCE
    s, _, _ = connect()
    if s is None:
        print(f"  {gap_ms:>10}  CONNECT FAILED (push A)")
        continue
    send_and_recv(s, pkt(CMD_ALL_SET, make_all_set(STATE_A)), ack_timeout=0.15)
    send_and_recv(s, pkt(CMD_HAND_LUMINANCE, STATE_A), ack_timeout=0.15)
    close(s)

    time.sleep(gap_ms / 1000)

    # Push state B via ALL_SET + HAND_LUMINANCE
    s, _, _ = connect()
    if s is None:
        print(f"  {gap_ms:>10}  CONNECT FAILED (push B)")
        time.sleep(1.0)
        continue
    set_ack, _ = send_and_recv(s, pkt(CMD_ALL_SET, make_all_set(STATE_B)), ack_timeout=0.15)
    lum_ack, _ = send_and_recv(s, pkt(CMD_HAND_LUMINANCE, STATE_B), ack_timeout=0.15)
    close(s)

    time.sleep(0.3)

    # Read back
    s, _, _ = connect()
    if s is None:
        print(f"  {gap_ms:>10}  CONNECT FAILED (readback)")
        time.sleep(1.0)
        continue
    s.sendall(pkt(CMD_ALL_READ))
    recv_with_timeout(s, 0.3)
    raw = recv_with_timeout(s, 5.0)
    close(s)
    ch = parse_read_response(raw)

    if ch is None:
        result, ch_str = "PARSE FAIL", "?"
    else:
        ch_str = f"{ch[0]:3d} {ch[1]:3d} {ch[2]:3d}"
        ok = (ch[0] == STATE_B[0] and ch[1] == STATE_B[1] and ch[2] == STATE_B[2])
        result = "OK — B stuck" if ok else "MISS — A or intermediate"

    print(f"  {gap_ms:>10}  {hex_or_none(set_ack):>10}  {hex_or_none(lum_ack):>10}  {ch_str:>18}  {result}")
    time.sleep(1.0)

# ═══════════════════════════════════════════════════════════════════════════
sep("TEST 5 — RAPID FIRE: 5 consecutive changes, which one sticks?")
# ═══════════════════════════════════════════════════════════════════════════

states = [
    ("A", bytes([80, 100, 100, 0, 0, 0])),
    ("B", bytes([30,  20,  10, 0, 0, 0])),
    ("C", bytes([60,  50,  40, 0, 0, 0])),
    ("D", bytes([10,  80,  60, 0, 0, 0])),
    ("E", bytes([50,  50,  50, 0, 0, 0])),
]

print("  Sending A→B→C→D→E as fast as possible (no deliberate delay between):")
timings = []
for label, state in states:
    s, conn_ms, _ = connect(timeout=2.0)
    if s is None:
        print(f"    {label}: CONNECT FAILED")
        continue
    ack, elapsed = send_and_recv(s, pkt(CMD_HAND_LUMINANCE, state), ack_timeout=0.15)
    close(s)
    timings.append((label, conn_ms*1000, elapsed*1000, hex_or_none(ack)))
    print(f"    {label}: connect {conn_ms*1000:.0f}ms  ack_wait {elapsed*1000:.0f}ms  ack={hex_or_none(ack)}")

time.sleep(0.3)
s, _, _ = connect()
if s:
    s.sendall(pkt(CMD_ALL_READ))
    recv_with_timeout(s, 0.3)
    raw = recv_with_timeout(s, 5.0)
    close(s)
    ch = parse_read_response(raw)
    print(f"  Final readback: {ch}  (expected E=[50,50,50,0,0,0])")

# ═══════════════════════════════════════════════════════════════════════════
sep("TEST 6 — ACK WAIT DEPTH: 1500ms vs 150ms, which reliably sticks?")
# Theory: lamp needs ~1000ms to commit a command. Closing the TCP connection
# before the ack arrives (FIN interrupts processing) causes silent drops.
# This test pairs each push with a readback to confirm whether it actually
# applied. All readbacks use a fresh connection with a single recv pass
# (no discard step) to avoid the parse bug seen in Tests 3-5.
# ═══════════════════════════════════════════════════════════════════════════

def clean_readback():
    """
    Read lamp state on a fresh connection with no prior pending acks.
    Returns (channels_list, raw_bytes) or (None, raw_bytes).
    """
    s, _, _ = connect()
    if s is None:
        return None, b''
    s.sendall(pkt(CMD_ALL_READ))
    # Single pass — no discard. ALL_READ response arrives within ~300ms;
    # the 5s window catches it whether the lamp is quick or slow.
    raw = recv_with_timeout(s, 5.0)
    close(s)
    # The real ALL_READ response is 200+ bytes; ack stubs are 4 bytes.
    # Find the longest AB-AA-prefixed chunk.
    ch = parse_read_response(raw)
    return ch, raw

ROUNDS = 5
print(f"  {ROUNDS} rounds per variant. Baseline (STATE_A) set before each push.")
print(f"  STATE_A={list(STATE_A[:3])}  STATE_B={list(STATE_B[:3])}")
print()

def run_variant(label, ack_wait_ms):
    ok_count = 0
    for i in range(ROUNDS):
        # --- set baseline STATE_A with a long wait so it reliably applies ---
        s, _, _ = connect()
        if s:
            send_and_recv(s, pkt(CMD_HAND_LUMINANCE, STATE_A), ack_timeout=1.5)
            close(s)
        time.sleep(0.5)

        # --- push STATE_B with the variant ack wait ---
        s, _, _ = connect()
        if s is None:
            print(f"    [{label}] round {i+1}: CONNECT FAILED (push B)")
            continue
        ack, elapsed = send_and_recv(s, pkt(CMD_HAND_LUMINANCE, STATE_B),
                                     ack_timeout=ack_wait_ms / 1000)
        close(s)
        time.sleep(0.5)

        # --- read back ---
        ch, raw = clean_readback()
        if ch is None:
            print(f"    [{label}] round {i+1}: READBACK FAILED  raw={raw[:12].hex() if raw else '?'}")
            continue

        b_stuck = (ch[0] == STATE_B[0] and ch[1] == STATE_B[1] and ch[2] == STATE_B[2])
        a_stuck = (ch[0] == STATE_A[0] and ch[1] == STATE_A[1] and ch[2] == STATE_A[2])
        verdict = "B STUCK ✓" if b_stuck else ("A STUCK" if a_stuck else "OTHER")
        if b_stuck:
            ok_count += 1
        print(f"    [{label}] round {i+1}: ack={hex_or_none(ack)} ({elapsed*1000:.0f} ms)  "
              f"ch={ch[:3]}  raw[0:8]={raw[:8].hex()}  → {verdict}")
        time.sleep(1.0)

    return ok_count

a_ok = run_variant("1500ms", 1500)
print()
b_ok = run_variant(" 150ms", 150)

print()
print(f"  ── RESULT ──────────────────────────────────────────────────────")
print(f"  1500ms ack wait: {a_ok}/{ROUNDS} applied correctly")
print(f"   150ms ack wait: {b_ok}/{ROUNDS} applied correctly")
if a_ok > b_ok:
    print("  → Waiting for ack reliably applies commands.")
    print("    Fix: increase _recvAck() timeout in K7Lamp.cpp to ≥1500ms.")
elif a_ok == b_ok and a_ok == ROUNDS:
    print("  → Both variants reliable — ack wait is not the cause.")
elif a_ok == b_ok:
    print("  → Neither variant reliable — something else is wrong.")
else:
    print("  → 150ms outperformed 1500ms — unexpected, investigate further.")

sep("DONE")
print()
