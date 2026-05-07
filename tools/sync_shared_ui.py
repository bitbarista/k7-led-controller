#!/usr/bin/env python3
"""Sync shared UI source files into generated runtime copies."""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "shared-ui"
DESTINATIONS = {
    "android": ROOT / "android" / "app" / "src" / "main" / "assets" / "static",
    "esp32": ROOT / "arduino" / "data" / "static",
    "pc-bridge": ROOT / "pc-bridge" / "internal" / "bridge" / "static",
}


def iter_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def relative_files(root: Path) -> set[Path]:
    return {path.relative_to(root) for path in iter_files(root)}


def planned_changes(dest: Path) -> tuple[list[Path], list[Path]]:
    if not SOURCE.is_dir():
        raise SystemExit(f"missing source directory: {SOURCE}")
    if not dest.is_dir():
        raise SystemExit(f"missing destination directory: {dest}")

    src_files = relative_files(SOURCE)
    dest_files = relative_files(dest)
    copy_needed: list[Path] = []
    remove_needed = sorted(dest_files - src_files)

    for rel in sorted(src_files):
        src = SOURCE / rel
        target = dest / rel
        if not target.exists() or not filecmp.cmp(src, target, shallow=False):
            copy_needed.append(rel)

    return copy_needed, remove_needed


def sync(dest: Path) -> tuple[list[Path], list[Path]]:
    copy_needed, remove_needed = planned_changes(dest)

    for rel in remove_needed:
        (dest / rel).unlink()

    for rel in copy_needed:
        src = SOURCE / rel
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)

    for directory in sorted((path for path in dest.rglob("*") if path.is_dir()), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass

    return copy_needed, remove_needed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if runtime copies are out of sync")
    parser.add_argument(
        "--target",
        choices=sorted(DESTINATIONS),
        action="append",
        help="runtime target to sync; may be passed more than once; defaults to all",
    )
    args = parser.parse_args()

    targets = args.target or sorted(DESTINATIONS)
    all_ok = True

    for target in targets:
        dest = DESTINATIONS[target]
        copy_needed, remove_needed = planned_changes(dest)
        if args.check:
            if copy_needed or remove_needed:
                all_ok = False
                for rel in copy_needed:
                    print(f"{target} needs copy: {rel}")
                for rel in remove_needed:
                    print(f"{target} needs remove: {rel}")
            else:
                print(f"{target} shared UI is in sync")
        else:
            copied, removed = sync(dest)
            for rel in copied:
                print(f"{target} copied: {rel}")
            for rel in removed:
                print(f"{target} removed: {rel}")
            if not copied and not removed:
                print(f"{target} shared UI already in sync")

    if args.check and not all_ok:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
