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
import moon

app  = Flask(__name__)
lock = threading.Lock()   # one device request at a time

cfg = {'host': '192.168.4.1', 'port': 8266, 'device': 'k7mini'}

# Last schedule/manual pushed to the lamp — used by lightning for restore
_last_schedule = [[h, 0, 0, 0, 0, 0, 0, 0] for h in range(24)]
_last_manual   = [0] * 6


def _interpolate_channels(schedule, h, m):
    """Linearly interpolate channel values between hour slots h and h+1 at minute m."""
    lo   = schedule[h % 24]
    hi   = schedule[(h + 1) % 24]
    frac = m / 60.0
    return [max(0, min(100, round(lo[2+i] + frac * (hi[2+i] - lo[2+i])))) for i in range(len(lo) - 2)]

PROFILES_FILE           = os.path.join(os.path.dirname(__file__), 'profiles.json')
LIGHTNING_SCHEDULE_FILE = os.path.join(os.path.dirname(__file__), 'lightning_schedule.json')
LUNAR_FILE              = os.path.join(os.path.dirname(__file__), 'lunar_schedule.json')

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


@app.route('/api/time', methods=['POST'])
def api_time():
    """No-op on PC — clock is always correct. Present so the browser call doesn't 404."""
    return jsonify({'ok': True})


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
    global _last_schedule, _last_manual
    d = request.json or {}
    with lock:
        try:
            manual   = d['manual']
            schedule = [tuple(e) for e in d['schedule']]
            mode     = d.get('mode', 'auto')
            with _lamp() as lamp:
                lamp.push_schedule(manual, schedule, mode)
            _last_schedule = [list(e) for e in schedule]
            _last_manual   = list(manual)
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
_manually_enabled = False   # tracks the user's intent, independent of schedule
_user_stopped     = False   # set when user presses Stop; prevents scheduler restarting

# Lightning schedule ── persisted to LIGHTNING_SCHEDULE_FILE
_ls = {'enabled': False, 'start': '20:00', 'end': '23:00'}

def _load_lightning_schedule():
    if os.path.exists(LIGHTNING_SCHEDULE_FILE):
        try:
            with open(LIGHTNING_SCHEDULE_FILE) as f:
                _ls.update(json.load(f))
        except Exception:
            pass

def _save_lightning_schedule():
    with open(LIGHTNING_SCHEDULE_FILE, 'w') as f:
        json.dump(_ls, f)

def _parse_hhmm(s):
    """Return total minutes from midnight for 'HH:MM', or None on error."""
    try:
        h, m = s.split(':')
        return int(h) * 60 + int(m)
    except Exception:
        return None

def _in_lightning_window():
    """True if current local time falls inside the configured schedule window."""
    if not _ls.get('enabled'):
        return False
    s_m = _parse_hhmm(_ls.get('start', ''))
    e_m = _parse_hhmm(_ls.get('end', ''))
    if s_m is None or e_m is None:
        return False
    t   = time.localtime()
    now = t.tm_hour * 60 + t.tm_min
    if s_m <= e_m:
        return s_m <= now < e_m
    else:                          # overnight window, e.g. 22:00 – 02:00
        return now >= s_m or now < e_m


def _sleep_interruptible(seconds):
    """Sleep in 0.25 s increments; returns False if lightning was stopped."""
    elapsed = 0.0
    while elapsed < seconds:
        time.sleep(0.25)
        elapsed += 0.25
        if not _lightning_active:
            return False
    return True


def _do_event():
    """
    Fire a complete lightning event, then restore.

    Single strike (80%): 1–3 pulses, 20–50 ms apart.
    Storm burst  (20%): 3–6 strikes, 80–250 ms between strikes.

    One TCP connection is used per strike so that a dropped connection
    during a long burst doesn't prevent the final restore from reaching
    the lamp.  Intra-strike pulses still share a single connection.
    A fresh connection is always opened for the final restore, regardless
    of whether any strike connections succeeded.
    """
    is_burst    = random.random() < 0.2
    num_strikes = random.randint(3, 6) if is_burst else 1
    flash       = _lightning_flash_channels()
    h           = time.localtime().tm_hour
    ambient     = list(_last_schedule[h][2:])   # restore between flashes

    for s in range(num_strikes):
        if not _lightning_active:
            break
        try:
            with lock:
                with _lamp() as lamp:
                    pulses = random.choices([1, 2, 3], weights=[65, 25, 10])[0]
                    for p in range(pulses):
                        if not _lightning_active:
                            break
                        lamp.preview_brightness(flash)
                        time.sleep(0.03 + random.random() * 0.05)    # 30–80 ms ON
                        lamp.preview_brightness(ambient)              # snap dark between pulses
                        if p < pulses - 1:
                            time.sleep(0.04 + random.random() * 0.06) # 40–100 ms dark gap
        except Exception:
            pass
        if s < num_strikes - 1:
            time.sleep(0.08 + random.random() * 0.17)    # 80–250 ms dark between strikes

    # Fresh connection for restore — always attempted even if a strike connection failed
    try:
        with lock:
            with _lamp() as lamp:
                lamp.preview_brightness(ambient)
                if not _ramp_active:
                    lamp.set_mode_auto()
    except Exception:
        pass


def _lightning_worker():
    global _lightning_active
    while _lightning_active:
        if not _sleep_interruptible(15 + random.random() * 75):
            return
        _do_event()


def _ensure_lightning_started():
    """Start the lightning worker if not already running. Reads lamp state first."""
    global _lightning_active, _lightning_thread, _last_schedule, _last_manual
    with _lightning_lock:
        if _lightning_active and _lightning_thread and _lightning_thread.is_alive():
            return
        try:
            with lock:
                with _lamp() as lamp:
                    raw = lamp.read_all()
            state = k7.decode_state(raw)
            if state and state.get('schedule'):
                _last_schedule = [list(row) for row in state['schedule']]
                _last_manual   = list(state['manual'])
        except Exception:
            pass   # lamp not reachable — use whatever is cached
        _lightning_active = True
        _lightning_thread = threading.Thread(target=_lightning_worker, daemon=True)
        _lightning_thread.start()


def _lightning_scheduler():
    """Background thread: enforce the lightning schedule window every 30 s."""
    global _lightning_active
    _load_lightning_schedule()
    while True:
        time.sleep(30)
        if not _ls.get('enabled'):
            continue
        if _in_lightning_window():
            if not _user_stopped:
                _ensure_lightning_started()
        else:
            _lightning_active = False


threading.Thread(target=_lightning_scheduler, daemon=True).start()


@app.route('/api/lightning/start', methods=['POST'])
def api_lightning_start():
    global _manually_enabled, _user_stopped
    _manually_enabled = True
    _user_stopped     = False
    _ensure_lightning_started()
    return jsonify({'ok': True})


@app.route('/api/lightning/stop', methods=['POST'])
def api_lightning_stop():
    global _lightning_active, _manually_enabled, _user_stopped
    _manually_enabled = False
    _user_stopped     = True
    _lightning_active = False
    return jsonify({'ok': True})


@app.route('/api/lightning/status')
def api_lightning_status():
    active = bool(_lightning_active and _lightning_thread and _lightning_thread.is_alive())
    return jsonify({'active': active})


@app.route('/api/lightning/schedule', methods=['GET'])
def api_lightning_schedule_get():
    return jsonify(_ls)


@app.route('/api/lightning/schedule', methods=['POST'])
def api_lightning_schedule_post():
    global _lightning_active, _user_stopped
    d = request.json or {}
    was_enabled = _ls.get('enabled', False)
    if 'enabled' in d: _ls['enabled'] = bool(d['enabled'])
    if 'start'   in d: _ls['start']   = str(d['start'])
    if 'end'     in d: _ls['end']     = str(d['end'])
    _save_lightning_schedule()
    # Schedule just enabled: clear user-stop so scheduler can fire
    if not was_enabled and _ls['enabled']:
        _user_stopped = False
    # Schedule just disabled: restore manual lightning state
    elif was_enabled and not _ls['enabled']:
        if _manually_enabled:
            _ensure_lightning_started()
        else:
            _lightning_active = False
    return jsonify(_ls)


# ── Smooth ramp ───────────────────────────────────────────────────────────────

_ramp_active    = False
_ramp_thread    = None
_ramp_last_tick = None   # epoch seconds of last preview_brightness sent


def _ramp_worker():
    """Send a preview_brightness every minute, interpolated to the current minute."""
    global _ramp_active, _ramp_last_tick
    while _ramp_active:
        t = time.localtime()
        h, m, s = t.tm_hour, t.tm_min, t.tm_sec
        channels = _interpolate_channels(_last_schedule, h, m)
        if _lunar_active and _in_lunar_window():
            _apply_lunar_overlay(channels)
        try:
            with lock:
                with _lamp() as lamp:
                    lamp.preview_brightness(channels)
            _ramp_last_tick = time.time()
        except Exception:
            pass
        # Sleep to the next minute boundary in small steps so _ramp_active is checked promptly
        sleep_s = max(1, 60 - s)
        elapsed = 0.0
        while elapsed < sleep_s and _ramp_active:
            time.sleep(0.5)
            elapsed += 0.5


def _ensure_ramp_started():
    global _ramp_active, _ramp_thread, _last_schedule, _last_manual
    if _ramp_active and _ramp_thread and _ramp_thread.is_alive():
        return
    # Seed schedule from lamp if we have no real data yet
    try:
        with lock:
            with _lamp() as lamp:
                raw = lamp.read_all()
        state = k7.decode_state(raw)
        if state and state.get('schedule'):
            _last_schedule = [list(row) for row in state['schedule']]
            _last_manual   = list(state['manual'])
    except Exception:
        pass
    _ramp_active = True
    _ramp_thread = threading.Thread(target=_ramp_worker, daemon=True)
    _ramp_thread.start()


@app.route('/api/ramp/start', methods=['POST'])
def api_ramp_start():
    _ensure_ramp_started()
    return jsonify({'ok': True})


@app.route('/api/ramp/stop', methods=['POST'])
def api_ramp_stop():
    global _ramp_active
    _ramp_active = False
    try:
        with lock:
            with _lamp() as lamp:
                lamp.set_mode_auto()
    except Exception:
        pass
    return jsonify({'ok': True})


@app.route('/api/ramp/status')
def api_ramp_status():
    active = bool(_ramp_active and _ramp_thread and _ramp_thread.is_alive())
    return jsonify({'active': active, 'last_tick': _ramp_last_tick})


# ── Lunar cycle ───────────────────────────────────────────────────────────────

_lm = {'enabled': False, 'start': '21:00', 'end': '06:00', 'max_intensity': 15}

_lunar_active  = False
_lunar_thread  = None
_lunar_stopped = False


def _load_lunar_cfg():
    if os.path.exists(LUNAR_FILE):
        try:
            with open(LUNAR_FILE) as f:
                _lm.update(json.load(f))
        except Exception:
            pass


def _save_lunar_cfg():
    with open(LUNAR_FILE, 'w') as f:
        json.dump(_lm, f)


def _in_lunar_window():
    s_m = _parse_hhmm(_lm.get('start', ''))
    e_m = _parse_hhmm(_lm.get('end', ''))
    if s_m is None or e_m is None:
        return False
    t   = time.localtime()
    now = t.tm_hour * 60 + t.tm_min
    if s_m <= e_m:
        return s_m <= now < e_m
    else:
        return now >= s_m or now < e_m


def _apply_lunar_overlay(channels):
    """Add lunar brightness contribution to channel list in-place (never dims)."""
    pct = round(_lm.get('max_intensity', 15) * moon.illumination())
    if pct <= 0:
        return
    if cfg['device'] == 'k7mini':
        channels[1] = max(channels[1], pct)
    else:
        channels[1] = max(channels[1], pct)
        channels[2] = max(channels[2], round(pct * 0.7))


def _lunar_worker():
    """Standalone worker used when ramp is not active."""
    global _lunar_active
    while _lunar_active:
        if _ramp_active:
            break
        if _in_lunar_window():
            channels = list(_last_schedule[time.localtime().tm_hour][2:])
            _apply_lunar_overlay(channels)
            try:
                with lock:
                    with _lamp() as lamp:
                        lamp.preview_brightness(channels)
            except Exception:
                pass
        t       = time.localtime()
        sleep_s = max(1, 60 - t.tm_sec)
        elapsed = 0.0
        while elapsed < sleep_s and _lunar_active and not _ramp_active:
            time.sleep(0.5)
            elapsed += 0.5
    if not _ramp_active:
        try:
            with lock:
                with _lamp() as lamp:
                    lamp.set_mode_auto()
        except Exception:
            pass
    _lunar_active = False


def _ensure_lunar_started():
    global _lunar_active, _lunar_thread
    _lunar_active = True
    if not _ramp_active:
        if not (_lunar_thread and _lunar_thread.is_alive()):
            _lunar_thread = threading.Thread(target=_lunar_worker, daemon=True)
            _lunar_thread.start()


def _lunar_scheduler():
    global _lunar_active
    _load_lunar_cfg()
    while True:
        time.sleep(60)
        if not _lm.get('enabled'):
            continue
        if _in_lunar_window():
            if not _lunar_stopped:
                _ensure_lunar_started()
        else:
            _lunar_active = False


threading.Thread(target=_lunar_scheduler, daemon=True).start()


@app.route('/api/lunar/status')
def api_lunar_status():
    active = bool(_lunar_active and (_ramp_active or (_lunar_thread and _lunar_thread.is_alive())))
    return jsonify({
        'active':        active,
        'phase':         moon.phase(),
        'illumination':  round(moon.illumination() * 100),
        'phase_name':    moon.phase_name(),
        'enabled':       _lm.get('enabled', False),
        'start':         _lm.get('start', '21:00'),
        'end':           _lm.get('end', '06:00'),
        'max_intensity': _lm.get('max_intensity', 15),
    })


@app.route('/api/lunar/start', methods=['POST'])
def api_lunar_start():
    global _lunar_stopped
    _lunar_stopped = False
    _ensure_lunar_started()
    return jsonify({'ok': True})


@app.route('/api/lunar/stop', methods=['POST'])
def api_lunar_stop():
    global _lunar_active, _lunar_stopped
    _lunar_stopped = True
    _lunar_active  = False
    return jsonify({'ok': True})


@app.route('/api/lunar/schedule', methods=['POST'])
def api_lunar_schedule_post():
    global _lunar_active, _lunar_stopped
    d = request.json or {}
    was_enabled = _lm.get('enabled', False)
    if 'enabled'       in d: _lm['enabled']       = bool(d['enabled'])
    if 'start'         in d: _lm['start']         = str(d['start'])
    if 'end'           in d: _lm['end']           = str(d['end'])
    if 'max_intensity' in d: _lm['max_intensity'] = int(d['max_intensity'])
    _save_lunar_cfg()
    if not was_enabled and _lm['enabled']:
        _lunar_stopped = False
    elif was_enabled and not _lm['enabled']:
        _lunar_active = False
    return jsonify(_lm)


# ─────────────────────────────────────────────────────────────────────────────

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
