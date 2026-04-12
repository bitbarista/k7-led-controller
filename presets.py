"""
Marine aquarium lighting presets for Noo-Psyche K7 LED lamps.

Channel order:
  K7 Mini: [white, royal_blue, blue, -, -, -]
  K7 Pro:  [uv, royal_blue, blue, white, warm_white, red]

K7 Mini uses channels 0-2 only (white, royal_blue, blue).
K7 Pro  uses all 6 channels.

Schedule format: list of 24 entries, each [hour, minute, c0..c5].

K7 Mini PPFD measurements at 150 mm (single channel at 100%, others off):
  White only:       473 µmol/m²/s
  Royal Blue only:  524 µmol/m²/s
  Blue only:         37 µmol/m²/s

Blue contributes ~7% as much PPFD as Royal Blue. It is a colour/spectrum
channel — Royal Blue is the primary PPFD driver.

LED output is not linear with the percentage value. Preset PPFD targets
are calibrated at 300 mm mounting distance from measured values. Verify
with a PPFD meter and fine-tune using the per-channel sliders.

Preset target PPFD at 300 mm:
  Fish Only:   ~100 µmol/m²/s
  LPS Reef:    ~120 µmol/m²/s
  Mixed Reef:  ~175 µmol/m²/s
  SPS Reef:    ~260 µmol/m²/s

Lighting philosophy per tank type
──────────────────────────────────
Fish Only (FO)
  • White-dominant for natural daylight appearance and fish colour rendering
  • Moderate Royal Blue for depth and sparkle
  • Low Blue for ocean colour balance
  • 10-hour photoperiod

LPS (Large Polyp Stony — Hammer, Torch, Brain, Frogspawn)
  • Royal Blue dominant (440–480 nm = peak zooxanthellae absorption)
  • Blue for spectrum depth and colour — not a primary PPFD driver
  • Restrained White — enough for polyp extension without bleaching
  • Actinic-only pre-dawn and post-dusk periods
  • 10-hour photoperiod

SPS (Small Polyp Stony — Acropora, Montipora, Pocillopora)
  • Royal Blue at maximum — primary PPFD and growth driver
  • White elevated to support higher total PPFD target
  • Blue at maximum for full spectrum coverage
  • Gradual 4-hour ramp critical — abrupt intensity increase bleaches
  • 10-hour photoperiod

Mixed Reef (LPS + SPS coexisting)
  • SPS-level Royal Blue with LPS-appropriate White
  • Placement matters (SPS high, LPS low) but schedule covers the middle ground
  • 10-hour photoperiod
"""

def _build(keyframes: list[tuple], hours: int = 24) -> list[list]:
    """
    Linear interpolation between keyframes to produce a full 24-slot schedule.
    keyframes: list of (hour, [c0..c5]) — must include hour 0.
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


# ── K7 Mini presets (3 active channels: white, royal_blue, blue) ─────────────
# Channel slots: [white, royal_blue, blue, 0, 0, 0]
#
# Calibrated from measured PPFD at 150 mm; scaled to target values at 300 mm.
# Scale factors applied to previous measured outputs:
#   FO:    ×0.645  (155 → ~100 µmol/m²/s at 300 mm)
#   LPS:   ×0.745  (161 → ~120 µmol/m²/s at 300 mm)
#   Mixed: ×0.875  (200 → ~175 µmol/m²/s at 300 mm)
#   SPS:   ×1.125  (231 → ~260 µmol/m²/s at 300 mm)

MINI = {

    'fo': {
        'name': 'Fish Only',
        'desc': 'White-dominant for natural daylight appearance and fish colour rendering. '
                '10-hour photoperiod. Target ~100 µmol/m²/s at 300 mm.',
        'schedule': _build([
            ( 0, [ 0,  0,  0, 0, 0, 0]),
            ( 7, [ 0,  1,  3, 0, 0, 0]),   # blue-only dawn glimmer
            ( 8, [ 6,  5,  6, 0, 0, 0]),
            ( 9, [19,  8, 10, 0, 0, 0]),
            (10, [32, 11, 14, 0, 0, 0]),
            (11, [42, 13, 16, 0, 0, 0]),   # peak: ~100 µmol/m²/s at 300 mm
            (17, [42, 13, 16, 0, 0, 0]),
            (18, [26,  8, 10, 0, 0, 0]),
            (19, [ 8,  3,  5, 0, 0, 0]),
            (20, [ 0,  0,  0, 0, 0, 0]),   # night
        ]),
        'manual': [42, 13, 16, 0, 0, 0],
    },

    'lps': {
        'name': 'LPS Reef',
        'desc': 'Royal Blue dominant for zooxanthellae absorption. Restrained White, '
                'Blue for spectrum depth. Actinic pre/post periods. '
                'Target ~120 µmol/m²/s at 300 mm — Hammer, Torch, Brain, Frogspawn.',
        'schedule': _build([
            ( 0, [ 0,  0,  0, 0, 0, 0]),
            ( 7, [ 0,  6,  9, 0, 0, 0]),   # actinic pre-dawn
            ( 8, [ 4, 19, 24, 0, 0, 0]),
            ( 9, [ 7, 36, 39, 0, 0, 0]),
            (10, [10, 46, 46, 0, 0, 0]),
            (11, [13, 56, 52, 0, 0, 0]),   # peak: ~120 µmol/m²/s at 300 mm
            (17, [13, 56, 52, 0, 0, 0]),
            (18, [ 9, 39, 37, 0, 0, 0]),
            (19, [ 4, 19, 21, 0, 0, 0]),
            (20, [ 0,  6,  9, 0, 0, 0]),   # actinic post-dusk
            (21, [ 0,  0,  0, 0, 0, 0]),
        ]),
        'manual': [13, 56, 52, 0, 0, 0],
    },

    'sps': {
        'name': 'SPS Reef',
        'desc': 'Royal Blue at maximum for growth. White elevated for high total PPFD. '
                'Gradual 4-hour ramp to prevent bleaching. '
                'Target ~260 µmol/m²/s at 300 mm — Acropora, Montipora.',
        'schedule': _build([
            ( 0, [ 0,   0,  0, 0, 0, 0]),
            ( 7, [ 6,  17, 23, 0, 0, 0]),   # ramp begins
            ( 8, [17,  47, 56, 0, 0, 0]),
            ( 9, [32,  77, 77, 0, 0, 0]),
            (10, [45,  96, 90, 0, 0, 0]),
            (11, [56, 100,100, 0, 0, 0]),   # peak: ~260 µmol/m²/s at 300 mm
            (17, [56, 100,100, 0, 0, 0]),
            (18, [39,  84, 77, 0, 0, 0]),
            (19, [20,  54, 50, 0, 0, 0]),
            (20, [ 7,  23, 25, 0, 0, 0]),
            (21, [ 0,   6,  9, 0, 0, 0]),
            (22, [ 0,   0,  0, 0, 0, 0]),
        ]),
        'manual': [56, 100, 100, 0, 0, 0],
    },

    'mixed': {
        'name': 'Mixed Reef (LPS + SPS)',
        'desc': 'SPS-level Royal Blue with LPS-appropriate White. '
                'Target ~175 µmol/m²/s at 300 mm.',
        'schedule': _build([
            ( 0, [ 0,  0,  0, 0, 0, 0]),
            ( 7, [ 2,  8, 11, 0, 0, 0]),
            ( 8, [ 6, 26, 35, 0, 0, 0]),
            ( 9, [12, 47, 45, 0, 0, 0]),
            (10, [18, 63, 54, 0, 0, 0]),
            (11, [28, 77, 70, 0, 0, 0]),   # peak: ~175 µmol/m²/s at 300 mm
            (17, [28, 77, 70, 0, 0, 0]),
            (18, [18, 54, 51, 0, 0, 0]),
            (19, [ 7, 28, 30, 0, 0, 0]),
            (20, [ 2,  9, 12, 0, 0, 0]),
            (21, [ 0,  0,  0, 0, 0, 0]),
        ]),
        'manual': [28, 77, 70, 0, 0, 0],
    },
}


# ── K7 Pro presets (6 channels: uv, royal_blue, blue, white, warm_white, red) ─
#
# K7 Pro PPFD not measured — channel ratios follow the same philosophy as Mini:
# Royal Blue is the primary PPFD driver; Blue is spectral/aesthetic;
# White arrives later and leaves earlier than blue (mimics solar arc).
# Red is kept at 0 for coral tanks.

PRO = {

    'fo': {
        'name': 'Fish Only',
        'desc': 'White-dominant for natural fish colour. '
                'Royal Blue for depth and sparkle. Bluer at dawn/dusk.',
        'schedule': _build([
            ( 0, [0,  0,  0,  0,  0, 0]),
            ( 7, [0,  3, 10,  0,  0, 0]),   # blue-only dawn
            ( 8, [2, 10, 20, 16,  8, 0]),
            ( 9, [3, 14, 28, 36, 14, 2]),
            (10, [4, 17, 34, 48, 18, 3]),
            (11, [4, 20, 38, 55, 21, 4]),   # peak
            (17, [4, 20, 38, 55, 21, 4]),
            (18, [3, 12, 26, 30, 11, 2]),
            (19, [1,  6, 13,  6,  4, 0]),
            (20, [0,  3, 10,  0,  0, 0]),   # blue-only dusk
            (21, [0,  0,  0,  0,  0, 0]),
        ]),
        'manual': [4, 20, 38, 55, 21, 4],
    },

    'lps': {
        'name': 'LPS Reef',
        'desc': 'Royal Blue dominant for zooxanthellae absorption. Restrained White. '
                'Actinic pre/post periods — Hammer, Torch, Brain, Frogspawn.',
        'schedule': _build([
            ( 0, [ 0,  0,  0,  0,  0, 0]),
            ( 7, [ 0,  6,  9,  0,  0, 0]),   # actinic only
            ( 8, [ 3, 20, 24,  8,  4, 0]),
            ( 9, [ 6, 34, 39, 16,  8, 0]),
            (10, [10, 46, 46, 22, 10, 0]),
            (11, [13, 56, 52, 27, 12, 0]),   # peak
            (17, [13, 56, 52, 27, 12, 0]),
            (18, [ 9, 39, 37, 14,  7, 0]),
            (19, [ 4, 19, 21,  4,  2, 0]),
            (20, [ 0,  6,  9,  0,  0, 0]),   # actinic only
            (21, [ 0,  0,  0,  0,  0, 0]),
        ]),
        'manual': [13, 56, 52, 27, 12, 0],
    },

    'sps': {
        'name': 'SPS Reef',
        'desc': 'Royal Blue at maximum. White supports high total PPFD. '
                'Gradual ramp to prevent bleaching — Acropora, Montipora.',
        'schedule': _build([
            ( 0, [ 0,   0,  0,  0,  0, 0]),
            ( 7, [ 5,  17, 23,  0,  0, 0]),   # ramp
            ( 8, [14,  47, 56, 11,  5, 0]),
            ( 9, [26,  77, 77, 20,  8, 0]),
            (10, [38,  96, 90, 29, 10, 0]),
            (11, [46, 100,100, 34, 11, 0]),   # peak
            (17, [46, 100,100, 34, 11, 0]),
            (18, [32,  84, 77, 19,  6, 0]),
            (19, [16,  54, 50,  6,  2, 0]),
            (20, [ 5,  23, 25,  0,  0, 0]),
            (21, [ 0,   6,  9,  0,  0, 0]),
            (22, [ 0,   0,  0,  0,  0, 0]),
        ]),
        'manual': [46, 100, 100, 34, 11, 0],
    },

    'mixed': {
        'name': 'Mixed Reef (LPS + SPS)',
        'desc': 'SPS-level Royal Blue with LPS-appropriate White.',
        'schedule': _build([
            ( 0, [ 0,  0,  0,  0,  0, 0]),
            ( 7, [ 2,  8, 11,  0,  0, 0]),
            ( 8, [ 6, 26, 35, 10,  4, 0]),
            ( 9, [12, 47, 45, 17,  8, 0]),
            (10, [18, 63, 54, 22, 10, 0]),
            (11, [24, 77, 70, 27, 12, 0]),   # peak
            (17, [24, 77, 70, 27, 12, 0]),
            (18, [15, 54, 51, 14,  6, 0]),
            (19, [ 6, 28, 30,  4,  2, 0]),
            (20, [ 2,  9, 12,  0,  0, 0]),
            (21, [ 0,  0,  0,  0,  0, 0]),
        ]),
        'manual': [24, 77, 70, 27, 12, 0],
    },
}

ALL = {'k7mini': MINI, 'k7pro': PRO}
