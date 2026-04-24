#include "Storage.h"
#include "Config.h"

fs::LittleFSFS UserDataFS;

static const char* USER_FILES[] = {
    CONFIG_FILE,
    PROFILES_FILE,
    LUNAR_FILE,
    STATE_FILE,
};

static bool copyFile(fs::FS& from, fs::FS& to, const char* path) {
    File src = from.open(path, "r");
    if (!src) return false;
    File dst = to.open(path, "w");
    if (!dst) {
        src.close();
        return false;
    }

    uint8_t buf[256];
    while (true) {
        size_t n = src.read(buf, sizeof(buf));
        if (!n) break;
        if (dst.write(buf, n) != n) {
            src.close();
            dst.close();
            return false;
        }
    }

    src.close();
    dst.close();
    return true;
}

bool initStorage() {
    if (!LittleFS.begin(true)) return false;
    if (!UserDataFS.begin(true, "/userdata", 10, "userdata")) return false;
    return true;
}

void migrateLegacyUserData() {
    for (const char* path : USER_FILES) {
        if (UserDataFS.exists(path) || !LittleFS.exists(path)) continue;
        copyFile(LittleFS, UserDataFS, path);
    }
}

void clearUserData() {
    for (const char* path : USER_FILES) {
        UserDataFS.remove(path);
        LittleFS.remove(path);
    }
}
