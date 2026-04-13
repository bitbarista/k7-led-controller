"""
Lunar phase calculator for K7 LED Controller.

phase()        — fractional position in synodic cycle (0.0 = new moon,
                 0.25 = first quarter, 0.5 = full moon, 0.75 = last quarter)
illumination() — fraction of visible disc that is lit (0.0–1.0, smooth cosine)
phase_name()   — human-readable phase name string
"""

import math
import time

SYNODIC  = 29.530588853    # mean synodic month, days
_REF_NEW = 947182440       # known new moon: 2000-01-06 18:14 UTC (Unix epoch)


def phase():
    """Fractional phase 0.0–1.0  (0 = new moon, 0.5 = full moon)."""
    return ((time.time() - _REF_NEW) / 86400.0 % SYNODIC) / SYNODIC


def illumination():
    """Illuminated fraction 0.0 (new) → 1.0 (full) → 0.0 (new), smooth cosine."""
    return (1.0 - math.cos(phase() * 2.0 * math.pi)) / 2.0


def phase_name():
    p = phase()
    if p < 0.0625 or p >= 0.9375: return 'New Moon'
    if p < 0.1875:                 return 'Waxing Crescent'
    if p < 0.3125:                 return 'First Quarter'
    if p < 0.4375:                 return 'Waxing Gibbous'
    if p < 0.5625:                 return 'Full Moon'
    if p < 0.6875:                 return 'Waning Gibbous'
    if p < 0.8125:                 return 'Last Quarter'
    return 'Waning Crescent'
