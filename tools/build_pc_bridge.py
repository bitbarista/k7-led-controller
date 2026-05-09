#!/usr/bin/env python3
"""Build distributable PC bridge archives for Linux and Windows."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "pc-bridge"
DEFAULT_OUT = ROOT / "dist" / "pc-bridge"
NSI_TEMPLATE = ROOT / "tools" / "k7-bridge-installer.nsi.template"
APPIMAGE_TOOL = ROOT / "tools" / "appimagetool-x86_64.AppImage"
APP_ICON_PNG = ROOT / "tools" / "k7-bridge-icon.png"
APP_ICON_ICO = ROOT / "tools" / "k7-bridge.ico"

TARGETS = {
    "linux-amd64": {
        "goos": "linux",
        "goarch": "amd64",
        "binary": "k7-bridge",
        "archive": "gztar",
    },
    "windows-amd64": {
        "goos": "windows",
        "goarch": "amd64",
        "binary": "k7-bridge.exe",
        "archive": "zip",
    },
}


def run(cmd: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
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


def launcher_text(target: str) -> tuple[str, str]:
    if target.startswith("windows-"):
        return (
            "run-k7-bridge.bat",
            "@echo off\r\n"
            "setlocal\r\n"
            "cd /d %~dp0\r\n"
            "echo K7 PC Bridge will start at http://127.0.0.1:8787/\r\n"
            "echo Connect this PC to the lamp WiFi before using Read or Push.\r\n"
            "k7-bridge.exe\r\n",
        )
    return (
        "run-k7-bridge.sh",
        "#!/usr/bin/env sh\n"
        "set -eu\n"
        "cd \"$(dirname \"$0\")\"\n"
        "echo \"K7 PC Bridge will start at http://127.0.0.1:8787/\"\n"
        "echo \"Connect this PC to the lamp WiFi before using Read or Push.\"\n"
        "exec ./k7-bridge\n",
    )


def readme_text(version: str, target: str) -> str:
    executable = "k7-bridge.exe" if target.startswith("windows-") else "./k7-bridge"
    launcher = "run-k7-bridge.bat" if target.startswith("windows-") else "./run-k7-bridge.sh"
    return f"""K7 PC Bridge {version}

This is the PC-only K7 bridge. It serves the shared controller UI locally and
talks directly to the lamp at 192.168.4.1:8266.

Run:
  {launcher}

Or run the binary directly:
  {executable}

Then open:
  http://127.0.0.1:8787/

The bridge opens the local UI in your default browser automatically. If that
does not work, open the URL above manually. For debugging, run the binary with
--no-open.

Before using Read, Preview, or Push, connect this computer to the lamp's WiFi.
The bridge stores local profiles and settings in k7-pc-bridge.json beside the
binary by default.

This app pushes schedules into the lamp's internal scheduler only when you ask
it to. The PC does not need to stay running after a schedule has been pushed.
ESP32-only runtime functions such as Smooth Ramp, feed/maintenance timers,
tracked lunar, acclimation, and seasonal daylength are not available here.

The graph is a planning preview. It draws smooth-looking curves to make the
schedule easier to read, but the PC bridge pushes hourly points to the lamp.
Unless the lamp firmware smooths between those points internally, real schedule,
siesta, and fixed moonlight changes may happen as hourly steps.
"""


def copy_runtime_files(package_dir: Path, target: str, version: str) -> None:
    launcher_name, launcher = launcher_text(target)
    launcher_path = package_dir / launcher_name
    launcher_path.write_text(launcher, encoding="utf-8", newline="")
    if target.startswith("linux-"):
        launcher_path.chmod(0o755)
    (package_dir / "README.txt").write_text(readme_text(version, target), encoding="utf-8")
    if target.startswith("windows-") and APP_ICON_ICO.exists():
        shutil.copy2(APP_ICON_ICO, package_dir / "k7-bridge.ico")


def build_appimage(package_dir: Path, version: str, out_dir: Path) -> Path | None:
    if not APPIMAGE_TOOL.exists():
        print("appimagetool not found — skipping AppImage")
        return None

    appdir = out_dir / "K7Bridge.AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)
    bin_dir = appdir / "usr" / "bin"
    bin_dir.mkdir(parents=True)

    shutil.copy2(package_dir / "k7-bridge", bin_dir / "k7-bridge")
    (bin_dir / "k7-bridge").chmod(0o755)

    desktop = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=K7 Bridge\n"
        "Comment=K7 lamp controller PC bridge\n"
        "Exec=k7-bridge\n"
        "Icon=k7-bridge\n"
        "Categories=Utility;\n"
        "Terminal=false\n"
    )
    (appdir / "k7-bridge.desktop").write_text(desktop, encoding="utf-8")

    apprun = "#!/usr/bin/env sh\nexec \"$(dirname \"$0\")/usr/bin/k7-bridge\" \"$@\"\n"
    apprun_path = appdir / "AppRun"
    apprun_path.write_text(apprun, encoding="utf-8")
    apprun_path.chmod(0o755)

    if APP_ICON_PNG.exists():
        shutil.copy2(APP_ICON_PNG, appdir / "k7-bridge.png")

    outfile = out_dir / f"K7-Bridge-v{version}-x86_64.AppImage"
    env = os.environ.copy()
    env["ARCH"] = "x86_64"
    run([str(APPIMAGE_TOOL), str(appdir), str(outfile)], env=env)
    outfile.chmod(0o755)
    shutil.rmtree(appdir)
    print(f"wrote {outfile}")
    return outfile


def build_nsis_installer(package_dir: Path, version: str, out_dir: Path) -> Path | None:
    makensis = shutil.which("makensis")
    if not makensis:
        return None
    template = NSI_TEMPLATE.read_text(encoding="utf-8")
    outfile = out_dir / f"k7-bridge-setup-v{version}.exe"
    nsi = (
        template
        .replace("${VERSION}", version)
        .replace("${OUTFILE}", str(outfile))
        .replace("${SRCDIR}", str(package_dir))
        .replace("${ICONFILE}", str(package_dir / "k7-bridge.ico"))
    )
    with tempfile.NamedTemporaryFile(suffix=".nsi", mode="w", encoding="utf-8", delete=False) as f:
        f.write(nsi)
        nsi_path = Path(f.name)
    try:
        run([makensis, str(nsi_path)])
    finally:
        nsi_path.unlink(missing_ok=True)
    print(f"wrote {outfile}")
    return outfile


def build_target(target: str, version: str, out_dir: Path, go_bin: str) -> list[Path]:
    spec = TARGETS[target]
    package_name = f"k7-pc-bridge-{target}-v{version}"
    package_dir = out_dir / package_name
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True)

    binary_path = package_dir / spec["binary"]
    env = os.environ.copy()
    env.update({"GOOS": spec["goos"], "GOARCH": spec["goarch"]})
    run([go_bin, "build", "-trimpath", "-o", str(binary_path), "./cmd/k7-bridge"], cwd=BRIDGE, env=env)
    if target.startswith("linux-"):
        binary_path.chmod(0o755)
    copy_runtime_files(package_dir, target, version)

    archive_base = out_dir / package_name
    for suffix in (".tar.gz", ".zip"):
        stale = archive_base.with_suffix(suffix)
        if stale.exists():
            stale.unlink()
    archive = shutil.make_archive(str(archive_base), spec["archive"], root_dir=out_dir, base_dir=package_name)
    print(f"wrote {archive}")
    outputs = [Path(archive)]

    if target.startswith("linux-"):
        appimage = build_appimage(package_dir, version, out_dir)
        if appimage:
            outputs.append(appimage)

    if target.startswith("windows-"):
        installer = build_nsis_installer(package_dir, version, out_dir)
        if installer:
            outputs.append(installer)
        else:
            print("makensis not found — skipping Windows installer")

    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="version string for archive names")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory")
    parser.add_argument("--go", default=os.environ.get("GO", "go"), help="go executable")
    parser.add_argument("--skip-tests", action="store_true", help="skip go test")
    parser.add_argument(
        "--target",
        choices=sorted(TARGETS),
        action="append",
        help="target to build; may be passed more than once; defaults to all",
    )
    args = parser.parse_args()

    version = args.version or default_version()
    targets = args.target or sorted(TARGETS)
    args.out.mkdir(parents=True, exist_ok=True)

    run([sys.executable, "tools/generate_pc_bridge_presets.py"], cwd=ROOT)
    run([sys.executable, "tools/generate_pc_bridge_presets.py", "--check"], cwd=ROOT)
    run([sys.executable, "tools/sync_shared_ui.py", "--check"], cwd=ROOT)
    if not args.skip_tests:
        run([args.go, "test", "./..."], cwd=BRIDGE)

    all_outputs: list[Path] = []
    for target in targets:
        all_outputs.extend(build_target(target, version, args.out, args.go))
    print("\nBuilt PC bridge outputs:")
    for output in all_outputs:
        try:
            display = output.relative_to(ROOT)
        except ValueError:
            display = output
        print(f"  {display}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
