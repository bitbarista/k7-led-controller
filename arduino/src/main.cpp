#include <Arduino.h>
#include <WiFi.h>
#include <LittleFS.h>
#include <ESPAsyncWebServer.h>
#include <ArduinoJson.h>
#include "Config.h"
#include "Effects.h"
#include "SetupPortal.h"
#include "ApiServer.h"

static AsyncWebServer server(80);

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
    startAP(AP_SSID_CONTROLLER, AP_PASSWORD);

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
                Serial.println("Seeded schedule from lamp");
            }
        }
    }

    setupApiServer(server);
    server.begin();
    Serial.println("Web server started — http://192.168.5.1");

    // Restore previously active effects (after server is up)
    loadEffectState();
    startEffectSchedulers();
}

// ── Loop ──────────────────────────────────────────────────────────────────────
void loop() {
    // Everything runs in async tasks / web server callbacks.
    // Reconnect STA if lamp AP drops.
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
    delay(100);
}
