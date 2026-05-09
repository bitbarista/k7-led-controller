#!/usr/bin/env python3
"""Build ESP32 firmware releases for SuperMini and XIAO variants.

Builds firmware and LittleFS for both boards, produces merged flash binaries
and individual component bins, generates ESP Web Tools manifests, and
optionally copies everything to website/releases/latest/ and updates flash.html.

Usage:
    # Build and stage to website/releases/latest/:
    python3 tools/build_esp32_release.py --version 2.7.0 --deploy

    # Build only (inspect output before deploying):
    python3 tools/build_esp32_release.py --version 2.7.0

    # Build, deploy, and create a GitHub Release:
    python3 tools/build_esp32_release.py --version 2.7.0 --deploy --release
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT      = Path(__file__).resolve().parents[1]
ARDUINO   = ROOT / "arduino"
WEBSITE   = ROOT / "website"
LATEST    = WEBSITE / "releases" / "latest"
FLASH_HTML = WEBSITE / "flash.html"
DIST      = ROOT / "dist" / "esp32"

MKLITTLEFS_DIR = Path.home() / ".platformio" / "packages" / "tool-mklittlefs"
PIO_PENV_PYTHON = Path.home() / ".platformio" / "penv" / "bin" / "python"

VARIANTS = {
    "supermini": {
        "env":        "supermini",
        "flash_size": "4MB",
        "littlefs_offset": 0x300000,
        "littlefs_size":   0x100000,
    },
    "xiao": {
        "env":        "xiao",
        "flash_size": "8MB",
        "littlefs_offset": 0x300000,
        "littlefs_size":   0x500000,
    },
}

OFFSETS = {
    "bootloader": 0x0,
    "partitions": 0x8000,
    "bootapp":    0xe000,
    "firmware":   0x10000,
}


def run(cmd: list[str], *, cwd: Path = ROOT, env: dict | None = None) -> None:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def capture(cmd: list[str], *, cwd: Path = ROOT) -> str:
    return subprocess.check_output(cmd, cwd=cwd, text=True).strip()


def default_version() -> str:
    try:
        tag = capture(["git", "describe", "--tags", "--exact-match"])
        return tag.removeprefix("v")
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    try:
        short = capture(["git", "rev-parse", "--short", "HEAD"])
        return f"dev-{short}"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "dev"


def find_boot_app0() -> Path:
    result = subprocess.run(
        ["find", str(Path.home() / ".platformio"), "-name", "boot_app0.bin"],
        capture_output=True, text=True,
    )
    candidates = [p for p in result.stdout.splitlines() if p.strip()]
    if not candidates:
        sys.exit("ERROR: boot_app0.bin not found under ~/.platformio — run a PlatformIO build first")
    return Path(candidates[0])


def find_esptool() -> str:
    # Prefer the PlatformIO-bundled esptool (guaranteed compatible version)
    pio_esptool = Path.home() / ".platformio" / "packages" / "tool-esptoolpy" / "esptool.py"
    if pio_esptool.exists() and PIO_PENV_PYTHON.exists():
        return f"{PIO_PENV_PYTHON} {pio_esptool}"
    system_esptool = shutil.which("esptool") or shutil.which("esptool.py")
    if system_esptool:
        return system_esptool
    sys.exit("ERROR: esptool not found — install it with: pip install esptool")


def build_variant(variant: str, version: str, env_extra: dict[str, str]) -> dict[str, Path]:
    """Build firmware + LittleFS for one variant. Returns paths to component bins."""
    spec = VARIANTS[variant]
    pio_env = spec["env"]
    build_dir = ARDUINO / ".pio" / "build" / pio_env

    pio_env_vars = os.environ.copy()
    pio_env_vars["PATH"] = f"{MKLITTLEFS_DIR}:{pio_env_vars.get('PATH', '')}"
    pio_env_vars["PLATFORMIO_BUILD_FLAGS"] = (
        f"-DK7_FIRMWARE_VERSION={version} -DK7_BUILD_GIT={env_extra.get('git_short', 'local')}"
    )

    print(f"\n{'='*60}")
    print(f"Building {variant} firmware (version {version})")
    print(f"{'='*60}")
    run(["pio", "run", "-e", pio_env], cwd=ARDUINO, env=pio_env_vars)

    print(f"\nBuilding {variant} LittleFS")
    run(["pio", "run", "-e", pio_env, "-t", "buildfs"], cwd=ARDUINO, env=pio_env_vars)

    return {
        "bootloader": build_dir / "bootloader.bin",
        "partitions": build_dir / "partitions.bin",
        "firmware":   build_dir / "firmware.bin",
        "littlefs":   build_dir / "littlefs.bin",
    }


def merge_binary(variant: str, version: str, bins: dict[str, Path], boot_app0: Path, esptool: str) -> Path:
    spec = VARIANTS[variant]
    out = DIST / f"k7controller-{variant}-v{version}.bin"

    cmd_prefix = esptool.split()
    cmd = cmd_prefix + [
        "--chip", "esp32s3",
        "merge_bin",
        "--flash_mode", "dio",
        "--flash_freq", "80m",
        "--flash_size", spec["flash_size"],
        "-o", str(out),
        hex(OFFSETS["bootloader"]), str(bins["bootloader"]),
        hex(OFFSETS["partitions"]), str(bins["partitions"]),
        hex(OFFSETS["bootapp"]),    str(boot_app0),
        hex(OFFSETS["firmware"]),   str(bins["firmware"]),
        hex(spec["littlefs_offset"]), str(bins["littlefs"]),
    ]
    run(cmd)
    print(f"wrote {out}")
    return out


def copy_component_bins(variant: str, version: str, bins: dict[str, Path], boot_app0: Path) -> dict[str, Path]:
    """Copy individual component bins to DIST with versioned names."""
    component_map = {
        "bootloader": bins["bootloader"],
        "partitions": bins["partitions"],
        "bootapp":    boot_app0,
        "firmware":   bins["firmware"],
        "littlefs":   bins["littlefs"],
    }
    out: dict[str, Path] = {}
    for name, src in component_map.items():
        dst = DIST / f"k7controller-{variant}-{name}-v{version}.bin"
        shutil.copy2(src, dst)
        out[name] = dst
    return out


def generate_manifest(variant: str, version: str, component_bins: dict[str, Path]) -> dict:
    spec = VARIANTS[variant]
    display_names = {"supermini": "SuperMini", "xiao": "XIAO"}
    return {
        "name": f"K7 LED Controller ({display_names[variant]})",
        "version": version,
        "new_install_prompt_erase": True,
        "funding_url": "https://ko-fi.com/bitbarista",
        "builds": [
            {
                "chipFamily": "ESP32-S3",
                "parts": [
                    {"path": component_bins["bootloader"].name, "offset": OFFSETS["bootloader"]},
                    {"path": component_bins["partitions"].name,  "offset": OFFSETS["partitions"]},
                    {"path": component_bins["bootapp"].name,     "offset": OFFSETS["bootapp"]},
                    {"path": component_bins["firmware"].name,    "offset": OFFSETS["firmware"]},
                    {"path": component_bins["littlefs"].name,    "offset": spec["littlefs_offset"]},
                ],
            }
        ],
    }


def deploy_to_website(version: str, all_files: list[Path]) -> None:
    """Copy built artifacts to website/releases/latest/ and update flash.html."""
    print(f"\nDeploying to {LATEST}")
    LATEST.mkdir(parents=True, exist_ok=True)

    for f in all_files:
        dst = LATEST / f.name
        shutil.copy2(f, dst)
        print(f"  {f.name}")

    # Update manifest-supermini.json and manifest-xiao.json (the unversioned live copies)
    for variant in VARIANTS:
        src = DIST / f"manifest-{variant}-v{version}.json"
        if src.exists():
            shutil.copy2(src, LATEST / f"manifest-{variant}.json")

    # Update the ?v= cache-buster in flash.html
    html = FLASH_HTML.read_text(encoding="utf-8")
    for variant in VARIANTS:
        pattern = rf'(manifest="https://[^"]*manifest-{variant}\.json)(\?[^"]*)?"'
        replacement = rf'\1?v=v{version}"'
        html = re.sub(pattern, replacement, html)
    FLASH_HTML.write_text(html, encoding="utf-8")
    print(f"Updated {FLASH_HTML.name} to v{version}")


def create_github_release(version: str, release_files: list[Path]) -> None:
    gh = shutil.which("gh")
    if not gh:
        print("WARNING: gh not found — skipping GitHub Release creation")
        return

    tag = f"v{version}"
    body = f"""## K7 LED Controller v{version}

### Installation

**Easiest — browser-based flash (Chrome/Edge/Opera):**
Visit the [flash page](https://bitbarista.github.io/k7-led-controller/flash.html), connect your board via USB, and click Install.

**Manual — esptool:**
```
# ESP32-S3 SuperMini (4 MB flash)
esptool --chip esp32s3 write_flash 0x0 k7controller-supermini-v{version}.bin

# Seeed XIAO ESP32-S3 (8 MB flash)
esptool --chip esp32s3 write_flash 0x0 k7controller-xiao-v{version}.bin
```

### After flashing
1. Connect to **K7-Setup** WiFi (open network)
2. Browse to **http://192.168.5.1**
3. Select your lamp and save
4. Connect to your **lamp's WiFi** (K7-XXXXXX)
5. Browse to **http://k7controller.local**

> To reset to setup mode, hold the BOOT button on the board while powering on for 3 seconds.

If the project has helped you, support it on [Ko-fi](https://ko-fi.com/bitbarista).
"""
    print(f"\nCreating GitHub Release {tag}")
    cmd = [gh, "release", "create", tag, "--title", f"K7 LED Controller v{version}", "--notes", body]
    for f in release_files:
        cmd.append(str(f))
    run(cmd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", help="release version (e.g. 2.7.0); defaults to git tag or dev-<sha>")
    parser.add_argument("--deploy", action="store_true", help="copy to website/releases/latest/ and update flash.html")
    parser.add_argument("--release", action="store_true", help="create a GitHub Release (implies --deploy)")
    parser.add_argument("--variant", choices=sorted(VARIANTS), action="append",
                        help="build only this variant; may be passed twice; defaults to all")
    parser.add_argument("--skip-build", action="store_true",
                        help="skip PlatformIO build (use existing .pio/build artefacts)")
    args = parser.parse_args()

    if args.release:
        args.deploy = True

    version = args.version or default_version()
    variants = args.variant or sorted(VARIANTS)
    DIST.mkdir(parents=True, exist_ok=True)

    try:
        git_short = capture(["git", "rev-parse", "--short", "HEAD"])
    except Exception:
        git_short = "local"

    env_extra = {"git_short": git_short}

    boot_app0 = find_boot_app0()
    esptool   = find_esptool()

    all_dist_files: list[Path] = []
    merged_bins:    list[Path] = []

    for variant in variants:
        if args.skip_build:
            pio_env  = VARIANTS[variant]["env"]
            build_dir = ARDUINO / ".pio" / "build" / pio_env
            bins = {
                "bootloader": build_dir / "bootloader.bin",
                "partitions": build_dir / "partitions.bin",
                "firmware":   build_dir / "firmware.bin",
                "littlefs":   build_dir / "littlefs.bin",
            }
        else:
            bins = build_variant(variant, version, env_extra)

        component_bins = copy_component_bins(variant, version, bins, boot_app0)
        all_dist_files.extend(component_bins.values())

        merged = merge_binary(variant, version, bins, boot_app0, esptool)
        all_dist_files.append(merged)
        merged_bins.append(merged)

        manifest = generate_manifest(variant, version, component_bins)
        manifest_versioned = DIST / f"manifest-{variant}-v{version}.json"
        manifest_versioned.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        all_dist_files.append(manifest_versioned)
        print(f"wrote {manifest_versioned}")

    if args.deploy:
        deploy_to_website(version, all_dist_files)

    if args.release:
        create_github_release(version, merged_bins + [
            DIST / f"manifest-{v}-v{version}.json" for v in variants
        ])

    print(f"\nBuild complete — version {version}")
    print(f"Output: {DIST}")
    if args.deploy:
        print(f"Deployed to: {LATEST}")
        print(f"flash.html updated to v{version}")
    if not args.deploy:
        print("\nRun with --deploy to copy to website/releases/latest/ and update flash.html")

    return 0


if __name__ == "__main__":
    sys.exit(main())
