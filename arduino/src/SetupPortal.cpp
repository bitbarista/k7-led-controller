#include "SetupPortal.h"
#include "Config.h"
#include <Arduino.h>
#include <WiFi.h>
#include <DNSServer.h>
#include <ESPAsyncWebServer.h>
#include <LittleFS.h>
#include <ArduinoJson.h>
#include <vector>

struct FoundLamp { String ssid; const char* device; };

static std::vector<FoundLamp> scanLamps() {
    std::vector<FoundLamp> found;
    WiFi.mode(WIFI_AP_STA);
    int n = WiFi.scanNetworks(false, true);
    for (int i = 0; i < n; i++) {
        String ssid = WiFi.SSID(i);
        if (ssid.startsWith("K7mini"))
            found.push_back({ssid, "k7mini"});
        else if (ssid.startsWith("K7_Pro"))
            found.push_back({ssid, "k7pro"});
    }
    WiFi.scanDelete();
    return found;
}

static String buildHtml(const std::vector<FoundLamp>& lamps) {
    String css = F(
        "body{font-family:system-ui,sans-serif;max-width:420px;margin:40px auto;"
        "padding:0 20px;background:#0d1117;color:#c9d1d9}"
        "h1{font-size:1.4rem;margin-bottom:4px}"
        "p{color:#8b949e;font-size:.9rem;margin-top:4px}"
        "label{display:block;margin:18px 0 6px;font-size:.9rem;font-weight:600}"
        "select,input{width:100%;padding:8px 10px;background:#161b22;"
        "border:1px solid rgba(255,255,255,.12);color:#c9d1d9;"
        "border-radius:6px;font-size:1rem;box-sizing:border-box}"
        ".btn{margin-top:16px;width:100%;padding:10px;background:#238636;"
        "border:1px solid #2ea043;color:#fff;border-radius:6px;"
        "font-size:1rem;cursor:pointer}"
        ".btn-sec{background:#1f2937;border-color:rgba(255,255,255,.12);margin-top:8px}"
        ".none{color:#f85149;font-size:.9rem;margin-top:12px}"
    );

    String body;
    if (!lamps.empty()) {
        body = F("<h1>K7 Controller Setup</h1>");
        if (lamps.size() == 1) {
            body += "<p>Found: <b>" + lamps[0].ssid + "</b></p>";
            body += "<form method='POST' action='/save'>";
            body += "<input type='hidden' name='lamp_ssid' value='" + lamps[0].ssid + "'>";
            body += "<input type='hidden' name='device' value='" + String(lamps[0].device) + "'>";
            body += "<button class='btn' type='submit'>Connect &amp; Save</button></form>";
        } else {
            body += F("<p>Select your lamp:</p><form method='POST' action='/save'>"
                      "<label>Select lamp</label><select name='lamp_sel'>");
            for (auto& l : lamps)
                body += "<option value='" + l.ssid + "|" + l.device + "'>" + l.ssid + "</option>";
            body += F("</select><button class='btn' type='submit'>Connect &amp; Save</button></form>");
        }
        body += F("<form method='POST' action='/scan'>"
                  "<button class='btn btn-sec' type='submit'>Scan again</button></form>");
    } else {
        body = F("<h1>K7 Controller Setup</h1>"
                 "<p class='none'>No K7 lamp found. Make sure the lamp is powered on.</p>"
                 "<form method='POST' action='/scan'>"
                 "<button class='btn' type='submit'>Scan again</button></form>"
                 "<details style='margin-top:24px'>"
                 "<summary style='font-size:.85rem;color:#8b949e;cursor:pointer'>Enter manually</summary>"
                 "<form method='POST' action='/save' style='margin-top:12px'>"
                 "<label>Lamp SSID (full name)</label>"
                 "<input name='lamp_ssid' placeholder='e.g. K7mini52609' required>"
                 "<button class='btn' type='submit'>Save &amp; Reboot</button>"
                 "</form></details>");
    }

    return "<!DOCTYPE html><html lang='en'><head>"
           "<meta charset='UTF-8'>"
           "<meta name='viewport' content='width=device-width,initial-scale=1'>"
           "<title>K7 Setup</title>"
           "<style>" + css + "</style></head><body>" + body + "</body></html>";
}

static String savedHtml() {
    return F("<!DOCTYPE html><html><head><meta charset='UTF-8'>"
             "<style>body{font-family:system-ui;max-width:420px;margin:40px auto;padding:0 20px;"
             "background:#0d1117;color:#c9d1d9}h1{color:#3fb950}</style></head>"
             "<body><h1>Saved!</h1>"
             "<p>Rebooting &mdash; connect to <b>K7-Controller</b> WiFi "
             "(password: <b>12345678</b>) then browse to <b>http://192.168.5.1</b></p>"
             "</body></html>");
}

static bool saveConfig(const String& lampSsid, const String& device) {
    File f = LittleFS.open(CONFIG_FILE, "w");
    if (!f) return false;
    JsonDocument doc;
    doc["lamp_ssid"] = lampSsid;
    doc["device"]    = device;
    serializeJson(doc, f);
    f.close();
    return true;
}

static String parseParam(const String& body, const String& key) {
    int idx = body.indexOf(key + "=");
    if (idx < 0) return "";
    int start = idx + key.length() + 1;
    int end   = body.indexOf('&', start);
    String val = (end < 0) ? body.substring(start) : body.substring(start, end);
    val.replace("+", " ");
    // URL decode %XX
    String decoded;
    for (int i = 0; i < (int)val.length(); i++) {
        if (val[i] == '%' && i + 2 < (int)val.length()) {
            char hex[3] = {val[i+1], val[i+2], 0};
            decoded += (char)strtol(hex, nullptr, 16);
            i += 2;
        } else {
            decoded += val[i];
        }
    }
    return decoded;
}

void runSetupPortal() {
    Serial.println("Starting setup portal");

    // AP only for scan, then AP+STA for operation
    WiFi.mode(WIFI_AP);
    WiFi.softAP(AP_SSID_SETUP);
    WiFi.softAPConfig(
        IPAddress(192, 168, 5, 1),
        IPAddress(192, 168, 5, 1),
        IPAddress(255, 255, 255, 0));
    delay(500);

    Serial.println("Scanning for lamps...");
    std::vector<FoundLamp> lamps = scanLamps();
    Serial.printf("Found %d lamp(s)\n", (int)lamps.size());

    // Captive portal DNS
    DNSServer dns;
    dns.start(53, "*", IPAddress(192, 168, 5, 1));

    AsyncWebServer server(80);

    // Captive portal probes → redirect
    auto redirect = [](AsyncWebServerRequest* req) {
        req->redirect("http://192.168.5.1/");
    };
    for (auto path : {"/hotspot-detect.html", "/library/test/success.html",
                      "/generate_204", "/gen_204",
                      "/connecttest.txt", "/ncsi.txt",
                      "/redirect", "/canonical.html"}) {
        server.on(path, HTTP_GET, redirect);
    }

    server.on("/", HTTP_GET, [&lamps](AsyncWebServerRequest* req) {
        req->send(200, "text/html", buildHtml(lamps));
    });

    server.on("/scan", HTTP_POST, [&lamps](AsyncWebServerRequest* req) {
        lamps = scanLamps();
        req->send(200, "text/html", buildHtml(lamps));
    });

    // Body accumulation for POST /save
    server.on("/save", HTTP_POST,
        [](AsyncWebServerRequest* req) {},
        nullptr,
        [](AsyncWebServerRequest* req, uint8_t* data, size_t len,
           size_t index, size_t total) {
            // Accumulate body in _tempObject
            if (index == 0) {
                req->_tempObject = new String();
            }
            auto* body = (String*)req->_tempObject;
            body->concat((char*)data, len);

            if (index + len == total) {
                String lampSsid = parseParam(*body, "lamp_ssid");
                String device   = parseParam(*body, "device");
                String lampSel  = parseParam(*body, "lamp_sel");

                if (lampSsid.isEmpty() && !lampSel.isEmpty()) {
                    int pipe = lampSel.indexOf('|');
                    if (pipe >= 0) {
                        lampSsid = lampSel.substring(0, pipe);
                        device   = lampSel.substring(pipe + 1);
                    }
                }
                if (device.isEmpty()) {
                    device = lampSsid.startsWith("K7_Pro") ? "k7pro" : "k7mini";
                }

                delete body;
                req->_tempObject = nullptr;

                if (lampSsid.isEmpty()) {
                    req->send(400, "text/html", "<p>No lamp selected.</p>");
                    return;
                }
                saveConfig(lampSsid, device);
                req->send(200, "text/html", savedHtml());
                delay(3000);
                ESP.restart();
            }
        }
    );

    server.onNotFound([&lamps](AsyncWebServerRequest* req) {
        req->send(200, "text/html", buildHtml(lamps));
    });

    server.begin();
    Serial.printf("Setup portal running — connect to %s\n", AP_SSID_SETUP);

    for (;;) {
        dns.processNextRequest();
        delay(10);
    }
}
