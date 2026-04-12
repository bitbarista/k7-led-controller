"""
Noo-Psyche K7 LED controller — MicroPython client (ESP32-S3)
Stripped-down port of the PC k7mini.py: K7 class + decode_state only.
No CLI, no YAML, no type hints.
"""

import socket
import time

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

TIME_NUM = 24
NUM_CH   = 6

DEVICES = {
    'k7mini': {'label': 'K7 Mini', 'channels': ['white', 'royal_blue', 'blue']},
    'k7pro':  {'label': 'K7 Pro',  'channels': ['uv', 'royal_blue', 'blue', 'white', 'warm_white', 'red']},
}


def _pkt(cmd, data=b''):
    return START + cmd + data + END


# ── Response decoder ──────────────────────────────────────────────────────────

def decode_state(data):
    """
    Decode a READ_ALL response (222 bytes) into:
      {'name': str, 'mode': 'auto'|'manual',
       'manual': [int*6], 'schedule': [(h, m, c0..c5)*24]}
    Returns None on bad data.
    """
    if len(data) < 10 or data[:2] != RESP or data[-1] != 0xBB:
        return None
    pos      = 4
    manual   = list(data[pos:pos+6]);  pos += 6
    time_num = data[pos];              pos += 1
    schedule = []
    for _ in range(time_num):
        schedule.append(tuple(data[pos:pos+8])); pos += 8
    mode = 'auto' if data[pos] else 'manual';  pos += 1
    name = data[pos:pos+11].rstrip(b'\x00').decode('ascii', errors='replace')
    return {'name': name, 'mode': mode, 'manual': manual, 'schedule': schedule}


# ── K7 class ──────────────────────────────────────────────────────────────────

class K7:
    def __init__(self, host='192.168.4.1', port=8266, timeout=4.0, verbose=False):
        self.host    = host
        self.port    = port
        self.timeout = timeout
        self.verbose = verbose
        self._sock   = None

    def connect(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout)
        self._sock.connect((self.host, self.port))
        # Drain any greeting
        self._sock.settimeout(0.5)
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

    def _recv(self, drain=False):
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
        except OSError:
            pass   # timeout or closed — normal end of data
        finally:
            self._sock.settimeout(saved)
        return buf

    def _send(self, pkt, drain=False):
        self._sock.sendall(pkt)
        return self._recv(drain=drain)

    def read_all(self):
        """Read all settings. Returns raw bytes; pass to decode_state()."""
        self._sock.sendall(_pkt(CMD_ALL_READ))
        self._recv()               # discard model-ID echo
        self._sock.settimeout(5.0)
        data = self._recv(drain=True)
        self._sock.settimeout(self.timeout)
        return data

    def preview_brightness(self, channels):
        """Preview brightness without saving. channels: 6 ints 0-100."""
        self._send(_pkt(CMD_PREVIEW_LUMINANCE, bytes(channels)))

    def set_mode_auto(self):
        self._send(_pkt(CMD_CHANGE_MODE, b'\x01'))

    def set_mode_manual(self):
        self._send(_pkt(CMD_CHANGE_MODE, b'\x00'))

    def sync_time(self, h=None, m=None, s=None):
        t = time.localtime()
        data = bytes([
            h if h is not None else t[3],
            m if m is not None else t[4],
            s if s is not None else t[5],
        ])
        self._send(_pkt(CMD_SYNC_TIME, data))

    def push_schedule(self, manual, schedule, mode='auto'):
        """
        Push full schedule + manual brightness + mode to the device.
        manual:   6-element list (0-100 per channel)
        schedule: 24 tuples of (hour, minute, c0, c1, c2, c3, c4, c5)
        mode:     'auto' or 'manual'
        """
        t = time.localtime()
        time_bytes   = bytes([t[3], t[4], t[5]])
        manual_bytes = bytes(manual)
        sched_bytes  = b''.join(bytes(e) for e in schedule)
        mode_byte    = b'\x01' if mode == 'auto' else b'\x00'
        data = manual_bytes + bytes([TIME_NUM]) + sched_bytes + mode_byte + time_bytes
        self._send(_pkt(CMD_ALL_SET, data))
