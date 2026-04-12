#!/usr/bin/env python3
"""K7 LED Controller — web server"""

from flask import Flask, render_template, jsonify, request
import threading
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
import k7mini as k7
import presets
import esptouch as et

app  = Flask(__name__)
lock = threading.Lock()   # one device request at a time

cfg = {'host': '192.168.4.1', 'port': 8266, 'device': 'k7mini'}


def _lamp():
    return k7.K7(cfg['host'], cfg['port'], verbose=False)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/devices')
def api_devices():
    return jsonify(k7.DEVICES)


@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    if request.method == 'POST':
        d = request.json or {}
        if 'host'   in d: cfg['host']   = d['host']
        if 'port'   in d: cfg['port']   = int(d['port'])
        if 'device' in d: cfg['device'] = d['device']
    return jsonify(cfg)


@app.route('/api/state')
def api_state():
    with lock:
        try:
            with _lamp() as lamp:
                raw = lamp.read_all()
            state = k7.decode_state(raw)
            if not state:
                return jsonify({'error': 'Could not decode device response'}), 500
            state['schedule'] = [list(e) for e in state['schedule']]
            return jsonify(state)
        except OSError as e:
            return jsonify({'error': f'Connection failed — {e}'}), 503
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@app.route('/api/push', methods=['POST'])
def api_push():
    d = request.json or {}
    with lock:
        try:
            manual   = d['manual']
            schedule = [tuple(e) for e in d['schedule']]
            mode     = d.get('mode', 'auto')
            with _lamp() as lamp:
                lamp.push_schedule(manual, schedule, mode)
            return jsonify({'ok': True})
        except OSError as e:
            return jsonify({'error': f'Connection failed — {e}'}), 503
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@app.route('/api/presets')
def api_presets():
    device = cfg['device']
    ps = presets.ALL.get(device, {})
    # Convert schedule lists (which _build returns) to plain lists for JSON
    out = {}
    for key, p in ps.items():
        out[key] = {
            'name':     p['name'],
            'desc':     p['desc'],
            'manual':   p['manual'],
            'schedule': [list(row) for row in p['schedule']],
        }
    return jsonify(out)


@app.route('/api/preview', methods=['POST'])
def api_preview():
    d = request.json or {}
    channels = d.get('channels', [0] * 6)
    with lock:
        try:
            with _lamp() as lamp:
                lamp.preview_brightness(channels)
            return jsonify({'ok': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


_prov_lock   = threading.Lock()
_prov_status = {'state': 'idle', 'msg': ''}
_prov_thread = None


@app.route('/api/provision/detect')
def api_prov_detect():
    return jsonify({
        'local_ip': et.get_local_ip(),
        'bssid':    et.get_bssid(),
    })


@app.route('/api/provision/start', methods=['POST'])
def api_prov_start():
    global _prov_thread
    d = request.json or {}
    ssid     = d.get('ssid', '')
    bssid    = d.get('bssid', '')
    password = d.get('password', '')
    local_ip = d.get('local_ip', '') or et.get_local_ip()

    if not ssid or not bssid or ':' not in bssid:
        return jsonify({'error': 'ssid, bssid (aa:bb:cc:dd:ee:ff) and password required'}), 400

    with _prov_lock:
        if _prov_thread and _prov_thread.is_alive():
            return jsonify({'error': 'Provisioning already in progress'}), 409

    def _run():
        _prov_status['state'] = 'running'
        _prov_status['msg']   = 'Starting…'
        def cb(msg):
            _prov_status['msg'] = msg

        prov = et.EsptouchProvisioner(ssid, bssid, password, local_ip, progress_cb=cb)
        ip = prov.run()
        if ip:
            _prov_status['state'] = 'done'
            _prov_status['ip']    = ip
            cfg['host'] = ip          # auto-update controller host
        else:
            _prov_status['state'] = 'failed'
        _prov_status['msg'] = f'Device IP: {ip}' if ip else 'Timeout — no response'

    with _prov_lock:
        _prov_thread = threading.Thread(target=_run, daemon=True)
        _prov_thread.start()

    return jsonify({'ok': True})


@app.route('/api/provision/status')
def api_prov_status():
    return jsonify(_prov_status)


@app.route('/api/provision/stop', methods=['POST'])
def api_prov_stop():
    # Can't easily stop the thread; just return current state
    _prov_status['state'] = 'idle'
    _prov_status['msg']   = 'Cancelled'
    return jsonify({'ok': True})


if __name__ == '__main__':
    import webbrowser, threading
    url = 'http://localhost:5000'
    print(f'K7 LED Controller  →  {url}')
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host='0.0.0.0', port=5000, debug=False)
