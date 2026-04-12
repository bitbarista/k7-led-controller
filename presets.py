"""
Marine aquarium lighting presets for Noo-Psyche K7 LED lamps.

Channel order:
  K7 Mini: [white, royal_blue, blue, -, -, -]
  K7 Pro:  [uv, royal_blue, blue, white, warm_white, red]

K7 Mini uses channels 0-2 only (white, royal_blue, blue).
K7 Pro  uses all 6 channels.

Schedule format: list of 24 entries, each [hour, minute, c0..c5].

Lighting philosophy per tank type
──────────────────────────────────
Fish Only (FO)
  • Moderate intensity — fish don't need high PAR
  • Bluer spectrum for natural seawater appearance
  • White channels prominent for fish colour rendering
  • 10-hour photoperiod with gentle ramp

LPS (Large Polyp Stony — Hammer, Torch, Brain, Frogspawn)
  • Low-moderate PAR (50-150 µmol)
  • Blue-dominant spectrum (440-480 nm is primary zooxanthellae absorption)
  • UV adds fluorescence and assists growth; keep ≤ 20%
  • Actinic-only pre-dawn and post-dusk periods
  • 10-hour photoperiod

SPS (Small Polyp Stony — Acropora, Montipora, Pocillopora)
  • High PAR (150-350+ µmol)
  • Strong UV (20-35%) and Royal Blue essential for Acropora growth
  • Gradual ramp critical — abrupt intensity increase bleaches
  • 10-hour photoperiod, longer than LPS is safe

Mixed Reef (LPS + SPS coexisting)
  • Compromise: SPS-level blues, LPS-appropriate whites
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
        # find surrounding keyframes
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

MINI = {

    'fo': {
        'name': 'Fish Only',
        'desc': 'Moderate blue with white accent for fish colour rendering. '
                '10-hour photoperiod, 45% blue peak.',
        'schedule': _build([
            ( 0, [0,  0,  0, 0, 0, 0]),
            ( 7, [0,  5, 10, 0, 0, 0]),   # gentle dawn glimmer
            ( 8, [2, 25, 35, 0, 0, 0]),
            ( 9, [4, 38, 48, 0, 0, 0]),
            (10, [5, 44, 55, 0, 0, 0]),   # peak
            (17, [5, 44, 55, 0, 0, 0]),
            (18, [3, 30, 40, 0, 0, 0]),
            (19, [1, 12, 18, 0, 0, 0]),
            (20, [0,  0,  0, 0, 0, 0]),   # night
        ]),
        'manual': [5, 44, 55, 0, 0, 0],
    },

    'lps': {
        'name': 'LPS Reef',
        'desc': 'Low-moderate PAR, blue-dominant with restrained white. Actinic pre/post periods. '
                '70% blue peak — suitable for Hammer, Torch, Brain, Frogspawn.',
        'schedule': _build([
            ( 0, [ 0,  0,  0, 0, 0, 0]),
            ( 7, [ 0,  8, 12, 0, 0, 0]),  # actinic pre-dawn (no UV yet)
            ( 8, [ 5, 25, 35, 0, 0, 0]),
            ( 9, [10, 42, 55, 0, 0, 0]),
            (10, [15, 55, 65, 0, 0, 0]),
            (11, [18, 60, 70, 0, 0, 0]),  # peak
            (17, [18, 60, 70, 0, 0, 0]),
            (18, [12, 44, 55, 0, 0, 0]),
            (19, [ 5, 24, 32, 0, 0, 0]),
            (20, [ 0,  8, 12, 0, 0, 0]),  # actinic post-dusk
            (21, [ 0,  0,  0, 0, 0, 0]),
        ]),
        'manual': [18, 60, 70, 0, 0, 0],
    },

    'sps': {
        'name': 'SPS Reef',
        'desc': 'High PAR with strong Royal Blue. Gradual 3-hour ramp '
                'to protect from bleaching. 90% blue peak — suits Acropora, Montipora.',
        'schedule': _build([
            ( 0, [ 0,  0,  0, 0, 0, 0]),
            ( 7, [ 5, 15, 20, 0, 0, 0]),  # ramp begins with UV
            ( 8, [12, 40, 52, 0, 0, 0]),
            ( 9, [22, 65, 76, 0, 0, 0]),
            (10, [28, 80, 88, 0, 0, 0]),
            (11, [32, 87, 92, 0, 0, 0]),  # peak
            (17, [32, 87, 92, 0, 0, 0]),
            (18, [22, 68, 78, 0, 0, 0]),
            (19, [12, 42, 52, 0, 0, 0]),
            (20, [ 5, 18, 22, 0, 0, 0]),
            (21, [ 0,  5,  8, 0, 0, 0]),
            (22, [ 0,  0,  0, 0, 0, 0]),
        ]),
        'manual': [32, 87, 92, 0, 0, 0],
    },

    'mixed': {
        'name': 'Mixed Reef (LPS + SPS)',
        'desc': 'Balanced for tanks housing both coral types. '
                '80% blue peak with moderate UV.',
        'schedule': _build([
            ( 0, [ 0,  0,  0, 0, 0, 0]),
            ( 7, [ 3, 10, 15, 0, 0, 0]),
            ( 8, [ 8, 30, 42, 0, 0, 0]),
            ( 9, [15, 52, 62, 0, 0, 0]),
            (10, [20, 65, 74, 0, 0, 0]),
            (11, [24, 72, 80, 0, 0, 0]),  # peak
            (17, [24, 72, 80, 0, 0, 0]),
            (18, [16, 55, 64, 0, 0, 0]),
            (19, [ 8, 30, 40, 0, 0, 0]),
            (20, [ 2, 10, 15, 0, 0, 0]),
            (21, [ 0,  0,  0, 0, 0, 0]),
        ]),
        'manual': [24, 72, 80, 0, 0, 0],
    },
}


# ── K7 Pro presets (6 channels: uv, royal_blue, blue, white, warm_white, red) ─
#
# White arrives later and leaves earlier than blue (mimics solar arc).
# Warm white peaks slightly after white — morning warmth is cooler, afternoon warmer.
# Red is kept at 0 for coral tanks (can irritate SPS; aids macroalgae, not corals).

PRO = {

    'fo': {
        'name': 'Fish Only',
        'desc': 'White-dominant for natural fish colour. '
                '68% white peak, bluer at dawn/dusk.',
        'schedule': _build([
            ( 0, [0,  0,  0,  0,  0, 0]),
            ( 7, [0,  5, 10,  0,  0, 0]),   # blue-only dawn
            ( 8, [2, 22, 30, 15,  8, 0]),
            ( 9, [3, 32, 42, 42, 15, 2]),
            (10, [4, 38, 48, 62, 22, 4]),
            (11, [5, 42, 52, 68, 25, 5]),   # peak
            (17, [5, 42, 52, 68, 25, 5]),
            (18, [3, 28, 38, 35, 14, 2]),
            (19, [1, 12, 18,  8,  4, 0]),
            (20, [0,  5, 10,  0,  0, 0]),   # blue-only dusk
            (21, [0,  0,  0,  0,  0, 0]),
        ]),
        'manual': [5, 42, 52, 68, 25, 5],
    },

    'lps': {
        'name': 'LPS Reef',
        'desc': 'Blue-dominant with restrained white. Actinic pre/post periods. '
                'Peak: 70% blue, 35% white — Hammer, Torch, Brain, Frogspawn.',
        'schedule': _build([
            ( 0, [ 0,  0,  0,  0,  0, 0]),
            ( 7, [ 0,  8, 12,  0,  0, 0]),  # actinic only
            ( 8, [ 5, 24, 32, 10,  5, 0]),
            ( 9, [10, 40, 52, 22, 10, 0]),
            (10, [15, 52, 62, 30, 14, 0]),
            (11, [18, 58, 68, 35, 18, 0]),  # peak
            (17, [18, 58, 68, 35, 18, 0]),
            (18, [12, 42, 52, 18,  9, 0]),
            (19, [ 5, 22, 32,  5,  2, 0]),
            (20, [ 0,  8, 12,  0,  0, 0]),  # actinic only
            (21, [ 0,  0,  0,  0,  0, 0]),
        ]),
        'manual': [18, 58, 68, 35, 18, 0],
    },

    'sps': {
        'name': 'SPS Reef',
        'desc': 'High-intensity blue/UV. White supports PAR without washing out '
                'coral colour. Peak: 90% blue, 38% white — Acropora, Montipora.',
        'schedule': _build([
            ( 0, [ 0,  0,  0,  0,  0, 0]),
            ( 7, [ 5, 15, 20,  0,  0, 0]),  # UV-blue ramp
            ( 8, [12, 38, 48, 15,  6, 0]),
            ( 9, [20, 62, 72, 28, 10, 0]),
            (10, [28, 78, 85, 35, 12, 0]),
            (11, [32, 85, 90, 38, 14, 0]),  # peak
            (17, [32, 85, 90, 38, 14, 0]),
            (18, [22, 65, 74, 20,  8, 0]),
            (19, [12, 38, 48,  8,  3, 0]),
            (20, [ 5, 15, 20,  0,  0, 0]),
            (21, [ 0,  5,  8,  0,  0, 0]),
            (22, [ 0,  0,  0,  0,  0, 0]),
        ]),
        'manual': [32, 85, 90, 38, 14, 0],
    },

    'mixed': {
        'name': 'Mixed Reef (LPS + SPS)',
        'desc': 'SPS-level blues with LPS-appropriate whites. '
                'Peak: 78% blue, 34% white.',
        'schedule': _build([
            ( 0, [ 0,  0,  0,  0,  0, 0]),
            ( 7, [ 3, 10, 14,  0,  0, 0]),
            ( 8, [ 8, 28, 38, 12,  5, 0]),
            ( 9, [15, 48, 58, 24, 10, 0]),
            (10, [20, 62, 70, 30, 13, 0]),
            (11, [24, 68, 76, 34, 16, 0]),  # peak
            (17, [24, 68, 76, 34, 16, 0]),
            (18, [16, 52, 62, 18,  8, 0]),
            (19, [ 8, 28, 38,  5,  2, 0]),
            (20, [ 2, 10, 14,  0,  0, 0]),
            (21, [ 0,  0,  0,  0,  0, 0]),
        ]),
        'manual': [24, 68, 76, 34, 16, 0],
    },
}

ALL = {'k7mini': MINI, 'k7pro': PRO}
