#pragma once
#include <Arduino.h>
#include <atomic>
#include "Config.h"
#include "K7Lamp.h"

// ── Shared effect state (read/write from ApiServer & Effects) ─────────────────

extern SemaphoreHandle_t gLampMutex;          // exclusive lamp TCP access
extern char              gLampHost[32];
extern char              gDevice[16];          // "k7mini" or "k7pro"

extern int               gMasterBrightness;   // 0-200
extern uint8_t           gLastSchedule[K7_SLOTS][8];
extern uint8_t           gLastManual[K7_CHANNELS];
extern char              gLampName[12];        // cached from boot read
extern bool              gLampAutoMode;        // cached, updated on push
extern char              gActivePreset[64];    // e.g. "preset:mixed" or "profile:My Tank"

// ── Effect active flags ───────────────────────────────────────────────────────
// std::atomic<bool> ensures writes on core 1 (loop/web) are immediately
// visible to tasks pinned to core 0 (lamp/effect tasks).  The Xtensa
// architecture requires explicit memory barriers that volatile cannot provide.
extern std::atomic<bool> gRampActive;
extern std::atomic<bool> gLightningActive;
extern std::atomic<bool> gLunarActive;
extern std::atomic<bool> gCloudActive;

// lightning: separate "user intent" vs scheduled
extern std::atomic<bool> gLightningUserEnabled;
extern std::atomic<bool> gLightningUserStopped;
extern std::atomic<bool> gLunarStopped;

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
// Must only be called from FreeRTOS tasks, NOT from HTTP handlers.
bool withLamp(const std::function<void(K7Lamp&)>& fn);

// ── Async lamp worker ─────────────────────────────────────────────────────────
// All lamp TCP is handled by a background task so HTTP handlers never block.

// Queue a full schedule push (non-blocking, latest wins).
struct PushJob {
    uint8_t manual[K7_CHANNELS];
    uint8_t sched[K7_SLOTS][8];
    bool    autoMode;
};
void queuePush(const uint8_t manual[K7_CHANNELS],
               const uint8_t sched[K7_SLOTS][8],
               bool autoMode);

// Queue a manual-preview update (non-blocking, latest wins).
void queuePreview(const uint8_t ch[K7_CHANNELS]);

// Start the combined lamp worker task (call once at startup).
void startLampWorker();

// ── Persistence ───────────────────────────────────────────────────────────────
void loadEffectConfigs();
void saveLightningSchedule();
void saveLunarConfig();
void saveCloudSettings();
void saveEffectState();
void loadEffectState();

// ── Effect control ────────────────────────────────────────────────────────────
// All start/stop functions are non-blocking — they set flags only.
// Mode switching (manual/auto) is managed by each effect task internally.
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
