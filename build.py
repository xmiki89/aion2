"""Build Aion2DamageMeter.exe and the folder-choosing installer with PyInstaller."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
DIST = ROOT / "dist"


def make_icon() -> Path:
    from PIL import Image, ImageDraw

    ASSETS.mkdir(exist_ok=True)
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([8, 8, 248, 248], radius=54, fill=(22, 22, 27, 255))
    draw.ellipse([58, 58, 198, 198], outline=(76, 111, 255, 255), width=12)
    for start, end in (((128, 40), (128, 96)), ((128, 160), (128, 216)),
                       ((40, 128), (96, 128)), ((160, 128), (216, 128))):
        draw.line([start, end], fill=(76, 111, 255, 255), width=10)
    draw.ellipse([116, 116, 140, 140], fill=(255, 255, 255, 255))
    icon_path = ASSETS / "icon.ico"
    img.save(icon_path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return icon_path


def build_app(icon: Path) -> int:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        "Aion2DamageMeter",
        "--icon",
        str(icon),
        "--distpath",
        str(DIST),
        "--workpath",
        str(ROOT / "build"),
        "--specpath",
        str(ROOT / "build"),
        str(ROOT / "main.py"),
    ]
    print(" ".join(command))
    return subprocess.call(command, cwd=ROOT)


def build_setup(icon: Path) -> int:
    app_exe = DIST / "Aion2DamageMeter.exe"
    if not app_exe.is_file():
        print(f"ERRORE: {app_exe} non esiste, build dell'app non riuscita.")
        return 1
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        "Aion2DamageMeter-Setup",
        "--icon",
        str(icon),
        "--add-data",
        f"{app_exe}{os.pathsep}payload",
        "--distpath",
        str(DIST),
        "--workpath",
        str(ROOT / "build" / "setup"),
        "--specpath",
        str(ROOT / "build" / "setup"),
        str(ROOT / "installer" / "setup_app.py"),
    ]
    print(" ".join(command))
    return subprocess.call(command, cwd=ROOT)


def main() -> int:
    icon = make_icon()
    code = build_app(icon)
    if code:
        return code
    return build_setup(icon)


if __name__ == "__main__":
    raise SystemExit(main())
