"""Self update: check GitHub for a newer build, download it and replace this exe."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import __version__

REPO = "xmiki89/aion2"
# the Contents API is not cached by the CDN, so a fresh release is seen immediately;
# the raw URL stays as a fallback for networks that block api.github.com
API_MANIFEST_URL = f"https://api.github.com/repos/{REPO}/contents/version.json"
MANIFEST_URL = f"https://raw.githubusercontent.com/{REPO}/main/version.json"
FALLBACK_ASSET = f"https://github.com/{REPO}/releases/latest/download/Aion2DamageMeter.exe"
USER_AGENT = "Aion2DamageMeter"
CREATE_NO_WINDOW = 0x08000000


@dataclass
class UpdateInfo:
    version: str
    url: str
    sha256: str = ""
    notes: str = ""
    size: int = 0


def local_version() -> str:
    return __version__


def parse_version(text: object) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in str(text).replace("-", ".").replace("+", ".").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(remote: str, local: str) -> bool:
    return parse_version(remote) > parse_version(local)


def _read_json(url: str, headers: dict[str, str], timeout: float) -> dict | None:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(500_000).decode("utf-8", "ignore")
        data = json.loads(payload)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def fetch_manifest(url: str | None = None, timeout: float = 6.0) -> dict | None:
    stamp = int(time.time())
    if url:
        candidates = [url]
    else:
        candidates = [API_MANIFEST_URL, MANIFEST_URL]
    for candidate in candidates:
        separator = "&" if "?" in candidate else "?"
        headers = {
            "User-Agent": USER_AGENT,
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        if "api.github.com" in candidate:
            headers["Accept"] = "application/vnd.github.raw"
        data = _read_json(f"{candidate}{separator}v={stamp}", headers, timeout)
        if data is not None and data.get("version"):
            return data
    return None


def check(url: str | None = None) -> UpdateInfo | None:
    data = fetch_manifest(url)
    if not data:
        return None
    version = str(data.get("version") or "").strip()
    asset = str(data.get("url") or "").strip() or FALLBACK_ASSET
    if not version or not asset or not is_newer(version, local_version()):
        return None
    return UpdateInfo(
        version=version,
        url=asset,
        sha256=str(data.get("sha256") or ""),
        notes=str(data.get("notes") or ""),
        size=int(data.get("size") or 0),
    )


def download(info: UpdateInfo, dest: Path, progress=None) -> bool:
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(info.url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=90) as response:
            total = int(response.headers.get("Content-Length") or 0) or info.size
            written = 0
            with dest.open("wb") as handle:
                while True:
                    chunk = response.read(262144)
                    if not chunk:
                        break
                    handle.write(chunk)
                    written += len(chunk)
                    if progress is not None and total:
                        progress(written, total)
    except (urllib.error.URLError, OSError, ValueError):
        return False

    if dest.stat().st_size < 1_000_000:
        return False
    if info.sha256:
        digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        if digest.lower() != info.sha256.lower():
            return False
    return True


def _ps(value: str) -> str:
    return value.replace("'", "''")


def apply_update(new_file: Path, restart: bool = True) -> bool:
    """Copy the download next to the running exe and let a helper swap it after exit."""
    if not getattr(sys, "frozen", False):
        return False
    current = Path(sys.executable).resolve()
    staged = current.with_name("Aion2DamageMeter.update.exe")
    try:
        shutil.copy2(new_file, staged)
    except OSError:
        return False

    script = (
        f"$old='{_ps(str(current))}';$new='{_ps(str(staged))}';"
        "Start-Sleep -Milliseconds 800;"
        "for($i=0;$i -lt 40;$i++){"
        "try{Move-Item -LiteralPath $new -Destination $old -Force -ErrorAction Stop;break}"
        "catch{Start-Sleep -Milliseconds 500}};"
        + (f"Start-Process -FilePath $old;" if restart else "")
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
        return True
    except OSError:
        return False


def cli_check() -> int:
    info = check()
    if info:
        print(f"Aggiornamento disponibile: {info.version} (locale {local_version()})")
    else:
        print(f"Nessun aggiornamento (locale {local_version()})")
    return 0


def cli_update() -> int:
    info = check()
    if info is None:
        print(f"Nessun aggiornamento (locale {local_version()})")
        return 0
    print(f"Scarico {info.version}…")
    dest = Path(tempfile.gettempdir()) / "Aion2DamageMeter-update.exe"
    if not download(info, dest):
        print("Download non riuscito.")
        return 1
    if not apply_update(dest):
        print("Applicazione non riuscita (avvia l'aggiornamento dall'app).")
        return 1
    print("Aggiornamento pronto: l'app si riavvia con la nuova versione.")
    return 0
