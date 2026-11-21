"""Combat aggregation: raw events -> roster rows and per-skill breakdowns."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .gamedata import class_info, normalize_class

TAB_KIND = {"damage": "damage", "healing": "heal", "taken": "taken"}
TAB_FIELD = {"damage": "damage", "healing": "healing", "taken": "taken"}

_KIND_ALIASES = {
    "hit": "damage",
    "damage": "damage",
    "dmg": "damage",
    "heal": "heal",
    "healing": "heal",
    "taken": "taken",
    "damage_taken": "taken",
}


@dataclass
class SkillStat:
    name: str
    hits: int
    amount: int
    share: float
    back_pct: float
    mult_pct: float


@dataclass
class MemberStat:
    key: str
    name: str
    cls: str
    role: str
    spec: str
    color: str
    damage: int = 0
    healing: int = 0
    taken: int = 0
    hits: int = 0
    metric: int = 0
    dps: float = 0.0
    share: float = 0.0
    crit: float = 0.0
    double: float = 0.0
    multi: float = 0.0
    back: float = 0.0
    skills: list[SkillStat] = field(default_factory=list)
    rank: int = 0
    fill: float = 0.0


@dataclass
class Snapshot:
    duration: float = 0.0
    total: int = 0
    dps: float = 0.0
    members: list[MemberStat] = field(default_factory=list)


class _Bucket:
    __slots__ = (
        "damage",
        "healing",
        "taken",
        "hits",
        "crit",
        "double",
        "multi",
        "back",
        "skills",
    )

    def __init__(self) -> None:
        self.damage = 0
        self.healing = 0
        self.taken = 0
        self.hits = 0
        self.crit = 0
        self.double = 0
        self.multi = 0
        self.back = 0
        # kind -> {skill name: [hits, amount, back hits, multi hits]}
        self.skills: dict[str, dict[str, list[int]]] = {"damage": {}, "heal": {}, "taken": {}}


class MeterEngine:
    """Accumulates events and produces ranked snapshots."""

    def __init__(self) -> None:
        self.reset()

    # ------------------------------------------------------------------ setup
    def reset(self) -> None:
        self.members: dict[str, dict[str, Any]] = {}
        self.buckets: dict[str, _Bucket] = {}
        self.first_t: float | None = None
        self.last_t: float | None = None
        self.session: dict[str, str | None] = {"server": None, "character": None, "class": None}

    def set_session(
        self,
        server: str | None = None,
        character: str | None = None,
        cls: str | None = None,
    ) -> None:
        if server:
            self.session["server"] = server
        if character:
            self.session["character"] = character
        if cls:
            self.session["class"] = normalize_class(cls)

    def define(
        self,
        name: str,
        cls: object = None,
        role: str | None = None,
        pet: bool = False,
        owner: str | None = None,
        joined: bool = False,
    ) -> None:
        """Register a party member. `joined` keeps them listed before their first hit."""
        if not name:
            return
        meta = self.members.setdefault(
            name, {"cls": "Unknown", "role": role, "pet": pet, "owner": owner, "joined": False}
        )
        if cls:
            meta["cls"] = normalize_class(cls)
        if role:
            meta["role"] = role
        if pet:
            meta["pet"] = True
        if owner:
            meta["owner"] = owner
        if joined:
            meta["joined"] = True

    def drop(self, name: str) -> None:
        """Remove a member that left the party / dungeon."""
        self.buckets.pop(name, None)
        self.members.pop(name, None)

    # ------------------------------------------------------------------ input
    def add(self, ev: dict[str, Any]) -> None:
        src = ev.get("src") or ev.get("name") or ev.get("player")
        if not src:
            return
        src = str(src)
        self.define(
            src,
            ev.get("class") or ev.get("cls"),
            ev.get("role"),
            bool(ev.get("pet")),
            ev.get("owner"),
        )

        kind = _KIND_ALIASES.get(str(ev.get("type", "hit")).lower(), "damage")
        try:
            amount = int(round(float(ev.get("amount") or ev.get("value") or 0)))
        except (TypeError, ValueError):
            return
        if amount <= 0:
            return

        if self.last_t is None:
            try:
                t = max(0.0, float(ev.get("t", 0.0) or 0.0))
            except (TypeError, ValueError):
                t = 0.0
        else:
            try:
                t = float(ev.get("t", self.last_t + 0.05))
            except (TypeError, ValueError):
                t = self.last_t + 0.05
            # feeds without timestamps just march forward
            if t < self.last_t - 5:
                t = self.last_t + 0.05
        if self.first_t is None or t < self.first_t:
            self.first_t = t
        if self.last_t is None or t > self.last_t:
            self.last_t = t

        bucket = self.buckets.setdefault(src, _Bucket())
        skill = str(ev.get("skill") or ev.get("ability") or "Melee").strip() or "Melee"
        position = str(ev.get("position") or ev.get("pos") or "").lower()
        is_back = position in ("back", "behind", "rear")

        if kind == "damage":
            bucket.damage += amount
            bucket.hits += 1
            if ev.get("crit"):
                bucket.crit += 1
            if ev.get("double"):
                bucket.double += 1
            if ev.get("multi"):
                bucket.multi += 1
            if is_back:
                bucket.back += 1
            entry = bucket.skills["damage"].setdefault(skill, [0, 0, 0, 0])
            entry[0] += 1
            entry[1] += amount
            entry[2] += 1 if is_back else 0
            entry[3] += 1 if ev.get("multi") else 0
        elif kind == "heal":
            bucket.healing += amount
            entry = bucket.skills["heal"].setdefault(skill, [0, 0, 0, 0])
            entry[0] += 1
            entry[1] += amount
        else:
            bucket.taken += amount
            entry = bucket.skills["taken"].setdefault(skill, [0, 0, 0, 0])
            entry[0] += 1
            entry[1] += amount

    # ----------------------------------------------------------------- output
    def duration(self) -> float:
        if self.first_t is None or self.last_t is None:
            return 0.0
        return max(self.last_t - self.first_t, 1.0)

    def snapshot(
        self,
        tab: str = "damage",
        merge_pets: bool = True,
        include_brawler: bool = True,
    ) -> Snapshot:
        tab = tab if tab in TAB_FIELD else "damage"
        kind = TAB_KIND[tab]
        field_name = TAB_FIELD[tab]
        duration = self.duration()

        def blank(name: str, cls: object, role: str | None) -> dict[str, Any]:
            return {
                "name": name,
                "cls": cls or "Unknown",
                "role": role,
                "damage": 0,
                "healing": 0,
                "taken": 0,
                "hits": 0,
                "crit": 0,
                "double": 0,
                "multi": 0,
                "back": 0,
                "skills": {"damage": {}, "heal": {}, "taken": {}},
            }

        groups: dict[str, dict[str, Any]] = {}

        # members that joined the dungeon are listed right away, even at 0 damage
        for name, meta in self.members.items():
            if not meta.get("joined") or meta.get("pet"):
                continue
            groups[name] = blank(name, meta.get("cls"), meta.get("role"))

        for name, bucket in self.buckets.items():
            meta = self.members.get(name, {})
            is_pet = bool(meta.get("pet"))
            owner = meta.get("owner")
            if is_pet and merge_pets and owner:
                key = owner
                owner_meta = self.members.get(owner, {})
                info = groups.setdefault(
                    key,
                    blank(owner, owner_meta.get("cls") or meta.get("cls"), owner_meta.get("role")),
                )
                if info["cls"] in (None, "Unknown"):
                    info["cls"] = owner_meta.get("cls") or meta.get("cls") or "Unknown"
            else:
                key = name
                info = groups.setdefault(key, blank(name, meta.get("cls"), meta.get("role")))

            info["damage"] += bucket.damage
            info["healing"] += bucket.healing
            info["taken"] += bucket.taken
            info["hits"] += bucket.hits
            info["crit"] += bucket.crit
            info["double"] += bucket.double
            info["multi"] += bucket.multi
            info["back"] += bucket.back
            for k, skills in bucket.skills.items():
                target = info["skills"][k]
                for skill_name, values in skills.items():
                    acc = target.setdefault(skill_name, [0, 0, 0, 0])
                    for i in range(4):
                        acc[i] += values[i]

        members: list[MemberStat] = []
        for key, info in groups.items():
            cls = normalize_class(info["cls"])
            if not include_brawler and cls == "Brawler":
                continue
            cdata = class_info(cls)
            metric = int(info[field_name])
            joined = bool(self.members.get(key, {}).get("joined"))
            if metric <= 0 and not joined:
                continue
            hits = int(info["hits"])
            stat = MemberStat(
                key=key,
                name=str(info["name"]),
                cls=cls,
                role=info["role"] or cdata["role"],
                spec=cdata["spec"],
                color=cdata["color"],
                damage=int(info["damage"]),
                healing=int(info["healing"]),
                taken=int(info["taken"]),
                hits=hits,
                metric=metric,
                dps=metric / duration if duration else 0.0,
                crit=(info["crit"] / hits) if hits else 0.0,
                double=(info["double"] / hits) if hits else 0.0,
                multi=(info["multi"] / hits) if hits else 0.0,
                back=(info["back"] / hits) if hits else 0.0,
            )
            skills = info["skills"][kind]
            for skill_name, values in skills.items():
                sk_hits, amount, back_hits, multi_hits = values
                if amount <= 0:
                    continue
                stat.skills.append(
                    SkillStat(
                        name=skill_name,
                        hits=sk_hits,
                        amount=amount,
                        share=(amount / metric) if metric else 0.0,
                        back_pct=(back_hits / sk_hits) if sk_hits else 0.0,
                        mult_pct=(multi_hits / sk_hits) if sk_hits else 0.0,
                    )
                )
            stat.skills.sort(key=lambda s: s.amount, reverse=True)
            members.append(stat)

        members.sort(key=lambda m: (-m.metric, m.name.lower()))
        total = sum(m.metric for m in members)
        top = members[0].metric if members else 0
        for rank, m in enumerate(members, start=1):
            m.rank = rank
            m.share = (m.metric / total) if total else 0.0
            m.fill = (m.metric / top) if top else 0.0
        return Snapshot(
            duration=duration,
            total=total,
            dps=(total / duration) if duration else 0.0,
            members=members,
        )

    def member(self, key: str, tab: str, merge_pets: bool, include_brawler: bool) -> MemberStat | None:
        for m in self.snapshot(tab, merge_pets, include_brawler).members:
            if m.key == key:
                return m
        return None
