#include "K7Lamp.h"
#include <time.h>

// ── Protocol constants ────────────────────────────────────────────────────────
static const uint8_t PKT_START[2]  = {0xAA, 0xA5};
static const uint8_t PKT_END       = 0xBB;
static const uint8_t RESP_MAGIC[2] = {0xAB, 0xAA};

static const uint8_t CMD_SYNC_TIME[2]         = {0x10, 0x03};
static const uint8_t CMD_CHANGE_MODE[2]       = {0x10, 0x04};
static const uint8_t CMD_HAND_LUMINANCE[2]    = {0x10, 0x05};
static const uint8_t CMD_PREVIEW_LUMINANCE[2] = {0x10, 0x06};
static const uint8_t CMD_ALL_SET[2]           = {0x10, 0x07};
static const uint8_t CMD_ALL_READ[2]          = {0x10, 0x08};

// ── Constructor ───────────────────────────────────────────────────────────────
K7Lamp::K7Lamp(const char* host, uint16_t port, uint32_t timeoutMs)
    : _host(host), _port(port), _timeoutMs(timeoutMs) {}

// ── connect / close ───────────────────────────────────────────────────────────
bool K7Lamp::connect() {
    uint32_t t0 = millis();
    if (!_client.connect(_host, _port, (int32_t)_timeoutMs)) {
        Serial.printf("[K7] TCP connect FAILED (%lu ms)\n", millis() - t0);
        return false;
    }
    Serial.printf("[K7] TCP connected in %lu ms\n", millis() - t0);

    // Drain any greeting the lamp sends on connect.
    // Confirmed: K7 lamp sends 0 greeting bytes.  Cap at 10 ms so we don't
    // waste time on the drain; real timeout stays in saved below.
    uint32_t saved = _timeoutMs;
    _timeoutMs = 10;
    uint8_t buf[64];
    size_t greet = _recv(buf, sizeof(buf), false);
    Serial.printf("[K7] greeting drain: %u bytes in %lu ms\n", (unsigned)greet, millis() - t0);
    _timeoutMs = saved;
    _client.setTimeout(_timeoutMs / 1000);
    return true;
}

void K7Lamp::close() {
    _client.stop();
}

// ── Internal helpers ──────────────────────────────────────────────────────────
void K7Lamp::_sendPkt(uint8_t cmdHi, uint8_t cmdLo,
                       const uint8_t* data, size_t len) {
    _client.write(PKT_START, 2);
    _client.write(cmdHi);
    _client.write(cmdLo);
    if (data && len > 0) _client.write(data, len);
    _client.write(PKT_END);
}

size_t K7Lamp::_recv(uint8_t* buf, size_t maxLen, bool drain) {
    size_t   total    = 0;
    uint32_t deadline = millis() + _timeoutMs;

    while (millis() < deadline && total < maxLen) {
        int avail = _client.available();
        if (avail > 0) {
            size_t n = min((size_t)avail, maxLen - total);
            total += _client.read(buf + total, n);
            if (!drain) break;
        } else {
            delay(10);
        }
    }
    return total;
}

// ── readAll ───────────────────────────────────────────────────────────────────
bool K7Lamp::readAll(LampState& out) {
    _sendPkt(CMD_ALL_READ[0], CMD_ALL_READ[1]);

    // Discard the model-ID echo (short, ~1 s timeout)
    uint32_t saved = _timeoutMs;
    _timeoutMs = 1000;
    uint8_t echo[32];
    _recv(echo, sizeof(echo), false);

    // Read the full state response (drain until timeout)
    _timeoutMs = 5000;
    uint8_t data[256];
    size_t len = _recv(data, sizeof(data), true);
    _timeoutMs = saved;

    // Validate framing
    if (len < 10) return false;
    if (data[0] != RESP_MAGIC[0] || data[1] != RESP_MAGIC[1]) return false;
    if (data[len - 1] != PKT_END) return false;

    // Decode state from offset 4
    size_t pos = 4;
    if (pos + K7_CHANNELS + 1 > len) return false;

    memcpy(out.manual, data + pos, K7_CHANNELS);
    pos += K7_CHANNELS;

    uint8_t timeNum = data[pos++];
    if (timeNum > K7_SLOTS) return false;
    if (pos + timeNum * 8 + 2 > len) return false;

    for (uint8_t i = 0; i < timeNum && i < K7_SLOTS; i++) {
        memcpy(out.schedule[i], data + pos, 8);
        pos += 8;
    }

    out.autoMode = (data[pos++] != 0);

    // Device name — 11 bytes, null-padded ASCII
    size_t nameAvail = len - pos - 1;   // -1 for END byte
    size_t nameLen   = min((size_t)11, nameAvail);
    memcpy(out.name, data + pos, nameLen);
    out.name[nameLen] = '\0';
    for (int i = (int)nameLen - 1; i >= 0 && out.name[i] == '\0'; i--)
        out.name[i] = '\0';

    out.valid = true;
    return true;
}

// ── Short-timeout ACK drain ───────────────────────────────────────────────────
// Control commands (hand, mode, preview, sync) may or may not send a response.
// We wait at most 150 ms so a non-responding lamp doesn't stall the caller.
void K7Lamp::_recvAck() {
    uint32_t saved = _timeoutMs;
    _timeoutMs = 150;
    uint8_t buf[32];
    _recv(buf, sizeof(buf), false);
    _timeoutMs = saved;
}

// ── Lamp control commands ─────────────────────────────────────────────────────
bool K7Lamp::handLuminance(const uint8_t ch[K7_CHANNELS]) {
    _sendPkt(CMD_HAND_LUMINANCE[0], CMD_HAND_LUMINANCE[1], ch, K7_CHANNELS);
    _recvAck();
    return true;
}

bool K7Lamp::handLuminanceFast(const uint8_t ch[K7_CHANNELS]) {
    _sendPkt(CMD_HAND_LUMINANCE[0], CMD_HAND_LUMINANCE[1], ch, K7_CHANNELS);
    return true;
}

bool K7Lamp::previewBrightness(const uint8_t ch[K7_CHANNELS]) {
    _sendPkt(CMD_PREVIEW_LUMINANCE[0], CMD_PREVIEW_LUMINANCE[1], ch, K7_CHANNELS);
    // Fire-and-forget: no ack wait.  The connection closes right after this
    // call so any unread response bytes are discarded harmlessly.  Skipping
    // the 150 ms ack window makes each preview operation ~20-60 ms total
    // instead of ~170-210 ms, keeping the mutex free for ramp / effects.
    return true;
}

bool K7Lamp::setModeAuto() {
    uint8_t d = 0x01;
    _sendPkt(CMD_CHANGE_MODE[0], CMD_CHANGE_MODE[1], &d, 1);
    _recvAck();
    return true;
}

bool K7Lamp::setModeManual() {
    uint8_t d = 0x00;
    _sendPkt(CMD_CHANGE_MODE[0], CMD_CHANGE_MODE[1], &d, 1);
    _recvAck();
    return true;
}

bool K7Lamp::syncTime() {
    time_t     now = time(nullptr);
    struct tm* t   = gmtime(&now);
    uint8_t    d[3] = {(uint8_t)t->tm_hour, (uint8_t)t->tm_min, (uint8_t)t->tm_sec};
    _sendPkt(CMD_SYNC_TIME[0], CMD_SYNC_TIME[1], d, 3);
    _recvAck();
    return true;
}

bool K7Lamp::pushSchedule(const uint8_t manual[K7_CHANNELS],
                           const uint8_t sched[K7_SLOTS][8],
                           bool autoMode) {
    time_t     now = time(nullptr);
    struct tm* t   = gmtime(&now);

    // manual(6) + timeNum(1) + sched(24×8=192) + mode(1) + time(3) = 203 bytes
    static const size_t DATALEN = K7_CHANNELS + 1 + K7_SLOTS * 8 + 1 + 3;
    uint8_t data[DATALEN];
    size_t  pos = 0;

    memcpy(data + pos, manual, K7_CHANNELS); pos += K7_CHANNELS;
    data[pos++] = K7_SLOTS;
    for (int i = 0; i < K7_SLOTS; i++) { memcpy(data + pos, sched[i], 8); pos += 8; }
    data[pos++] = autoMode ? 0x01 : 0x00;
    data[pos++] = (uint8_t)t->tm_hour;
    data[pos++] = (uint8_t)t->tm_min;
    data[pos++] = (uint8_t)t->tm_sec;

    _sendPkt(CMD_ALL_SET[0], CMD_ALL_SET[1], data, pos);
    _recvAck();
    return true;
}
