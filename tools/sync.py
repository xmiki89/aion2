"""Publish a change: bump version, rebuild, refresh the update payload, commit and push."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "xmiki89/aion2"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/main"
INIT = ROOT / "aion2meter" / "__init__.py"
PAYLOAD = ROOT / "update" / "Aion2DamageMeter.exe"
MANIFEST = ROOT / "version.json"
APP_EXE = ROOT / "dist" / "Aion2DamageMeter.exe"


def git_run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True)


def has_changes() -> bool:
    result = git_run("status", "--porcelain")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return bool(lines)


def bump_version() -> str:
    text = INIT.read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([0-9]+)\.([0-9]+)\.([0-9]+)"', text)
    if not match:
        raise SystemExit("Versione non trovata in aion2meter/__init__.py")
    major, minor, patch = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    new = f"{major}.{minor}.{patch + 1}"
    INIT.write_text(
        text.replace(match.group(0), f'__version__ = "{new}"'), encoding="utf-8"
    )
    return new


def build() -> None:
    result = subprocess.run([sys.executable, "build.py"], cwd=ROOT, text=True)
    if result.returncode != 0:
        raise SystemExit("Build fallita: nessun commit eseguito.")


def publish(version: str, notes: str) -> None:
    PAYLOAD.parent.mkdir(parents=True, exist_ok=True)
    PAYLOAD.write_bytes(APP_EXE.read_bytes())
    digest = hashlib.sha256(PAYLOAD.read_bytes()).hexdigest()
    MANIFEST.write_text(
        json.dumps(
            {
                "version": version,
                "url": f"{RAW_BASE}/update/Aion2DamageMeter.exe",
                "sha256": digest,
                "size": PAYLOAD.stat().st_size,
                "notes": notes,
                "published": datetime.now().strftime("%Y-%m-%d %H:%M"),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Payload aggiornato: {PAYLOAD} ({PAYLOAD.stat().st_size / 1_048_576:.1f} MB)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pubblica una modifica su GitHub")
    parser.add_argument("-m", "--message", default="", help="descrizione della modifica")
    parser.add_argument("--no-push", action="store_true", help="commit locale senza push")
    parser.add_argument("--force", action="store_true", help="pubblica anche senza modifiche")
    args = parser.parse_args()

    if not args.force and not has_changes():
        print("Nessuna modifica da pubblicare.")
        return 0

    version = bump_version()
    print(f"Nuova versione: {version}")
    build()
    publish(version, args.message)

    git_run("add", "-A")
    message = args.message.strip() or f"Release {version}"
    commit = git_run("commit", "-m", f"{message}\n\nVersione {version}")
    if commit.returncode != 0:
        print(commit.stdout.strip() or commit.stderr.strip())
        if "nothing to commit" in (commit.stdout + commit.stderr):
            return 0
        return 1

    if args.no_push:
        print("Commit creato (push saltato).")
        return 0

    push = git_run("push", "origin", "HEAD:main")
    if push.returncode != 0:
        print("PUSH NON RIUSCITO:")
        print((push.stderr or push.stdout).strip())
        return 1
    print(f"Pubblicato: {RAW_BASE}/version.json (v{version})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
