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
import socket

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
CLOUD_FILE              = 'cloud_settings.json'
STATE_FILE              = 'state.json'


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

def _load_state():
    if _file_exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_state():
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump({
                'ramp':      _ramp_active,
                'lightning': _manually_enabled,
                'lunar':     _lunar_active and not _lunar_stopped,
                'clouds':    _cloud_active,
            }, f)
    except Exception:
        pass


# ── Routes ────────────────────────────────────────────────────────────────────

_master_brightness = 100   # UI-side master dimmer, persisted so all clients share it

@app.route('/api/master', methods=['GET', 'POST'])
async def api_master(request):
    global _master_brightness
    if request.method == 'POST':
        d = request.json or {}
        if 'value' in d:
            _master_brightness = max(0, min(200, int(d['value'])))
    return {'value': _master_brightness}


@app.route('/')
async def index(request):
    view = (request.args or {}).get('view', '')
    if view == 'desktop':
        return send_file('static/index.html', content_type='text/html')
    ua = (request.headers or {}).get('User-Agent', '')
    if view == 'mobile' or any(kw in ua for kw in ('Mobile', 'Android', 'iPhone', 'iPad')):
        return send_file('static/mobile.html', content_type='text/html')
    return send_file('static/index.html', content_type='text/html')


@app.route('/static/<path:path>')
async def static_files(request, path):
    max_age = 86400 if path.startswith('vendor/') else None
    return send_file('static/' + path, max_age=max_age)


# ── Captive portal redirects ──────────────────────────────────────────────────
# iOS, Android, and Windows each probe different URLs to detect captive portals.
# Redirect them all to the controller root so the OS shows the portal dialog.

async def _captive_redirect(request):
    return '', 302, {'Location': 'http://192.168.5.1/'}

for _cp_url in (
    '/hotspot-detect.html', '/library/test/success.html',  # iOS/macOS
    '/generate_204', '/gen_204',                            # Android/Chrome
    '/connecttest.txt', '/ncsi.txt',                        # Windows
    '/redirect', '/canonical.html',                         # misc
):
    app.route(_cp_url)(_captive_redirect)


# ── DNS spoofing ──────────────────────────────────────────────────────────────

def _dns_response(data, ip):
    """Build a minimal DNS A-record response — resolves any name to ip."""
    resp  = data[:2]                                          # transaction ID
    resp += b'\x81\x80'                                       # QR=1, RD=1, RA=1
    resp += data[4:6]                                         # QDCOUNT (echo)
    resp += data[4:6]                                         # ANCOUNT = QDCOUNT
    resp += b'\x00\x00\x00\x00'                              # NSCOUNT, ARCOUNT
    resp += data[12:]                                         # original question
    resp += b'\xc0\x0c'                                       # name pointer → offset 12
    resp += b'\x00\x01'                                       # TYPE A
    resp += b'\x00\x01'                                       # CLASS IN
    resp += b'\x00\x00\x00\x3c'                              # TTL = 60 s
    resp += b'\x00\x04'                                       # RDLENGTH = 4
    resp += bytes(int(x) for x in ip.split('.'))              # RDATA
    return resp


async def _dns_server(ip='192.168.5.1'):
    """Non-blocking UDP DNS server — spoofs all A queries with the AP IP."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', 53))
    sock.setblocking(False)
    while True:
        try:
            data, addr = sock.recvfrom(512)
            if data:
                sock.sendto(_dns_response(data, ip), addr)
        except OSError:
            pass
        await asyncio.sleep(0.05)


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
            # Return _last_schedule unscaled by master so clients can apply
            # their own master for display — prevents double-scaling when
            # reading back a schedule that was pushed with master pre-applied.
            mb = _master_brightness / 100.0 if _master_brightness > 0 else 1.0
            state['schedule'] = [
                list(row[:2]) + [min(100, round((v or 0) / mb)) for v in row[2:]]
                for row in _last_schedule
            ]
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
            if _ramp_active:
                mode = 'manual'   # ramp owns the lamp; don't hand control back to auto
            with _lamp() as lamp:
                lamp.push_schedule(manual, schedule, mode)
            _last_schedule = [list(e) for e in schedule]
            _last_manual   = list(manual)
        except OSError as e:
            return {'error': f'Connection failed — {e}'}, 503
        except Exception as e:
            return {'error': str(e)}, 500
    await _lunar_apply_now()   # re-apply overlay immediately if lunar is active
    # If ramp is active but lunar didn't cover it (not active / out of window),
    # immediately drive the lamp to the new schedule so the change is visible
    # at once rather than waiting up to 60 s for the next ramp tick.
    if _ramp_active and not (_lunar_active and _in_lunar_window()):
        t = time.localtime()
        channels = _interpolate_channels(_last_schedule, t[3], t[4])
        async with lock:
            try:
                with _lamp() as lamp:
                    lamp.hand_luminance(channels)
            except Exception:
                pass
    return {'ok': True}


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
    t           = time.localtime()
    h, m        = t[3], t[4]
    # Interpolated so restore exactly matches what ramp is showing (not the raw hour slot)
    ambient = _interpolate_channels(_last_schedule, h, m)
    if _lunar_active and _in_lunar_window():
        _apply_lunar_overlay(ambient)

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
                if _ramp_active:
                    # Ramp owns the lamp in manual mode — restore with hand_luminance
                    # so the stored value stays in sync with what the ramp expects.
                    # preview_brightness here would cause a step at the next minute tick.
                    lamp.hand_luminance(ambient)
                else:
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
    global _manually_enabled, _user_stopped
    _manually_enabled = True
    _user_stopped     = False
    await _ensure_lightning_started()
    _save_state()
    return {'ok': True}


@app.route('/api/lightning/stop', methods=['POST'])
async def api_lightning_stop(request):
    global _lightning_active, _manually_enabled, _user_stopped
    _manually_enabled = False
    _user_stopped     = True
    _lightning_active = False
    _save_state()
    return {'ok': True}


@app.route('/api/lightning/status')
async def api_lightning_status(request):
    return {
        'active':  _lightning_active,
        'enabled': _ls.get('enabled', False),
        'start':   _ls.get('start', '20:00'),
        'end':     _ls.get('end',   '23:00'),
    }


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
    """
    Send hand_luminance every minute, interpolated to the current minute.

    Uses CMD_HAND_LUMINANCE (not preview_brightness) because the lamp runs its
    own internal schedule in auto mode — it would override a preview on every
    minute tick, causing the observed up/down oscillation.  We switch the lamp
    to manual mode on ramp start so the controller owns the brightness, then
    restore auto mode on stop.
    """
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
                    lamp.hand_luminance(channels)
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
    # Switch lamp to manual mode so its internal schedule can't override our values
    async with lock:
        try:
            with _lamp() as lamp:
                lamp.set_mode_manual()
        except Exception:
            pass
    _ramp_active = True
    _ramp_task   = asyncio.create_task(_ramp_worker())


@app.route('/api/ramp/start', methods=['POST'])
async def api_ramp_start(request):
    await _ensure_ramp_started()
    _save_state()
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
    _save_state()
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
    raw = _lm.get('max_intensity', 15) * moon.illumination()
    pct = int(raw) + (1 if raw > int(raw) else 0)  # ceiling so low intensity still fires
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


async def _lunar_apply_now():
    """Immediately push the current lunar overlay to the lamp.

    Called after any settings change so the effect is visible at once rather
    than waiting up to 59 s for the next minute-boundary tick.
    Both cases handled: ramp owns the lamp (hand_luminance) and standalone
    lunar (preview_brightness).
    """
    # Apply if explicitly active, OR if the schedule just enabled it and we're in window
    in_window = _in_lunar_window()
    scheduled_and_in_window = _lm.get('enabled') and in_window and not _lunar_stopped
    if not (_lunar_active or scheduled_and_in_window):
        return
    if not in_window:
        return
    t = time.localtime()
    channels = _interpolate_channels(_last_schedule, t[3], t[4])
    _apply_lunar_overlay(channels)
    async with lock:
        try:
            with _lamp() as lamp:
                if _ramp_active:
                    lamp.hand_luminance(channels)
                else:
                    lamp.preview_brightness(channels)
        except Exception:
            pass


async def _lunar_restore_now():
    """Immediately remove the lunar overlay — restore plain schedule brightness."""
    t = time.localtime()
    channels = _interpolate_channels(_last_schedule, t[3], t[4])
    async with lock:
        try:
            with _lamp() as lamp:
                if _ramp_active:
                    lamp.hand_luminance(channels)
                else:
                    lamp.preview_brightness(channels)
                    lamp.set_mode_auto()
        except Exception:
            pass


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
    await _lunar_apply_now()
    _save_state()
    return {'ok': True}


@app.route('/api/lunar/stop', methods=['POST'])
async def api_lunar_stop(request):
    global _lunar_active, _lunar_stopped
    _lunar_stopped = True
    _lunar_active  = False
    await _lunar_restore_now()
    _save_state()
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
        _lunar_stopped = False
        await _lunar_apply_now()       # just enabled — apply overlay immediately
    elif was_enabled and not _lm['enabled']:
        _lunar_active = False
        await _lunar_restore_now()     # just disabled — remove overlay immediately
    else:
        await _lunar_apply_now()       # settings changed (intensity/times) — re-apply
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


# ── Clouds effect ─────────────────────────────────────────────────────────────

_cs = {'density': 30, 'depth': 60, 'colour_shift': True}
_cloud_active = False
_cloud_task   = None


def _load_cloud_settings():
    if _file_exists(CLOUD_FILE):
        try:
            with open(CLOUD_FILE) as f:
                _cs.update(json.load(f))
        except Exception:
            pass


def _save_cloud_settings():
    try:
        with open(CLOUD_FILE, 'w') as f:
            json.dump(_cs, f)
    except Exception:
        pass


def _apply_cloud(base, dim, colour_shift):
    """Return a new channel list with cloud dimming applied.

    White is dimmed by (1-dim).  Blue channels are dimmed an extra 25 % at
    full depth to simulate the warmer colour of overcast light.
    """
    factor = 1.0 - dim
    extra  = 0.25 * dim if colour_shift else 0.0
    out = list(base)
    for i in range(len(out)):
        if i == 0:    # white — least affected
            out[i] = max(0, round(out[i] * factor))
        else:         # royal_blue, blue — dims more under clouds
            out[i] = max(0, round(out[i] * max(0.0, factor - extra)))
    return out


async def _cloud_worker():
    global _cloud_active
    while _cloud_active:
        density = _cs.get('density', 30) / 100.0   # 0–1
        depth   = _cs.get('depth', 60) / 100.0     # 0–1
        shift   = _cs.get('colour_shift', True)

        # Gap between cloud events: dense sky → short gaps, clear sky → long gaps
        gap_base = max(3.0, 120.0 * (1.0 - density) + 5.0 * density)
        gap_s    = gap_base + random.random() * gap_base
        elapsed  = 0.0
        while elapsed < gap_s and _cloud_active:
            await asyncio.sleep(0.5)
            elapsed += 0.5
        if not _cloud_active:
            break

        # Pick cloud properties
        dim        = depth * (0.4 + 0.6 * random.random())   # 40–100 % of max depth
        ramp_in_s  = 3.0 + random.random() * 9.0             # 3–12 s fade in
        hold_s     = 10.0 + random.random() * 80.0           # 10–90 s overcast
        ramp_out_s = 3.0 + random.random() * 9.0             # 3–12 s fade out

        # Fade in (darken)
        steps = max(4, round(ramp_in_s * 2))
        for step in range(steps + 1):
            if not _cloud_active:
                break
            t  = time.localtime()
            ch = _apply_cloud(
                _interpolate_channels(_last_schedule, t[3], t[4]),
                dim * step / steps, shift)
            if _lunar_active and _in_lunar_window():
                _apply_lunar_overlay(ch)
            async with lock:
                try:
                    with _lamp() as lamp:
                        if _ramp_active:
                            lamp.hand_luminance(ch)
                        else:
                            lamp.preview_brightness(ch)
                except Exception:
                    pass
            await asyncio.sleep(0.5)

        # Hold with subtle flicker
        elapsed = 0.0
        while elapsed < hold_s and _cloud_active:
            t       = time.localtime()
            flicker = max(0.0, min(1.0, dim + (random.random() - 0.5) * 0.08))
            ch      = _apply_cloud(
                _interpolate_channels(_last_schedule, t[3], t[4]),
                flicker, shift)
            if _lunar_active and _in_lunar_window():
                _apply_lunar_overlay(ch)
            async with lock:
                try:
                    with _lamp() as lamp:
                        if _ramp_active:
                            lamp.hand_luminance(ch)
                        else:
                            lamp.preview_brightness(ch)
                except Exception:
                    pass
            sleep_t = 2.0 + random.random() * 3.0
            await asyncio.sleep(sleep_t)
            elapsed += sleep_t

        if not _cloud_active:
            break

        # Fade out (brighten)
        steps = max(4, round(ramp_out_s * 2))
        for step in range(steps + 1):
            if not _cloud_active:
                break
            t  = time.localtime()
            ch = _apply_cloud(
                _interpolate_channels(_last_schedule, t[3], t[4]),
                dim * (1.0 - step / steps), shift)
            if _lunar_active and _in_lunar_window():
                _apply_lunar_overlay(ch)
            async with lock:
                try:
                    with _lamp() as lamp:
                        if _ramp_active:
                            lamp.hand_luminance(ch)
                        else:
                            lamp.preview_brightness(ch)
                except Exception:
                    pass
            await asyncio.sleep(0.5)

    # Restore on exit
    _cloud_active = False
    if not _ramp_active:
        t  = time.localtime()
        ch = _interpolate_channels(_last_schedule, t[3], t[4])
        async with lock:
            try:
                with _lamp() as lamp:
                    lamp.preview_brightness(ch)
                    lamp.set_mode_auto()
            except Exception:
                pass


@app.route('/api/clouds/status')
async def api_clouds_status(request):
    return {
        'active':        _cloud_active,
        'density':       _cs.get('density', 30),
        'depth':         _cs.get('depth', 60),
        'colour_shift':  _cs.get('colour_shift', True),
    }


@app.route('/api/clouds/start', methods=['POST'])
async def api_clouds_start(request):
    global _cloud_active, _cloud_task
    _cloud_active = True
    _cloud_task   = asyncio.create_task(_cloud_worker())
    _save_state()
    return {'ok': True}


@app.route('/api/clouds/stop', methods=['POST'])
async def api_clouds_stop(request):
    global _cloud_active
    _cloud_active = False
    _save_state()
    return {'ok': True}


@app.route('/api/clouds/settings', methods=['POST'])
async def api_clouds_settings(request):
    d = request.json or {}
    for k in ('density', 'depth', 'colour_shift'):
        if k in d:
            _cs[k] = d[k]
    _save_cloud_settings()
    return {'ok': True}


# ── Startup ───────────────────────────────────────────────────────────────────

async def main(host='0.0.0.0', port=80):
    """Start background tasks then run the web server."""
    global _manually_enabled, _user_stopped, _last_schedule, _last_manual
    # Load persisted config so effect restores have correct settings
    _load_lightning_schedule()
    _load_lunar_cfg()
    _load_cloud_settings()
    # Seed schedule from lamp so restored effects use real brightness values
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
    # Restore previously active effects
    saved = _load_state()
    if saved.get('ramp'):
        await _ensure_ramp_started()
    if saved.get('lightning'):
        _manually_enabled = True
        _user_stopped     = False
        await _ensure_lightning_started()
    if saved.get('lunar'):
        await _ensure_lunar_started()
        await _lunar_apply_now()
    if saved.get('clouds'):
        global _cloud_active, _cloud_task
        _cloud_active = True
        _cloud_task   = asyncio.create_task(_cloud_worker())
    asyncio.create_task(_lightning_scheduler())
    asyncio.create_task(_lunar_scheduler())
    asyncio.create_task(_dns_server())
    await app.start_server(host=host, port=port, debug=False)
