#pragma once
#include <ESPAsyncWebServer.h>

// Set up all API routes on the given server instance.
// Call after WiFi AP+STA is up and LittleFS is mounted.
void setupApiServer(AsyncWebServer& server);
