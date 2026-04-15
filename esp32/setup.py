"""
K7 LED Controller — first-run setup portal.

Imported only when no config.json exists, so this code never occupies
RAM during normal operation.
"""

import network
import socket
import uselect
import time
from machine import reset

AP_IP         = '192.168.5.1'
LAMP_PASSWORD = '12345678'

_CSS = """
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

_SAVED_HTML = """\
<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>body{font-family:system-ui;max-width:420px;margin:40px auto;padding:0 20px;
  background:#0d1117;color:#c9d1d9}h1{color:#3fb950}</style></head>
<body><h1>Saved!</h1>
<p>Rebooting &mdash; connect to <b>K7-Controller</b> WiFi
(password: <b>12345678</b>) then browse to <b>http://192.168.5.1</b></p>
</body></html>"""


def _scan_k7_lamps():
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
                found.append((ssid, 'k7mini', entry[3]))
            elif ssid.startswith('K7_Pro'):
                found.append((ssid, 'k7pro', entry[3]))
    except Exception as e:
        print('Scan error:', e)
    found.sort(key=lambda x: -x[2])
    return [(s, d) for s, d, _ in found]


def _build_html(lamps):
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
        f'<style>{_CSS}</style></head><body>{body}</body></html>'
    )


def _parse_form(raw):
    body = raw.split('\r\n\r\n', 1)[-1] if '\r\n\r\n' in raw else ''
    params = {}
    for kv in body.split('&'):
        if '=' in kv:
            k, v = kv.split('=', 1)
            params[k.strip()] = v.strip().replace('+', ' ')
    return params


def _dns_response(data, ip):
    """Build a minimal DNS A-record response — resolves any name to ip."""
    resp  = data[:2]
    resp += b'\x81\x80'
    resp += data[4:6]
    resp += data[4:6]
    resp += b'\x00\x00\x00\x00'
    resp += data[12:]
    resp += b'\xc0\x0c'
    resp += b'\x00\x01'
    resp += b'\x00\x01'
    resp += b'\x00\x00\x00\x3c'
    resp += b'\x00\x04'
    resp += bytes(int(x) for x in ip.split('.'))
    return resp


def _respond(conn, status, body, content_type='text/html'):
    body_bytes = body.encode('utf-8')
    header = (
        f'HTTP/1.1 {status}\r\n'
        f'Content-Type: {content_type}; charset=utf-8\r\n'
        f'Content-Length: {len(body_bytes)}\r\n'
        'Connection: close\r\n\r\n'
    ).encode()
    conn.sendall(header + body_bytes)


def save_config(cfg):
    import json
    with open('config.json', 'w') as f:
        json.dump(cfg, f)


_CAPTIVE_PATHS = frozenset((
    '/hotspot-detect.html', '/library/test/success.html',
    '/generate_204', '/gen_204',
    '/connecttest.txt', '/ncsi.txt',
    '/redirect', '/canonical.html',
))


def run_portal():
    """Block until first-run config is saved, then reboot."""
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid='K7-Setup', authmode=0)
    ap.ifconfig((AP_IP, '255.255.255.0', AP_IP, AP_IP))
    print('Scanning for K7 lamps...')
    lamps = _scan_k7_lamps()
    print(f'Found: {lamps}')
    print('Setup portal — connect to K7-Setup and browse to', AP_IP)

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', 80))
    srv.listen(3)

    dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dns.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    dns.bind(('0.0.0.0', 53))

    while True:
        readable, _, _ = uselect.select([srv, dns], [], [], 1.0)
        for sock in readable:
            if sock is dns:
                try:
                    data, addr = dns.recvfrom(512)
                    if data:
                        dns.sendto(_dns_response(data, AP_IP), addr)
                except Exception as e:
                    print('DNS error:', e)
                continue

            conn, _ = srv.accept()
            try:
                raw = conn.recv(2048).decode('utf-8', 'ignore')
                first_line = raw.split('\r\n')[0]

                if first_line.startswith('POST /scan'):
                    lamps = _scan_k7_lamps()
                    print(f'Rescan: {lamps}')
                    _respond(conn, '200 OK', _build_html(lamps))

                elif first_line.startswith('POST /save'):
                    params    = _parse_form(raw)
                    lamp_ssid = params.get('lamp_ssid', '').strip()
                    device    = params.get('device', '').strip()

                    if not lamp_ssid and 'lamp_sel' in params:
                        sel = params['lamp_sel']
                        if '|' in sel:
                            lamp_ssid, device = sel.split('|', 1)

                    if not device:
                        device = 'k7pro' if lamp_ssid.startswith('K7_Pro') else 'k7mini'

                    if lamp_ssid:
                        save_config({'lamp_ssid': lamp_ssid, 'device': device})
                        _respond(conn, '200 OK', _SAVED_HTML)
                        conn.close()
                        srv.close()
                        dns.close()
                        time.sleep(3)
                        reset()
                        return
                    _respond(conn, '400 Bad Request', '<p>No lamp selected.</p>')

                else:
                    parts = first_line.split()
                    path  = parts[1] if len(parts) > 1 else '/'
                    if path in _CAPTIVE_PATHS:
                        hdr = (
                            f'HTTP/1.1 302 Found\r\n'
                            f'Location: http://{AP_IP}/\r\n'
                            'Content-Length: 0\r\n'
                            'Connection: close\r\n\r\n'
                        ).encode()
                        conn.sendall(hdr)
                    else:
                        _respond(conn, '200 OK', _build_html(lamps))

            except Exception as e:
                print('Setup portal error:', e)
            finally:
                conn.close()
