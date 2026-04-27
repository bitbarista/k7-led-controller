#include "ApiServer.h"
#include "Config.h"
#include "Effects.h"
#include "Presets.h"
#include "Moon.h"
#include "K7Lamp.h"
#include <LittleFS.h>
#include <ArduinoJson.h>
#include <WebServer.h>
#include <time.h>
#include "Storage.h"

// ── JSON response helpers ─────────────────────────────────────────────────────
static void sendJson(WebServer& srv, const JsonDocument& doc, int code = 200) {
    String out;
    serializeJson(doc, out);
    srv.send(code, "application/json", out);
}
static void sendOk(WebServer& srv) {
    srv.send(200, "application/json", "{\"ok\":true}");
}
static void sendError(WebServer& srv, const char* msg, int code = 500) {
    String j = "{\"error\":\""; j += msg; j += "\"}";
    srv.send(code, "application/json", j);
}

static const Preset* findPresetByActiveKey(const char* activeKey) {
    if (!activeKey || strncmp(activeKey, "preset:", 7) != 0) return nullptr;
    const char* id = activeKey + 7;
    bool isPro = (strcmp(gDevice, "k7pro") == 0);
    const Preset* list = isPro ? PRO_PRESETS : MINI_PRESETS;
    uint8_t cnt = isPro ? NUM_PRO_PRESETS : NUM_MINI_PRESETS;
    for (uint8_t i = 0; i < cnt; i++) {
        if (strcmp(list[i].id, id) == 0) return &list[i];
    }
    return nullptr;
}

static bool loadJsonFile(const char* path, JsonDocument& doc) {
    doc.clear();
    if (!UserDataFS.exists(path)) return false;
    File f = UserDataFS.open(path, "r");
    if (!f) return false;
    DeserializationError err = deserializeJson(doc, f);
    f.close();
    return err == DeserializationError::Ok;
}

static bool saveJsonFile(const char* path, const JsonDocument& doc) {
    File f = UserDataFS.open(path, "w");
    if (!f) return false;
    serializeJson(doc, f);
    f.close();
    return true;
}

static String urlDecode(String s) {
    String out;
    out.reserve(s.length());
    for (size_t i = 0; i < s.length(); i++) {
        char ch = s[i];
        if (ch == '+') {
            out += ' ';
        } else if (ch == '%' && i + 2 < s.length()) {
            char hex[3] = { s[i + 1], s[i + 2], 0 };
            out += (char)strtol(hex, nullptr, 16);
            i += 2;
        } else {
            out += ch;
        }
    }
    return out;
}

static void loadConfigDoc(JsonDocument& doc) {
    doc.to<JsonObject>();
    loadJsonFile(CONFIG_FILE, doc);
    doc["device"] = gDevice;
    doc["host"]   = gLampHost;
}

static bool saveConfigDoc(JsonVariantConst src) {
    JsonDocument doc;
    doc.to<JsonObject>();
    if (src.is<JsonObjectConst>())
        doc.set(src);
    if (!doc["device"].is<const char*>()) doc["device"] = gDevice;
    if (!doc["host"].is<const char*>())   doc["host"]   = gLampHost;

    if (doc["device"].is<const char*>())
        strlcpy(gDevice, doc["device"], sizeof(gDevice));
    if (doc["host"].is<const char*>())
        strlcpy(gLampHost, doc["host"], sizeof(gLampHost));

    return saveJsonFile(CONFIG_FILE, doc);
}

static void buildStateDoc(JsonDocument& doc) {
    doc["ramp"]              = gRampActive.load();
    doc["lunar"]             = gLunarActive.load() && !gLunarStopped.load();
    doc["master_brightness"] = gMasterBrightness;
    doc["schedule_shift_minutes"] = gScheduleShiftMinutes;
    doc["feed_duration"]     = gFeedDuration;
    doc["feed_intensity"]    = gFeedIntensity;
    doc["maintenance_duration"]  = gMaintenanceDuration;
    doc["maintenance_intensity"] = gMaintenanceIntensity;
    doc["auto_mode"]         = gLampAutoMode;
    doc["active_preset"]     = gActivePreset;

    auto schedArr = doc["schedule"].to<JsonArray>();
    for (int h = 0; h < K7_SLOTS; h++) {
        auto row = schedArr.add<JsonArray>();
        for (int c = 0; c < 8; c++) row.add(gBaseSchedule[h][c]);
    }
    auto manArr = doc["manual"].to<JsonArray>();
    for (int i = 0; i < K7_CHANNELS; i++) manArr.add(gLastManual[i]);
}

static void buildOutputStatusDoc(JsonDocument& doc) {
    OutputStatus st;
    getOutputStatus(st);
    uint32_t nowMs = millis();
    doc["source"] = st.source;
    doc["last_write_ok"] = st.lastWriteOk;
    doc["target_age_ms"] = st.targetMs ? (uint32_t)(nowMs - st.targetMs) : 0;
    doc["sent_age_ms"] = st.sentMs ? (uint32_t)(nowMs - st.sentMs) : 0;
    doc["has_target"] = st.targetMs != 0;
    doc["has_sent"] = st.sentMs != 0;
    auto target = doc["target"].to<JsonArray>();
    auto sent = doc["sent"].to<JsonArray>();
    for (int i = 0; i < K7_CHANNELS; i++) {
        target.add(st.target[i]);
        sent.add(st.sent[i]);
    }
}

static void buildLunarDoc(JsonDocument& doc) {
    doc["enabled"]        = gLunarConfig.enabled;
    doc["start"]          = gLunarConfig.start;
    doc["end"]            = gLunarConfig.end;
    doc["clamp_start"]    = gLunarConfig.clampStart;
    doc["clamp_end"]      = gLunarConfig.clampEnd;
    doc["max_intensity"]  = gLunarConfig.maxIntensity;
    doc["day_threshold"]  = gLunarConfig.dayThreshold;
    doc["track_moonrise"] = gLunarConfig.trackMoonrise;
}

static void applyLunarDoc(JsonVariantConst src) {
    if (src["enabled"].is<bool>())            gLunarConfig.enabled = src["enabled"];
    if (src["start"].is<const char*>())       strlcpy(gLunarConfig.start, src["start"], sizeof(gLunarConfig.start));
    if (src["end"].is<const char*>())         strlcpy(gLunarConfig.end, src["end"], sizeof(gLunarConfig.end));
    if (src["clamp_start"].is<const char*>()) strlcpy(gLunarConfig.clampStart, src["clamp_start"], sizeof(gLunarConfig.clampStart));
    if (src["clamp_end"].is<const char*>())   strlcpy(gLunarConfig.clampEnd, src["clamp_end"], sizeof(gLunarConfig.clampEnd));
    if (src["max_intensity"].is<int>())       gLunarConfig.maxIntensity = max(1, min(100, src["max_intensity"].as<int>()));
    if (src["day_threshold"].is<int>())       gLunarConfig.dayThreshold = max(0, min(100, src["day_threshold"].as<int>()));
    if (src["track_moonrise"].is<bool>())     gLunarConfig.trackMoonrise = src["track_moonrise"];
}

static void buildAcclimationDoc(JsonDocument& doc) {
    time_t now = time(nullptr);
    int currentPct = acclimationPercentNow(now);
    int elapsedDays = 0;
    if (gAcclimationConfig.startEpoch > 0 && now > (time_t)gAcclimationConfig.startEpoch)
        elapsedDays = (int)((now - (time_t)gAcclimationConfig.startEpoch) / 86400);
    int daysRemaining = max(0, gAcclimationConfig.durationDays - elapsedDays);
    doc["enabled"]        = gAcclimationConfig.enabled;
    doc["start_percent"]  = gAcclimationConfig.startPercent;
    doc["duration_days"]  = gAcclimationConfig.durationDays;
    doc["start_epoch"]    = (uint32_t)gAcclimationConfig.startEpoch;
    doc["current_percent"] = currentPct;
    doc["days_remaining"] = daysRemaining;
}

static bool applyAcclimationDoc(JsonVariantConst src) {
    bool enabled = gAcclimationConfig.enabled;
    int startPercent = gAcclimationConfig.startPercent;
    int durationDays = gAcclimationConfig.durationDays;
    uint32_t startEpoch = gAcclimationConfig.startEpoch;

    if (src["enabled"].is<bool>())       enabled = src["enabled"];
    if (src["start_percent"].is<int>())  startPercent = max(1, min(100, src["start_percent"].as<int>()));
    if (src["duration_days"].is<int>())  durationDays = max(1, min(180, src["duration_days"].as<int>()));
    if (src["start_epoch"].is<unsigned long>()) startEpoch = src["start_epoch"].as<unsigned long>();
    if (enabled && (!gAcclimationConfig.enabled || src["start_percent"].is<int>() || src["duration_days"].is<int>()))
        startEpoch = (uint32_t)time(nullptr);

    gAcclimationConfig.enabled = enabled;
    gAcclimationConfig.startPercent = startPercent;
    gAcclimationConfig.durationDays = durationDays;
    gAcclimationConfig.startEpoch = startEpoch;
    return true;
}

static void buildSeasonalDoc(JsonDocument& doc) {
    doc["enabled"]            = gSeasonalConfig.enabled;
    doc["max_shift_minutes"]  = gSeasonalConfig.maxShiftMinutes;
    doc["current_shift_minutes"] = seasonalShiftMinutesNow();
}

static bool applySeasonalDoc(JsonVariantConst src) {
    if (src["enabled"].is<bool>()) gSeasonalConfig.enabled = src["enabled"];
    if (src["max_shift_minutes"].is<int>())
        gSeasonalConfig.maxShiftMinutes = max(0, min(180, src["max_shift_minutes"].as<int>()));
    return true;
}

static void buildMaintenanceDoc(JsonDocument& doc) {
    doc["active"]    = gMaintenanceActive.load();
    doc["remaining"] = maintenanceSecondsRemaining();
    doc["duration"]  = gMaintenanceDuration;
    doc["intensity"] = gMaintenanceIntensity;
}

static void addWarning(JsonArray arr, const char* level, const char* code, const String& message) {
    auto item = arr.add<JsonObject>();
    item["level"] = level;
    item["code"] = code;
    item["message"] = message;
}

static void buildWarningsDoc(JsonDocument& doc) {
    auto items = doc["items"].to<JsonArray>();
    const int sampleStep = 15;
    int litSamples = 0;
    int peakSamples = 0;
    int peakTotal = 0;
    int peakChannel = 0;
    bool darkFlags[1440 / sampleStep] = {};
    int sampleIndex = 0;

    for (int mins = 0; mins < 1440; mins += sampleStep) {
        uint8_t ch[K7_CHANNELS];
        interpolateChannels(gLastSchedule, mins / 60, mins % 60, ch);
        applyMasterBrightness(ch);
        int total = 0;
        int maxCh = 0;
        for (int i = 0; i < K7_CHANNELS; i++) {
            total += ch[i];
            maxCh = max(maxCh, (int)ch[i]);
        }
        peakTotal = max(peakTotal, total);
        peakChannel = max(peakChannel, maxCh);
        sampleIndex++;
    }

    const int numSamples = sampleIndex;
    const int darkMaxChannel = max(3, (int)roundf(peakChannel * 0.08f));
    const int darkMaxTotal = max(8, (int)roundf(peakTotal * 0.08f));
    const int daylightMinChannel = max(12, (int)roundf(peakChannel * 0.18f));
    const int daylightMinTotal = max(24, (int)roundf(peakTotal * 0.18f));
    int darkRun = 0;
    int maxDarkRun = 0;

    for (int i = 0; i < numSamples; i++) {
        int mins = i * sampleStep;
        uint8_t ch[K7_CHANNELS];
        interpolateChannels(gLastSchedule, mins / 60, mins % 60, ch);
        applyMasterBrightness(ch);
        int total = 0;
        int maxCh = 0;
        for (int c = 0; c < K7_CHANNELS; c++) {
            total += ch[c];
            maxCh = max(maxCh, (int)ch[c]);
        }
        bool isDaylight = (maxCh >= daylightMinChannel) || (total >= daylightMinTotal);
        bool isTrueDark = (maxCh <= darkMaxChannel) && (total <= darkMaxTotal);
        darkFlags[i] = isTrueDark;
        if (isDaylight) litSamples++;
        if (maxCh >= 90) peakSamples++;
    }

    for (int i = 0; i < numSamples * 2; i++) {
        if (darkFlags[i % numSamples]) {
            darkRun += sampleStep;
            maxDarkRun = max(maxDarkRun, darkRun);
        } else {
            darkRun = 0;
        }
    }

    int photoperiodMins = litSamples * sampleStep;
    if (maxDarkRun < 240) {
        addWarning(items, "caution", "no_true_dark",
                   "Main schedule has less than 4 hours of true darkness after ignoring low twilight levels relative to peak output. Lunar is ignored for this check.");
    }
    if (photoperiodMins > 14 * 60) {
        addWarning(items, "check", "long_day",
                   "Effective daylight period is longer than 14 hours, excluding low twilight levels.");
    } else if (photoperiodMins > 0 && photoperiodMins < 6 * 60) {
        addWarning(items, "check", "short_day",
                   "Effective daylight period is shorter than 6 hours, excluding low twilight levels.");
    }
    if (peakSamples * sampleStep >= 240) {
        addWarning(items, "check", "long_peak",
                   "At least one channel stays at 90%+ for 4 hours or more.");
    }

    int acclimationPct = acclimationPercentNow();
    int combinedPct = (int)roundf(acclimationPct * gMasterBrightness / 100.0f);
    if (combinedPct < 60) {
        addWarning(items, "info", "reduced_output",
                   String("Acclimation and master brightness currently cap the schedule to about ") +
                   combinedPct + "% of base output before Siesta/Lunar.");
    }

    if (items.size() == 0) {
        addWarning(items, "ok", "none", "No obvious schedule issues detected.");
    }
    doc["count"] = items.size();
}

static void buildSiestaDoc(JsonDocument& doc) {
    char effectiveStart[8], effectiveEnd[8];
    siestaWindowNow(effectiveStart, effectiveEnd);
    int baseStartMins = parseHHMM(gSiestaConfig.start);
    if (baseStartMins < 0) baseStartMins = 13 * 60;
    char baseEnd[8];
    snprintf(baseEnd, sizeof(baseEnd), "%02d:%02d",
             ((baseStartMins + gSiestaConfig.durationMins) / 60) % 24,
             (baseStartMins + gSiestaConfig.durationMins) % 60);
    int allowedStart = 0, allowedEnd = 0;
    bool allowed = siestaTimeAllowed(parseHHMM(gSiestaConfig.start), gSiestaConfig.durationMins,
                                     &allowedStart, &allowedEnd);
    doc["enabled"]     = gSiestaConfig.enabled;
    doc["start"]       = gSiestaConfig.start;
    doc["end"]         = baseEnd;
    doc["duration"]    = gSiestaConfig.durationMins;
    doc["intensity"]   = gSiestaConfig.intensity;
    doc["active"]      = siestaActiveNow();
    doc["ramp_active"] = gRampActive.load();
    doc["requires_ramp"] = true;
    doc["effective_start"] = effectiveStart;
    doc["effective_end"]   = effectiveEnd;
    doc["schedule_shift_minutes"] = gScheduleShiftMinutes;
    if (allowed || allowedStart != 0 || allowedEnd != 0) {
        char allowedStartStr[8], allowedEndStr[8];
        snprintf(allowedStartStr, sizeof(allowedStartStr), "%02d:%02d", allowedStart / 60, allowedStart % 60);
        snprintf(allowedEndStr, sizeof(allowedEndStr), "%02d:%02d", allowedEnd / 60, allowedEnd % 60);
        doc["allowed_start"] = allowedStartStr;
        doc["allowed_end"]   = allowedEndStr;
    }
}

static SiestaConfig siestaConfigFromDoc(JsonVariantConst src) {
    SiestaConfig cfg = gSiestaConfig;
    if (src["enabled"].is<bool>())      cfg.enabled      = src["enabled"];
    if (src["start"].is<const char*>()) strlcpy(cfg.start, src["start"], sizeof(cfg.start));
    if (src["duration"].is<int>())      cfg.durationMins = max(1, min(720, src["duration"].as<int>()));
    if (src["intensity"].is<int>())     cfg.intensity    = max(1, min(100, src["intensity"].as<int>()));
    return cfg;
}

static bool validateSiestaConfig(const SiestaConfig& cfg, bool rampActive, String* errMsg = nullptr) {
    if (cfg.enabled && !rampActive) {
        if (errMsg) *errMsg = "Siesta requires Smooth Ramp";
        return false;
    }

    int startMins = parseHHMM(cfg.start);
    int allowedStart = 0, allowedEnd = 0;
    if (cfg.enabled && !siestaTimeAllowed(startMins, cfg.durationMins, &allowedStart, &allowedEnd)) {
        if (errMsg) {
            char allowedStartStr[8], allowedEndStr[8];
            snprintf(allowedStartStr, sizeof(allowedStartStr), "%02d:%02d", allowedStart / 60, allowedStart % 60);
            snprintf(allowedEndStr, sizeof(allowedEndStr), "%02d:%02d", allowedEnd / 60, allowedEnd % 60);
            *errMsg = "Choose a siesta window inside the schedule's high-light period";
            if (allowedEnd > allowedStart) {
                *errMsg += " (";
                *errMsg += allowedStartStr;
                *errMsg += "-";
                *errMsg += allowedEndStr;
                *errMsg += ")";
            }
        }
        return false;
    }

    return true;
}

static bool applySiestaDoc(JsonVariantConst src, String* errMsg = nullptr) {
    SiestaConfig cfg = siestaConfigFromDoc(src);
    if (!validateSiestaConfig(cfg, gRampActive.load(), errMsg)) return false;
    gSiestaConfig = cfg;
    return true;
}

// ── Profiles helpers ──────────────────────────────────────────────────────────
static void loadProfiles(JsonDocument& doc) {
    doc.to<JsonObject>();  // ensures {} not null when no profiles file exists
    if (!UserDataFS.exists(PROFILES_FILE)) return;
    File f = UserDataFS.open(PROFILES_FILE, "r");
    if (f) { deserializeJson(doc, f); f.close(); }
}
static void saveProfiles(const JsonDocument& doc) {
    File f = UserDataFS.open(PROFILES_FILE, "w");
    if (f) { serializeJson(doc, f); f.close(); }
}

// ── setupApiServer ────────────────────────────────────────────────────────────
void setupApiServer(WebServer& server) {

    // ── Static files ─────────────────────────────────────────────────────────
    server.serveStatic("/static", LittleFS, "/static", "max-age=3600");

    server.on("/", HTTP_GET, [&server]() {
        String view = server.hasArg("view") ? server.arg("view") : "";
        String ua   = server.hasHeader("User-Agent") ? server.header("User-Agent") : "";
        bool mobile = (view == "mobile") ||
                      (view != "desktop" &&
                       (ua.indexOf("Mobile") >= 0 || ua.indexOf("Android") >= 0 ||
                        ua.indexOf("iPhone") >= 0 || ua.indexOf("iPad")    >= 0));
        const char* path = mobile ? "/static/mobile.html" : "/static/index.html";
        File f = LittleFS.open(path, "r");
        if (!f) { server.send(404, "text/plain", "Not found"); return; }
        server.streamFile(f, "text/html");
        f.close();
    });

    // ── /api/master ───────────────────────────────────────────────────────────
    server.on("/api/master", HTTP_GET, [&server]() {
        JsonDocument doc;
        doc["value"] = gMasterBrightness;
        sendJson(server, doc);
    });
    server.on("/api/master", HTTP_POST, [&server]() {
        JsonDocument doc;
        deserializeJson(doc, server.arg("plain"));
        if (doc["value"].is<int>())
            gMasterBrightness = max(0, min(200, doc["value"].as<int>()));
        saveEffectState();
        // Re-push lamp immediately so MB changes take effect without a separate push.
        // This also eliminates any race with a simultaneous /api/push: whichever
        // handler runs second will overwrite the first push in the queue, and the
        // lamp worker always processes the latest queued job.
        queueCurrentLampStatePush();
        JsonDocument resp;
        resp["value"] = gMasterBrightness;
        sendJson(server, resp);
    });

    // ── /api/devices ──────────────────────────────────────────────────────────
    server.on("/api/devices", HTTP_GET, [&server]() {
        server.send(200, "application/json",
            "{\"k7mini\":{\"label\":\"K7 Mini\","
            "\"channels\":[\"white\",\"royal_blue\",\"blue\"]},"
            "\"k7pro\":{\"label\":\"K7 Pro\","
            "\"channels\":[\"uv\",\"royal_blue\",\"blue\",\"white\",\"warm_white\",\"red\"]}}");
    });

    // ── /api/config ───────────────────────────────────────────────────────────
    server.on("/api/config", HTTP_GET, [&server]() {
        JsonDocument doc;
        doc["host"]   = gLampHost;
        doc["port"]   = LAMP_PORT;
        doc["device"] = gDevice;
        sendJson(server, doc);
    });
    server.on("/api/config", HTTP_POST, [&server]() {
        JsonDocument doc;
        deserializeJson(doc, server.arg("plain"));
        if (doc["host"].is<const char*>())   strlcpy(gLampHost, doc["host"],   sizeof(gLampHost));
        if (doc["device"].is<const char*>()) strlcpy(gDevice,   doc["device"], sizeof(gDevice));
        saveConfigDoc(doc.as<JsonVariantConst>());
        JsonDocument resp;
        resp["host"]   = gLampHost;
        resp["port"]   = LAMP_PORT;
        resp["device"] = gDevice;
        sendJson(server, resp);
    });

    // ── /api/backup ───────────────────────────────────────────────────────────
    server.on("/api/backup", HTTP_GET, [&server]() {
        JsonDocument backup;
        backup["kind"]        = "k7controller_backup";
        backup["schema"]      = 1;
        backup["exported_at"] = (long long)time(nullptr) * 1000LL;
        auto controller = backup["controller"].to<JsonObject>();
        controller["device"]    = gDevice;
        controller["lamp_name"] = gLampName;

        JsonDocument configDoc;
        loadConfigDoc(configDoc);
        backup["config"] = configDoc.as<JsonObject>();

        JsonDocument stateDoc;
        buildStateDoc(stateDoc);
        backup["state"] = stateDoc.as<JsonObject>();

        JsonDocument lunarDoc;
        buildLunarDoc(lunarDoc);
        backup["lunar"] = lunarDoc.as<JsonObject>();

        JsonDocument siestaDoc;
        buildSiestaDoc(siestaDoc);
        backup["siesta"] = siestaDoc.as<JsonObject>();

        JsonDocument acclimationDoc;
        buildAcclimationDoc(acclimationDoc);
        backup["acclimation"] = acclimationDoc.as<JsonObject>();

        JsonDocument seasonalDoc;
        buildSeasonalDoc(seasonalDoc);
        backup["seasonal"] = seasonalDoc.as<JsonObject>();

        JsonDocument profilesDoc;
        loadProfiles(profilesDoc);
        backup["profiles"] = profilesDoc.as<JsonObject>();

        server.sendHeader("Content-Disposition", "attachment; filename=\"k7controller-backup.json\"");
        sendJson(server, backup);
    });
    server.on("/api/backup", HTTP_POST, [&server]() {
        JsonDocument backup;
        if (deserializeJson(backup, server.arg("plain")) != DeserializationError::Ok) {
            sendError(server, "Bad JSON", 400);
            return;
        }
        if (String(backup["kind"] | "") != "k7controller_backup" || (backup["schema"] | 0) != 1) {
            sendError(server, "Unsupported backup format", 400);
            return;
        }

        bool rebootRecommended = false;
        bool applyPush = false;
        if (gFeedActive.load()) stopFeed();
        if (gMaintenanceActive.load()) stopMaintenance();

        JsonDocument profilesDoc;
        if (backup["profiles"].is<JsonObjectConst>())
            profilesDoc.set(backup["profiles"].as<JsonVariantConst>());

        if (backup["siesta"].is<JsonObjectConst>()) {
            String err;
            uint8_t oldBaseSchedule[K7_SLOTS][8];
            uint8_t oldLastSchedule[K7_SLOTS][8];
            memcpy(oldBaseSchedule, gBaseSchedule, sizeof(oldBaseSchedule));
            memcpy(oldLastSchedule, gLastSchedule, sizeof(oldLastSchedule));
            int oldScheduleShift = gScheduleShiftMinutes;
            SeasonalConfig oldSeasonal = gSeasonalConfig;
            AcclimationConfig oldAcclimation = gAcclimationConfig;
            SiestaConfig oldSiesta = gSiestaConfig;

            JsonVariantConst state = backup["state"].as<JsonVariantConst>();
            bool restoredRamp = state["ramp"].is<bool>() ? state["ramp"].as<bool>() : gRampActive.load();
            if (backup["seasonal"].is<JsonObjectConst>())
                applySeasonalDoc(backup["seasonal"].as<JsonVariantConst>());
            if (backup["acclimation"].is<JsonObjectConst>())
                applyAcclimationDoc(backup["acclimation"].as<JsonVariantConst>());
            if (state["schedule_shift_minutes"].is<int>())
                gScheduleShiftMinutes = max(-720, min(720, state["schedule_shift_minutes"].as<int>()));
            if (state["schedule"].is<JsonArrayConst>()) {
                JsonArrayConst arr = state["schedule"].as<JsonArrayConst>();
                for (int h = 0; h < K7_SLOTS && h < (int)arr.size(); h++) {
                    JsonArrayConst row = arr[h].as<JsonArrayConst>();
                    for (int c = 0; c < 8 && c < (int)row.size(); c++)
                        gBaseSchedule[h][c] = (uint8_t)max(0, min(100, row[c].as<int>()));
                }
            }
            rebuildEffectiveSchedule();

            SiestaConfig restoredSiesta = siestaConfigFromDoc(backup["siesta"].as<JsonVariantConst>());
            bool siestaOk = validateSiestaConfig(restoredSiesta, restoredRamp, &err);

            memcpy(gBaseSchedule, oldBaseSchedule, sizeof(gBaseSchedule));
            memcpy(gLastSchedule, oldLastSchedule, sizeof(gLastSchedule));
            gScheduleShiftMinutes = oldScheduleShift;
            gSeasonalConfig = oldSeasonal;
            gAcclimationConfig = oldAcclimation;
            gSiestaConfig = oldSiesta;

            if (!siestaOk) {
                sendError(server, err.c_str(), 400);
                return;
            }
        }

        if (backup["config"].is<JsonObjectConst>()) {
            if (!saveConfigDoc(backup["config"].as<JsonVariantConst>())) {
                sendError(server, "Failed to save config");
                return;
            }
            rebootRecommended = true;
        }

        if (backup["lunar"].is<JsonObjectConst>()) {
            applyLunarDoc(backup["lunar"].as<JsonVariantConst>());
            saveLunarConfig();
        }

        if (backup["acclimation"].is<JsonObjectConst>()) {
            applyAcclimationDoc(backup["acclimation"].as<JsonVariantConst>());
            saveAcclimationConfig();
        }

        if (backup["seasonal"].is<JsonObjectConst>()) {
            applySeasonalDoc(backup["seasonal"].as<JsonVariantConst>());
            saveSeasonalConfig();
        }

        if (backup["siesta"].is<JsonObjectConst>()) {
            gSiestaConfig = siestaConfigFromDoc(backup["siesta"].as<JsonVariantConst>());
            saveSiestaConfig();
        }

        if (!profilesDoc.isNull()) {
            if (!saveJsonFile(PROFILES_FILE, profilesDoc)) {
                sendError(server, "Failed to save profiles");
                return;
            }
        }

        if (backup["state"].is<JsonObjectConst>()) {
            JsonVariantConst state = backup["state"].as<JsonVariantConst>();
            if (state["schedule"].is<JsonArrayConst>()) {
                JsonArrayConst arr = state["schedule"].as<JsonArrayConst>();
                for (int h = 0; h < K7_SLOTS && h < (int)arr.size(); h++) {
                    JsonArrayConst row = arr[h].as<JsonArrayConst>();
                    for (int c = 0; c < 8 && c < (int)row.size(); c++)
                        gBaseSchedule[h][c] = (uint8_t)max(0, min(100, row[c].as<int>()));
                }
                applyPush = true;
            }
            if (state["manual"].is<JsonArrayConst>()) {
                JsonArrayConst arr = state["manual"].as<JsonArrayConst>();
                for (int i = 0; i < K7_CHANNELS && i < (int)arr.size(); i++)
                    gLastManual[i] = (uint8_t)max(0, min(100, arr[i].as<int>()));
                applyPush = true;
            }
            if (state["master_brightness"].is<int>())
                gMasterBrightness = max(0, min(200, state["master_brightness"].as<int>()));
            if (state["schedule_shift_minutes"].is<int>())
                gScheduleShiftMinutes = max(-720, min(720, state["schedule_shift_minutes"].as<int>()));
            if (state["feed_duration"].is<int>())
                gFeedDuration = max(1, min(60, state["feed_duration"].as<int>()));
            if (state["feed_intensity"].is<int>())
                gFeedIntensity = max(1, min(100, state["feed_intensity"].as<int>()));
            if (state["maintenance_duration"].is<int>())
                gMaintenanceDuration = max(1, min(180, state["maintenance_duration"].as<int>()));
            if (state["maintenance_intensity"].is<int>())
                gMaintenanceIntensity = max(1, min(100, state["maintenance_intensity"].as<int>()));
            if (state["auto_mode"].is<bool>())
                gLampAutoMode = state["auto_mode"];
            if (state["active_preset"].is<const char*>())
                strlcpy(gActivePreset, state["active_preset"], sizeof(gActivePreset));

            rebuildEffectiveSchedule();

            if (state["ramp"].is<bool>()) {
                if (state["ramp"].as<bool>()) startRamp();
                else stopRamp();
            }
            if (state["lunar"].is<bool>()) {
                if (state["lunar"].as<bool>()) {
                    gLunarStopped = false;
                    startLunar();
                    lunarApplyNow();
                } else {
                    stopLunar();
                    lunarRestoreNow();
                }
            }
            saveEffectState();
        }

        if (applyPush)
            queueCurrentLampStatePush();

        JsonDocument resp;
        resp["ok"] = true;
        resp["reboot_recommended"] = rebootRecommended;
        sendJson(server, resp);
    });

    // ── /api/time ─────────────────────────────────────────────────────────────
    server.on("/api/time", HTTP_POST, [&server]() {
        JsonDocument doc;
        deserializeJson(doc, server.arg("plain"));
        if (doc["timestamp"].is<long long>()) {
            time_t ts = (time_t)(doc["timestamp"].as<long long>() / 1000);
            struct timeval tv = {ts, 0};
            settimeofday(&tv, nullptr);
            rebuildEffectiveSchedule();
            if (!gFeedActive && !gRampActive && gLampAutoMode)
                queueCurrentLampStatePush();
        }
        sendOk(server);
    });

    // ── /api/state ────────────────────────────────────────────────────────────
    // Returns cached state — no lamp TCP, so page refresh is never blocked.
    // Cache is seeded at boot and kept current by /api/push.
    server.on("/api/state", HTTP_GET, [&server]() {
        JsonDocument doc;
        doc["name"]          = gLampName;
        doc["mode"]          = gLampAutoMode ? "auto" : "manual";
        doc["active_preset"] = gActivePreset;
        doc["schedule_shift_minutes"] = gScheduleShiftMinutes;
        auto schedArr = doc["schedule"].to<JsonArray>();
        for (int h = 0; h < K7_SLOTS; h++) {
            auto row = schedArr.add<JsonArray>();
            row.add(gBaseSchedule[h][0]);
            row.add(gBaseSchedule[h][1]);
            for (int c = 0; c < K7_CHANNELS; c++)
                row.add(gBaseSchedule[h][2+c]);
        }
        auto manArr = doc["manual"].to<JsonArray>();
        for (int i = 0; i < K7_CHANNELS; i++) manArr.add(gLastManual[i]);
        sendJson(server, doc);
    });

    // ── /api/warnings/status ─────────────────────────────────────────────────
    server.on("/api/warnings/status", HTTP_GET, [&server]() {
        JsonDocument doc;
        buildWarningsDoc(doc);
        sendJson(server, doc);
    });

    server.on("/api/output/status", HTTP_GET, [&server]() {
        JsonDocument doc;
        buildOutputStatusDoc(doc);
        sendJson(server, doc);
    });

    // ── /api/push ─────────────────────────────────────────────────────────────
    // The client sends the UNSCALED (base) schedule and raw manual values.
    // MB scaling is applied here so gLastSchedule never holds MB-tainted values.
    // This prevents data corruption at MB=0% and ensures rampTask always reads
    // the correct base regardless of how many times MB has been changed.
    server.on("/api/push", HTTP_POST, [&server]() {
        JsonDocument doc;
        if (deserializeJson(doc, server.arg("plain")) != DeserializationError::Ok) {
            sendError(server, "Bad JSON", 400); return;
        }

        uint8_t manual[K7_CHANNELS] = {};
        JsonArray manArr = doc["manual"];
        for (int i = 0; i < K7_CHANNELS && i < (int)manArr.size(); i++)
            manual[i] = (uint8_t)min(100, manArr[i].as<int>());

        uint8_t sched[K7_SLOTS][8] = {};
        JsonArray schedArr = doc["schedule"];
        for (int h = 0; h < K7_SLOTS && h < (int)schedArr.size(); h++) {
            JsonArray row = schedArr[h];
            for (int c = 0; c < 8 && c < (int)row.size(); c++)
                sched[h][c] = (uint8_t)row[c].as<int>();
        }

        String modeStr    = doc["mode"] | "auto";
        bool userAutoMode = (modeStr != "manual");
        if (doc["schedule_shift_minutes"].is<int>())
            gScheduleShiftMinutes = max(-720, min(720, doc["schedule_shift_minutes"].as<int>()));

        // Store unscaled base; do NOT apply MB here
        memcpy(gBaseSchedule, sched,  sizeof(sched));
        memcpy(gLastManual,   manual, sizeof(manual));
        gLampAutoMode = userAutoMode;
        const char* activePreset = doc["active_preset"].is<const char*>() ? doc["active_preset"].as<const char*>() : nullptr;
        if (activePreset)
            strlcpy(gActivePreset, activePreset, sizeof(gActivePreset));
        const Preset* preset = findPresetByActiveKey(activePreset);
        if (preset && preset->disableLunar) {
            gLunarConfig.enabled = false;
            saveLunarConfig();
            stopLunar();
            lunarRestoreNow();
        }
        rebuildEffectiveSchedule();
        saveEffectState();
        queueCurrentLampStatePush();
        sendOk(server);
    });

    // ── /api/presets ──────────────────────────────────────────────────────────
    server.on("/api/presets", HTTP_GET, [&server]() {
        bool isPro         = (strcmp(gDevice, "k7pro") == 0);
        const Preset* list = isPro ? PRO_PRESETS      : MINI_PRESETS;
        uint8_t       cnt  = isPro ? NUM_PRO_PRESETS   : NUM_MINI_PRESETS;

        JsonDocument doc;
        for (uint8_t i = 0; i < cnt; i++) {
            const Preset& p = list[i];
            auto ps = doc[p.id].to<JsonObject>();
            ps["name"] = p.name;
            ps["desc"] = p.desc;
            if (p.disableLunar) ps["disable_lunar"] = true;
            auto manArr = ps["manual"].to<JsonArray>();
            for (int c = 0; c < K7_CHANNELS; c++) manArr.add(p.manual[c]);

            uint8_t sched[K7_SLOTS][8];
            buildSchedule(p, sched);
            auto schedArr = ps["schedule"].to<JsonArray>();
            for (int h = 0; h < K7_SLOTS; h++) {
                auto row = schedArr.add<JsonArray>();
                for (int c = 0; c < 8; c++) row.add(sched[h][c]);
            }
        }
        sendJson(server, doc);
    });

    // ── /api/profiles ─────────────────────────────────────────────────────────
    server.on("/api/profiles", HTTP_GET, [&server]() {
        JsonDocument doc;
        loadProfiles(doc);
        sendJson(server, doc);
    });
    server.on("/api/profiles", HTTP_POST, [&server]() {
        JsonDocument in;
        deserializeJson(in, server.arg("plain"));
        String name = in["name"] | "";
        name.trim();
        if (name.isEmpty()) { sendError(server, "Name required", 400); return; }
        JsonDocument profiles;
        loadProfiles(profiles);
        profiles[name] = in;
        saveProfiles(profiles);
        sendOk(server);
    });

    // ── /api/preview ──────────────────────────────────────────────────────────
    // Queued async — returns immediately; background task applies to lamp.
    server.on("/api/preview", HTTP_POST, [&server]() {
        JsonDocument doc;
        deserializeJson(doc, server.arg("plain"));
        uint8_t ch[K7_CHANNELS] = {};
        JsonArray arr = doc["channels"];
        for (int i = 0; i < K7_CHANNELS && i < (int)arr.size(); i++)
            ch[i] = (uint8_t)arr[i].as<int>();
        applyMasterBrightness(ch);
        queuePreview(ch);
        sendOk(server);
    });

    // ── /api/ramp/* ───────────────────────────────────────────────────────────
    server.on("/api/ramp/status", HTTP_GET, [&server]() {
        JsonDocument doc;
        doc["active"]    = gRampActive.load();
        doc["last_tick"] = (long long)gRampLastTick;
        sendJson(server, doc);
    });
    server.on("/api/ramp/start", HTTP_POST, [&server]() {
        startRamp();
        saveEffectState();
        sendOk(server);
    });
    server.on("/api/ramp/stop", HTTP_POST, [&server]() {
        stopRamp();
        if (gSiestaConfig.enabled) {
            gSiestaConfig.enabled = false;
            saveSiestaConfig();
        }
        saveEffectState();
        sendOk(server);
    });
    server.on("/api/ramp/tick", HTTP_POST, [&server]() {
        if (gRampActive.load()) queueCurrentLampStatePush();
        sendOk(server);
    });

    // ── /api/feed/* ───────────────────────────────────────────────────────────
    server.on("/api/feed/status", HTTP_GET, [&server]() {
        JsonDocument doc;
        doc["active"]    = gFeedActive.load();
        doc["remaining"] = feedSecondsRemaining();
        doc["duration"]  = gFeedDuration;
        doc["intensity"] = gFeedIntensity;
        sendJson(server, doc);
    });
    server.on("/api/feed/start", HTTP_POST, [&server]() {
        JsonDocument doc;
        deserializeJson(doc, server.arg("plain"));
        if (doc["duration"].is<int>())
            gFeedDuration  = max(1, min(60,  doc["duration"].as<int>()));
        if (doc["intensity"].is<int>())
            gFeedIntensity = max(1, min(100, doc["intensity"].as<int>()));
        startFeed();
        saveEffectState();
        sendOk(server);
    });
    server.on("/api/feed/stop", HTTP_POST, [&server]() {
        stopFeed();
        sendOk(server);
    });

    // ── /api/maintenance/* ───────────────────────────────────────────────────
    server.on("/api/maintenance/status", HTTP_GET, [&server]() {
        JsonDocument doc;
        buildMaintenanceDoc(doc);
        sendJson(server, doc);
    });
    server.on("/api/maintenance/start", HTTP_POST, [&server]() {
        JsonDocument doc;
        deserializeJson(doc, server.arg("plain"));
        if (doc["duration"].is<int>())
            gMaintenanceDuration = max(1, min(180, doc["duration"].as<int>()));
        if (doc["intensity"].is<int>())
            gMaintenanceIntensity = max(1, min(100, doc["intensity"].as<int>()));
        startMaintenance();
        saveEffectState();
        sendOk(server);
    });
    server.on("/api/maintenance/stop", HTTP_POST, [&server]() {
        stopMaintenance();
        sendOk(server);
    });

    // ── /api/siesta/* ─────────────────────────────────────────────────────────
    server.on("/api/siesta/status", HTTP_GET, [&server]() {
        JsonDocument doc;
        buildSiestaDoc(doc);
        sendJson(server, doc);
    });
    server.on("/api/siesta/schedule", HTTP_POST, [&server]() {
        JsonDocument doc;
        deserializeJson(doc, server.arg("plain"));
        String err;
        if (!applySiestaDoc(doc.as<JsonVariantConst>(), &err)) {
            sendError(server, err.c_str(), 400);
            return;
        }
        saveSiestaConfig();
        if (!gFeedActive && !gRampActive) {
            time_t now = time(nullptr);
            struct tm* t = localtime(&now);
            uint8_t ch[K7_CHANNELS];
            interpolateChannels(gLastSchedule, t->tm_hour, t->tm_min, ch);
            applySiestaDimming(ch);
            applyMasterBrightness(ch);
            bool lunarOn = (gLunarActive.load() || (gLunarConfig.enabled && !gLunarStopped.load()))
                           && lunarWindowActiveNow()
                           && lunarScheduleAllowsNow();
            if (lunarOn) applyLunarOverlay(ch);
            sendHandLuminance("siesta", ch);
        }
        JsonDocument resp;
        buildSiestaDoc(resp);
        sendJson(server, resp);
    });

    // ── /api/acclimation/* ───────────────────────────────────────────────────
    server.on("/api/acclimation/status", HTTP_GET, [&server]() {
        JsonDocument doc;
        buildAcclimationDoc(doc);
        sendJson(server, doc);
    });
    server.on("/api/acclimation/config", HTTP_POST, [&server]() {
        JsonDocument doc;
        deserializeJson(doc, server.arg("plain"));
        applyAcclimationDoc(doc.as<JsonVariantConst>());
        saveAcclimationConfig();
        rebuildEffectiveSchedule();
        saveEffectState();
        if (!gFeedActive && !gRampActive && gLampAutoMode)
            queueCurrentLampStatePush();
        JsonDocument resp;
        buildAcclimationDoc(resp);
        sendJson(server, resp);
    });

    // ── /api/seasonal/* ──────────────────────────────────────────────────────
    server.on("/api/seasonal/status", HTTP_GET, [&server]() {
        JsonDocument doc;
        buildSeasonalDoc(doc);
        sendJson(server, doc);
    });
    server.on("/api/seasonal/config", HTTP_POST, [&server]() {
        JsonDocument doc;
        deserializeJson(doc, server.arg("plain"));
        applySeasonalDoc(doc.as<JsonVariantConst>());
        saveSeasonalConfig();
        rebuildEffectiveSchedule();
        saveEffectState();
        if (!gFeedActive && !gRampActive && gLampAutoMode)
            queueCurrentLampStatePush();
        JsonDocument resp;
        buildSeasonalDoc(resp);
        sendJson(server, resp);
    });

    // ── /api/lunar/* ──────────────────────────────────────────────────────────
    server.on("/api/lunar/status", HTTP_GET, [&server]() {
        char effectiveStart[8], effectiveEnd[8];
        int shiftMinutes = 0;
        lunarWindowNow(effectiveStart, effectiveEnd, &shiftMinutes);
        JsonDocument doc;
        doc["active"]        = gLunarActive.load();
        doc["phase"]         = Moon::phase();
        doc["illumination"]  = (int)roundf(Moon::illumination() * 100.0f);
        doc["phase_name"]    = Moon::phaseName();
        doc["enabled"]       = gLunarConfig.enabled;
        doc["start"]         = gLunarConfig.start;
        doc["end"]           = gLunarConfig.end;
        doc["clamp_start"]   = gLunarConfig.clampStart;
        doc["clamp_end"]     = gLunarConfig.clampEnd;
        doc["max_intensity"] = gLunarConfig.maxIntensity;
        doc["day_threshold"] = gLunarConfig.dayThreshold;
        doc["track_moonrise"] = gLunarConfig.trackMoonrise;
        doc["effective_start"] = effectiveStart;
        doc["effective_end"]   = effectiveEnd;
        doc["shift_minutes"]   = shiftMinutes;
        sendJson(server, doc);
    });
    server.on("/api/lunar/start", HTTP_POST, [&server]() {
        startLunar();
        lunarApplyNow();
        saveEffectState();
        sendOk(server);
    });
    server.on("/api/lunar/stop", HTTP_POST, [&server]() {
        stopLunar();
        lunarRestoreNow();
        saveEffectState();
        sendOk(server);
    });
    server.on("/api/lunar/schedule", HTTP_POST, [&server]() {
        JsonDocument doc;
        deserializeJson(doc, server.arg("plain"));
        bool wasEnabled = gLunarConfig.enabled;
        if (doc["enabled"].is<bool>())      gLunarConfig.enabled      = doc["enabled"];
        if (doc["start"].is<const char*>()) strlcpy(gLunarConfig.start, doc["start"], 8);
        if (doc["end"].is<const char*>())   strlcpy(gLunarConfig.end,   doc["end"],   8);
        if (doc["clamp_start"].is<const char*>()) strlcpy(gLunarConfig.clampStart, doc["clamp_start"], 8);
        if (doc["clamp_end"].is<const char*>())   strlcpy(gLunarConfig.clampEnd,   doc["clamp_end"],   8);
        if (doc["max_intensity"].is<int>()) gLunarConfig.maxIntensity  = doc["max_intensity"];
        if (doc["day_threshold"].is<int>()) gLunarConfig.dayThreshold = max(0, min(100, doc["day_threshold"].as<int>()));
        if (doc["track_moonrise"].is<bool>()) gLunarConfig.trackMoonrise = doc["track_moonrise"];
        saveLunarConfig();
        if (!wasEnabled && gLunarConfig.enabled) {
            gLunarStopped = false;
            lunarApplyNow();
        } else if (wasEnabled && !gLunarConfig.enabled) {
            gLunarActive = false;
            lunarRestoreNow();
        } else {
            lunarApplyNow();
        }
        char effectiveStart[8], effectiveEnd[8];
        int shiftMinutes = 0;
        lunarWindowNow(effectiveStart, effectiveEnd, &shiftMinutes);
        JsonDocument resp;
        resp["enabled"]       = gLunarConfig.enabled;
        resp["start"]         = gLunarConfig.start;
        resp["end"]           = gLunarConfig.end;
        resp["clamp_start"]   = gLunarConfig.clampStart;
        resp["clamp_end"]     = gLunarConfig.clampEnd;
        resp["max_intensity"] = gLunarConfig.maxIntensity;
        resp["day_threshold"] = gLunarConfig.dayThreshold;
        resp["track_moonrise"] = gLunarConfig.trackMoonrise;
        resp["effective_start"] = effectiveStart;
        resp["effective_end"]   = effectiveEnd;
        resp["shift_minutes"]   = shiftMinutes;
        sendJson(server, resp);
    });

    // ── Not found — handles DELETE /api/profiles/{name} and 404s ─────────────
    server.onNotFound([&server]() {
        if (server.method() == HTTP_DELETE) {
            String uri = server.uri();
            if (uri.startsWith("/api/profiles/")) {
                String name = urlDecode(uri.substring(strlen("/api/profiles/")));
                JsonDocument profiles;
                loadProfiles(profiles);
                profiles.remove(name.c_str());
                saveProfiles(profiles);
                sendOk(server);
                return;
            }
        }
        server.send(404, "text/plain", "Not found");
    });

    // Must be called before server.begin() so the WebServer collects this
    // header from incoming requests.  Without it, hasHeader("User-Agent")
    // always returns false and every client gets the desktop view.
    static const char* hdrs[] = { "User-Agent" };
    server.collectHeaders(hdrs, 1);
}
