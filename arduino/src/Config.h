#pragma once
#include <cstdint>

// ── Network ───────────────────────────────────────────────────────────────────
static constexpr const char* AP_SSID_SETUP      = "K7-Setup";
static constexpr const char* AP_SSID_CONTROLLER = "K7-Controller";
static constexpr const char* AP_PASSWORD        = "12345678";
static constexpr const char* AP_IP              = "192.168.5.1";
static constexpr const char* LAMP_PASSWORD      = "12345678";
static constexpr const char* LAMP_DEFAULT_IP    = "192.168.4.1";
static constexpr uint16_t    LAMP_PORT          = 8266;

// ── Files ─────────────────────────────────────────────────────────────────────
static constexpr const char* CONFIG_FILE            = "/config.json";
static constexpr const char* PROFILES_FILE          = "/profiles.json";
static constexpr const char* LIGHTNING_SCHEDULE_FILE = "/lightning_schedule.json";
static constexpr const char* LUNAR_FILE             = "/lunar_schedule.json";
static constexpr const char* CLOUD_FILE             = "/cloud_settings.json";
static constexpr const char* STATE_FILE             = "/state.json";

// ── Lamp protocol ─────────────────────────────────────────────────────────────
static constexpr int K7_CHANNELS = 6;
static constexpr int K7_SLOTS    = 24;
