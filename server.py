#!/usr/bin/env python3
"""K7 LED Controller — web server"""

from flask import Flask, render_template, jsonify, request
import threading
import random
import json
import sys
import os
import time

sys.path.insert(0, os.path.dirname(__file__))
import k7mini as k7
import presets
import esptouch as et

app  = Flask(__name__)
lock = threading.Lock()   # one device request at a time

cfg = {'host': '192.168.4.1', 'port': 8266, 'device': 'k7mini'}

# Last schedule pushed to the lamp — used by the lightning thread for restore values
_last_schedule = [[h, 0, 0, 0, 0, 0, 0, 0] for h in range(24)]

PROFILES_FILE = os.path.join(os.path.dirname(__file__), 'profiles.json')

def _load_profiles():
    if os.path.exists(PROFILES_FILE):
        with open(PROFILES_FILE) as f:
            return json.load(f)
    return {}

def _save_profiles(data):
    with open(PROFILES_FILE, 'w') as f:
        json.dump(data, f, indent=2)


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
    global _last_schedule
    d = request.json or {}
    with lock:
        try:
            manual   = d['manual']
            schedule = [tuple(e) for e in d['schedule']]
            mode     = d.get('mode', 'auto')
            with _lamp() as lamp:
                lamp.push_schedule(manual, schedule, mode)
            _last_schedule = [list(e) for e in schedule]
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


@app.route('/api/profiles', methods=['GET'])
def api_profiles_get():
    return jsonify(_load_profiles())


@app.route('/api/profiles', methods=['POST'])
def api_profiles_post():
    d = request.json or {}
    name = d.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Name required'}), 400
    profiles = _load_profiles()
    profiles[name] = d
    _save_profiles(profiles)
    return jsonify({'ok': True})


@app.route('/api/profiles/<name>', methods=['DELETE'])
def api_profiles_delete(name):
    profiles = _load_profiles()
    profiles.pop(name, None)
    _save_profiles(profiles)
    return jsonify({'ok': True})


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


def _lightning_flash_channels():
    """White-dominant flash values for the configured device."""
    if cfg['device'] == 'k7mini':
        return [100, 60, 60, 0, 0, 0]   # white, royal_blue, blue
    else:                                 # k7pro: uv, rb, blue, white, ww, red
        return [40, 60, 60, 100, 100, 0]


_lightning_lock   = threading.Lock()
_lightning_active = False
_lightning_thread = None


def _sleep_interruptible(seconds):
    """Sleep in 0.25 s increments; returns False if lightning was stopped."""
    elapsed = 0.0
    while elapsed < seconds:
        time.sleep(0.25)
        elapsed += 0.25
        if not _lightning_active:
            return False
    return True


def _flash_pulse():
    """Send one brief flash. Does not change mode — caller must restore afterwards."""
    flash = _lightning_flash_channels()
    dur   = 0.03 + random.random() * 0.05   # 30–80 ms
    try:
        with lock:
            with _lamp() as lamp:
                lamp.preview_brightness(flash)
        time.sleep(dur)
    except Exception:
        pass


def _do_event():
    """
    Fire a complete lightning event then return lamp to auto schedule.

    Single strike (80%): 1–3 rapid pulses, 20–50 ms apart.
    Storm burst  (20%): 3–6 strikes, each 1–3 pulses, 100–500 ms between strikes.
    set_mode_auto is called once after the whole event.
    """
    is_burst    = random.random() < 0.2
    num_strikes = random.randint(3, 6) if is_burst else 1

    for s in range(num_strikes):
        if not _lightning_active:
            break
        pulses = random.choices([1, 2, 3], weights=[65, 25, 10])[0]
        for p in range(pulses):
            if not _lightning_active:
                break
            _flash_pulse()
            if p < pulses - 1:
                time.sleep(0.02 + random.random() * 0.03)   # 20–50 ms between pulses
        if s < num_strikes - 1:
            time.sleep(0.1 + random.random() * 0.4)         # 100–500 ms between strikes

    try:
        with lock:
            with _lamp() as lamp:
                lamp.set_mode_auto()
                lamp.sync_time()   # force immediate schedule re-evaluation
    except Exception:
        pass


def _lightning_worker():
    global _lightning_active
    while _lightning_active:
        if not _sleep_interruptible(15 + random.random() * 75):
            return
        _do_event()


@app.route('/api/lightning/start', methods=['POST'])
def api_lightning_start():
    global _lightning_active, _lightning_thread
    with _lightning_lock:
        if _lightning_active and _lightning_thread and _lightning_thread.is_alive():
            return jsonify({'ok': True})
        _lightning_active = True
        _lightning_thread = threading.Thread(target=_lightning_worker, daemon=True)
        _lightning_thread.start()
    return jsonify({'ok': True})


@app.route('/api/lightning/stop', methods=['POST'])
def api_lightning_stop():
    global _lightning_active
    _lightning_active = False
    return jsonify({'ok': True})


@app.route('/api/lightning/status')
def api_lightning_status():
    active = bool(_lightning_active and _lightning_thread and _lightning_thread.is_alive())
    return jsonify({'active': active})


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
