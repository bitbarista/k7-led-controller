"""
K7 LED Controller — MicroPython/Microdot server (ESP32-S3)
Async port of the PC server.py:  Flask → Microdot,  threading → uasyncio.

Key differences from PC version:
  - Route handlers are async def
  - threading.Lock  → asyncio.Lock
  - threading.Thread → asyncio.create_task
  - No esptouch / provisioning
  - Serves static/index.html directly (no Jinja2)
  - File paths are relative to the device filesystem root
  - time.localtime() returns a tuple — use t[3]/t[4]/t[5] for H/M/S
  - random.choices() unavailable — use _weighted_choice()
  - /api/time  endpoint lets the browser sync the device RTC on page load
"""

import uasyncio as asyncio
import random
import json
import time
import os

from microdot import Microdot, send_file

import k7mini as k7
import presets

app  = Microdot()
lock = asyncio.Lock()   # one device request at a time

cfg = {'host': '192.168.4.1', 'port': 8266, 'device': 'k7mini'}

# Last schedule/manual pushed to the lamp — used by lightning for restore
_last_schedule = [[h, 0, 0, 0, 0, 0, 0, 0] for h in range(24)]
_last_manual   = [0] * 6

PROFILES_FILE           = 'profiles.json'
LIGHTNING_SCHEDULE_FILE = 'lightning_schedule.json'


# ── Helpers ───────────────────────────────────────────────────────────────────

def _file_exists(path):
    try: os.stat(path); return True
    except OSError: return False

def _weighted_choice(choices, weights):
    """random.choices() substitute for MicroPython."""
    total = sum(weights)
    r = random.random() * total
    for choice, weight in zip(choices, weights):
        r -= weight
        if r <= 0:
            return choice
    return choices[-1]

def _lamp():
    return k7.K7(cfg['host'], cfg['port'], verbose=False)

def _load_profiles():
    if _file_exists(PROFILES_FILE):
        with open(PROFILES_FILE) as f:
            return json.load(f)
    return {}

def _save_profiles(data):
    with open(PROFILES_FILE, 'w') as f:
        json.dump(data, f)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
async def index(request):
    return send_file('static/index.html', content_type='text/html')


@app.route('/api/devices')
async def api_devices(request):
    return k7.DEVICES


@app.route('/api/config', methods=['GET', 'POST'])
async def api_config(request):
    if request.method == 'POST':
        d = request.json or {}
        if 'host'   in d: cfg['host']   = d['host']
        if 'port'   in d: cfg['port']   = int(d['port'])
        if 'device' in d: cfg['device'] = d['device']
    return cfg


@app.route('/api/time', methods=['POST'])
async def api_time(request):
    """Sync device RTC from browser timestamp (ms since epoch)."""
    d = request.json or {}
    ts = d.get('timestamp')
    if ts:
        try:
            from machine import RTC
            t = time.gmtime(ts // 1000)
            # RTC.datetime: (year, month, day, weekday, hour, minute, second, subsecond)
            RTC().datetime((t[0], t[1], t[2], t[6], t[3], t[4], t[5], 0))
        except Exception as e:
            return {'error': str(e)}, 500
    return {'ok': True}


@app.route('/api/state')
async def api_state(request):
    async with lock:
        try:
            with _lamp() as lamp:
                raw = lamp.read_all()
            state = k7.decode_state(raw)
            if not state:
                return {'error': 'Could not decode device response'}, 500
            state['schedule'] = [list(e) for e in state['schedule']]
            return state
        except OSError as e:
            return {'error': f'Connection failed — {e}'}, 503
        except Exception as e:
            return {'error': str(e)}, 500


@app.route('/api/push', methods=['POST'])
async def api_push(request):
    global _last_schedule, _last_manual
    d = request.json or {}
    async with lock:
        try:
            manual   = d['manual']
            schedule = [tuple(e) for e in d['schedule']]
            mode     = d.get('mode', 'auto')
            with _lamp() as lamp:
                lamp.push_schedule(manual, schedule, mode)
            _last_schedule = [list(e) for e in schedule]
            _last_manual   = list(manual)
            return {'ok': True}
        except OSError as e:
            return {'error': f'Connection failed — {e}'}, 503
        except Exception as e:
            return {'error': str(e)}, 500


@app.route('/api/presets')
async def api_presets(request):
    device = cfg['device']
    ps = presets.ALL.get(device, {})
    out = {}
    for key, p in ps.items():
        out[key] = {
            'name':     p['name'],
            'desc':     p['desc'],
            'manual':   p['manual'],
            'schedule': [list(row) for row in p['schedule']],
        }
    return out


@app.route('/api/profiles', methods=['GET'])
async def api_profiles_get(request):
    return _load_profiles()


@app.route('/api/profiles', methods=['POST'])
async def api_profiles_post(request):
    d = request.json or {}
    name = d.get('name', '').strip()
    if not name:
        return {'error': 'Name required'}, 400
    profiles = _load_profiles()
    profiles[name] = d
    _save_profiles(profiles)
    return {'ok': True}


@app.route('/api/profiles/<name>', methods=['DELETE'])
async def api_profiles_delete(request, name):
    profiles = _load_profiles()
    profiles.pop(name, None)
    _save_profiles(profiles)
    return {'ok': True}


@app.route('/api/preview', methods=['POST'])
async def api_preview(request):
    d = request.json or {}
    channels = d.get('channels', [0] * 6)
    async with lock:
        try:
            with _lamp() as lamp:
                lamp.preview_brightness(channels)
            return {'ok': True}
        except Exception as e:
            return {'error': str(e)}, 500


# ── Lightning effect ──────────────────────────────────────────────────────────

def _lightning_flash_channels():
    if cfg['device'] == 'k7mini':
        return [100, 60, 60, 0, 0, 0]
    else:
        return [40, 60, 60, 100, 100, 0]


_lightning_lock   = asyncio.Lock()
_lightning_active = False
_lightning_task   = None


async def _do_event():
    """
    Fire one lightning event (single strike or storm burst) then restore.
    One TCP connection per strike; fresh connection for the final restore.
    """
    is_burst    = random.random() < 0.2
    num_strikes = random.randint(3, 6) if is_burst else 1
    flash       = _lightning_flash_channels()
    h           = time.localtime()[3]
    ambient     = list(_last_schedule[h][2:])

    for s in range(num_strikes):
        if not _lightning_active:
            break
        async with lock:
            try:
                with _lamp() as lamp:
                    pulses = _weighted_choice([1, 2, 3], [65, 25, 10])
                    for p in range(pulses):
                        if not _lightning_active:
                            break
                        lamp.preview_brightness(flash)
                        await asyncio.sleep(0.03 + random.random() * 0.05)
                        lamp.preview_brightness(ambient)
                        if p < pulses - 1:
                            await asyncio.sleep(0.04 + random.random() * 0.06)
            except Exception:
                pass
        if s < num_strikes - 1:
            await asyncio.sleep(0.08 + random.random() * 0.17)

    # Fresh connection for restore
    async with lock:
        try:
            with _lamp() as lamp:
                lamp.preview_brightness(ambient)
                lamp.set_mode_auto()
        except Exception:
            pass


async def _lightning_worker():
    global _lightning_active
    while _lightning_active:
        # Interruptible sleep: 15–90 s between events
        delay   = 15 + random.random() * 75
        elapsed = 0.0
        while elapsed < delay and _lightning_active:
            await asyncio.sleep(0.25)
            elapsed += 0.25
        if _lightning_active:
            await _do_event()


async def _ensure_lightning_started():
    global _lightning_active, _lightning_task, _last_schedule, _last_manual
    async with _lightning_lock:
        if _lightning_active and _lightning_task:
            return
        # Snapshot lamp state so ambient restore is correct
        try:
            async with lock:
                with _lamp() as lamp:
                    raw = lamp.read_all()
            state = k7.decode_state(raw)
            if state and state.get('schedule'):
                _last_schedule = [list(row) for row in state['schedule']]
                _last_manual   = list(state['manual'])
        except Exception:
            pass
        _lightning_active = True
        _lightning_task   = asyncio.create_task(_lightning_worker())


@app.route('/api/lightning/start', methods=['POST'])
async def api_lightning_start(request):
    await _ensure_lightning_started()
    return {'ok': True}


@app.route('/api/lightning/stop', methods=['POST'])
async def api_lightning_stop(request):
    global _lightning_active
    _lightning_active = False
    return {'ok': True}


@app.route('/api/lightning/status')
async def api_lightning_status(request):
    return {'active': _lightning_active}


# ── Lightning schedule ────────────────────────────────────────────────────────

_ls = {'enabled': False, 'start': '20:00', 'end': '23:00'}

def _load_lightning_schedule():
    if _file_exists(LIGHTNING_SCHEDULE_FILE):
        try:
            with open(LIGHTNING_SCHEDULE_FILE) as f:
                _ls.update(json.load(f))
        except Exception:
            pass

def _save_lightning_schedule():
    with open(LIGHTNING_SCHEDULE_FILE, 'w') as f:
        json.dump(_ls, f)

def _parse_hhmm(s):
    try:
        parts = s.split(':')
        return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        return None

def _in_lightning_window():
    if not _ls.get('enabled'):
        return False
    s_m = _parse_hhmm(_ls.get('start', ''))
    e_m = _parse_hhmm(_ls.get('end', ''))
    if s_m is None or e_m is None:
        return False
    t   = time.localtime()
    now = t[3] * 60 + t[4]
    if s_m <= e_m:
        return s_m <= now < e_m
    else:                       # overnight window e.g. 22:00-02:00
        return now >= s_m or now < e_m


async def _lightning_scheduler():
    global _lightning_active
    _load_lightning_schedule()
    while True:
        await asyncio.sleep(30)
        if not _ls.get('enabled'):
            continue
        if _in_lightning_window():
            await _ensure_lightning_started()
        else:
            _lightning_active = False


@app.route('/api/lightning/schedule', methods=['GET'])
async def api_lightning_schedule_get(request):
    return _ls


@app.route('/api/lightning/schedule', methods=['POST'])
async def api_lightning_schedule_post(request):
    d = request.json or {}
    if 'enabled' in d: _ls['enabled'] = bool(d['enabled'])
    if 'start'   in d: _ls['start']   = str(d['start'])
    if 'end'     in d: _ls['end']     = str(d['end'])
    _save_lightning_schedule()
    return _ls


# ── Startup ───────────────────────────────────────────────────────────────────

async def main(host='0.0.0.0', port=80):
    """Start background tasks then run the web server."""
    asyncio.create_task(_lightning_scheduler())
    await app.start_server(host=host, port=port, debug=False)
