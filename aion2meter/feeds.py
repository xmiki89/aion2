"""Data sources: live JSONL combat log, built-in demo run, game/process detection."""

from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Any

from .gamedata import CLASS_SKILLS, PET_SKILLS, class_info, normalize_class

# --------------------------------------------------------------------------- paths


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _local_appdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home())


def candidate_feed_paths() -> list[Path]:
    paths: list[Path] = []
    env = os.environ.get("AION2METER_LOG")
    if env:
        paths.append(Path(env))
    paths.append(_app_dir() / "combat.log")
    paths.append(_local_appdata() / "Aion2DamageMeter" / "combat.log")
    paths.append(Path.home() / "Documents" / "Aion2DamageMeter" / "combat.log")
    return paths


def candidate_session_paths() -> list[Path]:
    return [
        _app_dir() / "session.json",
        _local_appdata() / "Aion2DamageMeter" / "session.json",
        Path.home() / "Documents" / "Aion2DamageMeter" / "session.json",
    ]


def find_feed() -> Path | None:
    for path in candidate_feed_paths():
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


# --------------------------------------------------------------------- log feed


class LogFeed:
    """Tails a JSON-lines combat log written while the game is running."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.offset = 0
        self.buffer = ""

    def poll(self) -> list[dict[str, Any]]:
        try:
            size = self.path.stat().st_size
        except OSError:
            return []
        if size < self.offset:  # file was truncated / rotated
            self.offset = 0
            self.buffer = ""
        if size == self.offset:
            return []
        try:
            with self.path.open("rb") as handle:
                handle.seek(self.offset)
                data = handle.read()
                self.offset = handle.tell()
        except OSError:
            return []

        self.buffer += data.decode("utf-8", "ignore")
        *lines, self.buffer = self.buffer.split("\n")
        events: list[dict[str, Any]] = []
        for line in lines:
            line = line.strip().lstrip("\ufeff")
            if not line or line.startswith("#"):
                continue
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            if isinstance(payload, dict):
                events.append(payload)

        # a writer that does not end with a newline still gets its last line used,
        # but only when the buffered text is already valid JSON
        tail = self.buffer.strip().lstrip("\ufeff")
        if tail:
            try:
                payload = json.loads(tail)
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                events.append(payload)
                self.buffer = ""
        return events


def read_session_file() -> dict[str, str]:
    for path in candidate_session_paths():
        try:
            if not path.is_file():
                continue
            with path.open("r", encoding="utf-8-sig") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            out = {}
            for key in ("server", "realm", "character", "name", "class", "cls"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    out["server" if key == "realm" else ("class" if key == "cls" else key)] = value.strip()
            if out:
                return out
    return {}


# ---------------------------------------------------------- character detection

_CLASS_KEY = re.compile(
    r'"?\b(class|classname|characterclass|job|jobname|subclass)\b"?\s*[:=]\s*"?([A-Za-z]{3,20})',
    re.I,
)
_CHAR_KEY = re.compile(
    r'"?\b(character|charactername|charname|playername|mycharacter)\b"?\s*[:=]\s*"([^"\r\n]{2,24})"',
    re.I,
)
_SERVER_KEY = re.compile(
    r'"?\b(server|servername|realm|world|worldname)\b"?\s*[:=]\s*"?([A-Za-z0-9 _-]{2,24})"?',
    re.I,
)
_TEXT_EXT = {".log", ".txt", ".json", ".ini", ".cfg", ".xml", ".config", ".settings"}
_SCAN_BUDGET = 2.5
_SCAN_FILES = 250


class CharacterDetector:
    """Works out the player's own server/character/class from local game files."""

    def __init__(self) -> None:
        self.server: str | None = None
        self.character: str | None = None
        self.cls: str | None = None
        self._last_scan = 0.0
        self._seen: dict[str, tuple[int, float]] = {}

    def update(self, watcher: GameWatcher, hints: dict[str, str]) -> dict[str, str | None]:
        server = hints.get("server")
        character = hints.get("character")
        raw_class = hints.get("class")
        if server:
            self.server = server
        if character:
            self.character = character
        if raw_class:
            name = normalize_class(raw_class)
            if name != "Unknown":
                self.cls = name

        from_title = watcher.session_from_title()
        if not self.server and from_title.get("server"):
            self.server = from_title["server"]
        if not self.character and from_title.get("character"):
            self.character = from_title["character"]

        if watcher.running and not (self.character and self.cls):
            now = time.monotonic()
            if now - self._last_scan > 15:
                self._last_scan = now
                self._scan(watcher)

        return {"server": self.server, "character": self.character, "class": self.cls}

    # ------------------------------------------------------------- file search
    def _scan(self, watcher: GameWatcher) -> None:
        for path in self._candidate_files(watcher):
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_size > 400_000:
                continue
            key = str(path)
            previous = self._seen.get(key)
            if previous is not None and previous[0] == stat.st_size and previous[1] == stat.st_mtime:
                continue
            self._seen[key] = (stat.st_size, stat.st_mtime)
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            self._parse(text)
            if self.character and self.cls:
                return

    def _roots(self, watcher: GameWatcher) -> list[Path]:
        roots: list[Path] = []
        if watcher.pid:
            try:
                import psutil

                exe = psutil.Process(watcher.pid).exe()
                if exe:
                    roots.append(Path(exe).resolve().parent)
            except Exception:
                pass
        for env in ("LOCALAPPDATA", "APPDATA"):
            base = os.environ.get(env)
            if not base:
                continue
            try:
                for child in Path(base).iterdir():
                    if child.is_dir() and any(
                        hint in child.name.lower() for hint in ("aion", "ncsoft", "purple")
                    ):
                        roots.append(child)
            except OSError:
                pass
        try:
            for child in (Path.home() / "Documents").iterdir():
                if child.is_dir() and "aion" in child.name.lower():
                    roots.append(child)
        except OSError:
            pass
        return roots

    def _candidate_files(self, watcher: GameWatcher):
        deadline = time.monotonic() + _SCAN_BUDGET
        seen = 0
        for root in self._roots(watcher):
            try:
                if not root.is_dir():
                    continue
            except OSError:
                continue
            base_depth = len(root.parts)
            for current, dirs, files in os.walk(root):
                if time.monotonic() > deadline or seen > _SCAN_FILES:
                    return
                if len(Path(current).parts) - base_depth >= 3:
                    dirs[:] = []
                dirs[:] = [d for d in dirs if not d.startswith((".", "$"))][:20]
                for name in files:
                    if Path(name).suffix.lower() in _TEXT_EXT:
                        seen += 1
                        yield Path(current) / name

    def _parse(self, text: str) -> None:
        if not self.character:
            match = _CHAR_KEY.search(text)
            if match:
                candidate = match.group(2).strip()
                if candidate and " " not in candidate:
                    self.character = candidate
        if not self.cls:
            for match in _CLASS_KEY.finditer(text):
                name = normalize_class(match.group(2))
                if name != "Unknown":
                    self.cls = name
                    break
        if not self.server:
            match = _SERVER_KEY.search(text)
            if match:
                candidate = match.group(2).strip()
                if 2 <= len(candidate) <= 20 and candidate.lower() not in (
                    "true",
                    "false",
                    "null",
                    "none",
                ):
                    self.server = candidate


# --------------------------------------------------------------- game detection


_GAME_HINTS = ("aion2", "aion 2", "aion2client", "aion2_x64")
_OWN_HINTS = ("meter", "python", "pyinstaller")


class GameWatcher:
    """Looks for the Aion 2 client process and reads its window title."""

    def __init__(self) -> None:
        self.pid: int | None = None
        self.exe = ""
        self.title = ""
        self.last_scan = 0.0

    def scan(self) -> bool:
        try:
            import psutil
        except Exception:
            return False

        own_pid = os.getpid()
        found: tuple[int, str] | None = None
        try:
            for proc in psutil.process_iter(["pid", "name"]):
                name = (proc.info.get("name") or "").lower()
                pid = int(proc.info.get("pid") or 0)
                if not name or pid == own_pid:
                    continue
                # never mistake this meter (or a Python build) for the game
                if any(hint in name for hint in _OWN_HINTS):
                    continue
                if any(hint in name for hint in _GAME_HINTS):
                    found = (pid, proc.info.get("name") or "")
                    break
        except Exception:
            found = None

        if found is None:
            self.pid = None
            self.exe = ""
            self.title = ""
            return False

        self.pid, self.exe = found
        self.title = window_title(self.pid)
        return True

    @property
    def running(self) -> bool:
        return self.pid is not None

    def session_from_title(self) -> dict[str, str]:
        """Best-effort server/character guess from the client window title."""
        title = (self.title or "").strip()
        if not title:
            return {}
        cleaned = title
        for junk in ("Aion 2", "AION 2", "Aion2", "AION2", "PURPLE", "NCSOFT"):
            cleaned = cleaned.replace(junk, " ")
        cleaned = " ".join(cleaned.split())
        out: dict[str, str] = {}
        if "[" in cleaned and "]" in cleaned:
            head, _, tail = cleaned.partition("[")
            server, _, rest = tail.partition("]")
            server = server.strip()
            name = rest.strip(" -–|:·")
            if server:
                out["server"] = server
            if name and len(name.split()) <= 2:
                out["character"] = name
        return out


def window_title(pid: int) -> str:
    if os.name != "nt":
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        titles: list[str] = []
        proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def callback(hwnd, _lparam):  # noqa: ANN001
            if not user32.IsWindowVisible(hwnd):
                return True
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value != pid:
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if buf.value:
                    titles.append(buf.value)
            return True

        user32.EnumWindows(proc_type(callback), 0)
        return titles[0] if titles else ""
    except Exception:
        return ""


# ---------------------------------------------------------------- demo dungeon

DURATION = 165.0

# name, class, total damage, crit, double, multi, back, explicit skill table
# (skill, hits, share, back-rate, multi-rate) or None to auto-build one
DEMO_ROSTER: list[tuple] = [
    (
        "Lyra",
        "Sorcerer",
        996600,
        0.442,
        0.186,
        0.294,
        0.680,
        [
            ("Arcane Implosion", 14, 0.42, 0.714, 0.357),
            ("Flame Harpoon", 26, 0.33, 0.654, 0.269),
            ("Glacial Shard", 42, 0.25, 0.667, 0.238),
        ],
    ),
    ("Vex", "Assassin", 943800, 0.585, 0.221, 0.312, 0.712, None),
    ("Kaelen", "Ranger", 892650, 0.512, 0.198, 0.263, 0.641, None),
    ("Sylphie", "Spiritmaster", 800250, 0.468, 0.174, 0.401, 0.523, None),
    ("Draven", "Gladiator", 762300, 0.391, 0.245, 0.188, 0.688, None),
    ("Sora", "Chanter", 524700, 0.443, 0.162, 0.214, 0.472, None),
    ("Aegis", "Templar", 320100, 0.337, 0.141, 0.152, 0.395, None),
    ("Elara", "Cleric", 222750, 0.402, 0.133, 0.196, 0.418, None),
]

DEMO_MEMBERS = [(row[0], row[1]) for row in DEMO_ROSTER]


def _split(total: int, parts: int) -> list[int]:
    parts = max(parts, 1)
    base, rem = divmod(int(total), parts)
    return [base + (1 if i < rem else 0) for i in range(parts)]


def _pick(count: int, hits: int, rng: random.Random) -> set[int]:
    count = max(0, min(int(count), hits))
    return set(rng.sample(range(hits), count)) if count and hits else set()


def build_seed(rng: random.Random | None = None) -> list[dict[str, Any]]:
    """Build the demo dungeon run shown by the meter before a live feed exists."""
    rng = rng or random.Random(20261121)
    events: list[dict[str, Any]] = []

    for name, cls, total, crit_rate, double_rate, multi_rate, back_rate, skills in DEMO_ROSTER:
        info = class_info(cls)
        pool = CLASS_SKILLS.get(cls, ["Melee"])
        if skills is None:
            average = {"Sorcerer": 2900, "Assassin": 2100, "Ranger": 2400, "Spiritmaster": 3100,
                       "Gladiator": 3400, "Chanter": 2200, "Templar": 2600, "Cleric": 2000}.get(cls, 2500)
            shares = [0.34, 0.27, 0.22, 0.17]
            names = rng.sample(pool, 4)
            skills = []
            for skill_name, share in zip(names, shares):
                amount = total * share
                hits = max(6, min(70, int(amount / average)))
                rate = min(0.95, max(0.15, back_rate + rng.uniform(-0.08, 0.08)))
                skills.append((skill_name, hits, share, rate, min(0.7, max(0.05, multi_rate + rng.uniform(-0.06, 0.06)))))

        # Spiritmaster: a third of the damage comes from the summoned spirit
        pet_share = 0.30 if cls == "Spiritmaster" else 0.0
        pet_name = "Earth Spirit" if pet_share else ""

        for skill_name, hits, share, back_p, multi_p in skills:
            owner_total = int(round(total * (1.0 - pet_share)))
            amount = int(round(owner_total * share / sum(s[2] for s in skills)))
            amounts = _split(amount, hits)
            backs = _pick(round(hits * back_p), hits, rng)
            multis = _pick(round(hits * multi_p), hits, rng)
            crits = _pick(round(hits * crit_rate), hits, rng)
            doubles = _pick(round(hits * double_rate), hits, rng)
            for i in range(hits):
                events.append(
                    {
                        "type": "hit",
                        "t": rng.uniform(0.0, DURATION),
                        "src": name,
                        "class": cls,
                        "role": info["role"],
                        "skill": skill_name,
                        "amount": amounts[i],
                        "crit": i in crits,
                        "double": i in doubles,
                        "multi": i in multis,
                        "position": "back" if i in backs else ("front" if rng.random() < 0.7 else "flank"),
                    }
                )

        if pet_share:
            pet_total = int(round(total * pet_share))
            pet_hits = 44
            amounts = _split(pet_total, pet_hits)
            backs = _pick(round(pet_hits * 0.5), pet_hits, rng)
            multis = _pick(round(pet_hits * 0.35), pet_hits, rng)
            crits = _pick(round(pet_hits * crit_rate), pet_hits, rng)
            for i in range(pet_hits):
                events.append(
                    {
                        "type": "hit",
                        "t": rng.uniform(0.0, DURATION),
                        "src": pet_name,
                        "class": cls,
                        "pet": True,
                        "owner": name,
                        "skill": PET_SKILLS[i % len(PET_SKILLS)],
                        "amount": amounts[i],
                        "crit": i in crits,
                        "multi": i in multis,
                        "position": "back" if i in backs else "front",
                    }
                )

    # keep the measured fight exactly DURATION long
    if events:
        events.sort(key=lambda e: e["t"])
        events[0]["t"] = 0.0
        events[-1]["t"] = DURATION
    return events


class DemoFeed:
    """Seeds one full dungeon run, then keeps feeding small live hits."""

    def __init__(self) -> None:
        self.started = False
        self.clock = DURATION
        self.rng = random.Random()

    def poll(self, dt: float = 0.25) -> list[dict[str, Any]]:
        if not self.started:
            self.started = True
            return build_seed()

        self.clock += dt
        events: list[dict[str, Any]] = []
        for _ in range(self.rng.randint(2, 4)):
            name, cls = self.rng.choice(DEMO_MEMBERS)
            events.append(
                {
                    "type": "hit",
                    "t": self.clock + self.rng.random() * dt,
                    "src": name,
                    "class": cls,
                    "skill": self.rng.choice(CLASS_SKILLS[cls]),
                    "amount": self.rng.randint(1400, 4200),
                    "crit": self.rng.random() < 0.44,
                    "double": self.rng.random() < 0.19,
                    "multi": self.rng.random() < 0.28,
                    "position": "back" if self.rng.random() < 0.68 else ("front" if self.rng.random() < 0.75 else "flank"),
                }
            )
        return events
