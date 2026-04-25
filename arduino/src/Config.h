#pragma once
#include <cstdint>
#include <Arduino.h>
#include <esp_mac.h>

// ── Network ───────────────────────────────────────────────────────────────────
static constexpr const char* AP_SSID_SETUP_BASE      = "K7-Setup";
static constexpr const char* AP_SSID_CONTROLLER_BASE = "K7-Controller";
static constexpr const char* AP_PASSWORD             = "12345678";

// Build a unique AP SSID by appending the last 3 MAC bytes, e.g. "K7-Controller-D745A8"
inline String makeApSsid(const char* base) {
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_SOFTAP);
    char suffix[8];
    snprintf(suffix, sizeof(suffix), "-%02X%02X%02X", mac[3], mac[4], mac[5]);
    return String(base) + suffix;
}
static constexpr const char* AP_IP              = "192.168.5.1";
static constexpr const char* LAMP_PASSWORD      = "12345678";
static constexpr const char* LAMP_DEFAULT_IP    = "192.168.4.1";
static constexpr uint16_t    LAMP_PORT          = 8266;

// ── Files ─────────────────────────────────────────────────────────────────────
static constexpr const char* CONFIG_FILE   = "/config.json";
static constexpr const char* PROFILES_FILE = "/profiles.json";
static constexpr const char* LUNAR_FILE    = "/lunar_schedule.json";
static constexpr const char* SIESTA_FILE   = "/siesta_config.json";
static constexpr const char* ACCLIMATION_FILE = "/acclimation_config.json";
static constexpr const char* SEASONAL_FILE    = "/seasonal_config.json";
static constexpr const char* STATE_FILE    = "/state.json";

// ── Lamp protocol ─────────────────────────────────────────────────────────────
static constexpr int K7_CHANNELS = 6;
static constexpr int K7_SLOTS    = 24;
