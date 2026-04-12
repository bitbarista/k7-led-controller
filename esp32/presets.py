"""
Marine aquarium lighting presets — ESP32-S3 memory-optimised version.

Keyframes only are stored at import time (~4 KB).
Call build_schedule(keyframes) on demand; discard after use.
The PC version (root presets.py) pre-builds all schedules at import — fine
for a laptop, too costly for a ~200 KB MicroPython heap.
"""


def build_schedule(keyframes, hours=24):
    """
    Linear interpolation between keyframes → full 24-slot schedule.
    keyframes: list of (hour, [c0..c5])
    Returns list of 24 entries [h, 0, c0, c1, c2, c3, c4, c5].
    """
    kf = sorted(keyframes, key=lambda x: x[0])
    n  = len(kf[0][1])
    result = []
    for h in range(hours):
        lo = kf[0]
        hi = kf[-1]
        for i in range(len(kf) - 1):
            if kf[i][0] <= h <= kf[i + 1][0]:
                lo, hi = kf[i], kf[i + 1]
                break
        if lo[0] == hi[0] or h <= lo[0]:
            vals = lo[1]
        elif h >= hi[0]:
            vals = hi[1]
        else:
            t    = (h - lo[0]) / (hi[0] - lo[0])
            vals = [round(lo[1][j] + t * (hi[1][j] - lo[1][j])) for j in range(n)]
        result.append([h, 0] + [max(0, min(100, v)) for v in vals])
    return result


# ── K7 Mini presets ───────────────────────────────────────────────────────────
# Keyframes only — schedule built on demand via build_schedule()

MINI = {
    'fo': {
        'name':   'Fish Only',
        'desc':   'White-dominant for natural daylight appearance and fish colour rendering. '
                  '10-hour photoperiod. Target ~100 µmol/m²/s at 300 mm.',
        'manual': [42, 13, 16, 0, 0, 0],
        'keyframes': [
            ( 0, [ 0,  0,  0, 0, 0, 0]),
            ( 7, [ 0,  1,  3, 0, 0, 0]),
            ( 8, [ 6,  5,  6, 0, 0, 0]),
            ( 9, [19,  8, 10, 0, 0, 0]),
            (10, [32, 11, 14, 0, 0, 0]),
            (11, [42, 13, 16, 0, 0, 0]),
            (17, [42, 13, 16, 0, 0, 0]),
            (18, [26,  8, 10, 0, 0, 0]),
            (19, [ 8,  3,  5, 0, 0, 0]),
            (20, [ 0,  0,  0, 0, 0, 0]),
        ],
    },
    'lps': {
        'name':   'LPS Reef',
        'desc':   'Royal Blue dominant for zooxanthellae absorption. Restrained White, '
                  'Blue for spectrum depth. Actinic pre/post periods. '
                  'Target ~120 µmol/m²/s at 300 mm — Hammer, Torch, Brain, Frogspawn.',
        'manual': [12, 51, 48, 0, 0, 0],
        'keyframes': [
            ( 0, [ 0,  0,  0, 0, 0, 0]),
            ( 7, [ 0,  5,  8, 0, 0, 0]),
            ( 8, [ 4, 17, 22, 0, 0, 0]),
            ( 9, [ 6, 33, 36, 0, 0, 0]),
            (10, [ 9, 42, 42, 0, 0, 0]),
            (11, [12, 51, 48, 0, 0, 0]),
            (17, [12, 51, 48, 0, 0, 0]),
            (18, [ 8, 36, 34, 0, 0, 0]),
            (19, [ 4, 17, 19, 0, 0, 0]),
            (20, [ 0,  5,  8, 0, 0, 0]),
            (21, [ 0,  0,  0, 0, 0, 0]),
        ],
    },
    'sps': {
        'name':   'SPS Reef',
        'desc':   'Royal Blue at maximum for growth. White elevated for high total PPFD. '
                  'Gradual 4-hour ramp to prevent bleaching. '
                  'Target ~260 µmol/m²/s at 300 mm — Acropora, Montipora.',
        'manual': [69, 100, 100, 0, 0, 0],
        'keyframes': [
            ( 0, [ 0,   0,  0, 0, 0, 0]),
            ( 7, [ 7,  17, 23, 0, 0, 0]),
            ( 8, [21,  47, 56, 0, 0, 0]),
            ( 9, [39,  77, 77, 0, 0, 0]),
            (10, [55,  96, 90, 0, 0, 0]),
            (11, [69, 100,100, 0, 0, 0]),
            (17, [69, 100,100, 0, 0, 0]),
            (18, [48,  84, 77, 0, 0, 0]),
            (19, [25,  54, 50, 0, 0, 0]),
            (20, [ 9,  23, 25, 0, 0, 0]),
            (21, [ 0,   6,  9, 0, 0, 0]),
            (22, [ 0,   0,  0, 0, 0, 0]),
        ],
    },
    'mixed': {
        'name':   'Mixed Reef (LPS + SPS)',
        'desc':   'SPS-level Royal Blue with LPS-appropriate White. '
                  'Target ~175 µmol/m²/s at 300 mm.',
        'manual': [25, 70, 64, 0, 0, 0],
        'keyframes': [
            ( 0, [ 0,  0,  0, 0, 0, 0]),
            ( 7, [ 2,  7, 10, 0, 0, 0]),
            ( 8, [ 5, 24, 32, 0, 0, 0]),
            ( 9, [11, 43, 41, 0, 0, 0]),
            (10, [16, 57, 49, 0, 0, 0]),
            (11, [25, 70, 64, 0, 0, 0]),
            (17, [25, 70, 64, 0, 0, 0]),
            (18, [16, 49, 46, 0, 0, 0]),
            (19, [ 6, 25, 27, 0, 0, 0]),
            (20, [ 2,  8, 11, 0, 0, 0]),
            (21, [ 0,  0,  0, 0, 0, 0]),
        ],
    },
}


# ── K7 Pro presets ────────────────────────────────────────────────────────────

PRO = {
    'fo': {
        'name':   'Fish Only',
        'desc':   'White-dominant for natural fish colour. '
                  'Royal Blue for depth and sparkle. Bluer at dawn/dusk.',
        'manual': [4, 20, 38, 55, 21, 4],
        'keyframes': [
            ( 0, [0,  0,  0,  0,  0, 0]),
            ( 7, [0,  3, 10,  0,  0, 0]),
            ( 8, [2, 10, 20, 16,  8, 0]),
            ( 9, [3, 14, 28, 36, 14, 2]),
            (10, [4, 17, 34, 48, 18, 3]),
            (11, [4, 20, 38, 55, 21, 4]),
            (17, [4, 20, 38, 55, 21, 4]),
            (18, [3, 12, 26, 30, 11, 2]),
            (19, [1,  6, 13,  6,  4, 0]),
            (20, [0,  3, 10,  0,  0, 0]),
            (21, [0,  0,  0,  0,  0, 0]),
        ],
    },
    'lps': {
        'name':   'LPS Reef',
        'desc':   'Royal Blue dominant for zooxanthellae absorption. Restrained White. '
                  'Actinic pre/post periods — Hammer, Torch, Brain, Frogspawn.',
        'manual': [12, 51, 48, 25, 11, 0],
        'keyframes': [
            ( 0, [ 0,  0,  0,  0,  0, 0]),
            ( 7, [ 0,  5,  8,  0,  0, 0]),
            ( 8, [ 3, 18, 22,  7,  4, 0]),
            ( 9, [ 5, 31, 36, 15,  7, 0]),
            (10, [ 9, 42, 42, 20,  9, 0]),
            (11, [12, 51, 48, 25, 11, 0]),
            (17, [12, 51, 48, 25, 11, 0]),
            (18, [ 8, 36, 34, 12,  6, 0]),
            (19, [ 4, 17, 19,  4,  2, 0]),
            (20, [ 0,  5,  8,  0,  0, 0]),
            (21, [ 0,  0,  0,  0,  0, 0]),
        ],
    },
    'sps': {
        'name':   'SPS Reef',
        'desc':   'Royal Blue at maximum. White supports high total PPFD. '
                  'Gradual ramp to prevent bleaching — Acropora, Montipora.',
        'manual': [46, 100, 100, 42, 11, 0],
        'keyframes': [
            ( 0, [ 0,   0,  0,  0,  0, 0]),
            ( 7, [ 5,  17, 23,  0,  0, 0]),
            ( 8, [14,  47, 56, 14,  5, 0]),
            ( 9, [26,  77, 77, 25,  8, 0]),
            (10, [38,  96, 90, 36, 10, 0]),
            (11, [46, 100,100, 42, 11, 0]),
            (17, [46, 100,100, 42, 11, 0]),
            (18, [32,  84, 77, 23,  6, 0]),
            (19, [16,  54, 50,  7,  2, 0]),
            (20, [ 5,  23, 25,  0,  0, 0]),
            (21, [ 0,   6,  9,  0,  0, 0]),
            (22, [ 0,   0,  0,  0,  0, 0]),
        ],
    },
    'mixed': {
        'name':   'Mixed Reef (LPS + SPS)',
        'desc':   'SPS-level Royal Blue with LPS-appropriate White.',
        'manual': [22, 70, 64, 25, 11, 0],
        'keyframes': [
            ( 0, [ 0,  0,  0,  0,  0, 0]),
            ( 7, [ 2,  7, 10,  0,  0, 0]),
            ( 8, [ 5, 24, 32,  9,  4, 0]),
            ( 9, [11, 43, 41, 15,  7, 0]),
            (10, [16, 57, 49, 20,  9, 0]),
            (11, [22, 70, 64, 25, 11, 0]),
            (17, [22, 70, 64, 25, 11, 0]),
            (18, [14, 49, 46, 12,  5, 0]),
            (19, [ 5, 25, 27,  4,  2, 0]),
            (20, [ 2,  8, 11,  0,  0, 0]),
            (21, [ 0,  0,  0,  0,  0, 0]),
        ],
    },
}

ALL = {'k7mini': MINI, 'k7pro': PRO}
