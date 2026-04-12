#!/usr/bin/env python3
"""
Noo-Psyche K7 LED controller — PC client
Reverse engineered from noo_release_203.apk

Protocol: TCP to device_ip:8266
Packet:   AA A5 [CMD HI CMD LO] [data...] BB
Response: AB AA [CMD HI CMD LO] [data...] BB

AP mode:  connect to WiFi SSID "K7_mini****", password 12345678
          device IP = 192.168.4.1
LAN mode: find device IP from your router's DHCP table
"""

import socket
import time
import sys

# ── Protocol constants ────────────────────────────────────────────────────────

START = bytes.fromhex('AAA5')
END   = bytes.fromhex('BB')
RESP  = bytes.fromhex('ABAA')

CMD_SYNC_TIME         = bytes.fromhex('1003')
CMD_CHANGE_MODE       = bytes.fromhex('1004')
CMD_HAND_LUMINANCE    = bytes.fromhex('1005')
CMD_PREVIEW_LUMINANCE = bytes.fromhex('1006')
CMD_ALL_SET           = bytes.fromhex('1007')
CMD_ALL_READ          = bytes.fromhex('1008')
CMD_DEMONSTRATION     = bytes.fromhex('100A')

TIME_NUM = 24   # hourly schedule slots (0x18)

# ── Device profiles ───────────────────────────────────────────────────────────
#
# The protocol always carries 6 channel bytes; the Mini simply uses the first 3.
# Channel order is fixed by the firmware — don't reorder.

DEVICES = {
    'k7mini': {
        'label':    'K7 Mini',
        'channels': ['white', 'royal_blue', 'blue'],
    },
    'k7pro': {
        'label':    'K7 Pro',
        'channels': ['uv', 'royal_blue', 'blue', 'white', 'warm_white', 'red'],
    },
}
NUM_CH = 6   # protocol always sends 6 bytes


def _pkt(cmd: bytes, data: bytes = b'') -> bytes:
    return START + cmd + data + END


# ── Response decoder ──────────────────────────────────────────────────────────

def decode_state(data: bytes) -> dict | None:
    """
    Decode a READ_ALL response (222 bytes) into:
      {
        'name':     str,
        'mode':     'auto' | 'manual',
        'manual':   [int × 6],          # 0-100 per channel
        'schedule': [(h, m, c0..c5) × 24]
      }
    """
    if len(data) < 10 or data[:2] != RESP or data[-1] != 0xBB:
        return None
    pos = 4                                       # skip ABAA + cmd echo
    manual   = list(data[pos:pos+6]);   pos += 6
    time_num = data[pos];               pos += 1
    schedule = []
    for _ in range(time_num):
        schedule.append(tuple(data[pos:pos+8])); pos += 8
    mode = 'auto' if data[pos] else 'manual';   pos += 1
    name = data[pos:pos+11].rstrip(b'\x00').decode('ascii', errors='replace')
    return {'name': name, 'mode': mode, 'manual': manual, 'schedule': schedule}


def print_state(state: dict, device: str = 'k7mini'):
    chs = DEVICES[device]['channels']
    full = ['uv', 'royal_blue', 'blue', 'white', 'warm_white', 'red']
    print(f"Device : {state['name']}  ({DEVICES[device]['label']})")
    print(f"Mode   : {state['mode'].upper()}")
    print("Manual brightness:")
    for i, ch in enumerate(full):
        v = state['manual'][i]
        if ch in chs or v > 0:
            bar  = '#' * (v // 5)
            name = ch.replace('_', ' ').title()
            print(f"  {name:12s}: {v:3d}%  {bar}")
    print(f"Schedule ({len(state['schedule'])} time points):")
    hdr = '  '.join(f"{c.replace('_',' ').title():11s}" for c in chs)
    print(f"  Hr   {hdr}")
    for e in state['schedule']:
        vals = [e[2 + full.index(c)] for c in chs]
        if any(v > 0 for v in vals):
            row = '  '.join(f"{v:3d}%      " for v in vals)
            print(f"  {e[0]:02d}   {row}")
        else:
            print(f"  {e[0]:02d}   (all off)")


# ── YAML schedule file ────────────────────────────────────────────────────────
#
# Uses only the stdlib — no PyYAML needed.
# The file format is simple enough to parse with a tiny hand-rolled parser,
# but we use json for round-trips since Python's json handles dicts/lists
# and is always available.  We write human-friendly output manually.

import json, re

def state_to_yaml(state: dict, device: str) -> str:
    chs  = DEVICES[device]['channels']
    full = ['uv', 'royal_blue', 'blue', 'white', 'warm_white', 'red']
    lines = [
        f"# Noo-Psyche {DEVICES[device]['label']} schedule",
        f"# Generated {time.strftime('%Y-%m-%d %H:%M')}",
        f"device: {device}",
        f"mode: {state['mode']}",
        "",
        "# Manual brightness used when mode is 'manual' (0-100)",
        "manual:",
    ]
    for ch in chs:
        v = state['manual'][full.index(ch)]
        lines.append(f"  {ch}: {v}")
    lines += [
        "",
        "# 24 hourly time points (hours 0-23).",
        "# Omitted hours default to all channels off.",
        "# You may list only the non-zero hours for brevity.",
        "schedule:",
    ]
    for e in state['schedule']:
        vals = {ch: e[2 + full.index(ch)] for ch in chs}
        if any(v > 0 for v in vals.values()):
            ch_str = '  '.join(f"{ch}: {vals[ch]}" for ch in chs)
            lines.append(f"  - hour: {e[0]:2d}  minute: {e[1]:2d}  {ch_str}")
        else:
            lines.append(f"  - hour: {e[0]:2d}  minute: {e[1]:2d}  # off")
    return '\n'.join(lines) + '\n'


def yaml_to_schedule(path: str) -> tuple[str, str, list[int], list[tuple]]:
    """
    Parse the YAML file and return (device, mode, manual[6], schedule[24]).
    schedule entries are (hour, minute, c0, c1, c2, c3, c4, c5).
    """
    full = ['uv', 'royal_blue', 'blue', 'white', 'warm_white', 'red']

    with open(path) as f:
        text = f.read()

    def _val(key, src):
        m = re.search(rf'\b{key}\s*:\s*(\S+)', src)
        return m.group(1).strip() if m else None

    device = _val('device', text) or 'k7mini'
    mode   = _val('mode',   text) or 'auto'
    if device not in DEVICES:
        raise ValueError(f"Unknown device '{device}'. Choose: {list(DEVICES)}")
    chs = DEVICES[device]['channels']

    # Parse manual section
    m_block = re.search(r'manual:(.*?)(?=\nschedule:|\Z)', text, re.DOTALL)
    manual = [0] * 6
    if m_block:
        for ch in chs:
            v = _val(ch, m_block.group(1))
            if v is not None:
                manual[full.index(ch)] = int(v)

    # Parse schedule section — each "- hour: N ..." line
    sched_entries = {}
    s_block = re.search(r'schedule:(.*)', text, re.DOTALL)
    if s_block:
        for line in s_block.group(1).splitlines():
            if not line.strip().startswith('-'):
                continue
            h = _val('hour',   line)
            m = _val('minute', line)
            if h is None:
                continue
            hour, minute = int(h), int(m or 0)
            vals = [0] * 6
            for ch in chs:
                v = _val(ch, line)
                if v is not None:
                    vals[full.index(ch)] = int(v)
            sched_entries[hour] = (hour, minute, *vals)

    # Fill all 24 slots; missing hours are all-off
    schedule = []
    for hr in range(TIME_NUM):
        if hr in sched_entries:
            schedule.append(sched_entries[hr])
        else:
            schedule.append((hr, 0, 0, 0, 0, 0, 0, 0))

    return device, mode, manual, schedule


# ── K7 class ──────────────────────────────────────────────────────────────────

class K7:
    def __init__(self, host: str = '192.168.4.1', port: int = 8266,
                 timeout: float = 5.0, verbose: bool = True):
        self.host    = host
        self.port    = port
        self.timeout = timeout
        self.verbose = verbose
        self._sock   = None

    # ── Connection ────────────────────────────────────────────────────────────

    def connect(self):
        if self.verbose:
            print(f"Connecting to {self.host}:{self.port} ...", flush=True)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout)
        self._sock.connect((self.host, self.port))
        if self.verbose:
            print("Connected.")
        # Drain any greeting (there usually isn't one)
        self._sock.settimeout(1.0)
        self._recv()
        self._sock.settimeout(self.timeout)

    def close(self):
        if self._sock:
            try: self._sock.close()
            except: pass
            self._sock = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()

    # ── Low-level I/O ─────────────────────────────────────────────────────────

    def _recv(self, drain: bool = False) -> bytes:
        buf = b''
        saved = self._sock.gettimeout()
        try:
            while True:
                chunk = self._sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
                if not drain:
                    break
                self._sock.settimeout(0.5)
        except socket.timeout:
            pass
        finally:
            self._sock.settimeout(saved)
        if buf and self.verbose:
            h = buf.hex().upper()
            print(f"  RX: {' '.join(h[i:i+2] for i in range(0, len(h), 2))}")
        return buf

    def _send(self, pkt: bytes, drain: bool = False) -> bytes:
        if self.verbose:
            h = pkt.hex().upper()
            print(f"  TX: {' '.join(h[i:i+2] for i in range(0, len(h), 2))}")
        self._sock.sendall(pkt)
        return self._recv(drain=drain)

    # ── Commands ──────────────────────────────────────────────────────────────

    def read_all(self) -> bytes:
        """
        Read all settings from the device.
        Returns the raw 222-byte response; pass to decode_state().
        The device first echoes a 4-byte model-ID which we discard,
        then sends the full state packet.
        """
        pkt = _pkt(CMD_ALL_READ)
        if self.verbose:
            h = pkt.hex().upper()
            print(f"  TX: {' '.join(h[i:i+2] for i in range(0, len(h), 2))}")
        self._sock.sendall(pkt)
        self._recv()                       # discard model-ID echo (ABAAA5A1)
        self._sock.settimeout(5.0)
        data = self._recv(drain=True)
        self._sock.settimeout(self.timeout)
        return data

    def set_brightness(self, channels: list[int]):
        """Immediately set manual brightness. channels: 6 ints 0-100."""
        assert len(channels) == NUM_CH and all(0 <= v <= 100 for v in channels)
        self._send(_pkt(CMD_HAND_LUMINANCE, bytes(channels)))

    def preview_brightness(self, channels: list[int]):
        """Preview brightness without saving."""
        assert len(channels) == NUM_CH and all(0 <= v <= 100 for v in channels)
        self._send(_pkt(CMD_PREVIEW_LUMINANCE, bytes(channels)))

    def set_mode_manual(self):
        self._send(_pkt(CMD_CHANGE_MODE, b'\x00'))

    def set_mode_auto(self):
        self._send(_pkt(CMD_CHANGE_MODE, b'\x01'))

    def demo_mode(self, enable: bool):
        """Demo on = 0x00, off = 0x01 (inverted in firmware)."""
        self._send(_pkt(CMD_DEMONSTRATION, b'\x00' if enable else b'\x01'))

    def sync_time(self, h: int = None, m: int = None, s: int = None):
        now = time.localtime()
        data = bytes([
            h if h is not None else now.tm_hour,
            m if m is not None else now.tm_min,
            s if s is not None else now.tm_sec,
        ])
        self._send(_pkt(CMD_SYNC_TIME, data))

    def push_schedule(self, manual: list[int], schedule: list[tuple],
                      mode: str = 'auto'):
        """
        Push a full schedule + manual brightness + mode to the device.
        Also syncs the device clock to current PC time.

        Packet layout (derived from allSet() bytecode):
          [manual 6B] [0x18] [schedule 24×8B] [mode 1B] [hour min sec 3B]

        manual:   6-element list (0-100 per channel)
        schedule: 24 tuples of (hour, minute, c0, c1, c2, c3, c4, c5)
        mode:     'auto' or 'manual'
        """
        assert len(manual) == NUM_CH
        assert len(schedule) == TIME_NUM

        now = time.localtime()
        time_bytes   = bytes([now.tm_hour, now.tm_min, now.tm_sec])
        manual_bytes = bytes(manual)
        sched_bytes  = b''.join(bytes(e) for e in schedule)
        mode_byte    = b'\x01' if mode == 'auto' else b'\x00'

        data = manual_bytes + bytes([TIME_NUM]) + sched_bytes + mode_byte + time_bytes
        self._send(_pkt(CMD_ALL_SET, data))


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_vals(s: str) -> list[int]:
    return [int(x) for x in re.split(r'[\s,]+', s.strip()) if x]


def main():
    import argparse, os

    ap = argparse.ArgumentParser(
        prog='k7mini',
        description='Control a Noo-Psyche K7 LED lamp over WiFi',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  read            Show current state (mode, brightness, schedule)
  save FILE       Read state and save to a YAML schedule file
  push FILE       Push a YAML schedule file to the device
  manual VALUES   Set manual brightness, e.g.: 0,80,50,0,0,0
  preview VALUES  Preview brightness without saving
  auto            Switch to auto (scheduled) mode
  sync-time       Sync device clock to current PC time
  demo on|off     Enable / disable demo mode

YAML schedule file:
  device: k7mini        # k7mini (3ch) or k7pro (6ch)
  mode: auto            # auto or manual
  manual:
    uv: 0
    royal_blue: 50
    blue: 40
  schedule:
    - hour:  9  minute: 0  uv: 0  royal_blue: 5  blue: 10
    - hour: 15  minute: 0  uv: 65  royal_blue: 85  blue: 95
    ...                            # omitted hours = all off
""")

    ap.add_argument('--host',    default='192.168.4.1')
    ap.add_argument('--port',    type=int, default=8266)
    ap.add_argument('--device',  default='k7mini',
                    choices=list(DEVICES), help='Device type for display/YAML')
    ap.add_argument('--quiet',   action='store_true', help='Suppress TX/RX lines')
    ap.add_argument('command',   choices=['read','save','push','manual','preview',
                                          'auto','sync-time','demo'])
    ap.add_argument('args',      nargs='*')
    args = ap.parse_args()

    with K7(args.host, args.port, verbose=not args.quiet) as lamp:

        if args.command == 'read':
            data  = lamp.read_all()
            state = decode_state(data)
            if state:
                print()
                print_state(state, args.device)
            else:
                sys.exit(f"Bad response: {data.hex() if data else '(none)'}")

        elif args.command == 'save':
            if not args.args:
                ap.error("'save' requires a filename, e.g.: save schedule.yaml")
            path  = args.args[0]
            data  = lamp.read_all()
            state = decode_state(data)
            if not state:
                sys.exit(f"Bad response: {data.hex() if data else '(none)'}")
            yaml  = state_to_yaml(state, args.device)
            with open(path, 'w') as f:
                f.write(yaml)
            print(f"\nSaved to {path}")
            print_state(state, args.device)

        elif args.command == 'push':
            if not args.args:
                ap.error("'push' requires a filename, e.g.: push schedule.yaml")
            path = args.args[0]
            if not os.path.exists(path):
                sys.exit(f"File not found: {path}")
            device, mode, manual, schedule = yaml_to_schedule(path)
            print(f"Pushing {path}  [{DEVICES[device]['label']}, mode={mode}]")
            lamp.push_schedule(manual, schedule, mode)
            print("Done.")

        elif args.command == 'manual':
            if not args.args:
                ap.error("Provide channel values, e.g.: manual 0,80,50,0,0,0")
            vals = _parse_vals(args.args[0])
            if len(vals) < NUM_CH:
                vals += [0] * (NUM_CH - len(vals))
            lamp.set_mode_manual()
            time.sleep(0.2)
            lamp.set_brightness(vals[:NUM_CH])
            print("Done.")

        elif args.command == 'preview':
            if not args.args:
                ap.error("Provide channel values")
            vals = _parse_vals(args.args[0])
            if len(vals) < NUM_CH:
                vals += [0] * (NUM_CH - len(vals))
            lamp.preview_brightness(vals[:NUM_CH])
            print("Done.")

        elif args.command == 'auto':
            lamp.set_mode_auto()
            print("Switched to auto mode.")

        elif args.command == 'sync-time':
            lamp.sync_time()
            print(f"Synced: {time.strftime('%H:%M:%S')}")

        elif args.command == 'demo':
            if not args.args or args.args[0] not in ('on', 'off'):
                ap.error("'demo' requires 'on' or 'off'")
            lamp.demo_mode(args.args[0] == 'on')
            print(f"Demo {'enabled' if args.args[0]=='on' else 'disabled'}.")


if __name__ == '__main__':
    main()
