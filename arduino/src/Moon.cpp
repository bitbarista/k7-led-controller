#include "Moon.h"
#include <math.h>
#include <time.h>

static constexpr double SYNODIC  = 29.530588853;
static constexpr time_t REF_NEW  = 947182440;   // 2000-01-06 18:14 UTC (known new moon)

float Moon::phase() {
    double days = (double)(time(nullptr) - REF_NEW) / 86400.0;
    double cycle = fmod(days, SYNODIC);
    if (cycle < 0.0) cycle += SYNODIC;
    return (float)(cycle / SYNODIC);
}

float Moon::illumination() {
    return (float)((1.0 - cos((double)phase() * 2.0 * M_PI)) / 2.0);
}

const char* Moon::phaseName() {
    float p = phase();
    if (p < 0.0625f || p >= 0.9375f) return "New Moon";
    if (p < 0.1875f)                  return "Waxing Crescent";
    if (p < 0.3125f)                  return "First Quarter";
    if (p < 0.4375f)                  return "Waxing Gibbous";
    if (p < 0.5625f)                  return "Full Moon";
    if (p < 0.6875f)                  return "Waning Gibbous";
    if (p < 0.8125f)                  return "Last Quarter";
    return "Waning Crescent";
}
