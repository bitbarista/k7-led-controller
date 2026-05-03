# Public profiles

Public profiles are preset-only lighting schedules. They include the controller's built-in profiles and reviewed community presets. They must not contain controller backups, WiFi settings, lamp setup, saved profile collections, or other private configuration.

Preset files use this shape:

```json
{
  "kind": "k7_community_preset",
  "schema": 1,
  "lamp": "k7mini",
  "name": "Example preset",
  "use_case": "mixed reef",
  "notes": "Short reviewer/user notes",
  "schedule": [[0, 0, 0, 0, 0, 0, 0, 0]],
  "manual": [0, 0, 0]
}
```

`lamp` is `k7mini` or `k7pro`. `schedule` contains 24 rows in the controller schedule format. `manual` contains the active manual channel values for the target lamp.

The public profile gallery can generate an app-compatible QR payload from this JSON. The payload is six manual channel bytes, then `#`, then 24 hourly rows of eight bytes each: hour, minute, and six channel values. K7 Mini presets use the first three channel values and pad the remaining three channels with zero. K7 Pro presets use all six controller channel values.

Run `python3 tools/generate_public_profiles.py` after changing built-in presets in `arduino/src/Presets.h` so the public profile page stays in sync.
