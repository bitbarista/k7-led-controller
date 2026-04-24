#include "Effects.h"
#include "Moon.h"
#include <LittleFS.h>
#include <ArduinoJson.h>
#include <functional>
#include <time.h>

// ── Shared globals ────────────────────────────────────────────────────────────
SemaphoreHandle_t gLampMutex = nullptr;
char              gLampHost[32]  = "192.168.4.1";
char              gDevice[16]    = "k7mini";

int    gMasterBrightness = 100;
uint8_t gLastSchedule[K7_SLOTS][8] = {};
uint8_t gLastManual[K7_CHANNELS]   = {};
char   gLampName[12]    = "K7";
bool   gLampAutoMode    = true;
char   gActivePreset[64] = "";

std::atomic<bool> gRampActive{false};
std::atomic<bool> gLunarActive{false};
std::atomic<bool> gFeedActive{false};
std::atomic<bool> gLunarStopped{false};

int gFeedDuration  = 15;
int gFeedIntensity = 80;
static uint32_t gFeedEndMs = 0;

time_t gRampLastTick = 0;

LunarConfig gLunarConfig;

// ── Task handles ──────────────────────────────────────────────────────────────
static TaskHandle_t hRamp  = nullptr;
static TaskHandle_t hFeed  = nullptr;
static TaskHandle_t hLunar = nullptr;

// ── Helpers ───────────────────────────────────────────────────────────────────
void interpolateChannels(const uint8_t sched[K7_SLOTS][8], int h, int m,
                         uint8_t out[K7_CHANNELS]) {
    const uint8_t* lo = sched[h % K7_SLOTS];
    const uint8_t* hi = sched[(h + 1) % K7_SLOTS];
    float frac = m / 60.0f;
    for (int i = 0; i < K7_CHANNELS; i++) {
        float v = lo[2+i] + frac * ((int)hi[2+i] - (int)lo[2+i]);
        int   iv = (int)roundf(v);
        out[i] = (uint8_t)(iv < 0 ? 0 : (iv > 100 ? 100 : iv));
    }
}

int parseHHMM(const char* s) {
    if (!s || strlen(s) < 5) return -1;
    int h = atoi(s);
    const char* colon = strchr(s, ':');
    if (!colon) return -1;
    int m = atoi(colon + 1);
    return h * 60 + m;
}

static int wrapMinutes(int mins) {
    mins %= 1440;
    if (mins < 0) mins += 1440;
    return mins;
}

static void formatHHMM(int mins, char out[8]) {
    mins = wrapMinutes(mins);
    snprintf(out, 8, "%02d:%02d", mins / 60, mins % 60);
}

static int windowLength(int start, int end) {
    int len = end - start;
    if (len <= 0) len += 1440;
    return len;
}

static bool clampWindowToNight(int start, int end, int clampStart, int clampEnd,
                               int* outStart, int* outEnd) {
    int rawLen   = windowLength(start, end);
    int clampLen = windowLength(clampStart, clampEnd);
    int bestOverlap = -1;
    int bestStart = 0, bestEnd = 0;

    for (int rawShift = -1440; rawShift <= 1440; rawShift += 1440) {
        int shiftedStart = start + rawShift;
        int shiftedEnd   = shiftedStart + rawLen;
        for (int clampShift = 0; clampShift <= 1440; clampShift += 1440) {
            int shiftedClampStart = clampStart + clampShift;
            int shiftedClampEnd   = shiftedClampStart + clampLen;
            int overlapStart = max(shiftedStart, shiftedClampStart);
            int overlapEnd   = min(shiftedEnd, shiftedClampEnd);
            int overlapLen   = overlapEnd - overlapStart;
            if (overlapLen > bestOverlap) {
                bestOverlap = overlapLen;
                bestStart   = overlapStart;
                bestEnd     = overlapEnd;
            }
        }
    }

    if (bestOverlap <= 0) return false;
    *outStart = wrapMinutes(bestStart);
    *outEnd   = wrapMinutes(bestEnd);
    return true;
}

bool inTimeWindow(const char* start, const char* end) {
    int s = parseHHMM(start);
    int e = parseHHMM(end);
    if (s < 0 || e < 0) return false;
    time_t     now = time(nullptr);
    struct tm* t   = localtime(&now);
    int cur = t->tm_hour * 60 + t->tm_min;
    if (s <= e) return cur >= s && cur < e;
    return cur >= s || cur < e;   // overnight window
}

bool lunarScheduleAllowsNow() {
    time_t now = time(nullptr);
    struct tm* t = localtime(&now);
    uint8_t ch[K7_CHANNELS];
    interpolateChannels(gLastSchedule, t->tm_hour, t->tm_min, ch);
    int threshold = max(0, min(100, gLunarConfig.dayThreshold));
    for (int i = 0; i < K7_CHANNELS; i++) {
        if (ch[i] > threshold) return false;
    }
    return true;
}

void lunarWindowNow(char start[8], char end[8], int* shiftMinutes) {
    int rawStart = parseHHMM(gLunarConfig.start);
    int rawEnd   = parseHHMM(gLunarConfig.end);
    if (rawStart < 0) rawStart = 18 * 60 + 30;
    if (rawEnd   < 0) rawEnd   = 6 * 60 + 30;

    int windowLen = windowLength(rawStart, rawEnd);

    int shift = 0;
    if (gLunarConfig.trackMoonrise) {
        float delta = Moon::phase() - 0.5f;  // full moon = anchor window
        if (delta < -0.5f) delta += 1.0f;
        if (delta >= 0.5f) delta -= 1.0f;
        shift = (int)roundf(delta * 1440.0f);
    }

    int effectiveStart = wrapMinutes(rawStart + shift);
    int effectiveEnd   = wrapMinutes(effectiveStart + windowLen);
    if (gLunarConfig.trackMoonrise) {
        int clampStart = parseHHMM(gLunarConfig.clampStart);
        int clampEnd   = parseHHMM(gLunarConfig.clampEnd);
        if (clampStart < 0) clampStart = 18 * 60;
        if (clampEnd   < 0) clampEnd   = 8 * 60;
        int clampedStart = 0, clampedEnd = 0;
        if (clampWindowToNight(effectiveStart, effectiveEnd, clampStart, clampEnd,
                               &clampedStart, &clampedEnd)) {
            effectiveStart = clampedStart;
            effectiveEnd   = clampedEnd;
        } else {
            effectiveEnd = effectiveStart;
        }
    }
    formatHHMM(effectiveStart, start);
    formatHHMM(effectiveEnd, end);
    if (shiftMinutes) *shiftMinutes = shift;
}

bool lunarWindowActiveNow() {
    char start[8], end[8];
    lunarWindowNow(start, end);
    return inTimeWindow(start, end);
}

void applyLunarOverlay(uint8_t ch[K7_CHANNELS]) {
    float raw = gLunarConfig.maxIntensity * Moon::illumination();
    int   pct = (int)roundf(raw);
    if (pct <= 0) return;
    // Royal blue channel 1 for both models; also blue ch2 for Pro
    ch[1] = max(ch[1], (uint8_t)min(pct, 100));
    if (strcmp(gDevice, "k7pro") == 0) {
        int b = (int)roundf(pct * 0.7f);
        ch[2] = max(ch[2], (uint8_t)min(b, 100));
    }
}

void applyMasterBrightness(uint8_t ch[K7_CHANNELS]) {
    if (gMasterBrightness == 100) return;
    for (int i = 0; i < K7_CHANNELS; i++) {
        int v = (int)roundf(ch[i] * gMasterBrightness / 100.0f);
        ch[i] = (uint8_t)min(v, 100);
    }
}

// After a connect failure, back off for CONNECT_BACKOFF_MS before retrying.
// This prevents lampWorkerTask (priority 4) from busy-blocking in connect()
// and starving the web-server loop() task (priority 1).
static uint32_t sLastConnectFail  = 0;
static const uint32_t CONNECT_BACKOFF_MS = 1000;

bool withLamp(const std::function<void(K7Lamp&)>& fn) {
    if (sLastConnectFail && millis() - sLastConnectFail < CONNECT_BACKOFF_MS)
        return false;   // back off — return immediately, don't block

    if (xSemaphoreTake(gLampMutex, pdMS_TO_TICKS(5000)) != pdTRUE) {
        Serial.println("[lamp] withLamp: mutex timeout");
        return false;
    }
    bool ok = false;
    {
        K7Lamp lamp(gLampHost, LAMP_PORT);
        if (lamp.connect()) {
            sLastConnectFail = 0;
            fn(lamp);
            ok = true;
        } else {
            sLastConnectFail = millis();
            Serial.printf("[lamp] connect FAILED to %s:%u\n", gLampHost, (unsigned)LAMP_PORT);
        }
    }
    xSemaphoreGive(gLampMutex);
    return ok;
}

// ── Persistence ───────────────────────────────────────────────────────────────
void loadEffectConfigs() {
    if (!LittleFS.exists(LUNAR_FILE)) return;
    File f = LittleFS.open(LUNAR_FILE, "r");
    if (!f) return;
    JsonDocument doc;
    if (deserializeJson(doc, f) == DeserializationError::Ok) {
        gLunarConfig.enabled      = doc["enabled"]       | false;
        gLunarConfig.maxIntensity = doc["max_intensity"] | 15;
        strlcpy(gLunarConfig.start, doc["start"] | "18:30", 8);
        strlcpy(gLunarConfig.end,   doc["end"]   | "06:30", 8);
        strlcpy(gLunarConfig.clampStart, doc["clamp_start"] | "18:00", 8);
        strlcpy(gLunarConfig.clampEnd,   doc["clamp_end"]   | "08:00", 8);
        gLunarConfig.dayThreshold = max(0, min(100, (int)(doc["day_threshold"] | 2)));
        gLunarConfig.trackMoonrise = doc["track_moonrise"] | false;
    }
    f.close();
}

void saveLunarConfig() {
    File f = LittleFS.open(LUNAR_FILE, "w");
    if (!f) return;
    JsonDocument doc;
    doc["enabled"]       = gLunarConfig.enabled;
    doc["start"]         = gLunarConfig.start;
    doc["end"]           = gLunarConfig.end;
    doc["clamp_start"]   = gLunarConfig.clampStart;
    doc["clamp_end"]     = gLunarConfig.clampEnd;
    doc["max_intensity"] = gLunarConfig.maxIntensity;
    doc["day_threshold"] = gLunarConfig.dayThreshold;
    doc["track_moonrise"] = gLunarConfig.trackMoonrise;
    serializeJson(doc, f);
    f.close();
}

void saveEffectState() {
    File f = LittleFS.open(STATE_FILE, "w");
    if (!f) return;
    JsonDocument doc;
    doc["ramp"]          = gRampActive.load();
    doc["lunar"]         = gLunarActive.load() && !gLunarStopped.load();
    doc["feed_duration"]  = gFeedDuration;
    doc["feed_intensity"] = gFeedIntensity;
    doc["auto_mode"]     = gLampAutoMode;
    doc["active_preset"] = gActivePreset;
    // Persist unscaled base schedule so it survives reboot intact
    auto schedArr = doc["schedule"].to<JsonArray>();
    for (int h = 0; h < K7_SLOTS; h++) {
        auto row = schedArr.add<JsonArray>();
        for (int c = 0; c < 8; c++) row.add(gLastSchedule[h][c]);
    }
    auto manArr = doc["manual"].to<JsonArray>();
    for (int i = 0; i < K7_CHANNELS; i++) manArr.add(gLastManual[i]);
    serializeJson(doc, f);
    f.close();
}

void loadEffectState() {
    if (!LittleFS.exists(STATE_FILE)) return;
    File f = LittleFS.open(STATE_FILE, "r");
    if (!f) return;
    JsonDocument doc;
    if (deserializeJson(doc, f) != DeserializationError::Ok) { f.close(); return; }
    f.close();
    // Restore the unscaled base schedule (overrides the lamp-read which may have MB-scaled values)
    if (doc["schedule"].is<JsonArray>()) {
        JsonArray arr = doc["schedule"];
        for (int h = 0; h < K7_SLOTS && h < (int)arr.size(); h++) {
            JsonArray row = arr[h];
            for (int c = 0; c < 8 && c < (int)row.size(); c++)
                gLastSchedule[h][c] = (uint8_t)row[c].as<int>();
        }
    }
    if (doc["manual"].is<JsonArray>()) {
        JsonArray arr = doc["manual"];
        for (int i = 0; i < K7_CHANNELS && i < (int)arr.size(); i++)
            gLastManual[i] = (uint8_t)arr[i].as<int>();
    }
    // Restore auto_mode before effects so the mode is correct even if ramp starts
    if (doc["auto_mode"].is<bool>())       gLampAutoMode = doc["auto_mode"];
    if (doc["active_preset"].is<const char*>())
        strlcpy(gActivePreset, doc["active_preset"], sizeof(gActivePreset));
    if (doc["feed_duration"].is<int>())  gFeedDuration  = max(1,   min(60,  doc["feed_duration"].as<int>()));
    if (doc["feed_intensity"].is<int>()) gFeedIntensity = max(1,   min(100, doc["feed_intensity"].as<int>()));
    if (doc["ramp"].as<bool>())  startRamp();
    if (doc["lunar"].as<bool>()) { startLunar(); lunarApplyNow(); }
}

// ── Async lamp worker (push + preview) ───────────────────────────────────────
// HTTP handlers MUST NOT call withLamp() directly — that blocks loop() and
// freezes the web server.  Instead they queue work here and return immediately.

static QueueHandle_t hPushQueue    = nullptr;
static QueueHandle_t hPreviewQueue = nullptr;

static void lampWorkerTask(void*) {
    PushJob push;
    uint8_t prev[K7_CHANNELS];

    for (;;) {
        // ── Push (priority) ──────────────────────────────────────────────────
        if (hPushQueue && xQueueReceive(hPushQueue, &push, 0) == pdTRUE) {
            Serial.printf("[lamp] push autoMode=%d ch0=%d ch1=%d ch2=%d\n",
                          push.autoMode, push.manual[0], push.manual[1], push.manual[2]);
            // Always push in manual mode so handLuminance is persistent.
            // Pushing autoMode=true hands control to the lamp's internal clock
            // (UTC) which may differ from local time, and previewBrightness is
            // transient — the lamp reverts to its internal schedule tick and can
            // go dark.  Manual mode + handLuminance is immediate and stays put.
            time_t     now = time(nullptr);
            struct tm* t   = localtime(&now);
            uint8_t    ch[K7_CHANNELS];
            if (push.autoMode) {
                interpolateChannels(gLastSchedule, t->tm_hour, t->tm_min, ch);
                applyMasterBrightness(ch);
                bool lunarOn = (gLunarActive.load() ||
                               (gLunarConfig.enabled && !gLunarStopped.load()))
                               && lunarWindowActiveNow()
                               && lunarScheduleAllowsNow();
                if (lunarOn) applyLunarOverlay(ch);
            } else {
                memcpy(ch, push.manual, K7_CHANNELS);
            }

            // handLuminance only — CMD_ALL_SET blocks the lamp for ~2.5 s and
            // resets its output; schedule persistence lives in LittleFS.
            bool pushed = withLamp([&](K7Lamp& lamp) { lamp.handLuminance(ch); });
            Serial.printf("[lamp] push withLamp=%s\n", pushed ? "ok" : "FAIL");
            if (!pushed) xQueueSend(hPushQueue, &push, 0);
            vTaskDelay(pdMS_TO_TICKS(400));

        // ── Preview ──────────────────────────────────────────────────────────
        // Per-operation connection: mutex held only for the ~20-60 ms of the
        // TCP round-trip, so ramp / effects can always interleave.
        // preview_brightness is used regardless of ramp state — the Python
        // reference does the same; it works in both auto and manual modes.
        } else if (hPreviewQueue &&
                   xQueueReceive(hPreviewQueue, prev, pdMS_TO_TICKS(10)) == pdTRUE) {
            withLamp([&](K7Lamp& lamp) {
                lamp.previewBrightness(prev);
            });
        }
    }
}

void queuePush(const uint8_t manual[K7_CHANNELS],
               const uint8_t sched[K7_SLOTS][8],
               bool autoMode) {
    if (!hPushQueue) return;
    PushJob job;
    memcpy(job.manual, manual, K7_CHANNELS);
    memcpy(job.sched,  sched,  sizeof(job.sched));
    job.autoMode = autoMode;
    xQueueOverwrite(hPushQueue, &job);
}

void queuePreview(const uint8_t ch[K7_CHANNELS]) {
    if (!hPreviewQueue) return;
    xQueueOverwrite(hPreviewQueue, ch);
}

void startLampWorker() {
    hPushQueue    = xQueueCreate(1, sizeof(PushJob));
    hPreviewQueue = xQueueCreate(1, K7_CHANNELS * sizeof(uint8_t));
    xTaskCreatePinnedToCore(lampWorkerTask, "lamp_w", 8192, nullptr, 4, nullptr, 0);
}

// ── Ramp ──────────────────────────────────────────────────────────────────────
static void rampTask(void*) {
    while (gRampActive) {
        time_t     now = time(nullptr);
        struct tm* t   = localtime(&now);

        if (!gFeedActive) {
            gRampLastTick = time(nullptr);
            float   mbf = gMasterBrightness / 100.0f;
            uint8_t sc[K7_SLOTS][8];
            for (int h = 0; h < K7_SLOTS; h++) {
                sc[h][0] = gLastSchedule[h][0];
                sc[h][1] = gLastSchedule[h][1];
                for (int c = 0; c < K7_CHANNELS; c++) {
                    int v = (int)roundf(gLastSchedule[h][2 + c] * mbf);
                    sc[h][2 + c] = (uint8_t)(v > 100 ? 100 : v);
                }
            }
            uint8_t ch[K7_CHANNELS];
            interpolateChannels(sc, t->tm_hour, t->tm_min, ch);
            bool lunarOn = (gLunarActive.load() || (gLunarConfig.enabled && !gLunarStopped.load()))
                           && lunarWindowActiveNow()
                           && lunarScheduleAllowsNow();
            if (lunarOn) applyLunarOverlay(ch);
            withLamp([&](K7Lamp& lamp) { lamp.handLuminance(ch); });
        }

        int sleepSecs = max(1, 60 - t->tm_sec);
        for (int i = 0; i < sleepSecs * 2 && gRampActive; i++)
            vTaskDelay(pdMS_TO_TICKS(500));
    }
    hRamp = nullptr;
    vTaskDelete(nullptr);
}

void startRamp() {
    if (gRampActive && hRamp) return;
    gRampActive = true;
    xTaskCreatePinnedToCore(rampTask, "ramp", 4096, nullptr, 3, &hRamp, 0);
    // rampTask sets manual mode itself on its first iteration
}

void stopRamp() {
    gRampActive = false;
    // rampTask sees the flag, exits, and the lamp holds the last handLuminance value
}

// ── Lunar ─────────────────────────────────────────────────────────────────────
static void lunarTask(void*) {
    while (gLunarActive) {
        int lunarPct = (int)roundf(gLunarConfig.maxIntensity * Moon::illumination());
        if (!gRampActive && !gFeedActive && lunarPct > 0
            && lunarWindowActiveNow() && lunarScheduleAllowsNow()) {
            time_t     now = time(nullptr);
            struct tm* t   = localtime(&now);
            uint8_t    ch[K7_CHANNELS];
            interpolateChannels(gLastSchedule, t->tm_hour, t->tm_min, ch);
            applyMasterBrightness(ch);
            applyLunarOverlay(ch);
            withLamp([&](K7Lamp& lamp) { lamp.handLuminance(ch); });
        }
        time_t     now = time(nullptr);
        struct tm* t   = localtime(&now);
        int sleepSecs  = max(1, 60 - t->tm_sec);
        for (int i = 0; i < sleepSecs * 2 && gLunarActive; i++)
            vTaskDelay(pdMS_TO_TICKS(500));
    }
    if (!gRampActive && !gFeedActive) {
        time_t     now2 = time(nullptr);
        struct tm* t2   = localtime(&now2);
        uint8_t    ch2[K7_CHANNELS];
        interpolateChannels(gLastSchedule, t2->tm_hour, t2->tm_min, ch2);
        applyMasterBrightness(ch2);
        withLamp([&](K7Lamp& lamp) { lamp.handLuminance(ch2); });
    }
    hLunar       = nullptr;
    gLunarActive = false;
    vTaskDelete(nullptr);
}

void startLunar() {
    gLunarActive  = true;
    gLunarStopped = false;
    if (!gRampActive && !hLunar)
        xTaskCreatePinnedToCore(lunarTask, "lunar", 4096, nullptr, 2, &hLunar, 0);
}

void stopLunar() {
    gLunarStopped = true;
    gLunarActive  = false;
    // lunarTask exits on its next iteration — no blocking here
}

void lunarApplyNow() {
    bool inWindow = lunarWindowActiveNow() && lunarScheduleAllowsNow();
    if (!gLunarActive && !(gLunarConfig.enabled && inWindow && !gLunarStopped)) return;
    if (!inWindow) return;
    int lunarPct = (int)roundf(gLunarConfig.maxIntensity * Moon::illumination());
    if (lunarPct <= 0) return;
    time_t     now = time(nullptr);
    struct tm* t   = localtime(&now);
    uint8_t    ch[K7_CHANNELS];
    interpolateChannels(gLastSchedule, t->tm_hour, t->tm_min, ch);
    applyMasterBrightness(ch);
    applyLunarOverlay(ch);
    withLamp([&](K7Lamp& lamp) { lamp.handLuminance(ch); });
}

void lunarRestoreNow() {
    time_t     now = time(nullptr);
    struct tm* t   = localtime(&now);
    uint8_t    ch[K7_CHANNELS];
    interpolateChannels(gLastSchedule, t->tm_hour, t->tm_min, ch);
    applyMasterBrightness(ch);
    withLamp([&](K7Lamp& lamp) {
        lamp.handLuminance(ch);
    });
}

// ── Feed mode ─────────────────────────────────────────────────────────────────
// K7 mini: white=80, royal_blue=10, blue=10
// K7 pro:  uv=5, royal_blue=10, blue=10, white=80, warm_white=40, red=0
static const uint8_t FEED_MINI[K7_CHANNELS] = {80, 10, 10,  0,  0, 0};
static const uint8_t FEED_PRO [K7_CHANNELS] = { 5, 10, 10, 80, 40, 0};

int feedSecondsRemaining() {
    if (!gFeedActive) return 0;
    int32_t rem = (int32_t)(gFeedEndMs - millis()) / 1000;
    return rem > 0 ? rem : 0;
}

static void feedTask(void*) {
    uint8_t ch[K7_CHANNELS];
    bool isPro = (strcmp(gDevice, "k7pro") == 0);
    memcpy(ch, isPro ? FEED_PRO : FEED_MINI, K7_CHANNELS);
    ch[isPro ? 3 : 0] = (uint8_t)max(0, min(100, gFeedIntensity));
    applyMasterBrightness(ch);
    withLamp([&](K7Lamp& lamp) { lamp.handLuminance(ch); });

    while (gFeedActive && (int32_t)(gFeedEndMs - millis()) > 0)
        vTaskDelay(pdMS_TO_TICKS(1000));

    gFeedActive = false;

    // Immediately restore the lamp. ramp/lunar tasks were still running throughout
    // feed (just skipping their pushes); they resume normally on their next tick.
    {
        time_t     now = time(nullptr);
        struct tm* t   = localtime(&now);
        uint8_t    restored[K7_CHANNELS];
        interpolateChannels(gLastSchedule, t->tm_hour, t->tm_min, restored);
        applyMasterBrightness(restored);
        bool lunarOn = (gLunarActive.load() || (gLunarConfig.enabled && !gLunarStopped.load()))
                       && lunarWindowActiveNow()
                       && lunarScheduleAllowsNow();
        if (lunarOn) applyLunarOverlay(restored);
        withLamp([&](K7Lamp& lamp) { lamp.handLuminance(restored); });
    }

    hFeed = nullptr;
    vTaskDelete(nullptr);
}

void startFeed() {
    if (gFeedActive && hFeed) return;
    gFeedEndMs  = millis() + (uint32_t)gFeedDuration * 60000;
    gFeedActive = true;
    xTaskCreatePinnedToCore(feedTask, "feed", 4096, nullptr, 2, &hFeed, 0);
}

void stopFeed() {
    gFeedActive = false;
}

// ── Scheduler tasks ───────────────────────────────────────────────────────────
static void lunarSchedulerTask(void*) {
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(60000));
        if (!gLunarConfig.enabled) continue;
        if (lunarWindowActiveNow() && lunarScheduleAllowsNow()) {
            if (!gLunarStopped) startLunar();
        } else {
            gLunarActive = false;
        }
    }
}

void startEffectSchedulers() {
    xTaskCreatePinnedToCore(lunarSchedulerTask, "lun_sched", 2048, nullptr, 1, nullptr, 0);
}
