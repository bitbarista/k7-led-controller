#!/usr/bin/env python3
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRESETS_H = ROOT / "arduino" / "src" / "Presets.h"
INDEX_PATHS = [
    ROOT / "community-presets" / "index.json",
    ROOT / "website" / "community-presets" / "index.json",
]
HTML_PATH = ROOT / "website" / "community-presets.html"


def parse_keyframes(source):
    keyframes = {}
    pattern = re.compile(
        r"static const Keyframe (KF_(?:MINI|PRO)_[A-Z0-9]+)\[\] = \{\n(.*?)\n\};",
        re.S,
    )
    row_pattern = re.compile(r"\{\s*(\d+),\s*\{([^}]*)\}\s*\}")
    for name, body in pattern.findall(source):
        rows = []
        for hour, channels in row_pattern.findall(body):
            rows.append(
                {
                    "hour": int(hour),
                    "channels": [int(v.strip()) for v in channels.split(",")],
                }
            )
        keyframes[name] = rows
    return keyframes


def parse_presets(source, array_name):
    start = source.index(f"static const Preset {array_name}[] = {{")
    body_start = source.index("{", start) + 1
    body_end = source.index("\n};", body_start)
    body = source[body_start:body_end]
    pattern = re.compile(
        r'\{\s*"([^"]+)",\s*"([^"]+)",\s*"([^"]+)",\s*'
        r"\{([^}]*)\},\s*(KF_(?:MINI|PRO)_[A-Z0-9]+),\s*(\d+)(?:,\s*(true|false))?\s*\}",
        re.S,
    )
    presets = []
    for preset_id, name, desc, manual, keyframe_name, count, disable_lunar in pattern.findall(body):
        presets.append(
            {
                "id": preset_id,
                "name": name,
                "desc": " ".join(desc.split()),
                "manual": [int(v.strip()) for v in manual.split(",")],
                "keyframe_name": keyframe_name,
                "count": int(count),
                "disable_lunar": disable_lunar == "true",
            }
        )
    return presets


def interpolate_schedule(keyframes):
    schedule = []
    for hour in range(24):
        lo = keyframes[0]
        hi = keyframes[-1]
        for idx in range(len(keyframes) - 1):
            if keyframes[idx]["hour"] <= hour <= keyframes[idx + 1]["hour"]:
                lo = keyframes[idx]
                hi = keyframes[idx + 1]
                break
        row = [hour, 0]
        if lo["hour"] == hi["hour"] or hour <= lo["hour"]:
            row.extend(lo["channels"])
        elif hour >= hi["hour"]:
            row.extend(hi["channels"])
        else:
            t = (hour - lo["hour"]) / (hi["hour"] - lo["hour"])
            for lo_value, hi_value in zip(lo["channels"], hi["channels"]):
                value = lo_value + t * (hi_value - lo_value)
                row.append(max(0, min(100, int(math.floor(value + 0.5)))))
        schedule.append(row)
    return schedule


def profile_entry(lamp, preset, keyframes):
    preset_json = {
        "kind": "k7_community_preset",
        "schema": 1,
        "lamp": lamp,
        "name": preset["name"],
        "use_case": "built-in profile",
        "notes": preset["desc"],
        "manual": preset["manual"],
        "schedule": interpolate_schedule(keyframes[preset["keyframe_name"]]),
    }
    if preset["disable_lunar"]:
        preset_json["disable_lunar"] = True
    return {
        "name": preset["name"],
        "lamp": lamp,
        "use_case": "built-in profile",
        "notes": preset["desc"],
        "source": "built-in",
        "preset": preset_json,
    }


def build_index():
    source = PRESETS_H.read_text(encoding="utf-8")
    keyframes = parse_keyframes(source)
    presets = []
    for lamp, array_name in (("k7mini", "MINI_PRESETS"), ("k7pro", "PRO_PRESETS")):
        for preset in parse_presets(source, array_name):
            presets.append(profile_entry(lamp, preset, keyframes))
    return {
        "kind": "k7_community_preset_index",
        "schema": 1,
        "presets": presets,
    }


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def update_embedded_index(index):
    html = HTML_PATH.read_text(encoding="utf-8")
    replacement = (
        '<script type="application/json" id="embeddedPresetIndex">\n'
        + json.dumps(index, indent=2, ensure_ascii=False)
        + "\n  </script>"
    )
    updated, count = re.subn(
        r'<script type="application/json" id="embeddedPresetIndex">\n.*?\n\s*</script>',
        replacement,
        html,
        flags=re.S,
    )
    if count != 1:
        raise SystemExit("embeddedPresetIndex block not found")
    HTML_PATH.write_text(updated, encoding="utf-8")


def main():
    index = build_index()
    for path in INDEX_PATHS:
        write_json(path, index)
    update_embedded_index(index)
    print(f"generated {len(index['presets'])} public profiles")


if __name__ == "__main__":
    main()
