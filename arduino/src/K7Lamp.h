#pragma once
#include <Arduino.h>
#include <WiFiClient.h>
#include "Config.h"

struct LampState {
    char    name[12] = {};
    bool    autoMode = true;
    uint8_t manual[K7_CHANNELS]    = {};
    uint8_t schedule[K7_SLOTS][8]  = {};   // per slot: [h, m, c0..c5]
    bool    valid = false;
};

class K7Lamp {
public:
    explicit K7Lamp(const char* host = LAMP_DEFAULT_IP,
                    uint16_t    port = LAMP_PORT,
                    uint32_t    timeoutMs = 500);
    ~K7Lamp() { close(); }

    bool connect();
    bool connected() { return _client.connected(); }
    void close();

    bool readAll(LampState& out);
    bool handLuminance(const uint8_t ch[K7_CHANNELS]);
    bool handLuminanceFast(const uint8_t ch[K7_CHANNELS]); // no ACK wait — for smooth fade loops
    bool previewBrightness(const uint8_t ch[K7_CHANNELS]);
    bool setModeAuto();
    bool setModeManual();
    bool syncTime();
    bool pushSchedule(const uint8_t manual[K7_CHANNELS],
                      const uint8_t sched[K7_SLOTS][8],
                      bool autoMode);

private:
    const char* _host;
    uint16_t    _port;
    uint32_t    _timeoutMs;
    WiFiClient  _client;

    void   _sendPkt(uint8_t cmdHi, uint8_t cmdLo,
                    const uint8_t* data = nullptr, size_t len = 0);
    size_t _recv(uint8_t* buf, size_t maxLen, bool drain = false);
    void   _recvAck();   // short-timeout drain for fire-and-forget commands
};
