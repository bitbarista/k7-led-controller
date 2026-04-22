#include <Arduino.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include <LittleFS.h>
#include <WebServer.h>
#include <ArduinoJson.h>
#include "Config.h"
#include "Effects.h"
#include "Presets.h"
#include "SetupPortal.h"
#include "ApiServer.h"

static WebServer server(80);

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

// ── Setup ─────────────────────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n=== K7 LED Controller (C++ / Arduino) ===");

    if (!LittleFS.begin(true)) {
        Serial.println("LittleFS mount failed — halting");
        while (true) delay(1000);
    }

    // Boot button (GPIO0) held for 3 s on power-up → factory reset
    pinMode(0, INPUT_PULLUP);
    if (digitalRead(0) == LOW) {
        Serial.println("Boot button held — release within 3 s to cancel factory reset");
        uint32_t held = millis();
        while (digitalRead(0) == LOW && millis() - held < 3000) delay(50);
        if (millis() - held >= 3000) {
            LittleFS.remove(CONFIG_FILE);
            Serial.println("Config cleared — rebooting into setup portal");
            delay(500);
            ESP.restart();
        }
        Serial.println("Cancelled");
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

    // STA-only: no AP, no radio timesharing — eliminates push delivery delays
    WiFi.mode(WIFI_STA);
    Serial.printf("Connecting STA -> %s ...", lampSsid.c_str());
    if (connectSta(lampSsid)) {
        Serial.printf(" OK  (%s)\n", WiFi.localIP().toString().c_str());
        MDNS.begin("k7controller");
        MDNS.addService("http", "tcp", 80);
        Serial.println("mDNS: http://k7controller.local");
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
                Serial.println("Seeded schedule from lamp");
            }
        }
    }

    // On a fresh install (no state file), apply the Mixed Reef default schedule
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
    Serial.println("Web server started — http://k7controller.local");

    // Restore previously active effects (after server is up)
    loadEffectState();
    startEffectSchedulers();
    startLampWorker();
}

// ── Loop ──────────────────────────────────────────────────────────────────────
void loop() {
    server.handleClient();

    // Reconnect STA + restart mDNS if WiFi drops, or re-announce mDNS periodically
    // (ESP32 mDNS library stops responding after extended uptime)
    static uint32_t lastCheck  = 0;
    static uint32_t lastMdns   = 0;
    static bool     wasConnected = false;
    bool connected = (WiFi.status() == WL_CONNECTED);

    if (millis() - lastCheck > 30000) {
        lastCheck = millis();
        if (!connected) {
            wasConnected = false;
            String lampSsid, device;
            if (loadConfig(lampSsid, device)) {
                Serial.println("STA reconnecting...");
                WiFi.reconnect();
            }
        } else if (!wasConnected) {
            wasConnected = true;
            MDNS.end();
            MDNS.begin("k7controller");
            MDNS.addService("http", "tcp", 80);
            lastMdns = millis();
            Serial.println("mDNS restarted after reconnect");
        }
    }

    // Re-announce mDNS every 10 minutes regardless
    if (connected && millis() - lastMdns > 600000) {
        lastMdns = millis();
        MDNS.end();
        MDNS.begin("k7controller");
        MDNS.addService("http", "tcp", 80);
        Serial.println("mDNS re-announced");
    }
}
