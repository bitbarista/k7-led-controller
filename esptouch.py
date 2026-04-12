"""
ESPTouch v1 WiFi provisioning for Noo-Psyche K7 LED lamps.

Protocol confirmed from noo_release_203.apk (com.espressif.iot.esptouch):
  - CRC8 polynomial 0x8C (Dallas/Maxim)
  - Guide code packet sizes: [515, 514, 513, 512], interval ~8 ms
  - Each data byte → 3 UDP packets; sizes = encoded nibbles + 40
  - BSSID bytes interleaved at positions 5, 9, 13, 17, 21, 25 in the sequence
  - Broadcast to 255.255.255.255 on port 7001
  - Device responds on port 18266 when it connects successfully

Before calling: put lamp in LAN mode, then hold R button until blue flash (enters
"waiting for config" state). PC must be connected to the target 2.4 GHz network.
"""

import socket
import struct
import time
import threading
import subprocess
import re


# ── Constants ─────────────────────────────────────────────────────────────────
BCAST_ADDR    = '255.255.255.255'
PORT_SEND     = 7001
PORT_LISTEN   = 18266
GUIDE_SIZES   = [515, 514, 513, 512]
DATA_OFFSET   = 40      # added to all data-code packet sizes
TIMEOUT_GUIDE = 4.0     # seconds of guide code before data starts
TIMEOUT_TOTAL = 40.0    # total provisioning timeout (seconds)
INTERVAL_GC   = 0.008   # seconds between guide code packets
INTERVAL_DC   = 0.008   # seconds between data code packets


# ── CRC8 (polynomial 0x8C, confirmed from APK) ────────────────────────────────
_CRC8_TABLE = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = (_c >> 1) ^ 0x8C if (_c & 1) else (_c >> 1)
    _CRC8_TABLE.append(_c & 0xFF)

def _crc8(data: bytes) -> int:
    crc = 0
    for b in data:
        crc = _CRC8_TABLE[(crc ^ b) & 0xFF]
    return crc & 0xFF


# ── DataCode: encode one byte as 3 UDP packet sizes ───────────────────────────
def _data_code_sizes(value: int, index: int) -> tuple[int, int, int]:
    """
    Returns (size1, size2, size3) for a single data byte.
    value : 0–255, the byte to encode
    index : 0–127, sequence position (used for CRC)
    """
    crc  = _crc8(bytes([value & 0xFF, index & 0xFF]))
    dh   = (value >> 4) & 0xF
    dl   = value & 0xF
    ch   = (crc >> 4) & 0xF
    cl   = crc & 0xF
    return (
        (ch << 4 | dh) + DATA_OFFSET,   # high nibbles
        index + 256 + DATA_OFFSET,       # sequence sync (1<<8 | index + offset)
        (cl << 4 | dl) + DATA_OFFSET,   # low nibbles
    )


# ── Build the full data sequence ──────────────────────────────────────────────
def _build_sequence(ssid: str, bssid: str, password: str, local_ip: str) -> list[tuple[int, int]]:
    """
    Returns list of (value, crc_index) in transmission order.

    Data layout (traced from DatumCode constructor in APK):
      [0] total_len
      [1] pwd_len
      [2] crc8(ssid)
      [3] crc8(bssid)
      [4] total_xor  ← computed over all other fields
      [5] ip[0]  [6] ip[1]  [7] ip[2]  [8] ip[3]
      [9..9+N-1] password bytes
      [9+N..9+N+M-1] ssid bytes
      bssid[0..5] interleaved at list positions 5, 9, 13, 17, 21, 25
    """
    ssid_b  = ssid.encode('utf-8')
    pwd_b   = password.encode('utf-8')
    bssid_b = bytes(int(x, 16) for x in bssid.split(':'))
    ip_b    = socket.inet_aton(local_ip)

    if len(pwd_b) > 64:
        raise ValueError('Password too long (max 64 bytes)')

    crc_ssid  = _crc8(ssid_b)
    crc_bssid = _crc8(bssid_b)
    pwd_len   = len(pwd_b)

    # total_len from APK: ip_len(4) + 5(header fields) + pwd_len + ssid_len
    total_len = 4 + 5 + pwd_len + len(ssid_b)

    # Build (value, index) pairs in natural order
    idx = 0
    seq: list[tuple[int, int]] = []

    def push(v):
        nonlocal idx
        seq.append((v & 0xFF, idx))
        idx += 1

    push(total_len)     # 0
    push(pwd_len)       # 1
    push(crc_ssid)      # 2
    push(crc_bssid)     # 3
    xor_pos = len(seq)
    push(0)             # 4  placeholder for total_xor

    for b in ip_b:      # 5..8
        push(b)
    for b in pwd_b:     # 9..8+N
        push(b)
    for b in ssid_b:    # 9+N..9+N+M-1
        push(b)

    # Compute XOR over everything except the xor slot
    xor = 0
    for i, (v, _) in enumerate(seq):
        if i != xor_pos:
            xor ^= v
    seq[xor_pos] = (xor & 0xFF, 4)

    # Interleave BSSID bytes: insert at positions 5, 9, 13, 17, 21, 25
    # BSSID DataCode indices start at total_len (from APK: v2 + v6)
    insert_pos = 5
    for i, bb in enumerate(bssid_b):
        bssid_idx = total_len + i   # CRC index for this bssid byte
        pos = min(insert_pos, len(seq))
        seq.insert(pos, (bb & 0xFF, bssid_idx))
        insert_pos += 4

    return seq


# ── UDP sender ────────────────────────────────────────────────────────────────
def _send_payload(sock, size: int, addr: tuple):
    """Send a UDP packet whose payload is exactly `size` bytes."""
    sock.sendto(bytes(size), addr)


# ── Network helpers ───────────────────────────────────────────────────────────
def get_local_ip() -> str:
    """Best-effort detection of the local IP on the current network."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('192.168.0.1', 80))
            return s.getsockname()[0]
    except Exception:
        return '0.0.0.0'


def get_bssid() -> str:
    """Try to read the BSSID of the currently connected WiFi AP."""
    # Try iw
    try:
        out = subprocess.check_output(['iw', 'dev'], text=True, stderr=subprocess.DEVNULL)
        m = re.search(r'Connected to ([0-9a-f:]{17})', out, re.IGNORECASE)
        if not m:
            # find 'iw dev <if> link'
            ifaces = re.findall(r'Interface\s+(\S+)', out)
            for iface in ifaces:
                link = subprocess.check_output(['iw', 'dev', iface, 'link'],
                                               text=True, stderr=subprocess.DEVNULL)
                m = re.search(r'Connected to ([0-9a-f:]{17})', link, re.IGNORECASE)
                if m:
                    break
        if m:
            return m.group(1).lower()
    except Exception:
        pass
    # Try nmcli
    try:
        out = subprocess.check_output(['nmcli', '-t', '-f', 'BSSID', 'dev', 'wifi'],
                                      text=True, stderr=subprocess.DEVNULL)
        m = re.search(r'([0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:'
                      r'[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2})', out)
        if m:
            return m.group(1).lower()
    except Exception:
        pass
    return ''


# ── Main provisioner ──────────────────────────────────────────────────────────
class EsptouchProvisioner:
    """
    Broadcasts ESPTouch v1 packets until the device confirms connection
    or the timeout expires.
    """

    def __init__(self, ssid: str, bssid: str, password: str,
                 local_ip: str = '', timeout: float = TIMEOUT_TOTAL,
                 progress_cb=None):
        self.ssid       = ssid
        self.bssid      = bssid.lower()
        self.password   = password
        self.local_ip   = local_ip or get_local_ip()
        self.timeout    = timeout
        self.progress   = progress_cb or (lambda msg: None)
        self._stop      = threading.Event()
        self.result_ip  = None    # set to device IP on success

    def run(self) -> str | None:
        """Blocking. Returns device IP string on success, None on timeout/cancel."""
        seq = _build_sequence(self.ssid, self.bssid, self.password, self.local_ip)
        guide_payloads = [bytes(sz) for sz in GUIDE_SIZES]
        data_payloads  = []
        for val, cidx in seq:
            s1, s2, s3 = _data_code_sizes(val, cidx)
            data_payloads.extend([bytes(s1), bytes(s2), bytes(s3)])

        addr = (BCAST_ADDR, PORT_SEND)

        # Listen for device confirmation in background
        listener = threading.Thread(target=self._listen, daemon=True)
        listener.start()

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            t_start = time.monotonic()
            t_guide_end = t_start + TIMEOUT_GUIDE
            dc_idx = 0
            self.progress('Sending guide code…')

            while not self._stop.is_set():
                elapsed = time.monotonic() - t_start
                if elapsed >= self.timeout:
                    self.progress('Timeout')
                    break

                # Guide code phase
                if time.monotonic() < t_guide_end:
                    for p in guide_payloads:
                        sock.sendto(p, addr)
                        time.sleep(INTERVAL_GC)
                    continue

                # Announce data phase once
                if dc_idx == 0:
                    self.progress(f'Sending data (local IP {self.local_ip})…')

                # Data code: send one DataCode worth (3 packets) per iteration
                for j in range(3):
                    sock.sendto(data_payloads[(dc_idx + j) % len(data_payloads)], addr)
                    time.sleep(INTERVAL_DC)
                dc_idx = (dc_idx + 3) % len(data_payloads)

        finally:
            sock.close()
            self._stop.set()
            listener.join(timeout=2)

        if self.result_ip:
            self.progress(f'Device connected: {self.result_ip}')
        return self.result_ip

    def stop(self):
        self._stop.set()

    def _listen(self):
        """Wait for the device to broadcast its IP on port 18266."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(1.0)
            sock.bind(('', PORT_LISTEN))
            while not self._stop.is_set():
                try:
                    data, addr = sock.recvfrom(256)
                    if len(data) >= 11:
                        # Response: 1 byte (type) + 1 byte (error) + 4 bytes IP + 6 bytes MAC
                        ip_bytes = data[1:5]
                        ip_str   = socket.inet_ntoa(ip_bytes)
                        self.result_ip = ip_str
                        self.progress(f'Device responded from {addr[0]}, assigned IP: {ip_str}')
                        self._stop.set()
                        return
                except socket.timeout:
                    continue
        except Exception as e:
            self.progress(f'Listen error: {e}')
        finally:
            try:
                sock.close()
            except Exception:
                pass


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import sys

    if len(sys.argv) < 4:
        print('Usage: python3 esptouch.py <ssid> <bssid> <password> [local_ip]')
        print('  bssid format: aa:bb:cc:dd:ee:ff')
        print(f'  Auto-detected local IP: {get_local_ip()}')
        print(f'  Auto-detected BSSID:    {get_bssid()}')
        sys.exit(1)

    ssid     = sys.argv[1]
    bssid    = sys.argv[2]
    password = sys.argv[3]
    local_ip = sys.argv[4] if len(sys.argv) > 4 else get_local_ip()

    print(f'ESPTouch v1  SSID={ssid!r}  BSSID={bssid}  IP={local_ip}')
    print('(Make sure lamp is in LAN config-waiting state — blue flash on R button)')

    prov = EsptouchProvisioner(ssid, bssid, password, local_ip,
                               progress_cb=lambda m: print(f'  {m}'))
    result = prov.run()
    if result:
        print(f'\nSuccess! Device IP: {result}')
        print(f'Update the controller host to {result}')
    else:
        print('\nFailed — no response within timeout')
        sys.exit(1)
