"""Shared series-slot menu and presentation for both recording timelines."""
from __future__ import annotations

from PySide6.QtWidgets import QMenu, QPushButton

from core.stat_labels import abbreviate_stat_label
from projections import scrubber as scrubber_model


TIMELINE_SERIES_GROUPS = (
    (
        "Dmg",
        (
            "Damage",
            "Crit Chance",
            "Crit Damage",
            "Attack Speed",
            "Projectile Count",
            "Projectile Bounces",
        ),
    ),
    (
        "Effects",
        (
            "Size",
            "Projectile Speed",
            "Duration",
            "Damage to Elites",
            "Knockback",
        ),
    ),
    (
        "Run",
        (
            "Max HP",
            "HP Regen",
            "Overheal",
            "Shield",
            "Armor",
            "Evasion",
            "Lifesteal",
            "Thorns",
            "Extra Jumps",
            "Jump Height",
            "Movement Speed",
        ),
    ),
    (
        "Rewards & spawns",
        (
            "Luck",
            "Difficulty",
            "Pickup Range",
            "XP Gain",
            "Gold Gain",
            "Elite Spawn Increase",
            "Powerup Multiplier",
            "Powerup Drop Chance",
        ),
    ),
)

POWERUP_PAIR = ("Powerup Multiplier", "Powerup Drop Chance")

_ACCENT_ROLES = {
    "#38bdf8": "blue",
    "#4ade80": "green",
    "#facc15": "yellow",
    "#f59e0b": "orange",
    "#f0787e": "red",
    "#c084fc": "purple",
    "#60a5fa": "sky",
}


def build_timeline_series_menu(
    button: QPushButton,
    slot_index: int,
    on_selected,
) -> QMenu:
    def select(keys):
        return lambda _checked=False: on_selected(slot_index, tuple(keys))

    menu = QMenu(button)
    menu.addAction("None").triggered.connect(select(scrubber_model.EMPTY_SLOT))
    menu.addSeparator()
    for key in (scrubber_model.KILLS_SERIES, scrubber_model.ITEMS_SERIES):
        menu.addAction(scrubber_model.series_label(key)).triggered.connect(select((key,)))
    menu.addAction("PM + PDC").triggered.connect(select(POWERUP_PAIR))
    menu.addSeparator()
    allowed = set(scrubber_model.available_series_keys())
    for title, labels in TIMELINE_SERIES_GROUPS:
        submenu = menu.addMenu(title)
        for key in labels:
            if key in allowed:
                submenu.addAction(key).triggered.connect(select((key,)))
    return menu


def slot_button_text(keys) -> str:
    keys = tuple(keys)
    if not keys:
        return "None"
    return " + ".join(
        abbreviate_stat_label(scrubber_model.series_label(key)) for key in keys
    )


def timeline_series_accent_role(keys) -> str:
    keys = tuple(keys)
    if not keys:
        return "none"
    color = scrubber_model.series_color(keys[0]).lower()
    return _ACCENT_ROLES.get(color, "neutral")


def refresh_timeline_slot_button(button: QPushButton, slot_index: int, keys) -> None:
    keys = tuple(keys)
    button.setText(slot_button_text(keys))
    button.setToolTip(f"Timeline series slot {slot_index + 1}")
    button.setAccessibleName(f"Timeline series slot {slot_index + 1}: {button.text()}")
    button.setProperty("timelineSlot", True)
    accent = timeline_series_accent_role(keys)
    if button.property("accentRole") != accent:
        button.setProperty("accentRole", accent)
        style = button.style()
        style.unpolish(button)
        style.polish(button)
