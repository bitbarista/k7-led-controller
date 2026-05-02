#pragma once

#define K7_STRINGIFY_VALUE(x) #x
#define K7_STRINGIFY(x) K7_STRINGIFY_VALUE(x)

#ifndef K7_FIRMWARE_VERSION
#define K7_FIRMWARE_VERSION dev
#endif

#ifndef K7_BUILD_TARGET
#define K7_BUILD_TARGET unknown
#endif

#ifndef K7_BUILD_GIT
#define K7_BUILD_GIT unknown
#endif
