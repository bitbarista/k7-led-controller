#!/usr/bin/env python3
"""Generate the PC bridge preset JSON from the firmware preset definitions."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "arduino" / "src" / "Presets.h"
DEFAULT_OUTPUT = ROOT / "pc-bridge" / "internal" / "bridge" / "presets.json"

SLOTS = 24
CHANNELS = 6


def parse_int_list(value: str) -> list[int]:
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def parse_keyframes(source: str) -> dict[str, list[tuple[int, list[int]]]]:
    keyframes: dict[str, list[tuple[int, list[int]]]] = {}
    block_re = re.compile(r"static\s+const\s+Keyframe\s+(KF_[A-Z0-9_]+)\[\]\s*=\s*\{(.*?)\};", re.S)
    row_re = re.compile(r"\{\s*(\d+)\s*,\s*\{\s*([^}]*)\}\s*\}")
    for name, body in block_re.findall(source):
        rows: list[tuple[int, list[int]]] = []
        for hour_raw, channels_raw in row_re.findall(body):
            channels = parse_int_list(channels_raw)
            if len(channels) != CHANNELS:
                raise ValueError(f"{name} hour {hour_raw} has {len(channels)} channels")
            rows.append((int(hour_raw), channels))
        if not rows:
            raise ValueError(f"{name} has no keyframes")
        keyframes[name] = rows
    return keyframes


def cpp_round(value: float) -> int:
    return int(math.floor(value + 0.5))


def build_schedule(keyframes: list[tuple[int, list[int]]]) -> list[list[int]]:
    schedule: list[list[int]] = []
    for hour in range(SLOTS):
        lo = keyframes[0]
        hi = keyframes[-1]
        for index in range(len(keyframes) - 1):
            if keyframes[index][0] <= hour <= keyframes[index + 1][0]:
                lo = keyframes[index]
                hi = keyframes[index + 1]
                break

        row = [hour, 0, 0, 0, 0, 0, 0, 0]
        if lo[0] == hi[0] or hour <= lo[0]:
            values = lo[1]
        elif hour >= hi[0]:
            values = hi[1]
        else:
            t = (hour - lo[0]) / (hi[0] - lo[0])
            values = [max(0, min(100, cpp_round(a + t * (b - a)))) for a, b in zip(lo[1], hi[1])]
        row[2:] = values
        schedule.append(row)
    return schedule


def parse_preset_group(source: str, group: str, keyframes: dict[str, list[tuple[int, list[int]]]]) -> dict[str, dict[str, object]]:
    block_match = re.search(rf"static\s+const\s+Preset\s+{group}_PRESETS\[\]\s*=\s*\{{(.*?)\}};", source, re.S)
    if not block_match:
        raise ValueError(f"{group}_PRESETS not found")

    preset_re = re.compile(
        r'\{\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*'
        r"\{\s*([^}]*)\}\s*,\s*(KF_[A-Z0-9_]+)\s*,\s*(\d+)(?:\s*,\s*(true|false))?\s*\}",
        re.S,
    )
    presets: dict[str, dict[str, object]] = {}
    for preset_id, name, desc, manual_raw, keyframe_name, count_raw, disable_lunar in preset_re.findall(block_match.group(1)):
        manual = parse_int_list(manual_raw)
        if len(manual) != CHANNELS:
            raise ValueError(f"{group} preset {preset_id} has {len(manual)} manual channels")
        if keyframe_name not in keyframes:
            raise ValueError(f"{group} preset {preset_id} references missing {keyframe_name}")
        count = int(count_raw)
        if count != len(keyframes[keyframe_name]):
            raise ValueError(f"{group} preset {preset_id} count {count} does not match {keyframe_name}")
        presets[preset_id] = {
            "name": name,
            "desc": desc,
            "manual": manual,
            "schedule": build_schedule(keyframes[keyframe_name]),
        }
        if disable_lunar == "true":
            presets[preset_id]["disable_lunar"] = True
    return presets


def generate(source_path: Path) -> dict[str, dict[str, dict[str, object]]]:
    source = source_path.read_text(encoding="utf-8")
    keyframes = parse_keyframes(source)
    return {
        "k7mini": parse_preset_group(source, "MINI", keyframes),
        "k7pro": parse_preset_group(source, "PRO", keyframes),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="fail if the output file is stale")
    args = parser.parse_args()

    presets = generate(args.source)
    text = json.dumps(presets, indent=2) + "\n"

    if args.check:
        try:
            existing = args.output.read_text(encoding="utf-8")
        except FileNotFoundError:
            print(f"{args.output} is missing")
            return 1
        if existing != text:
            print(f"{args.output} is out of date")
            return 1
        print(f"{args.output} is up to date")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(f"generated {args.output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
