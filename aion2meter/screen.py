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


# righe del pannello party: `..II nome`, ` ..11 Nome (Gilda`, `Nome (Gilda`
_ROW_PREFIX = re.compile(
    r"^[.\s\u2022\u00b7\u2007|Il]*(?:[IVXl]{1,3}|\d{1,2})\s+(?P<name>\S+)"
)
_ROW_GUILD = re.compile(
    r"^(?P<name>[A-Za-z\u00c0-\u024f][\w\-]{2,15})\s*\(\s*[A-Za-z\u00c0-\u024f]"
)
# nome scritto da solo sopra la barra vita (client cinese/giapponese/coreano)
_ROW_CJK = re.compile(r"^[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]{2,12}$")


def names_from_lines(lines: list[str]) -> list[str]:
    """Solo i nomi del pannello party, ignorando chat, missioni e nametag."""
    names: list[str] = []
    for line in lines:
        text = line.strip()
        if not text or text.startswith("[") or "player" in text.lower():
            continue
        if _ROW_CJK.match(text):
            if text not in names:
                names.append(text)
            continue
        row = _ROW_PREFIX.match(text) or _ROW_GUILD.match(text)
        if row is None:
            continue
        token = row.group("name").strip("[],.;:")
        if token.isupper() and len(token) >= 3:
            continue
        if token.lower() in _STOP or token.lower().startswith("player"):
            continue
        if _token_ok(token) and token not in names:
            names.append(token)
    return names


def read_party_names(png_path: Path) -> list[str]:
    return names_from_lines(ocr_lines(png_path))


# il pannello del party sta sul lato sinistro dello schermo
REGION_LEFT = 0.00
REGION_TOP = 0.06
REGION_WIDTH = 0.36
REGION_HEIGHT = 0.72


def scan_names(png_path: Path) -> list[str]:
    """OCR + estrazione, usato dal timer periodico dell'app."""
    return names_from_lines(ocr_lines(png_path))


def has_cjk_ocr() -> bool:
    """True se Windows ha il pacchetto OCR per cinese/giapponese/coreano."""
    script = (
        "Add-Type -AssemblyName System.Runtime.WindowsRuntime\n"
        "$null=[Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType=WindowsRuntime]\n"
        "[Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages"
        " | ForEach-Object { $_.LanguageTag }\n"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            capture_output=True,
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout.decode("utf-8", "replace")
    except Exception:
        return False
    return any(tag.lower().startswith(("zh", "ja", "ko")) for tag in out.split())


def temp_png() -> Path:
    folder = Path(os.environ.get("TEMP") or ".") / "Aion2DamageMeter"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "party_panel.png"
