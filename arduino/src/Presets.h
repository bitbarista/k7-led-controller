#pragma once
#include <Arduino.h>
#include "Config.h"

struct Keyframe {
    uint8_t hour;
    uint8_t ch[K7_CHANNELS];
};

struct Preset {
    const char*     id;
    const char*     name;
    const char*     desc;
    uint8_t         manual[K7_CHANNELS];
    const Keyframe* keyframes;
    uint8_t         numKeyframes;
};

// Build a 24-slot schedule by linearly interpolating between keyframes.
// out[slot] = {hour, 0, c0, c1, c2, c3, c4, c5}
void buildSchedule(const Preset& p, uint8_t out[K7_SLOTS][8]);

// ── K7 Mini presets ───────────────────────────────────────────────────────────

static const Keyframe KF_MINI_FO[] = {
    { 0, { 0,  0,  0, 0, 0, 0}},
    { 7, { 0,  0,  0, 0, 0, 0}},
    { 8, { 0,  1,  3, 0, 0, 0}},
    { 9, { 6,  5,  6, 0, 0, 0}},
    {10, {19,  8, 10, 0, 0, 0}},
    {11, {32, 11, 14, 0, 0, 0}},
    {12, {42, 13, 16, 0, 0, 0}},
    {17, {42, 13, 16, 0, 0, 0}},
    {18, {26,  8, 10, 0, 0, 0}},
    {19, { 8,  3,  5, 0, 0, 0}},
    {20, { 0,  0,  0, 0, 0, 0}},
};
static const Keyframe KF_MINI_LPS[] = {
    { 0, { 0,  0,  0, 0, 0, 0}},
    { 7, { 0,  0,  0, 0, 0, 0}},
    { 8, { 0,  5,  8, 0, 0, 0}},
    { 9, { 4, 17, 22, 0, 0, 0}},
    {10, { 6, 33, 36, 0, 0, 0}},
    {11, { 9, 42, 42, 0, 0, 0}},
    {12, {12, 51, 48, 0, 0, 0}},
    {17, {12, 51, 48, 0, 0, 0}},
    {18, { 8, 36, 34, 0, 0, 0}},
    {19, { 4, 17, 19, 0, 0, 0}},
    {20, { 0,  5,  8, 0, 0, 0}},
    {21, { 0,  0,  0, 0, 0, 0}},
};
static const Keyframe KF_MINI_SPS[] = {
    { 0, { 0,   0,  0, 0, 0, 0}},
    { 7, { 0,   0,  0, 0, 0, 0}},
    { 8, { 7,  17, 23, 0, 0, 0}},
    { 9, {21,  47, 56, 0, 0, 0}},
    {10, {39,  77, 77, 0, 0, 0}},
    {11, {55,  96, 90, 0, 0, 0}},
    {12, {69, 100,100, 0, 0, 0}},
    {17, {69, 100,100, 0, 0, 0}},
    {18, {48,  84, 77, 0, 0, 0}},
    {19, {25,  54, 50, 0, 0, 0}},
    {20, { 9,  23, 25, 0, 0, 0}},
    {21, { 0,   6,  9, 0, 0, 0}},
    {22, { 0,   0,  0, 0, 0, 0}},
};
static const Keyframe KF_MINI_MIXED[] = {
    { 0, { 0,  0,  0, 0, 0, 0}},
    { 7, { 0,  0,  0, 0, 0, 0}},
    { 8, { 2,  7, 10, 0, 0, 0}},
    { 9, { 5, 24, 32, 0, 0, 0}},
    {10, {11, 43, 41, 0, 0, 0}},
    {11, {16, 57, 49, 0, 0, 0}},
    {12, {25, 70, 64, 0, 0, 0}},
    {17, {25, 70, 64, 0, 0, 0}},
    {18, {16, 49, 46, 0, 0, 0}},
    {19, { 6, 25, 27, 0, 0, 0}},
    {20, { 2,  8, 11, 0, 0, 0}},
    {21, { 0,  0,  0, 0, 0, 0}},
};
static const Keyframe KF_MINI_SOFTMIX[] = {
    { 0, { 0,  0,  0, 0, 0, 0}},
    { 7, { 0,  0,  0, 0, 0, 0}},
    { 8, { 1,  5,  7, 0, 0, 0}},
    { 9, { 3, 16, 22, 0, 0, 0}},
    {10, { 7, 28, 30, 0, 0, 0}},
    {11, {11, 38, 36, 0, 0, 0}},
    {12, {16, 48, 44, 0, 0, 0}},
    {17, {16, 48, 44, 0, 0, 0}},
    {18, {10, 30, 28, 0, 0, 0}},
    {19, { 4, 14, 16, 0, 0, 0}},
    {20, { 1,  4,  6, 0, 0, 0}},
    {21, { 0,  0,  0, 0, 0, 0}},
};
static const Keyframe KF_MINI_ACCLIMIX[] = {
    { 0, { 0,  0,  0, 0, 0, 0}},
    { 7, { 0,  0,  0, 0, 0, 0}},
    { 8, { 1,  4,  6, 0, 0, 0}},
    { 9, { 3, 12, 18, 0, 0, 0}},
    {10, { 6, 22, 24, 0, 0, 0}},
    {11, { 9, 30, 28, 0, 0, 0}},
    {12, {13, 38, 34, 0, 0, 0}},
    {17, {13, 38, 34, 0, 0, 0}},
    {18, { 8, 24, 22, 0, 0, 0}},
    {19, { 3, 11, 12, 0, 0, 0}},
    {20, { 1,  4,  5, 0, 0, 0}},
    {21, { 0,  0,  0, 0, 0, 0}},
};
static const Keyframe KF_MINI_LOWENERGY[] = {
    { 0, { 0,  0,  0, 0, 0, 0}},
    { 7, { 0,  0,  0, 0, 0, 0}},
    { 8, { 0,  3,  5, 0, 0, 0}},
    { 9, { 2, 10, 14, 0, 0, 0}},
    {10, { 4, 18, 22, 0, 0, 0}},
    {11, { 6, 24, 28, 0, 0, 0}},
    {12, { 8, 30, 32, 0, 0, 0}},
    {17, { 8, 30, 32, 0, 0, 0}},
    {18, { 5, 20, 21, 0, 0, 0}},
    {19, { 2,  9, 10, 0, 0, 0}},
    {20, { 0,  3,  4, 0, 0, 0}},
    {21, { 0,  0,  0, 0, 0, 0}},
};
static const Keyframe KF_MINI_SHALLOWSPS[] = {
    { 0, { 0,   0,  0, 0, 0, 0}},
    { 7, { 0,   0,  0, 0, 0, 0}},
    { 8, { 8,  22, 28, 0, 0, 0}},
    { 9, {26,  58, 66, 0, 0, 0}},
    {10, {46,  88, 92, 0, 0, 0}},
    {11, {62, 100,100, 0, 0, 0}},
    {12, {78, 100,100, 0, 0, 0}},
    {17, {78, 100,100, 0, 0, 0}},
    {18, {54,  88, 82, 0, 0, 0}},
    {19, {28,  58, 54, 0, 0, 0}},
    {20, {10,  26, 28, 0, 0, 0}},
    {21, { 0,   8, 10, 0, 0, 0}},
    {22, { 0,   0,  0, 0, 0, 0}},
};

static const Preset MINI_PRESETS[] = {
    {"fo",    "Fish Only",           "White-dominant for natural daylight appearance and fish colour rendering. 10-hour photoperiod. Target ~100 µmol/m²/s at 300 mm.",
     {42, 13, 16, 0, 0, 0}, KF_MINI_FO,    11},
    {"lps",   "LPS Reef",            "Royal Blue dominant for zooxanthellae absorption. Restrained White, Blue for spectrum depth. Actinic pre/post periods. Target ~120 µmol/m²/s at 300 mm — Hammer, Torch, Brain, Frogspawn.",
     {12, 51, 48, 0, 0, 0}, KF_MINI_LPS,   12},
    {"sps",   "SPS Reef",            "Royal Blue at maximum for growth. White elevated for high total PPFD. Gradual 4-hour ramp to prevent bleaching. Target ~260 µmol/m²/s at 300 mm — Acropora, Montipora.",
     {69,100,100, 0, 0, 0}, KF_MINI_SPS,   13},
    {"mixed", "Mixed Reef (LPS + SPS)", "SPS-level Royal Blue with LPS-appropriate White. Target ~175 µmol/m²/s at 300 mm.",
     {25, 70, 64, 0, 0, 0}, KF_MINI_MIXED, 12},
    {"softmixed", "Soft Mixed Reef", "Balanced mixed-reef schedule with a gentler peak and calmer dusk. Good default if Mixed Reef feels slightly too strong.",
     {16, 48, 44, 0, 0, 0}, KF_MINI_SOFTMIX, 12},
    {"acclimation", "Acclimation Mixed", "Reduced-output mixed-reef schedule for new corals, recent frags, or recovering colonies. Intended as a temporary step-up profile.",
     {13, 38, 34, 0, 0, 0}, KF_MINI_ACCLIMIX, 12},
    {"lowenergy", "LPS Low Energy", "Gentle low-light reef profile with restrained peak intensity and short dusk tail. Suitable for lower-demand LPS and shaded systems.",
     {8, 30, 32, 0, 0, 0}, KF_MINI_LOWENERGY, 12},
    {"shallowsps", "Shallow SPS", "Higher-output SPS profile for shallow tanks or elevated mounting, with strong midday intensity and a controlled evening falloff.",
     {78,100,100, 0, 0, 0}, KF_MINI_SHALLOWSPS, 13},
};

// ── K7 Pro presets ────────────────────────────────────────────────────────────

static const Keyframe KF_PRO_FO[] = {
    { 0, {0,  0,  0,  0,  0, 0}},
    { 7, {0,  0,  0,  0,  0, 0}},
    { 8, {0,  3, 10,  0,  0, 0}},
    { 9, {2, 10, 20, 16,  8, 0}},
    {10, {3, 14, 28, 36, 14, 2}},
    {11, {4, 17, 34, 48, 18, 3}},
    {12, {4, 20, 38, 55, 21, 4}},
    {17, {4, 20, 38, 55, 21, 4}},
    {18, {3, 12, 26, 30, 11, 2}},
    {19, {1,  6, 13,  6,  4, 0}},
    {20, {0,  3, 10,  0,  0, 0}},
    {21, {0,  0,  0,  0,  0, 0}},
};
static const Keyframe KF_PRO_LPS[] = {
    { 0, { 0,  0,  0,  0,  0, 0}},
    { 7, { 0,  0,  0,  0,  0, 0}},
    { 8, { 0,  5,  8,  0,  0, 0}},
    { 9, { 3, 18, 22,  7,  4, 0}},
    {10, { 5, 31, 36, 15,  7, 0}},
    {11, { 9, 42, 42, 20,  9, 0}},
    {12, {12, 51, 48, 25, 11, 0}},
    {17, {12, 51, 48, 25, 11, 0}},
    {18, { 8, 36, 34, 12,  6, 0}},
    {19, { 4, 17, 19,  4,  2, 0}},
    {20, { 0,  5,  8,  0,  0, 0}},
    {21, { 0,  0,  0,  0,  0, 0}},
};
static const Keyframe KF_PRO_SPS[] = {
    { 0, { 0,   0,  0,  0,  0, 0}},
    { 7, { 0,   0,  0,  0,  0, 0}},
    { 8, { 5,  17, 23,  0,  0, 0}},
    { 9, {14,  47, 56, 14,  5, 0}},
    {10, {26,  77, 77, 25,  8, 0}},
    {11, {38,  96, 90, 36, 10, 0}},
    {12, {46, 100,100, 42, 11, 0}},
    {17, {46, 100,100, 42, 11, 0}},
    {18, {32,  84, 77, 23,  6, 0}},
    {19, {16,  54, 50,  7,  2, 0}},
    {20, { 5,  23, 25,  0,  0, 0}},
    {21, { 0,   6,  9,  0,  0, 0}},
    {22, { 0,   0,  0,  0,  0, 0}},
};
static const Keyframe KF_PRO_MIXED[] = {
    { 0, { 0,  0,  0,  0,  0, 0}},
    { 7, { 0,  0,  0,  0,  0, 0}},
    { 8, { 2,  7, 10,  0,  0, 0}},
    { 9, { 5, 24, 32,  9,  4, 0}},
    {10, {11, 43, 41, 15,  7, 0}},
    {11, {16, 57, 49, 20,  9, 0}},
    {12, {22, 70, 64, 25, 11, 0}},
    {17, {22, 70, 64, 25, 11, 0}},
    {18, {14, 49, 46, 12,  5, 0}},
    {19, { 5, 25, 27,  4,  2, 0}},
    {20, { 2,  8, 11,  0,  0, 0}},
    {21, { 0,  0,  0,  0,  0, 0}},
};
static const Keyframe KF_PRO_SOFTMIX[] = {
    { 0, { 0,  0,  0,  0,  0, 0}},
    { 7, { 0,  0,  0,  0,  0, 0}},
    { 8, { 1,  5,  7,  0,  0, 0}},
    { 9, { 3, 16, 22,  6,  3, 0}},
    {10, { 7, 28, 30, 10,  5, 0}},
    {11, {11, 38, 36, 15,  7, 0}},
    {12, {16, 48, 44, 19,  8, 0}},
    {17, {16, 48, 44, 19,  8, 0}},
    {18, {10, 30, 28,  9,  4, 0}},
    {19, { 4, 14, 16,  3,  1, 0}},
    {20, { 1,  4,  6,  0,  0, 0}},
    {21, { 0,  0,  0,  0,  0, 0}},
};
static const Keyframe KF_PRO_ACCLIMIX[] = {
    { 0, { 0,  0,  0,  0,  0, 0}},
    { 7, { 0,  0,  0,  0,  0, 0}},
    { 8, { 1,  4,  6,  0,  0, 0}},
    { 9, { 3, 12, 18,  5,  2, 0}},
    {10, { 6, 22, 24,  9,  4, 0}},
    {11, { 9, 30, 28, 12,  5, 0}},
    {12, {13, 38, 34, 16,  7, 0}},
    {17, {13, 38, 34, 16,  7, 0}},
    {18, { 8, 24, 22,  7,  3, 0}},
    {19, { 3, 11, 12,  2,  1, 0}},
    {20, { 1,  4,  5,  0,  0, 0}},
    {21, { 0,  0,  0,  0,  0, 0}},
};
static const Keyframe KF_PRO_LOWENERGY[] = {
    { 0, { 0,  0,  0,  0,  0, 0}},
    { 7, { 0,  0,  0,  0,  0, 0}},
    { 8, { 0,  3,  5,  0,  0, 0}},
    { 9, { 2, 10, 14,  4,  2, 0}},
    {10, { 4, 18, 22,  7,  3, 0}},
    {11, { 6, 24, 28,  9,  4, 0}},
    {12, { 8, 30, 32, 12,  5, 0}},
    {17, { 8, 30, 32, 12,  5, 0}},
    {18, { 5, 20, 21,  5,  2, 0}},
    {19, { 2,  9, 10,  2,  1, 0}},
    {20, { 0,  3,  4,  0,  0, 0}},
    {21, { 0,  0,  0,  0,  0, 0}},
};
static const Keyframe KF_PRO_SHALLOWSPS[] = {
    { 0, { 0,   0,  0,  0,  0, 0}},
    { 7, { 0,   0,  0,  0,  0, 0}},
    { 8, { 6,  22, 28,  4,  2, 0}},
    { 9, {18,  58, 66, 18,  6, 0}},
    {10, {30,  88, 92, 34, 10, 0}},
    {11, {40, 100,100, 44, 12, 0}},
    {12, {48, 100,100, 52, 14, 0}},
    {17, {48, 100,100, 52, 14, 0}},
    {18, {34,  88, 82, 28,  8, 0}},
    {19, {18,  58, 54, 10,  3, 0}},
    {20, { 6,  26, 28,  0,  0, 0}},
    {21, { 0,   8, 10,  0,  0, 0}},
    {22, { 0,   0,  0,  0,  0, 0}},
};

static const Preset PRO_PRESETS[] = {
    {"fo",    "Fish Only",           "White-dominant for natural fish colour. Royal Blue for depth and sparkle. Bluer at dawn/dusk.",
     {4, 20, 38, 55, 21, 4}, KF_PRO_FO,    12},
    {"lps",   "LPS Reef",            "Royal Blue dominant for zooxanthellae absorption. Restrained White. Actinic pre/post periods — Hammer, Torch, Brain, Frogspawn.",
     {12, 51, 48, 25, 11, 0}, KF_PRO_LPS,  12},
    {"sps",   "SPS Reef",            "Royal Blue at maximum. White supports high total PPFD. Gradual ramp to prevent bleaching — Acropora, Montipora.",
     {46,100,100, 42, 11, 0}, KF_PRO_SPS,  13},
    {"mixed", "Mixed Reef (LPS + SPS)", "SPS-level Royal Blue with LPS-appropriate White.",
     {22, 70, 64, 25, 11, 0}, KF_PRO_MIXED, 12},
    {"softmixed", "Soft Mixed Reef", "Balanced mixed-reef schedule with a gentler peak and calmer dusk. Good default if Mixed Reef feels slightly too strong.",
     {16, 48, 44, 19, 8, 0}, KF_PRO_SOFTMIX, 12},
    {"acclimation", "Acclimation Mixed", "Reduced-output mixed-reef schedule for new corals, recent frags, or recovering colonies. Intended as a temporary step-up profile.",
     {13, 38, 34, 16, 7, 0}, KF_PRO_ACCLIMIX, 12},
    {"lowenergy", "LPS Low Energy", "Gentle low-light reef profile with restrained peak intensity and short dusk tail. Suitable for lower-demand LPS and shaded systems.",
     {8, 30, 32, 12, 5, 0}, KF_PRO_LOWENERGY, 12},
    {"shallowsps", "Shallow SPS", "Higher-output SPS profile for shallow tanks or elevated mounting, with strong midday intensity and a controlled evening falloff.",
     {48,100,100, 52,14, 0}, KF_PRO_SHALLOWSPS, 13},
};

static constexpr uint8_t NUM_MINI_PRESETS = 8;
static constexpr uint8_t NUM_PRO_PRESETS  = 8;

// ── buildSchedule implementation ──────────────────────────────────────────────
inline void buildSchedule(const Preset& p, uint8_t out[K7_SLOTS][8]) {
    for (int h = 0; h < K7_SLOTS; h++) {
        // Find surrounding keyframes
        const Keyframe* lo = &p.keyframes[0];
        const Keyframe* hi = &p.keyframes[p.numKeyframes - 1];
        for (int k = 0; k < (int)p.numKeyframes - 1; k++) {
            if (p.keyframes[k].hour <= h && h <= p.keyframes[k+1].hour) {
                lo = &p.keyframes[k];
                hi = &p.keyframes[k+1];
                break;
            }
        }
        out[h][0] = (uint8_t)h;
        out[h][1] = 0;
        if (lo->hour == hi->hour || h <= (int)lo->hour) {
            memcpy(out[h] + 2, lo->ch, K7_CHANNELS);
        } else if (h >= (int)hi->hour) {
            memcpy(out[h] + 2, hi->ch, K7_CHANNELS);
        } else {
            float t = (float)(h - lo->hour) / (float)(hi->hour - lo->hour);
            for (int c = 0; c < K7_CHANNELS; c++) {
                float v = lo->ch[c] + t * ((int)hi->ch[c] - (int)lo->ch[c]);
                int   iv = (int)roundf(v);
                out[h][2 + c] = (uint8_t)(iv < 0 ? 0 : (iv > 100 ? 100 : iv));
            }
        }
    }
}
