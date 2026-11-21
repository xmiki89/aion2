"""Windows install helpers: shortcuts, uninstall registry entry, self removal."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

APP_NAME = "Aion 2 Damage Meter"
EXE_NAME = "Aion2DamageMeter.exe"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Aion2DamageMeter"
VERSION = "1.0.0"

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008


def desktop_dir() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home()) / "Desktop"


def start_menu_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def shortcut_paths() -> list[Path]:
    start = start_menu_dir()
    return [
        desktop_dir() / f"{APP_NAME}.lnk",
        start / f"{APP_NAME}.lnk",
        start / f"Disinstalla {APP_NAME}.lnk",
    ]


def _ps(value: str) -> str:
    return value.replace("'", "''")


def create_shortcut(link: Path, target: Path, workdir: Path, description: str = "") -> bool:
    """Create a .lnk through WScript.Shell (no extra dependency)."""
    if os.name != "nt":
        return False
    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{link}');"
        "$s.TargetPath='{target}';"
        "$s.WorkingDirectory='{workdir}';"
        "$s.IconLocation='{target},0';"
        "$s.Description='{description}';"
        "$s.Save()"
    ).format(
        link=_ps(str(link)),
        target=_ps(str(target)),
        workdir=_ps(str(workdir)),
        description=_ps(description or APP_NAME),
    )
    try:
        link.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            creationflags=CREATE_NO_WINDOW,
            capture_output=True,
            timeout=40,
        )
        return link.is_file()
    except (OSError, subprocess.SubprocessError):
        return False


def remove_shortcuts() -> None:
    for path in shortcut_paths():
        try:
            path.unlink()
        except OSError:
            pass


def write_uninstall_entry(install_dir: Path, exe: Path) -> bool:
    """Register the app in Windows Settings > Apps."""
    if os.name != "nt":
        return False
    try:
        import winreg
    except ImportError:
        return False
    try:
        size_kb = max(1, int(exe.stat().st_size / 1024))
    except OSError:
        size_kb = 1
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, VERSION)
            winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "Aion2DamageMeter")
            winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(install_dir))
            winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(exe))
            winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'"{exe}" --uninstall')
            winreg.SetValueEx(key, "QuietUninstallString", 0, winreg.REG_SZ, f'"{exe}" --uninstall --quiet')
            winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, size_kb)
        return True
    except OSError:
        return False


def remove_uninstall_entry() -> None:
    if os.name != "nt":
        return
    try:
        import winreg

        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except (ImportError, OSError):
        pass


def launch_app(exe: Path) -> bool:
    try:
        subprocess.Popen(
            [str(exe)],
            cwd=str(exe.parent),
            creationflags=CREATE_NO_WINDOW,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        return True
    except OSError:
        return False


def schedule_removal(exe: Path) -> None:
    """Delete the exe (and its now-empty folder) after this process exits.

    Windows keeps the running image locked, so a detached PowerShell waits and retries;
    the folder is removed only when nothing else is left inside it.
    """
    if os.name != "nt":
        return
    folder = exe.parent
    script = (
        "Start-Sleep -Seconds 2;"
        f"$exe='{_ps(str(exe))}';$dir='{_ps(str(folder))}';"
        "for($i=0;$i -lt 16 -and (Test-Path -LiteralPath $exe);$i++){"
        "Start-Sleep -Milliseconds 500;"
        "Remove-Item -LiteralPath $exe -Force -ErrorAction SilentlyContinue};"
        "if(-not (Test-Path -LiteralPath $exe)){"
        "Remove-Item -LiteralPath $dir -Force -ErrorAction SilentlyContinue}"
    )
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
            creationflags=CREATE_NO_WINDOW,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError:
        pass


def current_exe() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return Path(sys.argv[0]).resolve()
