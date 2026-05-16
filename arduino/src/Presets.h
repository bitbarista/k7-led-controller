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
    bool            disableLunar;
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
static const Keyframe KF_MINI_DINO[] = {
    { 0, {0,  0,  0, 0, 0, 0}},
    {10, {0,  0,  0, 0, 0, 0}},
    {11, {1,  8,  8, 0, 0, 0}},
    {12, {2, 16, 14, 0, 0, 0}},
    {15, {2, 16, 14, 0, 0, 0}},
    {16, {1,  8,  8, 0, 0, 0}},
    {17, {0,  0,  0, 0, 0, 0}},
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
    { 0, {  0,   0,   0,   0,   0,   0}},
    { 7, {  0,   0,   0,   0,   0,   0}},
    { 8, {  0,   3,   0,   0,  10,   0}},
    { 9, { 16,  10,   8,   2,  20,   0}},
    {10, { 36,  14,  14,   3,  28,   2}},
    {11, { 48,  17,  18,   4,  34,   3}},
    {12, { 55,  20,  21,   4,  38,   4}},
    {17, { 55,  20,  21,   4,  38,   4}},
    {18, { 30,  12,  11,   3,  26,   2}},
    {19, {  6,   6,   4,   1,  13,   0}},
    {20, {  0,   3,   0,   0,  10,   0}},
    {21, {  0,   0,   0,   0,   0,   0}},
};
static const Keyframe KF_PRO_LPS[] = {
    { 0, {  0,   0,   0,   0,   0,   0}},
    { 7, {  0,   0,   0,   0,   0,   0}},
    { 8, {  0,   5,   0,   0,   8,   0}},
    { 9, {  7,  18,   4,   3,  22,   0}},
    {10, { 15,  31,   7,   5,  36,   0}},
    {11, { 20,  42,   9,   9,  42,   0}},
    {12, { 25,  51,  11,  12,  48,   0}},
    {17, { 25,  51,  11,  12,  48,   0}},
    {18, { 12,  36,   6,   8,  34,   0}},
    {19, {  4,  17,   2,   4,  19,   0}},
    {20, {  0,   5,   0,   0,   8,   0}},
    {21, {  0,   0,   0,   0,   0,   0}},
};
static const Keyframe KF_PRO_SPS[] = {
    { 0, {  0,   0,   0,   0,   0,   0}},
    { 7, {  0,   0,   0,   0,   0,   0}},
    { 8, {  0,  17,   0,   5,  23,   0}},
    { 9, { 14,  47,   5,  14,  56,   0}},
    {10, { 25,  77,   8,  26,  77,   0}},
    {11, { 36,  96,  10,  38,  90,   0}},
    {12, { 42, 100,  11,  46, 100,   0}},
    {17, { 42, 100,  11,  46, 100,   0}},
    {18, { 23,  84,   6,  32,  77,   0}},
    {19, {  7,  54,   2,  16,  50,   0}},
    {20, {  0,  23,   0,   5,  25,   0}},
    {21, {  0,   6,   0,   0,   9,   0}},
    {22, {  0,   0,   0,   0,   0,   0}},
};
static const Keyframe KF_PRO_MIXED[] = {
    { 0, {  0,   0,   0,   0,   0,   0}},
    { 7, {  0,   0,   0,   0,   0,   0}},
    { 8, {  0,   7,   0,   2,  10,   0}},
    { 9, {  9,  24,   4,   5,  32,   0}},
    {10, { 15,  43,   7,  11,  41,   0}},
    {11, { 20,  57,   9,  16,  49,   0}},
    {12, { 25,  70,  11,  22,  64,   0}},
    {17, { 25,  70,  11,  22,  64,   0}},
    {18, { 12,  49,   5,  14,  46,   0}},
    {19, {  4,  25,   2,   5,  27,   0}},
    {20, {  0,   8,   0,   2,  11,   0}},
    {21, {  0,   0,   0,   0,   0,   0}},
};
static const Keyframe KF_PRO_SOFTMIX[] = {
    { 0, {  0,   0,   0,   0,   0,   0}},
    { 7, {  0,   0,   0,   0,   0,   0}},
    { 8, {  0,   5,   0,   1,   7,   0}},
    { 9, {  6,  16,   3,   3,  22,   0}},
    {10, { 10,  28,   5,   7,  30,   0}},
    {11, { 15,  38,   7,  11,  36,   0}},
    {12, { 19,  48,   8,  16,  44,   0}},
    {17, { 19,  48,   8,  16,  44,   0}},
    {18, {  9,  30,   4,  10,  28,   0}},
    {19, {  3,  14,   1,   4,  16,   0}},
    {20, {  0,   4,   0,   1,   6,   0}},
    {21, {  0,   0,   0,   0,   0,   0}},
};
static const Keyframe KF_PRO_ACCLIMIX[] = {
    { 0, {  0,   0,   0,   0,   0,   0}},
    { 7, {  0,   0,   0,   0,   0,   0}},
    { 8, {  0,   4,   0,   1,   6,   0}},
    { 9, {  5,  12,   2,   3,  18,   0}},
    {10, {  9,  22,   4,   6,  24,   0}},
    {11, { 12,  30,   5,   9,  28,   0}},
    {12, { 16,  38,   7,  13,  34,   0}},
    {17, { 16,  38,   7,  13,  34,   0}},
    {18, {  7,  24,   3,   8,  22,   0}},
    {19, {  2,  11,   1,   3,  12,   0}},
    {20, {  0,   4,   0,   1,   5,   0}},
    {21, {  0,   0,   0,   0,   0,   0}},
};
static const Keyframe KF_PRO_LOWENERGY[] = {
    { 0, {  0,   0,   0,   0,   0,   0}},
    { 7, {  0,   0,   0,   0,   0,   0}},
    { 8, {  0,   3,   0,   0,   5,   0}},
    { 9, {  4,  10,   2,   2,  14,   0}},
    {10, {  7,  18,   3,   4,  22,   0}},
    {11, {  9,  24,   4,   6,  28,   0}},
    {12, { 12,  30,   5,   8,  32,   0}},
    {17, { 12,  30,   5,   8,  32,   0}},
    {18, {  5,  20,   2,   5,  21,   0}},
    {19, {  2,   9,   1,   2,  10,   0}},
    {20, {  0,   3,   0,   0,   4,   0}},
    {21, {  0,   0,   0,   0,   0,   0}},
};
static const Keyframe KF_PRO_SHALLOWSPS[] = {
    { 0, {  0,   0,   0,   0,   0,   0}},
    { 7, {  0,   0,   0,   0,   0,   0}},
    { 8, {  4,  22,   2,   6,  28,   0}},
    { 9, { 18,  58,   6,  18,  66,   0}},
    {10, { 34,  88,  10,  30,  92,   0}},
    {11, { 44, 100,  12,  40, 100,   0}},
    {12, { 52, 100,  14,  48, 100,   0}},
    {17, { 52, 100,  14,  48, 100,   0}},
    {18, { 28,  88,   8,  34,  82,   0}},
    {19, { 10,  58,   3,  18,  54,   0}},
    {20, {  0,  26,   0,   6,  28,   0}},
    {21, {  0,   8,   0,   0,  10,   0}},
    {22, {  0,   0,   0,   0,   0,   0}},
};
static const Keyframe KF_PRO_REFUGIUM[] = {
    { 0, { 18,   0,  45,   0,   0,  40}},
    { 7, { 18,   0,  45,   0,   0,  40}},
    { 8, {  6,   0,  16,   0,   0,  14}},
    { 9, {  0,   0,   0,   0,   0,   0}},
    {19, {  0,   0,   0,   0,   0,   0}},
    {20, {  6,   0,  16,   0,   0,  14}},
    {21, { 18,   0,  45,   0,   0,  40}},
    {23, { 18,   0,  45,   0,   0,  40}},
};

static const Preset PRO_PRESETS[] = {
    {"fo",    "Fish Only",           "White-dominant for natural fish colour. Royal Blue for depth and sparkle. Bluer at dawn/dusk.",
     { 55,  20,  21,   4,  38,   4}, KF_PRO_FO,    12},
    {"lps",   "LPS Reef",            "Royal Blue dominant for zooxanthellae absorption. Restrained White. Actinic pre/post periods — Hammer, Torch, Brain, Frogspawn.",
     { 25,  51,  11,  12,  48,   0}, KF_PRO_LPS,  12},
    {"sps",   "SPS Reef",            "Royal Blue at maximum. White supports high total PPFD. Gradual ramp to prevent bleaching — Acropora, Montipora.",
     { 42, 100,  11,  46, 100,   0}, KF_PRO_SPS,  13},
    {"mixed", "Mixed Reef (LPS + SPS)", "SPS-level Royal Blue with LPS-appropriate White.",
     { 25,  70,  11,  22,  64,   0}, KF_PRO_MIXED, 12},
    {"softmixed", "Soft Mixed Reef", "Balanced mixed-reef schedule with a gentler peak and calmer dusk. Good default if Mixed Reef feels slightly too strong.",
     { 19,  48,   8,  16,  44,   0}, KF_PRO_SOFTMIX, 12},
    {"acclimation", "Acclimation Mixed", "Reduced-output mixed-reef schedule for new corals, recent frags, or recovering colonies. Intended as a temporary step-up profile.",
     { 16,  38,   7,  13,  34,   0}, KF_PRO_ACCLIMIX, 12},
    {"lowenergy", "LPS Low Energy", "Gentle low-light reef profile with restrained peak intensity and short dusk tail. Suitable for lower-demand LPS and shaded systems.",
     { 12,  30,   5,   8,  32,   0}, KF_PRO_LOWENERGY, 12},
    {"shallowsps", "Shallow SPS", "Higher-output SPS profile for shallow tanks or elevated mounting, with strong midday intensity and a controlled evening falloff.",
     { 52, 100,  14,  48, 100,   0}, KF_PRO_SHALLOWSPS, 13},
    {"refugium", "Refugium", "Reverse-photoperiod schedule for macroalgae sumps. High green and red for Chaeto/Gracilaria growth; no blue or UV. Runs overnight (9 pm – 8 am) opposite to the display tank photoperiod. Disables Lunar effect.",
     { 18,   0,  45,   0,   0,  40}, KF_PRO_REFUGIUM, 8, true},
};

static constexpr uint8_t NUM_MINI_PRESETS = 8;
static constexpr uint8_t NUM_PRO_PRESETS  = 9;

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
