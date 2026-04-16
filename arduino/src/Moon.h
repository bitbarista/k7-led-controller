#pragma once
#include <Arduino.h>

namespace Moon {
    float       phase();          // 0.0 = new moon, 0.5 = full moon
    float       illumination();   // 0.0–1.0 lit fraction
    const char* phaseName();
}
