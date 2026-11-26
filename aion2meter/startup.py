"""Avvio del meter insieme a Windows, cosi' la cattura e' attiva prima del login."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

LINK_NAME = "Aion2DamageMeter.lnk"


def _target() -> str:
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    return os.path.abspath(sys.argv[0])


def _link_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    folder = Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return folder / LINK_NAME


def is_enabled() -> bool:
    return _link_path().exists()


def set_enabled(enabled: bool) -> bool:
    """Crea o rimuove il collegamento nella cartella Esecuzione automatica."""
    path = _link_path()
    try:
        if not enabled:
            path.unlink(missing_ok=True)
            return True
        target = _target()
        script = (
            "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{link}');"
            "$s.TargetPath='{target}';"
            "$s.WorkingDirectory='{folder}';"
            "$s.Save()"
        ).format(link=path, target=target, folder=os.path.dirname(target))
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            timeout=40,
        )
        return path.exists()
    except Exception:
        return False
