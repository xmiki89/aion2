"""Static game data: classes, colours, roles and skill pools."""

from __future__ import annotations

# colour = bar / dot colour used by the roster, role = short tag, spec = archetype
CLASSES: dict[str, dict[str, str]] = {
    "Sorcerer": {"color": "#4D7CFE", "role": "DPS", "spec": "Ranged Magic Burst"},
    "Assassin": {"color": "#F2557F", "role": "DPS", "spec": "Melee Burst"},
    "Ranger": {"color": "#22B573", "role": "DPS", "spec": "Ranged Physical"},
    "Spiritmaster": {"color": "#8B6FE8", "role": "DPS", "spec": "Summon Magic"},
    "Gladiator": {"color": "#D9A63C", "role": "Off-Tank", "spec": "Melee Cleave"},
    "Chanter": {"color": "#BFD63C", "role": "Support", "spec": "Aura Support"},
    "Templar": {"color": "#4F7392", "role": "Tank", "spec": "Shield Wall"},
    "Cleric": {"color": "#3FA9DB", "role": "Healer", "spec": "Holy Support"},
    "Brawler": {"color": "#E2703A", "role": "DPS", "spec": "Melee Combo"},
}

UNKNOWN_CLASS = {"color": "#6E7280", "role": "DPS", "spec": "Adventurer"}

CLASS_SKILLS: dict[str, list[str]] = {
    "Sorcerer": [
        "Arcane Implosion",
        "Flame Harpoon",
        "Glacial Shard",
        "Infernal Wave",
        "Frost Nova",
        "Meteor Strike",
        "Mana Burn",
    ],
    "Assassin": [
        "Shadow Strike",
        "Venom Slash",
        "Backstab",
        "Blade Dance",
        "Assassinate",
        "Smoke Bomb",
        "Rune Carve",
    ],
    "Ranger": [
        "Piercing Arrow",
        "Arrow Storm",
        "Hunter's Mark",
        "Explosive Trap",
        "Swift Shot",
        "Entangling Shot",
        "Falcon Dive",
    ],
    "Spiritmaster": [
        "Spirit Eruption",
        "Earthen Wrath",
        "Curse of Agony",
        "Soul Drain",
        "Binding Roots",
        "Spirit Chain",
        "Nether Bolt",
    ],
    "Gladiator": [
        "Whirlwind Cleave",
        "Shield Breaker",
        "Battle Roar",
        "Ground Smash",
        "Wrath Strike",
        "Iron Will",
        "Rending Charge",
    ],
    "Chanter": [
        "Word of Power",
        "Blessed Aura",
        "Mantra of Fury",
        "Divine Chant",
        "Healing Hymn",
        "Chant of Warding",
        "Sacred Strike",
    ],
    "Templar": [
        "Shield Bash",
        "Holy Shield",
        "Provoke",
        "Divine Judgment",
        "Aegis Strike",
        "Guardian's Oath",
        "Retribution",
    ],
    "Cleric": [
        "Healing Light",
        "Holy Bolt",
        "Divine Grace",
        "Sanctuary",
        "Purify",
        "Blessed Shield",
        "Radiant Mending",
    ],
    "Brawler": [
        "Fist Barrage",
        "Dragon Kick",
        "Iron Palm",
        "Storm Palm",
        "Counter Fist",
        "Chi Burst",
        "Tiger Stance",
    ],
}

PET_SKILLS = ["Spirit Claw", "Earthen Spikes", "Soul Flame", "Spirit Nova"]

_ALIASES = {
    "sorc": "Sorcerer",
    "sorceror": "Sorcerer",
    "mage": "Sorcerer",
    "sin": "Assassin",
    "assasin": "Assassin",
    "archer": "Ranger",
    "sm": "Spiritmaster",
    "spirit": "Spiritmaster",
    "summoner": "Spiritmaster",
    "glad": "Gladiator",
    "temp": "Templar",
    "cleric": "Cleric",
    "healer": "Cleric",
    "chanter": "Chanter",
    "brawler": "Brawler",
    "monk": "Brawler",
    "tank": "Templar",
}


def normalize_class(raw: object) -> str:
    """Return the canonical class name for whatever the feed reported."""
    if not raw:
        return "Unknown"
    text = str(raw).strip()
    key = text.lower().replace(" ", "").replace("_", "").replace("-", "")
    for name in CLASSES:
        if name.lower() == key:
            return name
    return _ALIASES.get(key, "Unknown")


def class_info(raw: object) -> dict[str, str]:
    name = normalize_class(raw)
    return CLASSES.get(name) or dict(UNKNOWN_CLASS)


def class_color(raw: object) -> str:
    return class_info(raw)["color"]


def class_role(raw: object) -> str:
    return class_info(raw)["role"]


def class_spec(raw: object) -> str:
    return class_info(raw)["spec"]
