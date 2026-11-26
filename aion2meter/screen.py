"""Lettura dei nomi del party dal pannello di gioco, via OCR di Windows."""

from __future__ import annotations

import base64
import os
import re
import subprocess
from pathlib import Path

_SCRIPT = """
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType=WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {{
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
}})[0]
function Await($op, $type) {{
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
    $task.Result
}}
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync('{path}')) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) {{ exit 0 }}
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
foreach ($line in $result.Lines) {{ Write-Output $line.Text }}
"""

# parole dell'interfaccia che non sono nomi di giocatori
_STOP = {
    "aion",
    "damage",
    "meter",
    "player",
    "skill",
    "skills",
    "off",
    "on",
    "group",
    "party",
    "quest",
    "level",
    "hp",
    "mp",
    "ep",
    "dps",
    "total",
    "dmg",
    "heal",
    "taken",
    "roster",
    "overlay",
    "include",
    "merge",
    "pet",
    "brawler",
    "solo",
    "gruppo",
    "tu",
    "in",
    "attesa",
    "visti",
    "global",
    "classes",
    "cattura",
    "pacchetti",
    "server",
    "rilevato",
    "attivo",
    "aggiorna",
    "sono",
    "avvia",
    "windows",
}


def _token_ok(token: str) -> bool:
    if not 3 <= len(token) <= 16:
        return False
    if token.lower() in _STOP:
        return False
    if token.lower().startswith("player"):
        return False
    if not any(ch.isalpha() for ch in token):
        return False
    return all(ch.isalnum() or ch in "-_[]" for ch in token)


def ocr_lines(png_path: Path) -> list[str]:
    """Esegue l'OCR di Windows sull'immagine e restituisce le righe lette."""
    if not png_path.exists():
        return []
    script = _SCRIPT.format(path=str(png_path).replace("'", "''"))
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            capture_output=True,
            timeout=40,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return []
    text = result.stdout.decode("utf-8", "replace")
    return [line.strip() for line in text.splitlines() if line.strip()]


def names_from_lines(lines: list[str]) -> list[str]:
    """Nomi dalle righe del pannello party: `..II xmiki`, `Vexanna (Gilda`."""
    names: list[str] = []
    for line in lines:
        text = line.strip()
        if not text or "player" in text.lower():
            continue
        head = text.split("(")[0]
        tokens = [t for t in re.split(r"[^\w\-]+", head) if t]
        tokens = [t for t in tokens if not re.fullmatch(r"[IVXl]{1,3}", t)]
        if not tokens:
            continue
        token = tokens[-1]
        if _token_ok(token) and len(token) >= 4 and token not in names:
            names.append(token)
    return names


def read_party_names(png_path: Path) -> list[str]:
    return names_from_lines(ocr_lines(png_path))


def scan_names(png_path: Path) -> list[str]:
    """OCR + estrazione, usato dal timer periodico dell'app."""
    return names_from_lines(ocr_lines(png_path))


def temp_png() -> Path:
    folder = Path(os.environ.get("TEMP") or ".") / "Aion2DamageMeter"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "party_panel.png"
