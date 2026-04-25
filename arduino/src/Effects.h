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
extern int               gScheduleShiftMinutes; // whole-schedule UI shift, minutes
extern uint8_t           gBaseSchedule[K7_SLOTS][8];
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
extern std::atomic<bool> gLunarActive;
extern std::atomic<bool> gFeedActive;
extern std::atomic<bool> gMaintenanceActive;

extern std::atomic<bool> gLunarStopped;

extern int gFeedDuration;   // minutes, 1-60
extern int gFeedIntensity;  // white channel %, 1-100
extern int gMaintenanceDuration;   // minutes, 1-180
extern int gMaintenanceIntensity;  // overall profile %, 1-100

extern time_t gRampLastTick;  // unix time of last ramp fire, 0 if never

int feedSecondsRemaining();
int maintenanceSecondsRemaining();

struct OutputStatus {
    uint8_t target[K7_CHANNELS] = {};
    uint8_t sent[K7_CHANNELS] = {};
    uint32_t targetMs = 0;
    uint32_t sentMs = 0;
    bool lastWriteOk = false;
    char source[16] = "unknown";
};

// ── Schedule config (persisted in JSON files) ─────────────────────────────────
struct LunarConfig {
    bool    enabled      = false;
    char    start[8]     = "18:30";
    char    end[8]       = "06:30";
    char    clampStart[8] = "18:00";
    char    clampEnd[8]   = "08:00";
    int     maxIntensity = 15;
    int     dayThreshold = 2;
    bool    trackMoonrise = false;
};

extern LunarConfig gLunarConfig;

struct SiestaConfig {
    bool enabled       = false;
    char start[8]      = "13:00";
    int  durationMins  = 90;
    int  intensity     = 25;  // percentage reduction
};

extern SiestaConfig gSiestaConfig;

struct AcclimationConfig {
    bool      enabled       = false;
    int       startPercent  = 70;
    int       durationDays  = 21;
    uint32_t  startEpoch    = 0;
};

extern AcclimationConfig gAcclimationConfig;

struct SeasonalConfig {
    bool enabled         = false;
    int  maxShiftMinutes = 60;
};

extern SeasonalConfig gSeasonalConfig;

// ── Helpers (used by both effects and ApiServer) ──────────────────────────────
void interpolateChannels(const uint8_t sched[K7_SLOTS][8], int h, int m,
                         uint8_t out[K7_CHANNELS]);

// Parse "HH:MM" → minutes since midnight, returns -1 on error
int  parseHHMM(const char* s);
bool inTimeWindow(const char* start, const char* end);
void lunarWindowNow(char start[8], char end[8], int* shiftMinutes = nullptr);
bool lunarWindowActiveNow();
bool lunarScheduleAllowsNow();
bool siestaActiveNow();
bool siestaTimeAllowed(int startMins, int durationMins,
                       int* outAllowedStart = nullptr,
                       int* outAllowedEnd = nullptr);
void siestaWindowNow(char start[8], char end[8]);
int  acclimationPercentNow(time_t now = time(nullptr));
int  seasonalShiftMinutesNow(time_t now = time(nullptr));
void rebuildEffectiveSchedule(time_t now = time(nullptr));
void queueCurrentLampStatePush();

void applyLunarOverlay(uint8_t ch[K7_CHANNELS]);
void applySiestaDimming(uint8_t ch[K7_CHANNELS]);
void applyMasterBrightness(uint8_t ch[K7_CHANNELS]);

// Make one K7 TCP connection, run fn(lamp), close.
// Must only be called from FreeRTOS tasks, NOT from HTTP handlers.
bool withLamp(const std::function<void(K7Lamp&)>& fn);
bool sendHandLuminance(const char* source, const uint8_t ch[K7_CHANNELS]);
void getOutputStatus(OutputStatus& out);

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
void saveLunarConfig();
void saveSiestaConfig();
void saveAcclimationConfig();
void saveSeasonalConfig();
void saveEffectState();
void loadEffectState();

// ── Effect control ────────────────────────────────────────────────────────────
// All start/stop functions are non-blocking — they set flags only.
// Mode switching (manual/auto) is managed by each effect task internally.
void startRamp();
void stopRamp();

void startFeed();
void stopFeed();

void startMaintenance();
void stopMaintenance();

void startLunar();
void stopLunar();
void lunarApplyNow();
void lunarRestoreNow();

// ── Background scheduler tasks (call once at startup) ─────────────────────────
void startEffectSchedulers();
