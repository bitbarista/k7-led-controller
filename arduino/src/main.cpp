#include <Arduino.h>
#include <WiFi.h>
#include <LittleFS.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <ArduinoJson.h>
#include "Config.h"
#include "Effects.h"
#include "Presets.h"
#include "SetupPortal.h"
#include "ApiServer.h"

static WebServer server(80);
static DNSServer dns;

// ── Config loading ────────────────────────────────────────────────────────────
static bool loadConfig(String& lampSsid, String& device) {
    if (!LittleFS.exists(CONFIG_FILE)) return false;
    File f = LittleFS.open(CONFIG_FILE, "r");
    if (!f) return false;
    JsonDocument doc;
    if (deserializeJson(doc, f) != DeserializationError::Ok) { f.close(); return false; }
    f.close();

    // Support old format (suffix + device)
    if (doc["lamp_ssid"].is<const char*>()) {
        lampSsid = doc["lamp_ssid"].as<String>();
    } else if (doc["suffix"].is<const char*>()) {
        String dev    = doc["device"] | "k7mini";
        String prefix = (dev == "k7pro") ? "K7_Pro" : "K7mini";
        lampSsid = prefix + doc["suffix"].as<String>();
    }
    device = doc["device"] | "k7mini";
    return !lampSsid.isEmpty();
}

// ── WiFi ──────────────────────────────────────────────────────────────────────
static bool connectSta(const String& ssid, uint32_t timeoutMs = 20000) {
    WiFi.begin(ssid.c_str(), LAMP_PASSWORD);
    uint32_t start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < timeoutMs) {
        delay(200);
        Serial.print('.');
    }
    Serial.println();
    return WiFi.status() == WL_CONNECTED;
}

static void startAP(const char* ssid, const char* password) {
    WiFi.softAP(ssid, password);
    WiFi.softAPConfig(
        IPAddress(192, 168, 5, 1),
        IPAddress(192, 168, 5, 1),
        IPAddress(255, 255, 255, 0));
    delay(500);
    Serial.printf("AP up: %s @ 192.168.5.1\n", ssid);
}

// ── Setup ─────────────────────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n=== K7 LED Controller (C++ / Arduino) ===");

    if (!LittleFS.begin(true)) {
        Serial.println("LittleFS mount failed — halting");
        while (true) delay(1000);
    }

    gLampMutex = xSemaphoreCreateMutex();

    String lampSsid, device;
    if (!loadConfig(lampSsid, device)) {
        Serial.println("No config — starting setup portal");
        runSetupPortal();   // does not return
        return;
    }

    strlcpy(gDevice, device.c_str(), sizeof(gDevice));
    Serial.printf("Config: lamp=%s device=%s\n", lampSsid.c_str(), device.c_str());

    WiFi.mode(WIFI_AP_STA);
    String apSsid = makeApSsid(AP_SSID_CONTROLLER_BASE);
    startAP(apSsid.c_str(), AP_PASSWORD);

    Serial.printf("Connecting STA -> %s ...", lampSsid.c_str());
    if (connectSta(lampSsid)) {
        Serial.printf(" OK  (%s)\n", WiFi.localIP().toString().c_str());
    } else {
        Serial.println(" FAILED — running without lamp connection");
    }

    // Load effect configs and seed last schedule from lamp
    loadEffectConfigs();
    if (WiFi.status() == WL_CONNECTED) {
        K7Lamp lamp(gLampHost);
        if (lamp.connect()) {
            LampState state;
            if (lamp.readAll(state)) {
                memcpy(gLastSchedule, state.schedule, sizeof(gLastSchedule));
                memcpy(gLastManual,   state.manual,   sizeof(gLastManual));
                strlcpy(gLampName, state.name, sizeof(gLampName));
                // gLampAutoMode is NOT seeded from lamp — it reflects the user's
                // last explicit choice, loaded from the state file by loadEffectState().
                Serial.println("Seeded schedule from lamp");
            }
        }
    }

    // On a fresh install (no state file), apply the Mixed Reef default schedule
    // if the lamp had nothing, and record it as the active preset.
    if (!LittleFS.exists(STATE_FILE)) {
        bool blank = true;
        for (int h = 0; h < K7_SLOTS && blank; h++)
            for (int c = 0; c < K7_CHANNELS && blank; c++)
                if (gLastSchedule[h][2+c]) blank = false;
        if (blank) {
            bool isPro = (strcmp(gDevice, "k7pro") == 0);
            const Preset* list  = isPro ? PRO_PRESETS    : MINI_PRESETS;
            int           count = isPro ? NUM_PRO_PRESETS : NUM_MINI_PRESETS;
            for (int i = 0; i < count; i++) {
                if (strcmp(list[i].id, "mixed") == 0) {
                    buildSchedule(list[i], gLastSchedule);
                    Serial.println("No schedule from lamp — using Mixed Reef default");
                    break;
                }
            }
        }
        strlcpy(gActivePreset, "preset:mixed", sizeof(gActivePreset));
    }

    setupApiServer(server);
    server.begin();
    // DNS after server.begin() so redirected requests find the server ready
    dns.start(53, "*", IPAddress(192, 168, 5, 1));
    Serial.println("Web server + DNS started — http://192.168.5.1");

    // Restore previously active effects (after server is up)
    loadEffectState();
    startEffectSchedulers();
    startLampWorker();
}

// ── Loop ──────────────────────────────────────────────────────────────────────
void loop() {
    dns.processNextRequest();
    server.handleClient();

    // Reconnect STA if lamp AP drops
    static uint32_t lastCheck = 0;
    if (millis() - lastCheck > 30000) {
        lastCheck = millis();
        if (WiFi.status() != WL_CONNECTED) {
            String lampSsid, device;
            if (loadConfig(lampSsid, device)) {
                Serial.println("STA reconnecting...");
                WiFi.reconnect();
            }
        }
    }
}
