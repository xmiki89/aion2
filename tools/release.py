"""Pubblica una release GitHub con il Setup allegato.

Il repo git contiene gia' l'app aggiornabile (`update/Aion2DamageMeter.exe`) e
`version.json`, ma `dist/` e' ignorato: il Setup da ~72 MB non finisce in git.
Questo script lo carica come asset di release, cosi' il link di download e'
stabile e non gonfia la cronologia del repository.

Uso:
    python tools/release.py --version 1.0.5
    python tools/release.py --version 1.0.5 --files dist/Aion2DamageMeter-Setup.exe
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "xmiki89/aion2"
API = f"https://api.github.com/repos/{REPO}"
SETUP_EXE = ROOT / "dist" / "Aion2DamageMeter-Setup.exe"
APP_EXE = ROOT / "dist" / "Aion2DamageMeter.exe"


def token() -> str:
    """Legge il token gia' usato da git (credential manager), senza stamparlo."""
    result = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    for line in result.stdout.splitlines():
        if line.startswith("password="):
            value = line[len("password=") :].strip()
            if value:
                return value
    raise SystemExit("Nessuna credenziale GitHub disponibile (git credential fill).")


def _curl(args: list[str], secret: str, timeout: int = 900) -> tuple[int, str]:
    """Esegue curl passando il token in un file di config temporaneo (non in argv)."""
    handle = tempfile.NamedTemporaryFile("w", suffix=".curl", delete=False, encoding="utf-8")
    try:
        handle.write(
            f'header = "Authorization: Bearer {secret}"\n'
            'header = "Accept: application/vnd.github+json"\n'
            'header = "X-GitHub-Api-Version: 2022-11-28"\n'
            'header = "User-Agent: Aion2DamageMeter"\n'
        )
        handle.close()
        if os.name == "posix":
            os.chmod(handle.name, 0o600)
        completed = subprocess.run(
            ["curl", "-sS", "--config", handle.name, "--max-time", str(timeout), *args],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        return completed.returncode, (completed.stdout or completed.stderr or "").strip()
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass


def ensure_release(version: str, notes: str, secret: str) -> int:
    tag = f"v{version}"
    code, out = _curl(
        ["-X", "GET", f"{API}/releases/tags/{tag}"], secret, timeout=60
    )
    if code == 0 and out.startswith("{"):
        try:
            data = json.loads(out)
        except ValueError:
            data = {}
        if data.get("id"):
            print(f"Release {tag} gia' esistente (id {data['id']}).")
            return int(data["id"])

    body = json.dumps(
        {
            "tag_name": tag,
            "name": f"Aion 2 Damage Meter {version}",
            "body": notes or f"Release {version}",
            "draft": False,
            "prerelease": False,
        }
    )
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as payload:
        payload.write(body)
        payload_path = payload.name
    try:
        code, out = _curl(
            [
                "-X",
                "POST",
                "-H",
                "Content-Type: application/json",
                "--data-binary",
                f"@{payload_path}",
                f"{API}/releases",
            ],
            secret,
            timeout=120,
        )
    finally:
        os.unlink(payload_path)
    if code != 0 or not out.startswith("{"):
        raise SystemExit(f"Creazione release non riuscita: {out[:300]}")
    data = json.loads(out)
    if not data.get("id"):
        raise SystemExit(f"Creazione release non riuscita: {out[:300]}")
    print(f"Release {tag} creata: {data.get('html_url')}")
    return int(data["id"])


def existing_assets(release_id: int, secret: str) -> dict[str, int]:
    code, out = _curl(
        ["-X", "GET", f"{API}/releases/{release_id}/assets?per_page=100"], secret, timeout=60
    )
    if code != 0 or not out.startswith("["):
        return {}
    try:
        items = json.loads(out)
    except ValueError:
        return {}
    return {str(item.get("name")): int(item.get("size") or 0) for item in items if item.get("name")}


def upload(release_id: int, path: Path, secret: str) -> None:
    name = path.name
    code, out = _curl(
        [
            "-X",
            "POST",
            "-H",
            "Content-Type: application/octet-stream",
            "--data-binary",
            f"@{path}",
            f"https://uploads.github.com/repos/{REPO}/releases/{release_id}/assets?name={name}",
        ],
        secret,
        timeout=1800,
    )
    if code != 0:
        raise SystemExit(f"Upload di {name} non riuscito: {out[:300]}")
    try:
        data = json.loads(out)
    except ValueError:
        data = {}
    if data.get("browser_download_url"):
        size = int(data.get("size") or 0)
        print(f"  {name}: {size / 1_048_576:.1f} MB -> {data['browser_download_url']}")
    else:
        print(f"  {name}: risposta inattesa {out[:200]}")


def publish(version: str, notes: str, files: list[Path]) -> int:
    secret = token()
    release_id = ensure_release(version, notes, secret)
    present = existing_assets(release_id, secret)
    for path in files:
        if not path.is_file():
            print(f"  salto {path} (non esiste)")
            continue
        if present.get(path.name) == path.stat().st_size:
            print(f"  {path.name}: gia' presente")
            continue
        upload(release_id, path, secret)
    return release_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Pubblica una release GitHub con gli eseguibili")
    parser.add_argument("--version", required=True)
    parser.add_argument("--notes", default="")
    parser.add_argument("--files", nargs="*", default=None)
    args = parser.parse_args()

    from aion2meter import __version__

    files = [Path(item) for item in args.files] if args.files else [SETUP_EXE]
    print(f"Release v{args.version} (app locale {__version__})")
    publish(args.version, args.notes, files)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
