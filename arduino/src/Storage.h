#pragma once

#include <FS.h>
#include <LittleFS.h>

extern fs::LittleFSFS UserDataFS;

bool initStorage();
void migrateLegacyUserData();
void clearUserData();
