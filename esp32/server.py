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

import asyncio
import random
import json
import time
import os
import gc

from microdot import Microdot, send_file

import k7mini as k7
import presets
import moon

app  = Microdot()
lock = asyncio.Lock()   # one device request at a time

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

PROFILES_FILE           = 'profiles.json'
LIGHTNING_SCHEDULE_FILE = 'lightning_schedule.json'
LUNAR_FILE              = 'lunar_schedule.json'


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


@app.route('/static/<path:path>')
async def static_files(request, path):
    gc.collect()
    return send_file('static/' + path)


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
            gc.collect()
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
            # Build schedule from keyframes on demand — don't hold all schedules in RAM
            'schedule': [list(row) for row in presets.build_schedule(p['keyframes'])],
        }
    gc.collect()   # recover the intermediate schedule lists immediately
    return out


@app.route('/api/profiles', methods=['GET'])
async def api_profiles_get(request):
    data = _load_profiles()
    gc.collect()
    return data


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
_manually_enabled = False   # tracks the user's intent, independent of schedule
_user_stopped     = False   # set when user presses Stop; prevents scheduler restarting


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
                if not _ramp_active:
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
    global _manually_enabled, _user_stopped
    _manually_enabled = True
    _user_stopped     = False
    await _ensure_lightning_started()
    return {'ok': True}


@app.route('/api/lightning/stop', methods=['POST'])
async def api_lightning_stop(request):
    global _lightning_active, _manually_enabled, _user_stopped
    _manually_enabled = False
    _user_stopped     = True
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
            if not _user_stopped:
                await _ensure_lightning_started()
        else:
            _lightning_active = False


@app.route('/api/lightning/schedule', methods=['GET'])
async def api_lightning_schedule_get(request):
    return _ls


@app.route('/api/lightning/schedule', methods=['POST'])
async def api_lightning_schedule_post(request):
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
            await _ensure_lightning_started()
        else:
            _lightning_active = False
    return _ls


# ── Smooth ramp ───────────────────────────────────────────────────────────────

_ramp_active    = False
_ramp_task      = None
_ramp_last_tick = None   # epoch seconds of last preview_brightness sent


async def _ramp_worker():
    """Send a preview_brightness every minute, interpolated to the current minute."""
    global _ramp_active, _ramp_last_tick
    while _ramp_active:
        t = time.localtime()
        h, m, s = t[3], t[4], t[5]
        channels = _interpolate_channels(_last_schedule, h, m)
        if _lunar_active and _in_lunar_window():
            _apply_lunar_overlay(channels)
        async with lock:
            try:
                with _lamp() as lamp:
                    lamp.preview_brightness(channels)
                _ramp_last_tick = time.time()
            except Exception:
                pass
        # Sleep to the next minute boundary in small steps so _ramp_active is checked promptly
        sleep_s = max(1, 60 - s)
        elapsed = 0.0
        while elapsed < sleep_s and _ramp_active:
            await asyncio.sleep(0.5)
            elapsed += 0.5


async def _ensure_ramp_started():
    global _ramp_active, _ramp_task, _last_schedule, _last_manual
    if _ramp_active and _ramp_task:
        return
    # Seed schedule from lamp if we have no real data yet
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
    _ramp_active = True
    _ramp_task   = asyncio.create_task(_ramp_worker())


@app.route('/api/ramp/start', methods=['POST'])
async def api_ramp_start(request):
    await _ensure_ramp_started()
    return {'ok': True}


@app.route('/api/ramp/stop', methods=['POST'])
async def api_ramp_stop(request):
    global _ramp_active
    _ramp_active = False
    async with lock:
        try:
            with _lamp() as lamp:
                lamp.set_mode_auto()
        except Exception:
            pass
    return {'ok': True}


@app.route('/api/ramp/status')
async def api_ramp_status(request):
    return {'active': _ramp_active, 'last_tick': _ramp_last_tick}


# ── Lunar cycle ───────────────────────────────────────────────────────────────

_lm = {'enabled': False, 'start': '21:00', 'end': '06:00', 'max_intensity': 15}

_lunar_active  = False
_lunar_task    = None
_lunar_stopped = False   # set when user stops; prevents scheduler restarting


def _load_lunar_cfg():
    if _file_exists(LUNAR_FILE):
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
    now = t[3] * 60 + t[4]
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


async def _lunar_worker():
    """Standalone worker used when ramp is not active."""
    global _lunar_active
    while _lunar_active:
        if _ramp_active:
            break   # ramp has taken over lunar duty
        if _in_lunar_window():
            channels = list(_last_schedule[time.localtime()[3]][2:])
            _apply_lunar_overlay(channels)
            async with lock:
                try:
                    with _lamp() as lamp:
                        lamp.preview_brightness(channels)
                except Exception:
                    pass
        t       = time.localtime()
        sleep_s = max(1, 60 - t[5])
        elapsed = 0.0
        while elapsed < sleep_s and _lunar_active and not _ramp_active:
            await asyncio.sleep(0.5)
            elapsed += 0.5
    if not _ramp_active:
        async with lock:
            try:
                with _lamp() as lamp:
                    lamp.set_mode_auto()
            except Exception:
                pass
    _lunar_active = False


async def _ensure_lunar_started():
    global _lunar_active, _lunar_task
    _lunar_active = True
    if not _ramp_active:
        _lunar_task = asyncio.create_task(_lunar_worker())


@app.route('/api/lunar/status')
async def api_lunar_status(request):
    return {
        'active':        _lunar_active,
        'phase':         moon.phase(),
        'illumination':  round(moon.illumination() * 100),
        'phase_name':    moon.phase_name(),
        'enabled':       _lm.get('enabled', False),
        'start':         _lm.get('start', '21:00'),
        'end':           _lm.get('end', '06:00'),
        'max_intensity': _lm.get('max_intensity', 15),
    }


@app.route('/api/lunar/start', methods=['POST'])
async def api_lunar_start(request):
    global _lunar_stopped
    _lunar_stopped = False
    await _ensure_lunar_started()
    return {'ok': True}


@app.route('/api/lunar/stop', methods=['POST'])
async def api_lunar_stop(request):
    global _lunar_active, _lunar_stopped
    _lunar_stopped = True
    _lunar_active  = False
    return {'ok': True}


@app.route('/api/lunar/schedule', methods=['POST'])
async def api_lunar_schedule_post(request):
    global _lunar_active, _lunar_stopped
    d = request.json or {}
    was_enabled = _lm.get('enabled', False)
    if 'enabled'       in d: _lm['enabled']       = bool(d['enabled'])
    if 'start'         in d: _lm['start']         = str(d['start'])
    if 'end'           in d: _lm['end']           = str(d['end'])
    if 'max_intensity' in d: _lm['max_intensity'] = int(d['max_intensity'])
    _save_lunar_cfg()
    if not was_enabled and _lm['enabled']:
        _lunar_stopped = False   # re-enabling schedule clears manual stop
    elif was_enabled and not _lm['enabled']:
        _lunar_active = False
    return _lm


async def _lunar_scheduler():
    global _lunar_active
    _load_lunar_cfg()
    while True:
        await asyncio.sleep(60)
        if not _lm.get('enabled'):
            continue
        if _in_lunar_window():
            if not _lunar_stopped:
                await _ensure_lunar_started()
        else:
            _lunar_active = False


# ── Startup ───────────────────────────────────────────────────────────────────

async def main(host='0.0.0.0', port=80):
    """Start background tasks then run the web server."""
    asyncio.create_task(_lightning_scheduler())
    asyncio.create_task(_lunar_scheduler())
    await app.start_server(host=host, port=port, debug=False)
