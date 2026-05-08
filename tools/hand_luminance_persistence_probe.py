#!/usr/bin/env python3
"""
Non-destructive K7 hand-luminance persistence probe.

This sends only CMD_HAND_LUMINANCE (0x10 0x05) and CMD_ALL_READ (0x10 0x08).
It never sends CMD_ALL_SET, so it should not rewrite the lamp's stored schedule.

Usage:
    python3 tools/hand_luminance_persistence_probe.py phase1 [lamp_ip] [controller_ip]
    python3 tools/hand_luminance_persistence_probe.py phase2 [lamp_ip]

Phase 1:
    - reads the lamp state
    - sends a small live luminance change
    - reads the lamp state again
    - restores the controller's last sent output when available
    - writes /tmp/k7_hand_luminance_probe.json

Phase 2:
    - run after power-cycling only the lamp
    - reads the lamp state and compares it with the phase 1 snapshot
"""

import json
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

LAMP_PORT = 8266
SNAPSHOT = Path("/tmp/k7_hand_luminance_probe.json")

PKT_START = bytes([0xAA, 0xA5])
PKT_END = bytes([0xBB])
RESP_MAGIC = bytes([0xAB, 0xAA])
CMD_HAND_LUMINANCE = bytes([0x10, 0x05])
CMD_ALL_READ = bytes([0x10, 0x08])
NUM_CH = 6
NUM_SLOTS = 24


def pkt(cmd, data=b""):
    return PKT_START + cmd + data + PKT_END


def connect(lamp_ip, timeout=4.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect((lamp_ip, LAMP_PORT))
    s.settimeout(0.05)
    try:
        s.recv(64)
    except socket.timeout:
        pass
    s.settimeout(timeout)
    return s


def recv_until_timeout(s, timeout):
    s.settimeout(timeout)
    data = b""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            chunk = s.recv(512)
            if not chunk:
                break
            data += chunk
        except socket.timeout:
            break
    return data


def send_packet(lamp_ip, packet, read_timeout=0.3):
    with connect(lamp_ip) as s:
        s.sendall(packet)
        return recv_until_timeout(s, read_timeout)


def parse_read_response(data):
    header = RESP_MAGIC + CMD_ALL_READ
    pos = data.find(header)
    if pos < 0:
        return None
    pos += len(header)
    min_len = NUM_CH + 1 + NUM_SLOTS * 8 + 1
    if pos + min_len > len(data):
        return None

    manual = list(data[pos:pos + NUM_CH])
    pos += NUM_CH
    time_num = data[pos]
    pos += 1
    schedule = []
    for _ in range(min(time_num, NUM_SLOTS)):
        schedule.append(list(data[pos:pos + 8]))
        pos += 8
    auto_mode = bool(data[pos])
    pos += 1
    name_bytes = data[pos:pos + 11]
    name = name_bytes.split(b"\x00", 1)[0].decode("ascii", "replace")
    return {
        "manual": manual,
        "time_num": time_num,
        "schedule": schedule,
        "auto_mode": auto_mode,
        "name": name,
    }


def read_lamp(lamp_ip):
    with connect(lamp_ip) as s:
        s.sendall(pkt(CMD_ALL_READ))
        raw = recv_until_timeout(s, 5.0)
    parsed = parse_read_response(raw)
    if not parsed:
        raise RuntimeError(f"Could not parse CMD_ALL_READ response: {raw.hex()}")
    return parsed


def hand_luminance(lamp_ip, channels):
    data = bytes(max(0, min(100, int(v))) for v in channels[:NUM_CH])
    if len(data) != NUM_CH:
        raise ValueError("Need exactly 6 channel values")
    return send_packet(lamp_ip, pkt(CMD_HAND_LUMINANCE, data), read_timeout=0.3)


def get_controller_output(controller_ip):
    try:
        with urllib.request.urlopen(
            f"http://{controller_ip}/api/output/status", timeout=4
        ) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    if doc.get("has_sent") and isinstance(doc.get("sent"), list):
        sent = [int(v) for v in doc["sent"][:NUM_CH]]
        return sent + [0] * (NUM_CH - len(sent))
    return None


def make_probe_value(current):
    probe = list(current[:NUM_CH])
    idx = 0
    for i, value in enumerate(probe):
        if value > 0:
            idx = i
            break
    probe[idx] = 1 if probe[idx] >= 2 else 3
    return probe


def same_schedule(a, b):
    return a.get("time_num") == b.get("time_num") and a.get("schedule") == b.get("schedule")


def phase1(lamp_ip, controller_ip):
    restore = get_controller_output(controller_ip) if controller_ip else None
    before = read_lamp(lamp_ip)
    base = restore or before["manual"]
    probe = make_probe_value(base)

    print(f"Lamp name: {before['name']}")
    print(f"Baseline manual/readback: {before['manual']}")
    print(f"Controller restore value: {restore if restore else '(not available)'}")
    print(f"Sending live-only probe value: {probe}")
    hand_luminance(lamp_ip, probe)
    time.sleep(0.6)
    after_probe = read_lamp(lamp_ip)

    restore_value = restore or before["manual"]
    print(f"Restoring live output value: {restore_value}")
    hand_luminance(lamp_ip, restore_value)
    time.sleep(0.6)
    after_restore = read_lamp(lamp_ip)

    snapshot = {
        "lamp_ip": lamp_ip,
        "controller_ip": controller_ip,
        "before": before,
        "probe": probe,
        "after_probe": after_probe,
        "restore_value": restore_value,
        "after_restore": after_restore,
        "schedule_unchanged_after_probe": same_schedule(before, after_probe),
        "schedule_unchanged_after_restore": same_schedule(before, after_restore),
        "created_at": time.time(),
    }
    SNAPSHOT.write_text(json.dumps(snapshot, indent=2) + "\n")

    print(f"After probe manual/readback: {after_probe['manual']}")
    print(f"After restore manual/readback: {after_restore['manual']}")
    print(f"Schedule unchanged after probe: {snapshot['schedule_unchanged_after_probe']}")
    print(f"Schedule unchanged after restore: {snapshot['schedule_unchanged_after_restore']}")
    print(f"Wrote snapshot: {SNAPSHOT}")
    print("Power-cycle only the lamp, then run phase2 to check whether the probe value persisted.")


def phase2(lamp_ip):
    snapshot = json.loads(SNAPSHOT.read_text())
    current = read_lamp(lamp_ip)
    probe = snapshot["probe"]
    restore = snapshot["restore_value"]
    print(f"Current manual/readback after power cycle: {current['manual']}")
    print(f"Phase 1 probe value: {probe}")
    print(f"Phase 1 restore value: {restore}")
    print(f"Schedule unchanged vs phase 1 baseline: {same_schedule(snapshot['before'], current)}")
    if current["manual"] == probe:
        print("Result: live probe value appears to have persisted across power cycle.")
    elif current["manual"] == restore:
        print("Result: restored value is present after power cycle.")
    elif current["manual"] == snapshot["before"]["manual"]:
        print("Result: original baseline value is present after power cycle.")
    else:
        print("Result: current value differs from probe, restore, and baseline.")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("phase1", "phase2"):
        print(__doc__.strip())
        raise SystemExit(2)
    command = sys.argv[1]
    lamp_ip = sys.argv[2] if len(sys.argv) > 2 else "192.168.4.1"
    controller_ip = sys.argv[3] if len(sys.argv) > 3 else "192.168.4.200"
    if command == "phase1":
        phase1(lamp_ip, controller_ip)
    else:
        phase2(lamp_ip)


if __name__ == "__main__":
    main()
