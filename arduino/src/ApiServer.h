#pragma once
#include <WebServer.h>

// Set up all API routes on the given server instance.
// Call after WiFi AP+STA is up and LittleFS is mounted.
void setupApiServer(WebServer& server);
