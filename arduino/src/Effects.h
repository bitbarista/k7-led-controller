#pragma once
#include <Arduino.h>
#include "Config.h"
#include "K7Lamp.h"

// ── Shared effect state (read/write from ApiServer & Effects) ─────────────────

extern SemaphoreHandle_t gLampMutex;          // exclusive lamp TCP access
extern char              gLampHost[32];
extern char              gDevice[16];          // "k7mini" or "k7pro"

extern int               gMasterBrightness;   // 0-200
extern uint8_t           gLastSchedule[K7_SLOTS][8];
extern uint8_t           gLastManual[K7_CHANNELS];

// ── Effect active flags ───────────────────────────────────────────────────────
extern volatile bool gRampActive;
extern volatile bool gLightningActive;
extern volatile bool gLunarActive;
extern volatile bool gCloudActive;

// lightning: separate "user intent" vs scheduled
extern volatile bool gLightningUserEnabled;
extern volatile bool gLightningUserStopped;
extern volatile bool gLunarStopped;

// ── Schedule config (persisted in JSON files) ─────────────────────────────────
struct LightningSchedule {
    bool    enabled = false;
    char    start[8] = "20:00";
    char    end[8]   = "23:00";
};
struct LunarConfig {
    bool    enabled      = false;
    char    start[8]     = "21:00";
    char    end[8]       = "06:00";
    int     maxIntensity = 15;
};
struct CloudSettings {
    int     density     = 30;
    int     depth       = 60;
    bool    colourShift = true;
};

extern LightningSchedule gLightningSchedule;
extern LunarConfig       gLunarConfig;
extern CloudSettings     gCloudSettings;

// ── Helpers (used by both effects and ApiServer) ──────────────────────────────
void interpolateChannels(const uint8_t sched[K7_SLOTS][8], int h, int m,
                         uint8_t out[K7_CHANNELS]);

// Parse "HH:MM" → minutes since midnight, returns -1 on error
int  parseHHMM(const char* s);
bool inTimeWindow(const char* start, const char* end);

void applyLunarOverlay(uint8_t ch[K7_CHANNELS]);
void applyMasterBrightness(uint8_t ch[K7_CHANNELS]);

// Make one K7 TCP connection, run fn(lamp), close.
// Returns false if lamp not reachable.
bool withLamp(const std::function<void(K7Lamp&)>& fn);

// ── Persistence ───────────────────────────────────────────────────────────────
void loadEffectConfigs();
void saveLightningSchedule();
void saveLunarConfig();
void saveCloudSettings();
void saveEffectState();
void loadEffectState();

// ── Effect control ────────────────────────────────────────────────────────────
void startRamp();
void stopRamp();

void startLightning();
void stopLightning();

void startLunar();
void stopLunar();
void lunarApplyNow();
void lunarRestoreNow();

void startCloud();
void stopCloud();

// ── Background scheduler tasks (call once at startup) ─────────────────────────
void startEffectSchedulers();
