#include "ApiServer.h"
#include "Config.h"
#include "Effects.h"
#include "Presets.h"
#include "Moon.h"
#include "K7Lamp.h"
#include <LittleFS.h>
#include <ArduinoJson.h>
#include <ESPAsyncWebServer.h>
#include <time.h>

// ── Body-accumulation helper ──────────────────────────────────────────────────
// Used for every POST endpoint that needs a JSON body.

using BodyHandler = std::function<void(AsyncWebServerRequest*, const String& body)>;

static void onBody(AsyncWebServerRequest* req, uint8_t* data, size_t len,
                   size_t index, size_t total) {
    if (index == 0) req->_tempObject = new String();
    ((String*)req->_tempObject)->concat((char*)data, len);
    if (index + len < total) return;

    String* body = (String*)req->_tempObject;
    req->_tempObject = nullptr;

    // The actual handler is stored as a BodyHandler* in the request path attribute.
    // We use a per-route lambda captured via a task spawn instead.
    // Handled by the lambda in each route's body callback; this is just the shared flush.
    delete body;
}

// Convenience: register a POST route with JSON body support.
// The handler receives the raw body string.
static void postJson(AsyncWebServer& srv, const char* path, BodyHandler handler) {
    // We box the handler into a heap object so the lambda can capture it safely.
    auto* h = new BodyHandler(std::move(handler));
    srv.on(path, HTTP_POST,
        [](AsyncWebServerRequest* req) {},
        nullptr,
        [h](AsyncWebServerRequest* req, uint8_t* data, size_t len,
             size_t index, size_t total) {
            if (index == 0) req->_tempObject = new String();
            ((String*)req->_tempObject)->concat((char*)data, len);
            if (index + len < total) return;
            String body = *(String*)req->_tempObject;
            delete (String*)req->_tempObject;
            req->_tempObject = nullptr;
            (*h)(req, body);
        }
    );
}

// ── JSON response helpers ─────────────────────────────────────────────────────
static void sendJson(AsyncWebServerRequest* req, const JsonDocument& doc,
                     int code = 200) {
    String out;
    serializeJson(doc, out);
    req->send(code, "application/json", out);
}

static void sendOk(AsyncWebServerRequest* req) {
    req->send(200, "application/json", "{\"ok\":true}");
}

static void sendError(AsyncWebServerRequest* req, const char* msg, int code = 500) {
    String j = "{\"error\":\"";
    j += msg;
    j += "\"}";
    req->send(code, "application/json", j);
}

// ── Lamp task helper ──────────────────────────────────────────────────────────
// Spawns a short-lived FreeRTOS task so we don't block the lwIP thread.
struct LampTaskCtx {
    AsyncWebServerRequest* req;
    std::function<void(AsyncWebServerRequest*)> fn;
};

static void lampTaskRun(void* arg) {
    auto* ctx = (LampTaskCtx*)arg;
    ctx->fn(ctx->req);
    delete ctx;
    vTaskDelete(nullptr);
}

static void spawnLampTask(AsyncWebServerRequest* req,
                          std::function<void(AsyncWebServerRequest*)> fn) {
    auto* ctx = new LampTaskCtx{req, std::move(fn)};
    xTaskCreate(lampTaskRun, "api", 8192, ctx, 4, nullptr);
}

// ── Profiles helpers ──────────────────────────────────────────────────────────
static void loadProfiles(JsonDocument& doc) {
    doc.clear();
    if (!LittleFS.exists(PROFILES_FILE)) return;
    File f = LittleFS.open(PROFILES_FILE, "r");
    if (f) { deserializeJson(doc, f); f.close(); }
}

static void saveProfiles(const JsonDocument& doc) {
    File f = LittleFS.open(PROFILES_FILE, "w");
    if (f) { serializeJson(doc, f); f.close(); }
}

// ── setupApiServer ────────────────────────────────────────────────────────────
void setupApiServer(AsyncWebServer& server) {

    // ── Static files ─────────────────────────────────────────────────────────
    server.serveStatic("/static", LittleFS, "/static")
          .setCacheControl("max-age=3600");

    server.on("/", HTTP_GET, [](AsyncWebServerRequest* req) {
        String view = req->hasArg("view") ? req->arg("view") : "";
        String ua   = req->hasHeader("User-Agent")
                      ? req->header("User-Agent") : "";
        bool mobile = (view == "mobile") ||
                      (view != "desktop" &&
                       (ua.indexOf("Mobile") >= 0 || ua.indexOf("Android") >= 0 ||
                        ua.indexOf("iPhone") >= 0 || ua.indexOf("iPad")    >= 0));
        req->send(LittleFS,
                  mobile ? "/static/mobile.html" : "/static/index.html",
                  "text/html");
    });

    // ── Captive portal redirects ──────────────────────────────────────────────
    auto redir = [](AsyncWebServerRequest* req) {
        req->redirect("http://192.168.5.1/");
    };
    for (auto p : {"/hotspot-detect.html", "/library/test/success.html",
                   "/generate_204",         "/gen_204",
                   "/connecttest.txt",       "/ncsi.txt",
                   "/redirect",              "/canonical.html"}) {
        server.on(p, HTTP_GET, redir);
    }

    // ── /api/master ───────────────────────────────────────────────────────────
    server.on("/api/master", HTTP_GET, [](AsyncWebServerRequest* req) {
        JsonDocument doc;
        doc["value"] = gMasterBrightness;
        sendJson(req, doc);
    });
    postJson(server, "/api/master", [](AsyncWebServerRequest* req, const String& body) {
        JsonDocument doc;
        deserializeJson(doc, body);
        if (doc["value"].is<int>()) {
            gMasterBrightness = max(0, min(200, doc["value"].as<int>()));
        }
        JsonDocument resp;
        resp["value"] = gMasterBrightness;
        sendJson(req, resp);
    });

    // ── /api/devices ──────────────────────────────────────────────────────────
    server.on("/api/devices", HTTP_GET, [](AsyncWebServerRequest* req) {
        req->send(200, "application/json",
            "{\"k7mini\":{\"label\":\"K7 Mini\","
            "\"channels\":[\"white\",\"royal_blue\",\"blue\"]},"
            "\"k7pro\":{\"label\":\"K7 Pro\","
            "\"channels\":[\"uv\",\"royal_blue\",\"blue\",\"white\",\"warm_white\",\"red\"]}}");
    });

    // ── /api/config ───────────────────────────────────────────────────────────
    server.on("/api/config", HTTP_GET, [](AsyncWebServerRequest* req) {
        JsonDocument doc;
        doc["host"]   = gLampHost;
        doc["port"]   = LAMP_PORT;
        doc["device"] = gDevice;
        sendJson(req, doc);
    });
    postJson(server, "/api/config", [](AsyncWebServerRequest* req, const String& body) {
        JsonDocument doc;
        deserializeJson(doc, body);
        if (doc["host"].is<const char*>())   strlcpy(gLampHost, doc["host"],   sizeof(gLampHost));
        if (doc["device"].is<const char*>()) strlcpy(gDevice,   doc["device"], sizeof(gDevice));
        JsonDocument resp;
        resp["host"]   = gLampHost;
        resp["port"]   = LAMP_PORT;
        resp["device"] = gDevice;
        sendJson(req, resp);
    });

    // ── /api/time ─────────────────────────────────────────────────────────────
    postJson(server, "/api/time", [](AsyncWebServerRequest* req, const String& body) {
        JsonDocument doc;
        deserializeJson(doc, body);
        if (doc["timestamp"].is<long long>()) {
            time_t ts = (time_t)(doc["timestamp"].as<long long>() / 1000);
            struct timeval tv = {ts, 0};
            settimeofday(&tv, nullptr);
        }
        sendOk(req);
    });

    // ── /api/state ────────────────────────────────────────────────────────────
    server.on("/api/state", HTTP_GET, [](AsyncWebServerRequest* req) {
        spawnLampTask(req, [](AsyncWebServerRequest* req) {
            LampState state;
            bool ok = false;
            if (xSemaphoreTake(gLampMutex, pdMS_TO_TICKS(6000)) == pdTRUE) {
                K7Lamp lamp(gLampHost);
                if (lamp.connect()) ok = lamp.readAll(state);
                xSemaphoreGive(gLampMutex);
            }
            if (!ok) { sendError(req, "Connection failed"); return; }

            JsonDocument doc;
            doc["name"]     = state.name;
            doc["mode"]     = state.autoMode ? "auto" : "manual";
            // Return gLastSchedule unscaled so the UI can apply its own master
            float mb = gMasterBrightness > 0 ? gMasterBrightness / 100.0f : 1.0f;
            auto schedArr = doc["schedule"].to<JsonArray>();
            for (int h = 0; h < K7_SLOTS; h++) {
                auto row = schedArr.add<JsonArray>();
                row.add(gLastSchedule[h][0]);
                row.add(gLastSchedule[h][1]);
                for (int c = 0; c < K7_CHANNELS; c++) {
                    int v = (int)roundf((gLastSchedule[h][2+c]) / mb);
                    row.add(min(100, v));
                }
            }
            auto manArr = doc["manual"].to<JsonArray>();
            for (int i = 0; i < K7_CHANNELS; i++) manArr.add(state.manual[i]);
            sendJson(req, doc);
        });
    });

    // ── /api/push ─────────────────────────────────────────────────────────────
    postJson(server, "/api/push", [](AsyncWebServerRequest* req, const String& body) {
        spawnLampTask(req, [body](AsyncWebServerRequest* req) {
            JsonDocument doc;
            if (deserializeJson(doc, body) != DeserializationError::Ok) {
                sendError(req, "Bad JSON", 400); return;
            }
            // Parse manual
            uint8_t manual[K7_CHANNELS] = {};
            JsonArray manArr = doc["manual"];
            for (int i = 0; i < K7_CHANNELS && i < (int)manArr.size(); i++)
                manual[i] = (uint8_t)manArr[i].as<int>();

            // Parse schedule
            uint8_t sched[K7_SLOTS][8] = {};
            JsonArray schedArr = doc["schedule"];
            for (int h = 0; h < K7_SLOTS && h < (int)schedArr.size(); h++) {
                JsonArray row = schedArr[h];
                for (int c = 0; c < 8 && c < (int)row.size(); c++)
                    sched[h][c] = (uint8_t)row[c].as<int>();
            }

            String modeStr = doc["mode"] | "auto";
            bool   autoMode = (modeStr != "manual");
            if (gRampActive) autoMode = false;   // ramp owns the lamp

            // Apply master brightness before pushing to lamp
            uint8_t scaledManual[K7_CHANNELS];
            uint8_t scaledSched[K7_SLOTS][8];
            for (int i = 0; i < K7_CHANNELS; i++) {
                int v = (int)roundf(manual[i] * gMasterBrightness / 100.0f);
                scaledManual[i] = (uint8_t)min(100, v);
            }
            for (int h = 0; h < K7_SLOTS; h++) {
                scaledSched[h][0] = sched[h][0];
                scaledSched[h][1] = sched[h][1];
                for (int c = 0; c < K7_CHANNELS; c++) {
                    int v = (int)roundf(sched[h][2+c] * gMasterBrightness / 100.0f);
                    scaledSched[h][2+c] = (uint8_t)min(100, v);
                }
            }

            bool ok = false;
            if (xSemaphoreTake(gLampMutex, pdMS_TO_TICKS(6000)) == pdTRUE) {
                K7Lamp lamp(gLampHost);
                if (lamp.connect()) {
                    ok = lamp.pushSchedule(scaledManual, scaledSched, autoMode);
                }
                xSemaphoreGive(gLampMutex);
            }
            // Store unscaled schedule for effects to reference
            memcpy(gLastSchedule, sched, sizeof(sched));
            memcpy(gLastManual,   manual, sizeof(manual));

            if (!ok) { sendError(req, "Connection failed", 503); return; }
            lunarApplyNow();
            sendOk(req);
        });
    });

    // ── /api/presets ──────────────────────────────────────────────────────────
    server.on("/api/presets", HTTP_GET, [](AsyncWebServerRequest* req) {
        bool isPro = (strcmp(gDevice, "k7pro") == 0);
        const Preset* list  = isPro ? PRO_PRESETS  : MINI_PRESETS;
        uint8_t       count = isPro ? NUM_PRO_PRESETS : NUM_MINI_PRESETS;

        JsonDocument doc;
        for (uint8_t i = 0; i < count; i++) {
            const Preset& p  = list[i];
            auto           ps = doc[p.id].to<JsonObject>();
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
        sendJson(req, doc);
    });

    // ── /api/profiles ─────────────────────────────────────────────────────────
    server.on("/api/profiles", HTTP_GET, [](AsyncWebServerRequest* req) {
        JsonDocument doc;
        loadProfiles(doc);
        sendJson(req, doc);
    });
    postJson(server, "/api/profiles", [](AsyncWebServerRequest* req, const String& body) {
        JsonDocument in;
        deserializeJson(in, body);
        String name = in["name"] | "";
        name.trim();
        if (name.isEmpty()) { sendError(req, "Name required", 400); return; }
        JsonDocument profiles;
        loadProfiles(profiles);
        profiles[name] = in;
        saveProfiles(profiles);
        sendOk(req);
    });
    server.on("/api/profiles/*", HTTP_DELETE, [](AsyncWebServerRequest* req) {
        String path = req->url();
        String name = path.substring(path.lastIndexOf('/') + 1);
        JsonDocument profiles;
        loadProfiles(profiles);
        profiles.remove(name);
        saveProfiles(profiles);
        sendOk(req);
    });

    // ── /api/preview ──────────────────────────────────────────────────────────
    postJson(server, "/api/preview", [](AsyncWebServerRequest* req, const String& body) {
        spawnLampTask(req, [body](AsyncWebServerRequest* req) {
            JsonDocument doc;
            deserializeJson(doc, body);
            uint8_t ch[K7_CHANNELS] = {};
            JsonArray arr = doc["channels"];
            for (int i = 0; i < K7_CHANNELS && i < (int)arr.size(); i++)
                ch[i] = (uint8_t)arr[i].as<int>();
            applyMasterBrightness(ch);
            bool ok = withLamp([&](K7Lamp& lamp) { lamp.previewBrightness(ch); });
            if (ok) sendOk(req); else sendError(req, "Connection failed");
        });
    });

    // ── /api/lightning/* ──────────────────────────────────────────────────────
    server.on("/api/lightning/status", HTTP_GET, [](AsyncWebServerRequest* req) {
        JsonDocument doc;
        doc["active"]  = gLightningActive;
        doc["enabled"] = gLightningSchedule.enabled;
        doc["start"]   = gLightningSchedule.start;
        doc["end"]     = gLightningSchedule.end;
        sendJson(req, doc);
    });
    server.on("/api/lightning/start", HTTP_POST, [](AsyncWebServerRequest* req) {
        gLightningUserEnabled = true;
        gLightningUserStopped = false;
        startLightning();
        saveEffectState();
        sendOk(req);
    });
    server.on("/api/lightning/stop", HTTP_POST, [](AsyncWebServerRequest* req) {
        gLightningUserEnabled = false;
        gLightningUserStopped = true;
        stopLightning();
        saveEffectState();
        sendOk(req);
    });
    server.on("/api/lightning/schedule", HTTP_GET, [](AsyncWebServerRequest* req) {
        JsonDocument doc;
        doc["enabled"] = gLightningSchedule.enabled;
        doc["start"]   = gLightningSchedule.start;
        doc["end"]     = gLightningSchedule.end;
        sendJson(req, doc);
    });
    postJson(server, "/api/lightning/schedule",
             [](AsyncWebServerRequest* req, const String& body) {
        JsonDocument doc;
        deserializeJson(doc, body);
        bool wasEnabled = gLightningSchedule.enabled;
        if (doc["enabled"].is<bool>()) gLightningSchedule.enabled = doc["enabled"];
        if (doc["start"].is<const char*>()) strlcpy(gLightningSchedule.start, doc["start"], 8);
        if (doc["end"].is<const char*>())   strlcpy(gLightningSchedule.end,   doc["end"],   8);
        saveLightningSchedule();
        if (!wasEnabled && gLightningSchedule.enabled)
            gLightningUserStopped = false;
        else if (wasEnabled && !gLightningSchedule.enabled) {
            if (gLightningUserEnabled) startLightning();
            else gLightningActive = false;
        }
        JsonDocument resp;
        resp["enabled"] = gLightningSchedule.enabled;
        resp["start"]   = gLightningSchedule.start;
        resp["end"]     = gLightningSchedule.end;
        sendJson(req, resp);
    });

    // ── /api/ramp/* ───────────────────────────────────────────────────────────
    server.on("/api/ramp/status", HTTP_GET, [](AsyncWebServerRequest* req) {
        JsonDocument doc;
        doc["active"] = gRampActive;
        sendJson(req, doc);
    });
    server.on("/api/ramp/start", HTTP_POST, [](AsyncWebServerRequest* req) {
        spawnLampTask(req, [](AsyncWebServerRequest* req) {
            startRamp();
            saveEffectState();
            sendOk(req);
        });
    });
    server.on("/api/ramp/stop", HTTP_POST, [](AsyncWebServerRequest* req) {
        spawnLampTask(req, [](AsyncWebServerRequest* req) {
            stopRamp();
            saveEffectState();
            sendOk(req);
        });
    });

    // ── /api/lunar/* ──────────────────────────────────────────────────────────
    server.on("/api/lunar/status", HTTP_GET, [](AsyncWebServerRequest* req) {
        JsonDocument doc;
        doc["active"]        = gLunarActive;
        doc["phase"]         = Moon::phase();
        doc["illumination"]  = (int)roundf(Moon::illumination() * 100.0f);
        doc["phase_name"]    = Moon::phaseName();
        doc["enabled"]       = gLunarConfig.enabled;
        doc["start"]         = gLunarConfig.start;
        doc["end"]           = gLunarConfig.end;
        doc["max_intensity"] = gLunarConfig.maxIntensity;
        sendJson(req, doc);
    });
    server.on("/api/lunar/start", HTTP_POST, [](AsyncWebServerRequest* req) {
        spawnLampTask(req, [](AsyncWebServerRequest* req) {
            startLunar();
            lunarApplyNow();
            saveEffectState();
            sendOk(req);
        });
    });
    server.on("/api/lunar/stop", HTTP_POST, [](AsyncWebServerRequest* req) {
        spawnLampTask(req, [](AsyncWebServerRequest* req) {
            stopLunar();
            lunarRestoreNow();
            saveEffectState();
            sendOk(req);
        });
    });
    postJson(server, "/api/lunar/schedule",
             [](AsyncWebServerRequest* req, const String& body) {
        spawnLampTask(req, [body](AsyncWebServerRequest* req) {
            JsonDocument doc;
            deserializeJson(doc, body);
            bool wasEnabled = gLunarConfig.enabled;
            if (doc["enabled"].is<bool>())       gLunarConfig.enabled      = doc["enabled"];
            if (doc["start"].is<const char*>())  strlcpy(gLunarConfig.start, doc["start"], 8);
            if (doc["end"].is<const char*>())    strlcpy(gLunarConfig.end,   doc["end"],   8);
            if (doc["max_intensity"].is<int>())  gLunarConfig.maxIntensity  = doc["max_intensity"];
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
            JsonDocument resp;
            resp["enabled"]       = gLunarConfig.enabled;
            resp["start"]         = gLunarConfig.start;
            resp["end"]           = gLunarConfig.end;
            resp["max_intensity"] = gLunarConfig.maxIntensity;
            sendJson(req, resp);
        });
    });

    // ── /api/clouds/* ─────────────────────────────────────────────────────────
    server.on("/api/clouds/status", HTTP_GET, [](AsyncWebServerRequest* req) {
        JsonDocument doc;
        doc["active"]       = gCloudActive;
        doc["density"]      = gCloudSettings.density;
        doc["depth"]        = gCloudSettings.depth;
        doc["colour_shift"] = gCloudSettings.colourShift;
        sendJson(req, doc);
    });
    server.on("/api/clouds/start", HTTP_POST, [](AsyncWebServerRequest* req) {
        startCloud();
        saveEffectState();
        sendOk(req);
    });
    server.on("/api/clouds/stop", HTTP_POST, [](AsyncWebServerRequest* req) {
        stopCloud();
        saveEffectState();
        sendOk(req);
    });
    postJson(server, "/api/clouds/settings",
             [](AsyncWebServerRequest* req, const String& body) {
        JsonDocument doc;
        deserializeJson(doc, body);
        if (doc["density"].is<int>())       gCloudSettings.density     = doc["density"];
        if (doc["depth"].is<int>())         gCloudSettings.depth       = doc["depth"];
        if (doc["colour_shift"].is<bool>()) gCloudSettings.colourShift = doc["colour_shift"];
        saveCloudSettings();
        sendOk(req);
    });
}
