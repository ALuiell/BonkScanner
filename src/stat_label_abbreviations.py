from __future__ import annotations

STAT_LABEL_ABBREVIATIONS: dict[str, str] = {
    "Max HP": "HP",
    "HP Regen": "Regen",
    "Overheal": "Overheal",
    "Shield": "Shield",
    "Armor": "Armor",
    "Evasion": "Evasion",
    "Lifesteal": "Lifesteal",
    "Thorns": "Thorns",
    "Damage": "DMG",
    "Crit Chance": "Crit",
    "Crit Damage": "CritDMG",
    "Attack Speed": "AS",
    "Projectile Count": "Proj",
    "Projectile Bounces": "Bounces",
    "Size": "Size",
    "Projectile Speed": "ProjSpeed",
    "Duration": "Dur",
    "Damage to Elites": "EliteDMG",
    "Knockback": "KB",
    "Movement Speed": "MS",
    "Extra Jumps": "Jumps",
    "Jump Height": "JumpHeight",
    "Luck": "Luck",
    "Difficulty": "Diff",
    "Pickup Range": "Pickup",
    "XP Gain": "XP",
    "Gold Gain": "Gold",
    "Elite Spawn Increase": "ESI",
    "Powerup Multiplier": "PM",
    "Powerup Drop Chance": "PDC",
}


def abbreviate_stat_label(label: str) -> str:
    normalized_label = str(label or "")
    return STAT_LABEL_ABBREVIATIONS.get(normalized_label, normalized_label)
