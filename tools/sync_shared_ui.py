#!/usr/bin/env python3
"""Sync shared UI source files into the ESP32 LittleFS static directory."""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "shared-ui"
DEST = ROOT / "arduino" / "data" / "static"


def iter_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def relative_files(root: Path) -> set[Path]:
    return {path.relative_to(root) for path in iter_files(root)}


def planned_changes() -> tuple[list[Path], list[Path]]:
    if not SOURCE.is_dir():
        raise SystemExit(f"missing source directory: {SOURCE}")
    if not DEST.is_dir():
        raise SystemExit(f"missing destination directory: {DEST}")

    src_files = relative_files(SOURCE)
    dest_files = relative_files(DEST)
    copy_needed: list[Path] = []
    remove_needed = sorted(dest_files - src_files)

    for rel in sorted(src_files):
        src = SOURCE / rel
        dest = DEST / rel
        if not dest.exists() or not filecmp.cmp(src, dest, shallow=False):
            copy_needed.append(rel)

    return copy_needed, remove_needed


def sync() -> tuple[list[Path], list[Path]]:
    copy_needed, remove_needed = planned_changes()

    for rel in remove_needed:
        (DEST / rel).unlink()

    for rel in copy_needed:
        src = SOURCE / rel
        dest = DEST / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

    for directory in sorted((path for path in DEST.rglob("*") if path.is_dir()), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass

    return copy_needed, remove_needed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if ESP32 static files are out of sync")
    args = parser.parse_args()

    copy_needed, remove_needed = planned_changes()

    if args.check:
        if copy_needed or remove_needed:
            for rel in copy_needed:
                print(f"needs copy: {rel}")
            for rel in remove_needed:
                print(f"needs remove: {rel}")
            return 1
        print("shared UI is in sync")
        return 0

    copied, removed = sync()
    for rel in copied:
        print(f"copied: {rel}")
    for rel in removed:
        print(f"removed: {rel}")
    if not copied and not removed:
        print("shared UI already in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
