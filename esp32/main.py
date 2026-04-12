"""
K7 LED Controller — ESP32-S3 boot / WiFi setup
Runs on MicroPython (XIAO ESP32-S3 or similar).

Network architecture:
  STA → lamp AP  (192.168.4.1, always 12345678) — permanent connection
  AP  → K7-Controller (192.168.5.1) — users browse here

First boot (no config): starts open AP "K7-Setup" and serves a one-page
portal so the user can enter the last 4 digits of the lamp SSID.
Config is saved to /config.json and the device reboots into normal mode.
"""

import network
import socket
import time
import json
import os
import uasyncio as asyncio
from machine import RTC, reset

CONFIG_FILE = 'config.json'

LAMP_SSID_PREFIXES = {
    'k7mini': 'K7mini',
    'k7pro':  'K7_Pro',
}
LAMP_PASSWORD  = '12345678'
AP_SSID        = 'K7-Controller'
AP_PASSWORD    = '12345678'
AP_IP          = '192.168.5.1'


# ── Config helpers ────────────────────────────────────────────────────────────

def _file_exists(path):
    try: os.stat(path); return True
    except OSError: return False

def load_config():
    if _file_exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}

def save_config(cfg):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(cfg, f)


# ── WiFi helpers ──────────────────────────────────────────────────────────────

def connect_sta(ssid, password=LAMP_PASSWORD, timeout=20):
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    if sta.isconnected():
        sta.disconnect()
        time.sleep(0.5)
    sta.connect(ssid, password)
    t = 0
    while not sta.isconnected() and t < timeout:
        time.sleep(0.5)
        t += 0.5
        print('.', end='')
    print()
    return sta.isconnected()

def start_ap(ssid=AP_SSID, password=AP_PASSWORD):
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid=ssid, password=password, authmode=3)  # WPA2
    # Use a different subnet to avoid clash with the lamp's 192.168.4.x
    ap.ifconfig((AP_IP, '255.255.255.0', AP_IP, '8.8.8.8'))
    t = 0
    while not ap.active() and t < 5:
        time.sleep(0.2); t += 0.2
    return ap


# ── First-run setup portal ────────────────────────────────────────────────────
# Minimal raw HTTP server — no Microdot, no dependencies.

SETUP_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>K7 Controller Setup</title>
<style>
  body{font-family:system-ui,sans-serif;max-width:420px;margin:40px auto;padding:0 20px;background:#0d1117;color:#c9d1d9}
  h1{font-size:1.4rem;margin-bottom:8px}
  p{color:#8b949e;font-size:.9rem}
  label{display:block;margin:20px 0 6px;font-size:.9rem;font-weight:600}
  input,select{width:100%;padding:8px 10px;background:#161b22;border:1px solid rgba(255,255,255,.12);
    color:#c9d1d9;border-radius:6px;font-size:1rem;box-sizing:border-box}
  button{margin-top:16px;width:100%;padding:10px;background:#238636;border:1px solid #2ea043;
    color:#fff;border-radius:6px;font-size:1rem;cursor:pointer}
  .hint{font-size:.78rem;color:#8b949e;margin-top:4px}
</style></head>
<body>
<h1>🪸 K7 Controller Setup</h1>
<p>Connect your lamp and enter the last 4 digits of its WiFi name.</p>
<form method="POST" action="/save">
  <label>Lamp WiFi suffix</label>
  <input name="ssid4" maxlength="4" pattern="[0-9A-Za-z]{4}" placeholder="e.g. 1A2B" required>
  <p class="hint">The last 4 characters of your lamp's SSID — e.g. K7mini<b>1A2B</b></p>
  <label>Device type</label>
  <select name="device">
    <option value="k7mini">K7 Mini</option>
    <option value="k7pro">K7 Pro</option>
  </select>
  <button type="submit">Save &amp; Reboot</button>
</form>
</body></html>"""

SAVED_HTML = """\
<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>body{font-family:system-ui;max-width:420px;margin:40px auto;padding:0 20px;
  background:#0d1117;color:#c9d1d9}h1{color:#3fb950}</style></head>
<body><h1>Saved!</h1><p>Rebooting — connect to <b>K7-Controller</b> WiFi
(password: <b>12345678</b>) and browse to <b>192.168.5.1</b>.</p></body></html>"""


def _http_respond(conn, status, body, content_type='text/html'):
    response = (
        f'HTTP/1.1 {status}\r\n'
        f'Content-Type: {content_type}; charset=utf-8\r\n'
        f'Content-Length: {len(body)}\r\n'
        'Connection: close\r\n\r\n'
    )
    conn.sendall(response.encode() + body.encode())


def run_setup_portal():
    """Block until first-run config is saved, then reboot."""
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid='K7-Setup', authmode=0)   # open network — easy first-connect
    ap.ifconfig((AP_IP, '255.255.255.0', AP_IP, '8.8.8.8'))
    print('Setup portal started — connect to K7-Setup and browse to', AP_IP)

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', 80))
    srv.listen(3)

    while True:
        conn, _ = srv.accept()
        try:
            raw = conn.recv(2048).decode('utf-8', 'ignore')
            first_line = raw.split('\r\n')[0]

            if first_line.startswith('POST /save'):
                # Parse URL-encoded body
                body = raw.split('\r\n\r\n', 1)[-1] if '\r\n\r\n' in raw else ''
                params = {}
                for kv in body.split('&'):
                    if '=' in kv:
                        k, v = kv.split('=', 1)
                        params[k.strip()] = v.strip()
                ssid4  = params.get('ssid4', '').strip()[:4]
                device = params.get('device', 'k7mini').strip()
                if ssid4:
                    save_config({'ssid4': ssid4, 'device': device})
                    _http_respond(conn, '200 OK', SAVED_HTML)
                    conn.close()
                    srv.close()
                    time.sleep(3)
                    reset()
                    return
                _http_respond(conn, '400 Bad Request', '<p>Invalid input.</p>')
            else:
                _http_respond(conn, '200 OK', SETUP_HTML)
        except Exception as e:
            print('Setup portal error:', e)
        finally:
            conn.close()


# ── Normal boot ───────────────────────────────────────────────────────────────

def boot():
    cfg = load_config()

    if not cfg.get('ssid4'):
        print('No config — starting setup portal')
        run_setup_portal()
        return

    ssid4  = cfg['ssid4']
    device = cfg.get('device', 'k7mini')
    prefix = LAMP_SSID_PREFIXES.get(device, 'K7mini')
    lamp_ssid = f'{prefix}{ssid4}'

    print(f'Connecting STA → {lamp_ssid} ...', end='')
    if not connect_sta(lamp_ssid):
        print('Failed to connect to lamp AP — falling back to setup portal')
        run_setup_portal()
        return

    ap = start_ap()
    print(f'AP ready: {AP_SSID}  @  {ap.ifconfig()[0]}')
    print('Browse to http://192.168.5.1')

    # Start Microdot server (async)
    import server as srv
    srv.cfg['device'] = device
    asyncio.run(srv.main())


if __name__ == '__main__':
    boot()
