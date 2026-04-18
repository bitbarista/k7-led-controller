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
std::atomic<bool> gLightningActive{false};
std::atomic<bool> gLunarActive{false};
std::atomic<bool> gCloudActive{false};
std::atomic<bool> gLightningUserEnabled{false};
std::atomic<bool> gLightningUserStopped{false};
std::atomic<bool> gLunarStopped{false};

LightningSchedule gLightningSchedule;
LunarConfig       gLunarConfig;
CloudSettings     gCloudSettings;

// ── Task handles ──────────────────────────────────────────────────────────────
static TaskHandle_t hRamp      = nullptr;
static TaskHandle_t hLightning = nullptr;
static TaskHandle_t hLunar     = nullptr;
static TaskHandle_t hCloud     = nullptr;

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
    File f;
    JsonDocument doc;
    if (LittleFS.exists(LIGHTNING_SCHEDULE_FILE)) {
        f = LittleFS.open(LIGHTNING_SCHEDULE_FILE, "r");
        if (f && deserializeJson(doc, f) == DeserializationError::Ok) {
            gLightningSchedule.enabled = doc["enabled"] | false;
            strlcpy(gLightningSchedule.start, doc["start"] | "20:00", 8);
            strlcpy(gLightningSchedule.end,   doc["end"]   | "23:00", 8);
        }
        if (f) f.close();
    }
    doc.clear();
    if (LittleFS.exists(LUNAR_FILE)) {
        f = LittleFS.open(LUNAR_FILE, "r");
        if (f && deserializeJson(doc, f) == DeserializationError::Ok) {
            gLunarConfig.enabled      = doc["enabled"]       | false;
            gLunarConfig.maxIntensity = doc["max_intensity"] | 15;
            strlcpy(gLunarConfig.start, doc["start"] | "21:00", 8);
            strlcpy(gLunarConfig.end,   doc["end"]   | "06:00", 8);
        }
        if (f) f.close();
    }
    doc.clear();
    if (LittleFS.exists(CLOUD_FILE)) {
        f = LittleFS.open(CLOUD_FILE, "r");
        if (f && deserializeJson(doc, f) == DeserializationError::Ok) {
            gCloudSettings.density     = doc["density"]      | 30;
            gCloudSettings.depth       = doc["depth"]        | 60;
            gCloudSettings.colourShift = doc["colour_shift"] | true;
        }
        if (f) f.close();
    }
}

void saveLightningSchedule() {
    File f = LittleFS.open(LIGHTNING_SCHEDULE_FILE, "w");
    if (!f) return;
    JsonDocument doc;
    doc["enabled"] = gLightningSchedule.enabled;
    doc["start"]   = gLightningSchedule.start;
    doc["end"]     = gLightningSchedule.end;
    serializeJson(doc, f);
    f.close();
}

void saveLunarConfig() {
    File f = LittleFS.open(LUNAR_FILE, "w");
    if (!f) return;
    JsonDocument doc;
    doc["enabled"]       = gLunarConfig.enabled;
    doc["start"]         = gLunarConfig.start;
    doc["end"]           = gLunarConfig.end;
    doc["max_intensity"] = gLunarConfig.maxIntensity;
    serializeJson(doc, f);
    f.close();
}

void saveCloudSettings() {
    File f = LittleFS.open(CLOUD_FILE, "w");
    if (!f) return;
    JsonDocument doc;
    doc["density"]      = gCloudSettings.density;
    doc["depth"]        = gCloudSettings.depth;
    doc["colour_shift"] = gCloudSettings.colourShift;
    serializeJson(doc, f);
    f.close();
}

void saveEffectState() {
    File f = LittleFS.open(STATE_FILE, "w");
    if (!f) return;
    JsonDocument doc;
    doc["ramp"]          = gRampActive.load();
    doc["lightning"]     = gLightningUserEnabled.load();
    doc["lunar"]         = gLunarActive.load() && !gLunarStopped.load();
    doc["clouds"]        = gCloudActive.load();
    doc["auto_mode"]     = gLampAutoMode;
    doc["active_preset"] = gActivePreset;
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
    // Restore auto_mode before effects so the mode is correct even if ramp starts
    if (doc["auto_mode"].is<bool>())       gLampAutoMode = doc["auto_mode"];
    if (doc["active_preset"].is<const char*>())
        strlcpy(gActivePreset, doc["active_preset"], sizeof(gActivePreset));
    if (doc["ramp"].as<bool>())      startRamp();
    if (doc["lightning"].as<bool>()) { gLightningUserEnabled = true; gLightningUserStopped = false; startLightning(); }
    if (doc["lunar"].as<bool>())     { startLunar(); lunarApplyNow(); }
    if (doc["clouds"].as<bool>())    startCloud();
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
            Serial.printf("[lamp] push autoMode=%d ch0=%d ch1=%d ch2=%d rampActive=%d\n",
                          push.autoMode, push.manual[0], push.manual[1], push.manual[2],
                          (int)gRampActive);
            // Push schedule and — if ramp is active — immediately drive the lamp
            // to the current interpolated value, all in ONE connection.
            // Using two separate withLamp() calls risks the second connect
            // hitting the lamp's connection limit and being dropped by the backoff.
            bool pushed = withLamp([&](K7Lamp& lamp) {
                lamp.pushSchedule(push.manual, push.sched, push.autoMode);
                if (gRampActive.load()) {
                    time_t     now = time(nullptr);
                    struct tm* t   = localtime(&now);
                    uint8_t    ch[K7_CHANNELS];
                    interpolateChannels(gLastSchedule, t->tm_hour, t->tm_min, ch);
                    if (gLunarActive.load() && inTimeWindow(gLunarConfig.start, gLunarConfig.end))
                        applyLunarOverlay(ch);
                    applyMasterBrightness(ch);
                    lamp.handLuminance(ch);
                }
            });
            Serial.printf("[lamp] push withLamp=%s\n", pushed ? "ok" : "FAIL");
            lunarApplyNow();

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
    xTaskCreatePinnedToCore(lampWorkerTask, "lamp_w", 6144, nullptr, 4, nullptr, 0);
}

// ── Ramp ──────────────────────────────────────────────────────────────────────
static void rampTask(void*) {
    // Put lamp in manual mode so its internal schedule doesn't override us
    withLamp([](K7Lamp& lamp) { lamp.setModeManual(); });

    while (gRampActive) {
        time_t     now = time(nullptr);
        struct tm* t   = localtime(&now);
        uint8_t    ch[K7_CHANNELS];
        interpolateChannels(gLastSchedule, t->tm_hour, t->tm_min, ch);
        if (gLunarActive && inTimeWindow(gLunarConfig.start, gLunarConfig.end))
            applyLunarOverlay(ch);
        applyMasterBrightness(ch);
        withLamp([&](K7Lamp& lamp) { lamp.handLuminance(ch); });

        int sleepSecs = max(1, 60 - t->tm_sec);
        for (int i = 0; i < sleepSecs * 2 && gRampActive; i++)
            vTaskDelay(pdMS_TO_TICKS(500));
    }

    // Re-push the current schedule (master-brightness-scaled) with autoMode=true.
    // Async pushes can fail silently (backoff / connection limit), so the lamp's
    // stored schedule may be stale.  A simple setModeAuto() would then make the
    // lamp run those stale (possibly zero) values.  Pushing here guarantees the
    // lamp has the correct schedule before it resumes auto mode.
    Serial.println("[ramp] stopped — pushing scaled schedule with autoMode=true");
    bool autoOk = withLamp([](K7Lamp& lamp) {
        float    mb = gMasterBrightness / 100.0f;
        uint8_t  scaledManual[K7_CHANNELS];
        uint8_t  scaledSched[K7_SLOTS][8];
        for (int i = 0; i < K7_CHANNELS; i++) {
            int v = (int)roundf(gLastManual[i] * mb);
            scaledManual[i] = (uint8_t)(v > 100 ? 100 : v);
        }
        for (int h = 0; h < K7_SLOTS; h++) {
            scaledSched[h][0] = gLastSchedule[h][0];
            scaledSched[h][1] = gLastSchedule[h][1];
            for (int c = 0; c < K7_CHANNELS; c++) {
                int v = (int)roundf(gLastSchedule[h][2+c] * mb);
                scaledSched[h][2+c] = (uint8_t)(v > 100 ? 100 : v);
            }
        }
        lamp.pushSchedule(scaledManual, scaledSched, true);
    });
    Serial.printf("[ramp] restore withLamp=%s\n", autoOk ? "ok" : "FAIL");
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
    // rampTask sees the flag, exits, and restores auto mode — no blocking here
}

// ── Lightning ─────────────────────────────────────────────────────────────────
static void doLightningEvent() {
    time_t     now = time(nullptr);
    struct tm* t   = localtime(&now);
    uint8_t    ambient[K7_CHANNELS];
    interpolateChannels(gLastSchedule, t->tm_hour, t->tm_min, ambient);
    if (gLunarActive && inTimeWindow(gLunarConfig.start, gLunarConfig.end))
        applyLunarOverlay(ambient);
    applyMasterBrightness(ambient);

    static const uint8_t FLASH_MINI[K7_CHANNELS] = {100, 60, 60, 0,   0,   0};
    static const uint8_t FLASH_PRO [K7_CHANNELS] = { 40, 60, 60, 100, 100, 0};
    uint8_t flash[K7_CHANNELS];
    memcpy(flash, (strcmp(gDevice, "k7mini") == 0) ? FLASH_MINI : FLASH_PRO, K7_CHANNELS);

    bool burst      = (esp_random() % 5 == 0);
    int  numStrikes = burst ? (3 + esp_random() % 4) : 1;

    for (int s = 0; s < numStrikes && gLightningActive; s++) {
        withLamp([&](K7Lamp& lamp) {
            int pulses = 1;
            int r = esp_random() % 100;
            if (r >= 65 && r < 90) pulses = 2;
            else if (r >= 90)      pulses = 3;
            for (int p = 0; p < pulses && gLightningActive; p++) {
                lamp.previewBrightness(flash);
                vTaskDelay(pdMS_TO_TICKS(30 + esp_random() % 50));
                lamp.previewBrightness(ambient);
                if (p < pulses - 1)
                    vTaskDelay(pdMS_TO_TICKS(40 + esp_random() % 60));
            }
        });
        if (s < numStrikes - 1)
            vTaskDelay(pdMS_TO_TICKS(80 + esp_random() % 170));
    }

    // Restore
    withLamp([&](K7Lamp& lamp) {
        if (gRampActive) {
            lamp.handLuminance(ambient);
        } else if (gLunarActive || gCloudActive) {
            lamp.previewBrightness(ambient);   // lunar/cloud task will maintain from here
        } else {
            lamp.previewBrightness(ambient);
            lamp.setModeAuto();
        }
    });
}

static void lightningTask(void*) {
    while (gLightningActive) {
        int delay_ms = 15000 + (int)(esp_random() % 75000);
        for (int i = 0; i < delay_ms / 250 && gLightningActive; i++)
            vTaskDelay(pdMS_TO_TICKS(250));
        if (gLightningActive) doLightningEvent();
    }
    hLightning = nullptr;
    vTaskDelete(nullptr);
}

void startLightning() {
    if (gLightningActive && hLightning) return;
    gLightningActive = true;
    xTaskCreatePinnedToCore(lightningTask, "lightning", 4096, nullptr, 2, &hLightning, 0);
}

void stopLightning() {
    gLightningActive = false;
    // task exits on its next iteration — no blocking here
}

// ── Lunar ─────────────────────────────────────────────────────────────────────
static void lunarTask(void*) {
    while (gLunarActive) {
        if (!gRampActive && inTimeWindow(gLunarConfig.start, gLunarConfig.end)) {
            time_t     now = time(nullptr);
            struct tm* t   = localtime(&now);
            uint8_t    ch[K7_CHANNELS];
            memcpy(ch, gLastSchedule[t->tm_hour % K7_SLOTS] + 2, K7_CHANNELS);
            applyLunarOverlay(ch);
            applyMasterBrightness(ch);
            withLamp([&](K7Lamp& lamp) { lamp.previewBrightness(ch); });
        }
        time_t     now = time(nullptr);
        struct tm* t   = localtime(&now);
        int sleepSecs  = max(1, 60 - t->tm_sec);
        for (int i = 0; i < sleepSecs * 2 && gLunarActive && !gRampActive; i++)
            vTaskDelay(pdMS_TO_TICKS(500));
    }
    if (!gRampActive)
        withLamp([](K7Lamp& lamp) { lamp.setModeAuto(); });
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
    bool inWindow = inTimeWindow(gLunarConfig.start, gLunarConfig.end);
    if (!gLunarActive && !(gLunarConfig.enabled && inWindow && !gLunarStopped)) return;
    if (!inWindow) return;
    time_t     now = time(nullptr);
    struct tm* t   = localtime(&now);
    uint8_t    ch[K7_CHANNELS];
    interpolateChannels(gLastSchedule, t->tm_hour, t->tm_min, ch);
    applyLunarOverlay(ch);
    applyMasterBrightness(ch);
    withLamp([&](K7Lamp& lamp) {
        if (gRampActive) lamp.handLuminance(ch);
        else             lamp.previewBrightness(ch);
    });
}

void lunarRestoreNow() {
    time_t     now = time(nullptr);
    struct tm* t   = localtime(&now);
    uint8_t    ch[K7_CHANNELS];
    interpolateChannels(gLastSchedule, t->tm_hour, t->tm_min, ch);
    applyMasterBrightness(ch);
    withLamp([&](K7Lamp& lamp) {
        if (gRampActive) lamp.handLuminance(ch);
        else { lamp.previewBrightness(ch); lamp.setModeAuto(); }
    });
}

// ── Clouds ────────────────────────────────────────────────────────────────────
static uint8_t applyCloud(const uint8_t base[K7_CHANNELS],
                           float dim, bool shift,
                           uint8_t out[K7_CHANNELS]) {
    float factor = 1.0f - dim;
    float extra  = 0.15f * dim * (shift ? 1.0f : 0.0f);
    for (int i = 0; i < K7_CHANNELS; i++) {
        float f = (i == 0) ? factor : max(0.0f, factor - extra);
        int v = (int)roundf(base[i] * f);
        out[i] = (uint8_t)(v < 0 ? 0 : (v > 100 ? 100 : v));
    }
    return 0;
}

static void cloudTask(void*) {
    // Enter manual mode immediately
    if (!gRampActive) {
        time_t     now = time(nullptr);
        struct tm* t   = localtime(&now);
        uint8_t    full[K7_CHANNELS];
        interpolateChannels(gLastSchedule, t->tm_hour, t->tm_min, full);
        if (gLunarActive && inTimeWindow(gLunarConfig.start, gLunarConfig.end))
            applyLunarOverlay(full);
        applyMasterBrightness(full);
        withLamp([&](K7Lamp& lamp) { lamp.setModeManual(); lamp.handLuminance(full); });
    }

    while (gCloudActive) {
        float density = gCloudSettings.density / 100.0f;
        float depth   = gCloudSettings.depth   / 100.0f;
        bool  shift   = gCloudSettings.colourShift;

        // ── Gap ──────────────────────────────────────────────────────────────
        float gapBase  = max(300.0f, 7200.0f * (1.0f - density) * (1.0f - density));
        int   gapMs    = (int)(gapBase * 1000.0f) + (int)(esp_random() % (int)(gapBase * 1000.0f));
        int   lastSync = 0;
        for (int elapsed = 0; elapsed < gapMs && gCloudActive; elapsed += 500) {
            vTaskDelay(pdMS_TO_TICKS(500));
            if (!gRampActive && elapsed - lastSync >= 15000) {
                lastSync = elapsed;
                time_t     now = time(nullptr);
                struct tm* t   = localtime(&now);
                uint8_t    full[K7_CHANNELS];
                interpolateChannels(gLastSchedule, t->tm_hour, t->tm_min, full);
                if (gLunarActive && inTimeWindow(gLunarConfig.start, gLunarConfig.end))
                    applyLunarOverlay(full);
                applyMasterBrightness(full);
                withLamp([&](K7Lamp& lamp) { lamp.handLuminance(full); });
            }
        }
        if (!gCloudActive) break;

        // ── Snap dim ─────────────────────────────────────────────────────────
        float targetDim = depth * (0.4f + 0.6f * (esp_random() % 1000) / 1000.0f);
        {
            time_t     now = time(nullptr);
            struct tm* t   = localtime(&now);
            uint8_t    base[K7_CHANNELS], dimmed[K7_CHANNELS];
            interpolateChannels(gLastSchedule, t->tm_hour, t->tm_min, base);
            if (gLunarActive && inTimeWindow(gLunarConfig.start, gLunarConfig.end))
                applyLunarOverlay(base);
            applyMasterBrightness(base);
            applyCloud(base, targetDim, shift, dimmed);
            withLamp([&](K7Lamp& lamp) { lamp.handLuminance(dimmed); });
        }

        // ── Hold ─────────────────────────────────────────────────────────────
        int holdMs = 20000 + (int)(esp_random() % 70000);
        lastSync = 0;
        for (int elapsed = 0; elapsed < holdMs && gCloudActive; elapsed += 500) {
            vTaskDelay(pdMS_TO_TICKS(500));
            if (elapsed - lastSync >= 15000) {
                lastSync = elapsed;
                time_t     now = time(nullptr);
                struct tm* t   = localtime(&now);
                uint8_t    base[K7_CHANNELS], dimmed[K7_CHANNELS];
                interpolateChannels(gLastSchedule, t->tm_hour, t->tm_min, base);
                if (gLunarActive && inTimeWindow(gLunarConfig.start, gLunarConfig.end))
                    applyLunarOverlay(base);
                applyMasterBrightness(base);
                applyCloud(base, targetDim, shift, dimmed);
                withLamp([&](K7Lamp& lamp) { lamp.handLuminance(dimmed); });
            }
        }

        // ── Snap bright ───────────────────────────────────────────────────────
        {
            time_t     now = time(nullptr);
            struct tm* t   = localtime(&now);
            uint8_t    full[K7_CHANNELS];
            interpolateChannels(gLastSchedule, t->tm_hour, t->tm_min, full);
            if (gLunarActive && inTimeWindow(gLunarConfig.start, gLunarConfig.end))
                applyLunarOverlay(full);
            applyMasterBrightness(full);
            withLamp([&](K7Lamp& lamp) { lamp.handLuminance(full); });
        }
    }

    // Restore auto mode
    gCloudActive = false;
    if (!gRampActive) {
        withLamp([](K7Lamp& lamp) {
            lamp.pushSchedule(gLastManual,
                              (const uint8_t(*)[8])gLastSchedule,
                              true);
        });
    }
    hCloud = nullptr;
    vTaskDelete(nullptr);
}

void startCloud() {
    if (gCloudActive && hCloud) return;
    gCloudActive = true;
    xTaskCreatePinnedToCore(cloudTask, "cloud", 6144, nullptr, 2, &hCloud, 0);
}

void stopCloud() {
    gCloudActive = false;
    // cloudTask exits on its next iteration — no blocking here
}

// ── Scheduler tasks ───────────────────────────────────────────────────────────
static void lightningSchedulerTask(void*) {
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(30000));
        if (!gLightningSchedule.enabled) continue;
        if (inTimeWindow(gLightningSchedule.start, gLightningSchedule.end)) {
            if (!gLightningUserStopped) startLightning();
        } else {
            gLightningActive = false;
        }
    }
}

static void lunarSchedulerTask(void*) {
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(60000));
        if (!gLunarConfig.enabled) continue;
        if (inTimeWindow(gLunarConfig.start, gLunarConfig.end)) {
            if (!gLunarStopped) startLunar();
        } else {
            gLunarActive = false;
        }
    }
}

void startEffectSchedulers() {
    xTaskCreatePinnedToCore(lightningSchedulerTask, "ls_sched",  2048, nullptr, 1, nullptr, 0);
    xTaskCreatePinnedToCore(lunarSchedulerTask,     "lun_sched", 2048, nullptr, 1, nullptr, 0);
}
