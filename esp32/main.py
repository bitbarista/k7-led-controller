"""
K7 LED Controller — ESP32 boot / WiFi setup
Runs on MicroPython (ESP32-C3 Super Mini, XIAO ESP32-S3, etc.).

Network architecture:
  STA → lamp AP  (192.168.4.1, always 12345678) — permanent connection
  AP  → K7-Controller (192.168.5.1) — users browse here

First boot (no config): scans for K7 lamp APs and presents what it finds.
If the lamp is on it will appear in the scan; the user just confirms.
Config is saved to config.json and the device reboots into normal mode.
"""

import network
import socket
import time
import json
import os
import asyncio
from machine import reset

CONFIG_FILE   = 'config.json'
LAMP_PASSWORD = '12345678'
AP_SSID       = 'K7-Controller'
AP_PASSWORD   = '12345678'
AP_IP         = '192.168.5.1'

LAMP_PREFIXES = ('K7mini', 'K7_Pro')


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

def scan_k7_lamps():
    """Scan for K7 lamp APs. Returns list of (ssid, device_type) sorted by signal."""
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    found = []
    try:
        for entry in sta.scan():
            try:
                ssid = entry[0].decode('utf-8')
            except Exception:
                continue
            if ssid.startswith('K7mini'):
                found.append((ssid, 'k7mini', entry[3]))   # ssid, type, rssi
            elif ssid.startswith('K7_Pro'):
                found.append((ssid, 'k7pro', entry[3]))
    except Exception as e:
        print('Scan error:', e)
    found.sort(key=lambda x: -x[2])   # strongest signal first
    return [(s, d) for s, d, _ in found]

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
    ap.config(essid=ssid, password=password, authmode=3)
    ap.ifconfig((AP_IP, '255.255.255.0', AP_IP, '8.8.8.8'))
    t = 0
    while not ap.active() and t < 5:
        time.sleep(0.2); t += 0.2
    return ap


# ── First-run setup portal ────────────────────────────────────────────────────

CSS = """
  body{font-family:system-ui,sans-serif;max-width:420px;margin:40px auto;
       padding:0 20px;background:#0d1117;color:#c9d1d9}
  h1{font-size:1.4rem;margin-bottom:4px}
  p{color:#8b949e;font-size:.9rem;margin-top:4px}
  label{display:block;margin:18px 0 6px;font-size:.9rem;font-weight:600}
  select,input{width:100%;padding:8px 10px;background:#161b22;
    border:1px solid rgba(255,255,255,.12);color:#c9d1d9;
    border-radius:6px;font-size:1rem;box-sizing:border-box}
  .btn{margin-top:16px;width:100%;padding:10px;background:#238636;
    border:1px solid #2ea043;color:#fff;border-radius:6px;
    font-size:1rem;cursor:pointer}
  .btn-sec{background:#1f2937;border-color:rgba(255,255,255,.12);margin-top:8px}
  .none{color:#f85149;font-size:.9rem;margin-top:12px}
"""

SAVED_HTML = """\
<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>body{font-family:system-ui;max-width:420px;margin:40px auto;padding:0 20px;
  background:#0d1117;color:#c9d1d9}h1{color:#3fb950}</style></head>
<body><h1>Saved!</h1>
<p>Rebooting &mdash; connect to <b>K7-Controller</b> WiFi
(password: <b>12345678</b>) then browse to <b>http://192.168.5.1</b></p>
</body></html>"""


def _build_setup_html(lamps):
    """Build the setup page HTML based on scan results."""
    if lamps:
        if len(lamps) == 1:
            ssid, device = lamps[0]
            lamp_input = (
                f'<p>Found: <b>{ssid}</b></p>'
                f'<input type="hidden" name="lamp_ssid" value="{ssid}">'
                f'<input type="hidden" name="device"    value="{device}">'
            )
        else:
            options = '\n'.join(
                f'<option value="{s}|{d}">{s}</option>' for s, d in lamps
            )
            lamp_input = (
                '<label>Select lamp</label>'
                f'<select name="lamp_sel">{options}</select>'
            )
        body = f"""
<h1>K7 Controller Setup</h1>
<p>Lamp{" " if len(lamps)==1 else "s "}found nearby &mdash; make sure it is powered on.</p>
<form method="POST" action="/save">
  {lamp_input}
  <button class="btn" type="submit">Connect &amp; Save</button>
</form>
<form method="POST" action="/scan">
  <button class="btn btn-sec" type="submit">Scan again</button>
</form>"""
    else:
        body = """
<h1>K7 Controller Setup</h1>
<p class="none">No K7 lamp found. Make sure the lamp is powered on, then scan again.</p>
<form method="POST" action="/scan">
  <button class="btn" type="submit">Scan again</button>
</form>
<details style="margin-top:24px">
  <summary style="font-size:.85rem;color:#8b949e;cursor:pointer">Enter manually</summary>
  <form method="POST" action="/save" style="margin-top:12px">
    <label>Lamp SSID (full name)</label>
    <input name="lamp_ssid" placeholder="e.g. K7mini52609" required>
    <button class="btn" type="submit">Save &amp; Reboot</button>
  </form>
</details>"""

    return (
        '<!DOCTYPE html><html lang="en"><head>'
        '<meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>K7 Setup</title>'
        f'<style>{CSS}</style></head><body>{body}</body></html>'
    )


def _parse_form(raw):
    body = raw.split('\r\n\r\n', 1)[-1] if '\r\n\r\n' in raw else ''
    params = {}
    for kv in body.split('&'):
        if '=' in kv:
            k, v = kv.split('=', 1)
            params[k.strip()] = v.strip().replace('+', ' ')
    return params


def _http_respond(conn, status, body, content_type='text/html'):
    body_bytes = body.encode('utf-8')
    header = (
        f'HTTP/1.1 {status}\r\n'
        f'Content-Type: {content_type}; charset=utf-8\r\n'
        f'Content-Length: {len(body_bytes)}\r\n'
        'Connection: close\r\n\r\n'
    ).encode()
    conn.sendall(header + body_bytes)


def run_setup_portal():
    """Block until first-run config is saved, then reboot."""
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid='K7-Setup', authmode=0)
    ap.ifconfig((AP_IP, '255.255.255.0', AP_IP, '8.8.8.8'))
    print('Scanning for K7 lamps...')
    lamps = scan_k7_lamps()
    print(f'Found: {lamps}')
    print('Setup portal — connect to K7-Setup and browse to', AP_IP)

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', 80))
    srv.listen(3)

    while True:
        conn, _ = srv.accept()
        try:
            raw = conn.recv(2048).decode('utf-8', 'ignore')
            first_line = raw.split('\r\n')[0]

            if first_line.startswith('POST /scan'):
                # Re-scan and serve updated page
                lamps = scan_k7_lamps()
                print(f'Rescan: {lamps}')
                _http_respond(conn, '200 OK', _build_setup_html(lamps))

            elif first_line.startswith('POST /save'):
                params    = _parse_form(raw)
                lamp_ssid = params.get('lamp_ssid', '').strip()
                device    = params.get('device', '').strip()

                # If user chose from a dropdown the value is "ssid|device"
                if not lamp_ssid and 'lamp_sel' in params:
                    sel = params['lamp_sel']
                    if '|' in sel:
                        lamp_ssid, device = sel.split('|', 1)

                # Derive device from SSID prefix if not already set
                if not device:
                    device = 'k7pro' if lamp_ssid.startswith('K7_Pro') else 'k7mini'

                if lamp_ssid:
                    save_config({'lamp_ssid': lamp_ssid, 'device': device})
                    _http_respond(conn, '200 OK', SAVED_HTML)
                    conn.close()
                    srv.close()
                    time.sleep(3)
                    reset()
                    return
                _http_respond(conn, '400 Bad Request', '<p>No lamp selected.</p>')

            else:
                _http_respond(conn, '200 OK', _build_setup_html(lamps))

        except Exception as e:
            print('Setup portal error:', e)
        finally:
            conn.close()


# ── Normal boot ───────────────────────────────────────────────────────────────

def boot():
    cfg = load_config()

    # Support old config format (suffix + device) and new (lamp_ssid + device)
    if not cfg.get('lamp_ssid') and cfg.get('suffix'):
        prefix = 'K7_Pro' if cfg.get('device') == 'k7pro' else 'K7mini'
        cfg['lamp_ssid'] = prefix + cfg['suffix']

    if not cfg.get('lamp_ssid'):
        print('No config — starting setup portal')
        run_setup_portal()
        return

    lamp_ssid = cfg['lamp_ssid']
    device    = cfg.get('device', 'k7mini')

    print(f'Connecting STA → {lamp_ssid} ...', end='')
    if not connect_sta(lamp_ssid):
        print('Failed to connect to lamp AP — falling back to setup portal')
        run_setup_portal()
        return

    ap = start_ap()
    print(f'AP ready: {AP_SSID}  @  {ap.ifconfig()[0]}')
    print('Browse to http://192.168.5.1')

    import server as srv
    srv.cfg['device'] = device
    asyncio.run(srv.main())


if __name__ == '__main__':
    boot()
