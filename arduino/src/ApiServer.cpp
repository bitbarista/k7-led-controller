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
    doc["feed_duration"]     = gFeedDuration;
    doc["feed_intensity"]    = gFeedIntensity;
    doc["auto_mode"]         = gLampAutoMode;
    doc["active_preset"]     = gActivePreset;

    auto schedArr = doc["schedule"].to<JsonArray>();
    for (int h = 0; h < K7_SLOTS; h++) {
        auto row = schedArr.add<JsonArray>();
        for (int c = 0; c < 8; c++) row.add(gLastSchedule[h][c]);
    }
    auto manArr = doc["manual"].to<JsonArray>();
    for (int i = 0; i < K7_CHANNELS; i++) manArr.add(gLastManual[i]);
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
        float   mb = gMasterBrightness / 100.0f;
        uint8_t scaledManual[K7_CHANNELS];
        uint8_t scaledSched[K7_SLOTS][8];
        for (int i = 0; i < K7_CHANNELS; i++) {
            int v = (int)roundf(gLastManual[i] * mb);
            scaledManual[i] = (uint8_t)(v > 100 ? 100 : v);
        }
        for (int h = 0; h < K7_SLOTS; h++) {
            scaledSched[h][0] = gLastSchedule[h][0];
            scaledSched[h][1] = gLastSchedule[h][1];
            for (int c = 0; c < K7_CHANNELS; c++) {
                int v = (int)roundf(gLastSchedule[h][2 + c] * mb);
                scaledSched[h][2 + c] = (uint8_t)(v > 100 ? 100 : v);
            }
        }
        queuePush(scaledManual, scaledSched, gLampAutoMode);
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

        if (backup["profiles"].is<JsonObjectConst>()) {
            JsonDocument profilesDoc;
            profilesDoc.set(backup["profiles"].as<JsonVariantConst>());
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
                        gLastSchedule[h][c] = (uint8_t)max(0, min(100, row[c].as<int>()));
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
            if (state["feed_duration"].is<int>())
                gFeedDuration = max(1, min(60, state["feed_duration"].as<int>()));
            if (state["feed_intensity"].is<int>())
                gFeedIntensity = max(1, min(100, state["feed_intensity"].as<int>()));
            if (state["auto_mode"].is<bool>())
                gLampAutoMode = state["auto_mode"];
            if (state["active_preset"].is<const char*>())
                strlcpy(gActivePreset, state["active_preset"], sizeof(gActivePreset));

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
            queuePush(gLastManual, gLastSchedule, gLampAutoMode);

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
        auto schedArr = doc["schedule"].to<JsonArray>();
        for (int h = 0; h < K7_SLOTS; h++) {
            auto row = schedArr.add<JsonArray>();
            row.add(gLastSchedule[h][0]);
            row.add(gLastSchedule[h][1]);
            for (int c = 0; c < K7_CHANNELS; c++)
                row.add(gLastSchedule[h][2+c]);
        }
        auto manArr = doc["manual"].to<JsonArray>();
        for (int i = 0; i < K7_CHANNELS; i++) manArr.add(gLastManual[i]);
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

        // Store unscaled base; do NOT apply MB here
        memcpy(gLastSchedule, sched,  sizeof(sched));
        memcpy(gLastManual,   manual, sizeof(manual));
        gLampAutoMode = userAutoMode;
        if (doc["active_preset"].is<const char*>())
            strlcpy(gActivePreset, doc["active_preset"], sizeof(gActivePreset));
        saveEffectState();

        // Scale by current MB for the lamp push
        float   mb = gMasterBrightness / 100.0f;
        uint8_t scaledManual[K7_CHANNELS];
        uint8_t scaledSched[K7_SLOTS][8];
        for (int i = 0; i < K7_CHANNELS; i++) {
            int v = (int)roundf(manual[i] * mb);
            scaledManual[i] = (uint8_t)(v > 100 ? 100 : v);
        }
        for (int h = 0; h < K7_SLOTS; h++) {
            scaledSched[h][0] = sched[h][0];
            scaledSched[h][1] = sched[h][1];
            for (int c = 0; c < K7_CHANNELS; c++) {
                int v = (int)roundf(sched[h][2 + c] * mb);
                scaledSched[h][2 + c] = (uint8_t)(v > 100 ? 100 : v);
            }
        }
        queuePush(scaledManual, scaledSched, userAutoMode);
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
        saveEffectState();
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
                String name = uri.substring(strlen("/api/profiles/"));
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
